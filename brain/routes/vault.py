import os
import shutil
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from brain.db.session import get_db

VAULT_STORAGE_PATH = os.environ.get(
    "ALPHA_VAULT_PATH", "/Users/jarvisbrain/jarvis-alpha/vault_storage"
)

VALID_CLASSIFICATIONS = (
    "10_PUBLIC",
    "20_PROJECTS",
    "30_FINANCE",
    "40_PRIVATE",
    "50_SECRETS",
)

router = APIRouter(prefix="/v1/vault", tags=["vault"])


@router.post("/upload")
async def vault_upload(
    file: UploadFile = File(...),
    classification: str = Form(default="10_PUBLIC"),
):
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

    async with get_db("anon") as db:
        await db.execute(
            """
            INSERT INTO vault_documents
              (id, filename, content_type, size_bytes, classification, local_path, storage_tier)
            VALUES
              ($1, $2, $3, $4, $5, $6, 'hot')
            """,
            uuid.UUID(doc_id),
            filename,
            content_type,
            size,
            classification,
            local_path,
        )
        row = await db.fetchrow(
            """
            INSERT INTO vault_pipeline
              (filename, content_type, local_path, size_bytes, stage)
            VALUES
              ($1, $2, $3, $4, 'inbox')
            RETURNING id
            """,
            filename,
            content_type,
            local_path,
            size,
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
async def vault_pipeline_list():
    async with get_db("anon") as db:
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
                "created_at": str(r["created_at"]) if r["created_at"] is not None else None,
            }
        )
    return out


@router.post("/pipeline/{pipeline_id}/confirm")
async def vault_pipeline_confirm(pipeline_id: str):
    pid = uuid.UUID(pipeline_id)
    async with get_db("anon") as db:
        await db.execute(
            """
            UPDATE vault_pipeline
            SET stage = 'confirmed', confirmed_at = now()
            WHERE id = $1
            """,
            pid,
        )
    return {"pipeline_id": pipeline_id, "stage": "confirmed"}


@router.post("/search")
async def vault_search(_request: Request):
    return {"status": "stub", "results": []}


@router.post("/ask")
async def vault_ask(_request: Request):
    return {"status": "stub", "answer": None}
