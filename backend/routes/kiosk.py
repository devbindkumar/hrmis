"""Public kiosk endpoints for the face-recognition attendance scanner.

These endpoints are UNAUTHENTICATED — access is gated by a per-company
``kiosk_token`` bootstrapped by the super_admin in Settings. Each kiosk
device holds the URL ``/kiosk/scan?token=<TOKEN>`` (typically loaded in
full-screen browser at the office entrance).

Endpoints:
    GET  /api/kiosk/session         → company info (name, logo, accent)
    POST /api/kiosk/match           → embedding → matched employee
    POST /api/kiosk/check-in        → confirm check-in for a matched user
    POST /api/kiosk/check-out       → confirm check-out for a matched user
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from db import get_db
from face_service import (
    MIN_ANTISPOOF_SCORE,
    MIN_LIVENESS_SCORE,
    is_check_in_late,
    match_face,
    resolve_kiosk_company,
    resolve_shift_config,
)
from notification_service import notify_checkin_checkout

logger = logging.getLogger("hrmis.kiosk")

router = APIRouter(prefix="/api/kiosk", tags=["kiosk"])


# ─────────────────────────── payloads ───────────────────────────

class MatchRequest(BaseModel):
    token: str = Field(min_length=8)
    embedding: List[float]
    liveness_score: Optional[float] = None
    antispoof_score: Optional[float] = None


class KioskAction(BaseModel):
    token: str = Field(min_length=8)
    employee_id: str


# ─────────────────────────── helpers ────────────────────────────

async def _require_kiosk(token: str) -> dict:
    company = await resolve_kiosk_company(token)
    if not company:
        raise HTTPException(status_code=401, detail="Invalid or disabled kiosk token")
    return company


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ─────────────────────────── routes ─────────────────────────────

@router.get("/session")
async def kiosk_session(token: str = Query(min_length=8)):
    """Return the tenant metadata the scanner UI needs to render itself."""
    company = await _require_kiosk(token)
    return {
        "company": {
            "id": company["id"],
            "name": company["name"],
            "accent_color": company.get("accent_color", "#0f172a"),
            "has_logo": bool(company.get("has_logo", False)),
        },
        "thresholds": {
            "min_liveness": MIN_LIVENESS_SCORE,
            "min_antispoof": MIN_ANTISPOOF_SCORE,
        },
    }


@router.post("/match")
async def kiosk_match(body: MatchRequest):
    company = await _require_kiosk(body.token)
    # Anti-spoof + liveness gate (client posts; server enforces)
    if body.liveness_score is not None and body.liveness_score < MIN_LIVENESS_SCORE:
        raise HTTPException(status_code=400, detail={"code": "LIVENESS_FAIL", "score": body.liveness_score})
    if body.antispoof_score is not None and body.antispoof_score < MIN_ANTISPOOF_SCORE:
        raise HTTPException(status_code=400, detail={"code": "SPOOF_DETECTED", "score": body.antispoof_score})

    try:
        hit = await match_face(company_id=company["id"], embedding=body.embedding)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not hit:
        return {"matched": False}

    # attach current attendance so the UI knows which button to highlight
    db = get_db()
    att = await db.attendance.find_one(
        {"user_id": hit["user_id"], "date": _today_str()},
        {"_id": 0, "check_in": 1, "check_out": 1, "current_status": 1},
    ) or {}
    already_checked_in = bool(att.get("check_in") and not att.get("check_out"))
    already_checked_out = bool(att.get("check_out"))

    return {
        "matched": True,
        "employee": {
            "id": hit["employee_id"],
            "user_id": hit["user_id"],
            "name": hit["name"],
            "avatar_url": hit.get("avatar_url"),
        },
        "confidence": hit.get("confidence", 0),
        "distance": hit.get("distance"),
        "attendance": {
            "checked_in": already_checked_in,
            "checked_out": already_checked_out,
            "check_in": att.get("check_in"),
            "check_out": att.get("check_out"),
            "current_status": att.get("current_status"),
        },
    }


async def _perform_check_in(company_id: str, employee_id: str, tz_name: str) -> dict:
    db = get_db()
    emp = await db.employees.find_one(
        {"id": employee_id, "company_id": company_id},
        {"_id": 0, "user_id": 1, "name": 1},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    today = _today_str()
    now = _now_iso()
    existing = await db.attendance.find_one({"user_id": emp["user_id"], "date": today}, {"_id": 0})
    if existing and existing.get("check_in"):
        raise HTTPException(status_code=400, detail="Already checked in today")

    shift = await resolve_shift_config(company_id=company_id, employee_id=employee_id)
    late = is_check_in_late(now, shift["shift_start_time"], shift["late_grace_minutes"], tz_name)

    doc = {
        "id": existing["id"] if existing else str(uuid.uuid4()),
        "user_id": emp["user_id"],
        "company_id": company_id,
        "date": today,
        "check_in": now,
        "check_out": None,
        "status": "present",
        "current_status": "active",
        "breaks": [],
        "is_late": late,
        "via": "kiosk",
        "shift_start_time": shift["shift_start_time"],
        "shift_source": shift["source"],
    }
    await db.attendance.update_one({"user_id": emp["user_id"], "date": today}, {"$set": doc}, upsert=True)
    # WhatsApp — reuse existing notification path
    await notify_checkin_checkout(
        company_id=company_id, employee_user_id=emp["user_id"], action="Checked In", ts_iso=now,
    )
    return {"success": True, "employee_name": emp["name"], "is_late": late, "via": "kiosk"}


async def _perform_check_out(company_id: str, employee_id: str) -> dict:
    db = get_db()
    emp = await db.employees.find_one(
        {"id": employee_id, "company_id": company_id},
        {"_id": 0, "user_id": 1, "name": 1},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    today = _today_str()
    rec = await db.attendance.find_one({"user_id": emp["user_id"], "date": today}, {"_id": 0})
    if not rec or not rec.get("check_in"):
        raise HTTPException(status_code=400, detail="Not checked in today")
    if rec.get("check_out"):
        raise HTTPException(status_code=400, detail="Already checked out today")

    now = _now_iso()
    check_in_dt = datetime.fromisoformat(rec["check_in"].replace("Z", "+00:00"))
    duration = int((datetime.fromisoformat(now).replace(tzinfo=timezone.utc) - check_in_dt).total_seconds()) if check_in_dt.tzinfo else 0
    await db.attendance.update_one(
        {"user_id": emp["user_id"], "date": today},
        {"$set": {
            "check_out": now,
            "current_status": "offline",
            "duration_seconds": max(0, duration),
            "via_out": "kiosk",
        }},
    )
    await notify_checkin_checkout(
        company_id=company_id, employee_user_id=emp["user_id"], action="Checked Out", ts_iso=now,
    )
    return {"success": True, "employee_name": emp["name"], "via": "kiosk"}


@router.post("/check-in")
async def kiosk_check_in(body: KioskAction):
    company = await _require_kiosk(body.token)
    # tenant tz lives on whatsapp_configs — reuse it for consistent late-detection
    db = get_db()
    wa = await db.whatsapp_configs.find_one({"company_id": company["id"]}, {"_id": 0, "timezone": 1}) or {}
    tz_name = wa.get("timezone") or "Asia/Kolkata"
    return await _perform_check_in(company["id"], body.employee_id, tz_name)


@router.post("/check-out")
async def kiosk_check_out(body: KioskAction):
    company = await _require_kiosk(body.token)
    return await _perform_check_out(company["id"], body.employee_id)


# ─── Admin-only activity feed ────────────────────────────────────────

from auth import require_roles  # noqa: E402
from tenant import company_id_of  # noqa: E402
from fastapi import Depends, Query as FQuery  # noqa: E402


@router.get("/activity")
async def kiosk_activity(
    admin: dict = Depends(require_roles("super_admin", "hr")),
    limit: int = FQuery(default=20, ge=1, le=100),
):
    """Recent kiosk-driven attendance events for the current tenant.

    Returns the last N ``check_in`` or ``check_out`` records that were
    written by the face-scanner kiosk (``via='kiosk'`` or ``via_out='kiosk'``),
    joined with the employee name + avatar. Perfect for an audit feed
    on the admin dashboard.
    """
    db = get_db()
    cid = company_id_of(admin)
    q = {
        "company_id": cid,
        "$or": [{"via": "kiosk"}, {"via_out": "kiosk"}],
    }
    rows = await db.attendance.find(q, {"_id": 0}).sort([
        ("check_in", -1), ("date", -1),
    ]).to_list(limit * 2)  # over-fetch to account for split in/out events

    events: List[Dict[str, Any]] = []
    user_ids = list({r.get("user_id") for r in rows if r.get("user_id")})
    if user_ids:
        emps = await db.employees.find(
            {"user_id": {"$in": user_ids}, "company_id": cid},
            {"_id": 0, "user_id": 1, "name": 1, "avatar_url": 1},
        ).to_list(len(user_ids))
        emp_by_uid = {e["user_id"]: e for e in emps}
    else:
        emp_by_uid = {}

    for r in rows:
        emp = emp_by_uid.get(r.get("user_id")) or {}
        base = {
            "employee_user_id": r.get("user_id"),
            "employee_name": emp.get("name") or "Unknown",
            "avatar_url": emp.get("avatar_url"),
            "date": r.get("date"),
            "is_late": bool(r.get("is_late")),
            "shift_start_time": r.get("shift_start_time"),
        }
        if r.get("via") == "kiosk" and r.get("check_in"):
            events.append({**base, "action": "check_in", "at": r["check_in"]})
        if r.get("via_out") == "kiosk" and r.get("check_out"):
            events.append({**base, "action": "check_out", "at": r["check_out"]})

    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return {"events": events[:limit], "total": len(events)}
