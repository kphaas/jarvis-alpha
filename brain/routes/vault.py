import os
import shutil
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from brain.db.rls import rls_connection
from brain.ingest.docx import ingest_docx
from brain.middleware.scopes import check_scopes
from brain.ingest.excel import ingest_excel
from brain.ingest.pdf import ingest_pdf
from brain.ingest.text import ingest_plain_text
from brain.storage.archive import archive_document

import hashlib  # noqa: F401

VAULT_STORAGE_PATH = os.environ.get(
    "ALPHA_VAULT_PATH", "/Users/jarvisbrain/jarvis-alpha/vault_storage"
)

VALID_CLASSIFICATIONS = (
    "10_PUBLIC",
    "15_KIDS",
    "20_PROJECTS",
    "30_FINANCE",
    "40_PRIVATE",
    "50_SECRETS",
)

router = APIRouter(prefix="/v1/vault", tags=["vault"])


async def _pipeline_document_row(db, pipeline_id: str):
    row = await db.fetchrow(
        """
        SELECT
          vp.id,
          vp.filename,
          vp.local_path,
          vp.content_type,
          COALESCE(vd.id, fallback_vd.id) AS doc_id,
          COALESCE(vd.classification, fallback_vd.classification) AS classification
        FROM vault_pipeline vp
        LEFT JOIN vault_documents vd ON vd.id = vp.document_id
        LEFT JOIN LATERAL (
          SELECT id, classification
          FROM vault_documents
          WHERE filename = vp.filename
          ORDER BY created_at DESC
          LIMIT 1
        ) fallback_vd ON vp.document_id IS NULL
        WHERE vp.id = $1
        """,
        pipeline_id,
    )
    if not row or not row["doc_id"]:
        raise HTTPException(status_code=404, detail="Pipeline entry not found")
    return row


async def _mark_ingestion_result(db, pipeline_id: str, result: dict) -> None:
    error = result.get("error")
    await db.execute(
        "UPDATE vault_pipeline SET stage = $1, error = $2 WHERE id = $3",
        "ingest_error" if error else "ingested",
        str(error) if error else None,
        pipeline_id,
    )


@router.post("/upload")
async def vault_upload(
    request: Request,
    file: UploadFile = File(...),
    classification: str = Form(default="10_PUBLIC"),
):
    check_scopes(request, "vault.write", "admin")
    if classification not in VALID_CLASSIFICATIONS:
        raise HTTPException(status_code=400, detail="invalid classification")

    doc_id = str(uuid.uuid4())
    filename = file.filename or "unnamed"
    dest_dir = os.path.join(VAULT_STORAGE_PATH, classification)
    local_path = os.path.join(dest_dir, f"{doc_id}_{filename}")

    os.makedirs(dest_dir, exist_ok=True)
    with open(local_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    size = os.path.getsize(local_path)
    content_type = file.content_type or "application/octet-stream"

    async with rls_connection(request) as db:
        await db.execute(
            """
            INSERT INTO vault_documents
              (id, filename, content_type, size_bytes, classification, local_path, storage_tier, uploaded_by, workspace_id)
            VALUES
              ($1, $2, $3, $4, $5, $6, 'hot', $7, $8)
            """,
            uuid.UUID(doc_id),
            filename,
            content_type,
            size,
            classification,
            local_path,
            getattr(request.state, "user_id", None),
            getattr(request.state, "workspace_id", None) or "personal",
        )
        row = await db.fetchrow(
            """
            INSERT INTO vault_pipeline
              (document_id, filename, content_type, local_path, size_bytes, stage, uploaded_by, workspace_id)
            VALUES
              ($1, $2, $3, $4, $5, 'inbox', $6, $7)
            RETURNING id
            """,
            uuid.UUID(doc_id),
            filename,
            content_type,
            local_path,
            size,
            getattr(request.state, "user_id", None),
            getattr(request.state, "workspace_id", None) or "personal",
        )

    pipeline_id = row["id"]

    return JSONResponse(
        {
            "doc_id": doc_id,
            "pipeline_id": str(pipeline_id),
            "filename": file.filename,
            "classification": classification,
            "stage": "inbox",
            "size_bytes": size,
        }
    )


@router.get("/pipeline")
async def vault_pipeline_list(request: Request):
    check_scopes(request, "vault.read", "admin")
    async with rls_connection(request) as db:
        rows = await db.fetch(
            """
            SELECT id, filename, content_type, stage, size_bytes, created_at
            FROM vault_pipeline
            ORDER BY created_at DESC
            LIMIT 50
            """
        )
    out = []
    for r in rows:
        out.append(
            {
                "id": str(r["id"]),
                "filename": r["filename"],
                "content_type": r["content_type"],
                "stage": r["stage"],
                "size_bytes": r["size_bytes"],
                "created_at": str(r["created_at"])
                if r["created_at"] is not None
                else None,
            }
        )
    return out


@router.post("/pipeline/{pipeline_id}/confirm")
async def vault_pipeline_confirm(pipeline_id: str, request: Request):
    check_scopes(request, "vault.write", "admin")
    async with rls_connection(request) as db:
        row = await _pipeline_document_row(db, pipeline_id)

        result = await archive_document(
            local_path=row["local_path"],
            filename=row["filename"],
            classification=row["classification"],
            doc_id=str(row["doc_id"]),
        )

        archive_path = result.get("archive_path", row["local_path"])
        tier = result.get("tier", "nvme_only")
        error = result.get("error")

        await db.execute(
            "UPDATE vault_pipeline SET stage = $1, confirmed_at = now() WHERE id = $2",
            "archived" if not error else "confirm_error",
            pipeline_id,
        )
        await db.execute(
            "UPDATE vault_documents SET local_path = $1, status = $2 WHERE id = $3",
            archive_path,
            "archived" if not error else "confirm_error",
            str(row["doc_id"]),
        )

    return {
        "pipeline_id": pipeline_id,
        "stage": "archived" if not error else "confirm_error",
        "archive_path": archive_path,
        "tier": tier,
        "error": error,
    }


@router.post("/ingest/pdf")
async def vault_ingest_pdf(
    request: Request,
    file: UploadFile = File(...),
    pipeline_id: str = Form(...),
):
    check_scopes(request, "vault.write", "admin")
    file_bytes = await file.read()
    async with rls_connection(request) as db:
        row = await _pipeline_document_row(db, pipeline_id)
    result = await ingest_pdf(
        file_bytes=file_bytes,
        doc_id=str(row["doc_id"]),
        request=request,
    )
    async with rls_connection(request) as db:
        await _mark_ingestion_result(db, pipeline_id, result)
    return JSONResponse(result)


@router.post("/ingest/docx")
async def vault_ingest_docx(
    request: Request,
    file: UploadFile = File(...),
    pipeline_id: str = Form(...),
):
    check_scopes(request, "vault.write", "admin")
    file_bytes = await file.read()
    async with rls_connection(request) as db:
        row = await _pipeline_document_row(db, pipeline_id)
    result = await ingest_docx(
        file_bytes=file_bytes,
        doc_id=str(row["doc_id"]),
        request=request,
    )
    async with rls_connection(request) as db:
        await _mark_ingestion_result(db, pipeline_id, result)
    return JSONResponse(result)


@router.post("/ingest/text")
async def vault_ingest_text(
    request: Request,
    file: UploadFile = File(...),
    pipeline_id: str = Form(...),
):
    check_scopes(request, "vault.write", "admin")
    file_bytes = await file.read()
    async with rls_connection(request) as db:
        row = await _pipeline_document_row(db, pipeline_id)
    result = await ingest_plain_text(
        file_bytes=file_bytes,
        filename=file.filename or "unknown.txt",
        doc_id=str(row["doc_id"]),
        request=request,
    )
    async with rls_connection(request) as db:
        await _mark_ingestion_result(db, pipeline_id, result)
    return JSONResponse(result)


@router.post("/ingest/excel")
async def vault_ingest_excel(
    request: Request,
    file: UploadFile = File(...),
    pipeline_id: str = Form(...),
):
    check_scopes(request, "vault.write", "admin")
    file_bytes = await file.read()
    async with rls_connection(request) as db:
        row = await _pipeline_document_row(db, pipeline_id)
    result = await ingest_excel(
        file_bytes=file_bytes,
        filename=file.filename or "unknown.xlsx",
        doc_id=str(row["doc_id"]),
        request=request,
    )
    async with rls_connection(request) as db:
        await _mark_ingestion_result(db, pipeline_id, result)
    return JSONResponse(result)


@router.post("/search")
async def vault_search(request: Request):
    check_scopes(request, "vault.read", "admin")
    return {"status": "stub", "results": []}


@router.post("/ask")
async def vault_ask(request: Request):
    check_scopes(request, "vault.read", "admin")
    return {"status": "stub", "answer": None}
