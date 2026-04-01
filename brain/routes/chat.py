from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None
    workspace_id: str | None = None


@router.post("/v1/chat")
async def chat(body: ChatRequest, request: Request):
    return {
        "status": "stub",
        "message": body.message,
        "thread_id": body.thread_id,
        "user_id": getattr(request.state, "user_id", None),
    }
