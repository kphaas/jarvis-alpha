import os

ALPHA_DB_DSN: str = os.environ["ALPHA_DB_DSN"]
ALPHA_DB_DSN_WRITER: str = os.environ["ALPHA_DB_DSN_WRITER"]

ALPHA_PORT = int(os.getenv("ALPHA_PORT", "8186"))
ALPHA_NODE = os.getenv("ALPHA_NODE", "brain")
ALPHA_VERSION = "0.1.0"

GATEWAY_URL = os.environ["ALPHA_GATEWAY_URL"]
OLLAMA_URL = os.environ.get("ALPHA_OLLAMA_URL", "http://127.0.0.1:11434")
