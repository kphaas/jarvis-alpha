from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class AskRequest(BaseModel):
    query: str
    workspace_id: str | None = None


@router.post("/v1/ask")
async def ask(body: AskRequest, request: Request):
    return {
        "status": "stub",
        "query": body.query,
        "user_id": getattr(request.state, "user_id", None),
    }
