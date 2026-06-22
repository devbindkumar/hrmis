"""Local-filesystem object storage.

Files are stored under UPLOAD_DIR (default /opt/hrmis/uploads).
This is a drop-in replacement for the previous Emergent storage helper:
the public API (init_storage / put_object / get_object) is unchanged so
the rest of the codebase doesn't need to know we swapped backends.
"""
import os
import mimetypes
import logging
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

# Where uploaded files live on disk.
# Defaults to <project_root>/uploads (i.e. /opt/hrmis/uploads on the VPS).
# Override via UPLOAD_DIR in .env for any other location (e.g. /var/lib/hrmis).
_DEFAULT_UPLOAD = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(_DEFAULT_UPLOAD))).expanduser().resolve()
APP_NAME = os.environ.get("APP_NAME", "hrmis")


def init_storage() -> str:
    """Make sure the upload directory exists. Returns the absolute path."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Local storage initialized at {UPLOAD_DIR}")
    return str(UPLOAD_DIR)


def _safe_path(rel_path: str) -> Path:
    """Resolve a storage path safely under UPLOAD_DIR (blocks ../ traversal)."""
    if not rel_path:
        raise ValueError("Empty storage path")
    if rel_path.startswith("/") or ".." in rel_path.split("/"):
        raise ValueError("Invalid storage path")
    full = (UPLOAD_DIR / rel_path).resolve()
    # Final check: the resolved path must still be inside UPLOAD_DIR.
    if not str(full).startswith(str(UPLOAD_DIR) + os.sep) and str(full) != str(UPLOAD_DIR):
        raise ValueError("Path traversal blocked")
    return full


def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Write bytes to UPLOAD_DIR/<path> and store its content-type in a sidecar."""
    full = _safe_path(path)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    # Persist content-type so downloads send the right header even if the
    # extension is unknown or missing.
    meta = full.with_suffix(full.suffix + ".meta")
    try:
        meta.write_text(content_type or "application/octet-stream")
    except OSError:
        pass
    return {"path": path, "size": len(data), "etag": str(full.stat().st_mtime_ns)}


def get_object(path: str) -> Tuple[bytes, str]:
    """Read the file back along with its stored or guessed content-type."""
    full = _safe_path(path)
    if not full.exists():
        raise FileNotFoundError(path)
    data = full.read_bytes()
    meta = full.with_suffix(full.suffix + ".meta")
    if meta.exists():
        try:
            content_type = meta.read_text().strip() or "application/octet-stream"
        except OSError:
            content_type = "application/octet-stream"
    else:
        content_type = mimetypes.guess_type(str(full))[0] or "application/octet-stream"
    return data, content_type
