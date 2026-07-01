"""Unified notification dispatcher.

A single place that knows how to notify a user's reporting manager (or any
recipient) about HR events. It currently dispatches via WhatsApp Cloud API
(template-based) and is the *only* layer the route files should call for
WA notifications — keeping route files free of provider concerns.

All helpers are fire-and-forget safe: they catch all exceptions internally
and never propagate them to the calling FastAPI endpoint.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from db import get_db
from whatsapp_service import (
    DEFAULT_STATUS_FILTERS,
    DEFAULT_TEMPLATES,
    get_config,
    send_template,
)

logger = logging.getLogger("hrmis.notifications")


# ---------- helpers ----------

STATUS_LABELS = {
    "active": "Active",
    "present": "Active",
    "on_break": "On Break",
    "in_meeting": "In a Meeting",
    "remote": "Working from Home",
    "wfh": "Working from Home",
    "offline": "Offline",
}

# India Standard Time is the default because the customer's ops are India-based.
# Admins can override via the `timezone` field on whatsapp_configs (any IANA
# zone name, e.g. "America/New_York", "Europe/London").
DEFAULT_TZ = "Asia/Kolkata"
TZ_ABBRS = {
    "Asia/Kolkata": "IST",
    "Asia/Calcutta": "IST",
    "UTC": "UTC",
    "America/New_York": "ET",
    "America/Los_Angeles": "PT",
    "Europe/London": "GMT",
}


def _resolve_tz(tz_name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, Exception):
        return ZoneInfo(DEFAULT_TZ)


def _tz_abbr(tz_name: str) -> str:
    return TZ_ABBRS.get(tz_name, tz_name.split("/")[-1])


async def _tenant_tz(company_id: str) -> str:
    cfg = await get_config(company_id) or {}
    return cfg.get("timezone") or DEFAULT_TZ


def _fmt_now(tz_name: str = DEFAULT_TZ) -> str:
    tz = _resolve_tz(tz_name)
    return datetime.now(tz).strftime("%d %b %Y, %H:%M ") + _tz_abbr(tz_name)


def _fmt_iso(ts_iso: str, tz_name: str = DEFAULT_TZ) -> str:
    """Convert an ISO-8601 timestamp (assumed UTC if naive) to a pretty string
    in the given tenant timezone."""
    try:
        dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_resolve_tz(tz_name)).strftime("%d %b %Y, %H:%M ") + _tz_abbr(tz_name)
    except Exception:
        return ts_iso


def _fmt_status(s: str) -> str:
    return STATUS_LABELS.get(s, s.replace("_", " ").title())


async def _resolve_manager(company_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Return the manager's employee record (with phone) for a given user, if any."""
    db = get_db()
    emp = await db.employees.find_one(
        {"user_id": user_id, "company_id": company_id},
        {"_id": 0, "manager_id": 1},
    )
    if not emp or not emp.get("manager_id"):
        return None
    mgr = await db.employees.find_one(
        {"id": emp["manager_id"], "company_id": company_id},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "user_id": 1, "email": 1},
    )
    return mgr


async def _resolve_employee_name(company_id: str, user_id: str) -> str:
    db = get_db()
    emp = await db.employees.find_one(
        {"user_id": user_id, "company_id": company_id},
        {"_id": 0, "name": 1},
    )
    if emp and emp.get("name"):
        return emp["name"]
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "name": 1})
    return (u or {}).get("name", "Someone")


async def _event_enabled(company_id: str, event_key: str) -> bool:
    cfg = await get_config(company_id)
    if not cfg or not cfg.get("enabled"):
        return False
    events = cfg.get("events_enabled") or {}
    # default True for known events when key missing
    return bool(events.get(event_key, True))


async def _template_name(company_id: str, event_key: str) -> str:
    cfg = await get_config(company_id) or {}
    templates = cfg.get("templates") or {}
    return templates.get(event_key) or DEFAULT_TEMPLATES.get(event_key, "")


async def _status_filters(company_id: str) -> List[str]:
    cfg = await get_config(company_id) or {}
    return cfg.get("status_filters") or DEFAULT_STATUS_FILTERS


# ---------- event dispatchers ----------

async def notify_leave_request(
    *, company_id: str, employee_user_id: str, employee_name: str,
    leave_type: str, start_date: str, end_date: str, reason: str,
) -> None:
    try:
        if not await _event_enabled(company_id, "leave_request"):
            return
        mgr = await _resolve_manager(company_id, employee_user_id)
        if not mgr or not mgr.get("phone"):
            return
        tmpl = await _template_name(company_id, "leave_request")
        params = [
            mgr.get("name", "Manager"),
            employee_name,
            leave_type,
            start_date,
            end_date,
            (reason or "—")[:200],
        ]
        await send_template(company_id, mgr["phone"], tmpl, params)
    except Exception as e:
        logger.error(f"notify_leave_request error: {e}")


async def notify_wfh_request(
    *, company_id: str, employee_user_id: str, employee_name: str,
    date_str: str, reason: str,
) -> None:
    try:
        if not await _event_enabled(company_id, "wfh_request"):
            return
        mgr = await _resolve_manager(company_id, employee_user_id)
        if not mgr or not mgr.get("phone"):
            return
        tmpl = await _template_name(company_id, "wfh_request")
        params = [
            mgr.get("name", "Manager"),
            employee_name,
            date_str,
            (reason or "—")[:200],
        ]
        await send_template(company_id, mgr["phone"], tmpl, params)
    except Exception as e:
        logger.error(f"notify_wfh_request error: {e}")


async def notify_meeting_scheduled(
    *, company_id: str, organizer_name: str, title: str,
    starts_at: str, location: str, attendee_user_ids: List[str],
) -> None:
    """Notify every attendee. Sends per-attendee (only those with phone)."""
    try:
        if not await _event_enabled(company_id, "meeting_scheduled"):
            return
        if not attendee_user_ids:
            return
        db = get_db()
        attendees = await db.employees.find(
            {"user_id": {"$in": attendee_user_ids}, "company_id": company_id},
            {"_id": 0, "name": 1, "phone": 1, "user_id": 1},
        ).to_list(500)
        tmpl = await _template_name(company_id, "meeting_scheduled")
        # Split "starts_at" ISO into date + time for cleaner template
        date_part, time_part = starts_at, ""
        if "T" in starts_at:
            date_part, time_part = starts_at.split("T", 1)
            time_part = time_part[:5]
        for att in attendees:
            phone = att.get("phone")
            if not phone:
                continue
            params = [
                att.get("name", "there"),
                organizer_name,
                title,
                date_part,
                time_part or location or "—",
            ]
            await send_template(company_id, phone, tmpl, params)
    except Exception as e:
        logger.error(f"notify_meeting_scheduled error: {e}")


async def notify_status_update(
    *, company_id: str, employee_user_id: str, new_status: str,
) -> None:
    try:
        if not await _event_enabled(company_id, "status_update"):
            return
        filters = await _status_filters(company_id)
        if new_status not in filters:
            return
        mgr = await _resolve_manager(company_id, employee_user_id)
        if not mgr or not mgr.get("phone"):
            return
        emp_name = await _resolve_employee_name(company_id, employee_user_id)
        tmpl = await _template_name(company_id, "status_update")
        tz_name = await _tenant_tz(company_id)
        params = [
            mgr.get("name", "Manager"),
            emp_name,
            _fmt_status(new_status),
            _fmt_now(tz_name),
        ]
        await send_template(company_id, mgr["phone"], tmpl, params)
    except Exception as e:
        logger.error(f"notify_status_update error: {e}")


async def notify_checkin_checkout(
    *, company_id: str, employee_user_id: str, action: str, ts_iso: str,
) -> None:
    """action = 'Checked In' or 'Checked Out'."""
    try:
        if not await _event_enabled(company_id, "checkin_checkout"):
            return
        mgr = await _resolve_manager(company_id, employee_user_id)
        if not mgr or not mgr.get("phone"):
            return
        emp_name = await _resolve_employee_name(company_id, employee_user_id)
        tmpl = await _template_name(company_id, "checkin_checkout")
        tz_name = await _tenant_tz(company_id)
        params = [
            mgr.get("name", "Manager"),
            emp_name,
            action,
            _fmt_iso(ts_iso, tz_name),
        ]
        await send_template(company_id, mgr["phone"], tmpl, params)
    except Exception as e:
        logger.error(f"notify_checkin_checkout error: {e}")
