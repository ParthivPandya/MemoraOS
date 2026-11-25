"""MemoraOS: local-first adaptive memory for AI agents."""

from .config import Settings
from .engine import MemoryOS, NotFoundError, PermissionDenied
from .models import RecallResult, Scope

__version__ = "0.7.0"
__all__ = ["MemoryOS", "NotFoundError", "PermissionDenied", "RecallResult", "Scope", "Settings", "__version__"]
