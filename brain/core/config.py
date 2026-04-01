import os

ALPHA_PORT = int(os.getenv("ALPHA_PORT", "8186"))
ALPHA_NODE = os.getenv("ALPHA_NODE", "brain")
ALPHA_VERSION = "0.1.0"

GATEWAY_URL = os.environ.get("ALPHA_GATEWAY_URL", "https://100.112.63.25:8282")
OLLAMA_URL = os.environ.get("ALPHA_OLLAMA_URL", "http://127.0.0.1:11434")
