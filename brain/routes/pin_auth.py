import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from jose import jwt
from pydantic import BaseModel

router = APIRouter(prefix="/v1/auth", tags=["auth"])

_DEFAULT_KEY = "~/jarvis/pki/jwt/jwt_private.pem"


class PinBody(BaseModel):
    pin: str


@router.post("/pin")
def auth_pin(body: PinBody):
    alpha_pin = os.environ.get("ALPHA_PIN")
    if alpha_pin is None:
        raise HTTPException(
            status_code=500,
            detail="ALPHA_PIN not configured",
        )

    if not secrets.compare_digest(body.pin, alpha_pin):
        raise HTTPException(status_code=401, detail="Invalid PIN")

    key_path = os.environ.get("ALPHA_JWT_PRIVATE_KEY", _DEFAULT_KEY)
    pem_path = Path(key_path).expanduser()
    private_key = pem_path.read_text(encoding="utf-8")

    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=30)
    payload = {
        "sub": "alpha_ui",
        "role": "admin",
        "exp": int(exp.timestamp()),
        "iat": int(now.timestamp()),
    }

    token = jwt.encode(payload, private_key, algorithm="RS256")
    expires_at = exp.isoformat().replace("+00:00", "Z")
    return {"token": token, "expires_at": expires_at}
