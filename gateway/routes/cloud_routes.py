from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from gateway.adapters import ClaudeAdapter, PerplexityAdapter, GeminiAdapter
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_gateway")
router = APIRouter(prefix="/v1/cloud", tags=["cloud"])

_adapters = {
    "claude": ClaudeAdapter(),
    "perplexity": PerplexityAdapter(),
    "gemini": GeminiAdapter(),
}


class CloudRequest(BaseModel):
    provider: str
    payload: dict


@router.post("/call")
async def cloud_call(req: CloudRequest):
    adapter = _adapters.get(req.provider)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"unknown provider: {req.provider}")
    try:
        result = await adapter.call(req.payload)
        return {"provider": req.provider, "result": result}
    except Exception as e:
        logger.error("cloud_call: provider=%s error=%s", req.provider, e)
        raise HTTPException(status_code=502, detail=str(e))
