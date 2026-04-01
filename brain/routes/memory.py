from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/v1/memory")
async def get_memory(request: Request):
    return {
        "status": "stub",
        "user_id": getattr(request.state, "user_id", None),
        "memories": [],
    }
