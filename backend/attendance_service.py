"""Attendance domain logic — session tracking, event log, per-day statistics.

Design decisions
----------------
* An attendance record is one **document per (user_id, date)**. That doc is
  authoritative for the day and carries the latest `check_in` / `check_out`
  for backwards-compatibility with existing UI code.
* A `sessions` array is appended to the same doc. Each session is
  ``{"in": iso, "out": iso|None}``. A day can have multiple sessions when the
  employee accidentally checked out and used **Re-Check-In**.
* Every state transition (check_in / check_out / re_check_in / status change)
  is also written to the **``attendance_events`` collection** for a
  tamper-evident audit trail: (user_id, date, event_type, ts, via, actor,
  meta). Nothing is ever deleted from this log.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, time as dtime
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from db import get_db


UTC = timezone.utc


def _tz(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, Exception):
        return ZoneInfo("UTC")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso() -> str:
    return _now().isoformat()


async def log_event(
    *,
    company_id: str,
    user_id: str,
    date: str,
    event_type: str,
    ts: Optional[str] = None,
    via: str = "web",
    actor_user_id: Optional[str] = None,
    meta: Optional[dict] = None,
) -> dict:
    """Append an immutable event to the audit log."""
    db = get_db()
    doc = {
        "id": str(uuid.uuid4()),
        "company_id": company_id,
        "user_id": user_id,
        "date": date,
        "event_type": event_type,   # check_in | check_out | re_check_in | status_change
        "ts": ts or _iso(),
        "via": via,                 # web | kiosk | admin | api
        "actor_user_id": actor_user_id or user_id,
        "meta": meta or {},
    }
    await db.attendance_events.insert_one(doc)
    doc.pop("_id", None)
    return doc


def sum_session_seconds(sessions: list[dict], *, until: Optional[datetime] = None) -> int:
    """Total worked seconds across all sessions.

    An open session counts up to ``until`` (default: now)."""
    if not sessions:
        return 0
    ref = until or _now()
    total = 0
    for s in sessions:
        try:
            start = datetime.fromisoformat(s["in"].replace("Z", "+00:00"))
        except Exception:
            continue
        end = None
        if s.get("out"):
            try:
                end = datetime.fromisoformat(s["out"].replace("Z", "+00:00"))
            except Exception:
                end = None
        if end is None:
            end = ref
        if end > start:
            total += int((end - start).total_seconds())
    return total


def _localise(iso: str, tz) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz)


def _parse_hhmm(hhmm: str) -> Optional[dtime]:
    try:
        h, m = hhmm.split(":")
        return dtime(int(h), int(m))
    except Exception:
        return None


def compute_stats(record: dict, *, shift_start_time: str, shift_end_time: str,
                  grace_minutes: int, tz_name: str = "Asia/Kolkata") -> dict:
    """Derive per-day attendance statistics from an attendance document.

    Returns a dict with:
      total_seconds, total_hours, sessions_count,
      first_check_in_local (HH:MM), last_check_out_local (HH:MM),
      late_minutes, is_late,
      early_departure_minutes, overtime_hours
    """
    try:
        tz = _tz(tz_name)
    except Exception:
        tz = _tz("UTC")

    sessions = record.get("sessions") or []
    # backfill sessions for legacy records
    if not sessions and record.get("check_in"):
        sessions = [{"in": record["check_in"], "out": record.get("check_out")}]

    total_seconds = sum_session_seconds(sessions)

    first_iso = sessions[0]["in"] if sessions else record.get("check_in")
    last_iso = None
    if sessions:
        for s in reversed(sessions):
            if s.get("out"):
                last_iso = s["out"]
                break
    if last_iso is None:
        last_iso = record.get("check_out")

    first_local = _localise(first_iso, tz) if first_iso else None
    last_local = _localise(last_iso, tz) if last_iso else None

    shift_start = _parse_hhmm(shift_start_time or "09:00")
    shift_end = _parse_hhmm(shift_end_time or "18:00")

    # late calc
    late_minutes = 0
    is_late = False
    if first_local and shift_start:
        cut_h = shift_start.hour
        cut_m = shift_start.minute + int(grace_minutes or 0)
        cut_h += cut_m // 60
        cut_m = cut_m % 60
        cutoff = first_local.replace(hour=cut_h, minute=cut_m, second=0, microsecond=0)
        if first_local > cutoff:
            late_minutes = int((first_local - cutoff).total_seconds() // 60)
            is_late = True

    # early departure calc — only if the day is closed
    early_departure_minutes = 0
    day_closed = bool(sessions and sessions[-1].get("out"))
    if day_closed and last_local and shift_end:
        expected_out = last_local.replace(hour=shift_end.hour, minute=shift_end.minute,
                                          second=0, microsecond=0)
        if last_local < expected_out:
            early_departure_minutes = int((expected_out - last_local).total_seconds() // 60)

    # overtime — anything worked beyond 8h counted as overtime (simple rule)
    shift_seconds = 8 * 3600
    if shift_start and shift_end:
        s_seconds = shift_start.hour * 3600 + shift_start.minute * 60
        e_seconds = shift_end.hour * 3600 + shift_end.minute * 60
        if e_seconds > s_seconds:
            shift_seconds = e_seconds - s_seconds
    overtime_seconds = max(0, total_seconds - shift_seconds)

    return {
        "total_seconds": total_seconds,
        "total_hours": round(total_seconds / 3600, 2),
        "sessions_count": len(sessions),
        "first_check_in_local": first_local.strftime("%H:%M") if first_local else "",
        "last_check_out_local": last_local.strftime("%H:%M") if last_local else "",
        "late_minutes": late_minutes,
        "is_late": is_late,
        "early_departure_minutes": early_departure_minutes,
        "overtime_hours": round(overtime_seconds / 3600, 2),
    }
