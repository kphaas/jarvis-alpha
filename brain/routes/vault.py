from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/v1/vault/upload")
async def vault_upload(request: Request):
    return {"status": "stub", "stage": "inbox"}


@router.get("/v1/vault/pipeline")
async def vault_pipeline(request: Request):
    return {"status": "stub", "items": []}


@router.post("/v1/vault/pipeline/{item_id}/confirm")
async def vault_confirm(item_id: str, request: Request):
    return {"status": "stub", "item_id": item_id}


@router.post("/v1/vault/search")
async def vault_search(request: Request):
    return {"status": "stub", "results": []}


@router.post("/v1/vault/ask")
async def vault_ask(request: Request):
    return {"status": "stub", "answer": None}
