from .auth import ApiKeyStore, Principal

__all__ = ["ApiKeyStore", "Principal", "create_app"]


def create_app(*args, **kwargs):  # lazy import keeps FastAPI optional
    from .app import create_app as _create

    return _create(*args, **kwargs)
