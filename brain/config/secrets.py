"""Re-export from jarvis_common — kept for backward compatibility."""

from jarvis_common.secrets import get_secret, register_audit_hook, clear_cache

__all__ = ["get_secret", "register_audit_hook", "clear_cache"]
