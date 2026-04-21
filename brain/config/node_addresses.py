import os

BRAIN_HOST = os.getenv("ALPHA_BRAIN_HOST", "jarvis-brain.tail40ed36.ts.net")
BRAIN_PORT = int(os.getenv("ALPHA_BRAIN_PORT", "8186"))
BRAIN_URL = os.getenv("ALPHA_BRAIN_URL", f"https://{BRAIN_HOST}:{BRAIN_PORT}")

GATEWAY_HOST = os.getenv("ALPHA_GATEWAY_HOST", "jarvis-gateway.tail40ed36.ts.net")
GATEWAY_PORT = int(os.getenv("ALPHA_GATEWAY_PORT", "8283"))
GATEWAY_URL = os.getenv("ALPHA_GATEWAY_URL", f"https://{GATEWAY_HOST}:{GATEWAY_PORT}")

ENDPOINT_HOST = os.getenv("ALPHA_ENDPOINT_HOST", "jarvis-endpoint.tail40ed36.ts.net")
ENDPOINT_PORT = int(os.getenv("ALPHA_ENDPOINT_PORT", "4100"))
ENDPOINT_URL = os.getenv(
    "ALPHA_ENDPOINT_URL", f"https://{ENDPOINT_HOST}:{ENDPOINT_PORT}"
)

SANDBOX_HOST = os.getenv("ALPHA_SANDBOX_HOST", "jarvis-sandbox.tail40ed36.ts.net")
SANDBOX_PORT = int(os.getenv("ALPHA_SANDBOX_PORT", "5001"))
SANDBOX_URL = os.getenv("ALPHA_SANDBOX_URL", f"https://{SANDBOX_HOST}:{SANDBOX_PORT}")
