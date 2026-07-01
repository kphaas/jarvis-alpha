import os

from brain.db.dsn import ensure_writer_password

ALPHA_DB_DSN: str = os.environ["ALPHA_DB_DSN"]
ALPHA_DB_DSN_WRITER: str = ensure_writer_password(os.environ["ALPHA_DB_DSN_WRITER"])
ALPHA_DB_DSN_BUDDY: str = ensure_writer_password(os.environ["ALPHA_DB_DSN_BUDDY"])

ALPHA_PORT = int(os.getenv("ALPHA_PORT", "8186"))
ALPHA_NODE = os.getenv("ALPHA_NODE", "brain")
ALPHA_VERSION = "0.1.0"

GATEWAY_URL = os.environ["ALPHA_GATEWAY_URL"]
OLLAMA_URL = os.environ.get("ALPHA_OLLAMA_URL", "http://127.0.0.1:11434")
ALPHA_AGENT_WORKSPACE_ROOT = os.getenv(
    "ALPHA_AGENT_WORKSPACE_ROOT",
    "/Users/jarvisbrain/jarvis-alpha/agent_workspaces",
)
ALPHA_AGENTFS_MAX_ARTIFACT_BYTES = int(
    os.getenv("ALPHA_AGENTFS_MAX_ARTIFACT_BYTES", str(5 * 1024 * 1024))
)
ALPHA_AGENTFS_MAX_WORKSPACE_BYTES = int(
    os.getenv("ALPHA_AGENTFS_MAX_WORKSPACE_BYTES", str(20 * 1024 * 1024))
)
ALPHA_AGENTFS_PREVIEW_BYTES = int(
    os.getenv("ALPHA_AGENTFS_PREVIEW_BYTES", str(64 * 1024))
)
