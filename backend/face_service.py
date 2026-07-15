"""Face-recognition service for HRMIS attendance kiosk.

Design notes
------------
* Embeddings are produced client-side (browser) by ``@vladmandic/human`` and
  posted here as a plain ``list[float]`` of length ``EMBEDDING_DIM``. The
  backend never touches raw camera bytes for matching — just the vector.
* We match with Euclidean distance because ``human`` outputs L2-normalised
  descriptors; distance ≤ ``MATCH_THRESHOLD`` is a positive match.
* Anti-spoof + liveness scores are also produced client-side; we enforce
  minimum thresholds server-side so a tampered client cannot bypass them.
* Enrollment stores 3 samples per employee in ``employees.face.embeddings``
  and optionally saves the source JPEGs to ``uploads/faces/<company>/<empid>/``.
* Late-detection logic lives here so kiosk + web check-ins share one impl.
"""
from __future__ import annotations

import base64
import logging
import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from db import get_db

logger = logging.getLogger("hrmis.face")

EMBEDDING_DIM = 1024           # @vladmandic/human 3.3.x FaceRes v2 output size
MATCH_THRESHOLD = 0.6          # Euclidean distance on L2-normalised vectors (0..2)
MIN_LIVENESS_SCORE = 0.60      # 0..1; from human.result.face[0].live
MIN_ANTISPOOF_SCORE = 0.60     # 0..1; from human.result.face[0].real
MAX_ENROLL_SAMPLES = 5
DEFAULT_SAMPLES_REQUIRED = 3

FACES_DIR = os.environ.get("FACES_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "uploads", "faces"
)


# ─────────────────────────── vector math ────────────────────────────

def _euclid(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _l2_normalize(vec: List[float]) -> List[float]:
    """Unit-normalise so euclidean distance is dimension-independent (0..2)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0:
        return vec
    return [x / norm for x in vec]


def _validate_embedding(vec: Any) -> List[float]:
    if not isinstance(vec, list) or len(vec) != EMBEDDING_DIM:
        raise ValueError(
            f"Embedding must be a list of {EMBEDDING_DIM} floats "
            f"(got {type(vec).__name__} · len={len(vec) if isinstance(vec, list) else 'n/a'})"
        )
    out: List[float] = []
    for x in vec:
        if isinstance(x, (int, float)) and not math.isnan(float(x)) and math.isfinite(float(x)):
            out.append(float(x))
        else:
            raise ValueError("Embedding contains non-finite values")
    return _l2_normalize(out)


# ─────────────────────────── enrollment ─────────────────────────────

async def save_enrollment(
    *, company_id: str, employee_id: str,
    embeddings: List[List[float]], photos_b64: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Store embeddings on the employee doc and (optionally) save JPEGs to disk."""
    db = get_db()
    emp = await db.employees.find_one({"id": employee_id, "company_id": company_id}, {"_id": 0, "id": 1})
    if not emp:
        raise ValueError("Employee not found")
    if not embeddings or len(embeddings) < DEFAULT_SAMPLES_REQUIRED:
        raise ValueError(f"At least {DEFAULT_SAMPLES_REQUIRED} face samples are required")
    if len(embeddings) > MAX_ENROLL_SAMPLES:
        embeddings = embeddings[:MAX_ENROLL_SAMPLES]

    clean = [_validate_embedding(e) for e in embeddings]

    saved_photos: List[str] = []
    if photos_b64:
        emp_dir = os.path.join(FACES_DIR, company_id, employee_id)
        os.makedirs(emp_dir, exist_ok=True)
        for i, b64 in enumerate(photos_b64[:MAX_ENROLL_SAMPLES]):
            try:
                # accept data URLs OR raw base64
                if isinstance(b64, str) and "," in b64:
                    b64 = b64.split(",", 1)[1]
                raw = base64.b64decode(b64)
                # basic size guard — max ~1MB per sample
                if len(raw) > 1_500_000:
                    continue
                path = os.path.join(emp_dir, f"sample_{i}.jpg")
                with open(path, "wb") as f:
                    f.write(raw)
                saved_photos.append(f"{company_id}/{employee_id}/sample_{i}.jpg")
            except Exception as e:
                logger.warning(f"[face] photo save failed for {employee_id} #{i}: {e}")

    face_doc = {
        "embeddings": clean,
        "sample_count": len(clean),
        "photos": saved_photos,
        "has_photos": bool(saved_photos),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.employees.update_one(
        {"id": employee_id, "company_id": company_id},
        {"$set": {"face": face_doc}},
    )
    return {"enrolled": True, "sample_count": len(clean), "has_photos": bool(saved_photos)}


async def get_enrollment_status(company_id: str, employee_id: str) -> Dict[str, Any]:
    db = get_db()
    emp = await db.employees.find_one(
        {"id": employee_id, "company_id": company_id},
        {"_id": 0, "face.sample_count": 1, "face.updated_at": 1, "face.has_photos": 1},
    )
    if not emp:
        return {"enrolled": False}
    face = emp.get("face") or {}
    return {
        "enrolled": (face.get("sample_count") or 0) > 0,
        "sample_count": face.get("sample_count", 0),
        "has_photos": bool(face.get("has_photos", False)),
        "updated_at": face.get("updated_at"),
    }


async def delete_enrollment(company_id: str, employee_id: str) -> Dict[str, Any]:
    db = get_db()
    await db.employees.update_one(
        {"id": employee_id, "company_id": company_id},
        {"$unset": {"face": ""}},
    )
    emp_dir = os.path.join(FACES_DIR, company_id, employee_id)
    if os.path.isdir(emp_dir):
        for f in os.listdir(emp_dir):
            try:
                os.remove(os.path.join(emp_dir, f))
            except OSError:
                pass
    return {"success": True}


# ─────────────────────────── matching ───────────────────────────────

async def match_face(
    *, company_id: str, embedding: List[float],
) -> Optional[Dict[str, Any]]:
    """Find the closest enrolled employee within the same tenant.

    Returns ``{ employee_id, name, distance, confidence }`` if a match under
    ``MATCH_THRESHOLD`` is found, otherwise ``None``.
    """
    vec = _validate_embedding(embedding)
    db = get_db()
    cursor = db.employees.find(
        {"company_id": company_id, "status": "active", "face.sample_count": {"$gt": 0}},
        {"_id": 0, "id": 1, "name": 1, "avatar_url": 1, "face.embeddings": 1, "user_id": 1},
    )
    best: Optional[Tuple[float, Dict[str, Any]]] = None
    async for emp in cursor:
        for sample in (emp.get("face", {}).get("embeddings") or []):
            try:
                d = _euclid(vec, sample)
            except Exception:
                continue
            if best is None or d < best[0]:
                best = (d, {
                    "employee_id": emp["id"],
                    "user_id": emp.get("user_id"),
                    "name": emp.get("name"),
                    "avatar_url": emp.get("avatar_url"),
                })
    if not best or best[0] > MATCH_THRESHOLD:
        return None
    distance, hit = best
    # confidence is a friendly 0-1 score: 1 at distance 0, 0 at threshold
    confidence = max(0.0, 1.0 - distance / MATCH_THRESHOLD)
    hit["distance"] = round(distance, 4)
    hit["confidence"] = round(confidence, 3)
    return hit


# ─────────────────────────── shift config ───────────────────────────

DEFAULT_SHIFT_START = "09:30"
DEFAULT_GRACE_MIN = 15


async def resolve_shift_config(
    *, company_id: str, employee_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return effective (shift_start_time, late_grace_minutes) for an employee.

    Resolution order (each overrides the previous if set):
        1. Global default (09:30, 15 min)
        2. Company (companies.shift_start_time, companies.late_grace_minutes)
        3. Department (departments.shift_start_time, ...)
        4. Employee (employees.shift_start_time, ...)
    """
    db = get_db()
    shift_start = DEFAULT_SHIFT_START
    grace = DEFAULT_GRACE_MIN
    source = "default"

    company = await db.companies.find_one({"id": company_id}, {"_id": 0}) or {}
    if company.get("shift_start_time"):
        shift_start = company["shift_start_time"]
        source = "company"
    if isinstance(company.get("late_grace_minutes"), int):
        grace = company["late_grace_minutes"]

    emp: Dict[str, Any] = {}
    if employee_id:
        emp = await db.employees.find_one(
            {"id": employee_id, "company_id": company_id},
            {"_id": 0, "department_id": 1, "shift_start_time": 1, "late_grace_minutes": 1},
        ) or {}
        dept_id = emp.get("department_id")
        if dept_id:
            dept = await db.departments.find_one({"id": dept_id, "company_id": company_id}, {"_id": 0}) or {}
            if dept.get("shift_start_time"):
                shift_start = dept["shift_start_time"]
                source = "department"
            if isinstance(dept.get("late_grace_minutes"), int):
                grace = dept["late_grace_minutes"]
        if emp.get("shift_start_time"):
            shift_start = emp["shift_start_time"]
            source = "employee"
        if isinstance(emp.get("late_grace_minutes"), int):
            grace = emp["late_grace_minutes"]

    return {"shift_start_time": shift_start, "late_grace_minutes": grace, "source": source}


def is_check_in_late(check_in_iso: str, shift_start_time: str, grace_minutes: int, tz_name: str) -> bool:
    """Return True if a check-in timestamp is late per the shift rules."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        try:
            tz = ZoneInfo(tz_name or "Asia/Kolkata")
        except (ZoneInfoNotFoundError, Exception):
            tz = ZoneInfo("Asia/Kolkata")
        dt = datetime.fromisoformat(check_in_iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(tz)
        m = re.match(r"^(\d{1,2}):(\d{2})$", (shift_start_time or "09:30").strip())
        if not m:
            return False
        cutoff = local.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        cutoff_min = cutoff.hour * 60 + cutoff.minute + int(grace_minutes or 0)
        actual_min = local.hour * 60 + local.minute
        return actual_min > cutoff_min
    except Exception as e:
        logger.warning(f"[face] is_check_in_late error: {e}")
        return False


# ─────────────────────────── kiosk tokens ───────────────────────────

def new_kiosk_token() -> str:
    import secrets
    return secrets.token_urlsafe(24)


async def resolve_kiosk_company(token: str) -> Optional[Dict[str, Any]]:
    if not token or len(token) < 12:
        return None
    db = get_db()
    company = await db.companies.find_one(
        {"kiosk_token": token, "kiosk_enabled": True},
        {"_id": 0, "id": 1, "name": 1, "accent_color": 1, "has_logo": 1, "kiosk_enabled": 1},
    )
    return company
