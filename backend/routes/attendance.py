import csv
import io
import uuid
from datetime import datetime, timezone, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from attendance_service import compute_stats, log_event, sum_session_seconds
from auth import get_current_user, require_roles
from db import get_db
from face_service import is_check_in_late, resolve_shift_config
from notification_service import notify_checkin_checkout, notify_status_update
from tenant import company_id_of

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _company_tz(cid: str) -> str:
    db = get_db()
    wa = await db.whatsapp_configs.find_one({"company_id": cid}, {"_id": 0, "timezone": 1}) or {}
    return wa.get("timezone") or "Asia/Kolkata"


@router.get("/today")
async def today_status(user: dict = Depends(get_current_user)):
    db = get_db()
    today = _today_str()
    rec = await db.attendance.find_one({"user_id": user["id"], "date": today}, {"_id": 0})
    return rec or {
        "user_id": user["id"], "date": today,
        "check_in": None, "check_out": None,
        "sessions": [], "status": "absent", "breaks": [],
    }


class StatusUpdate(BaseModel):
    status: str  # active | on_break | in_meeting | wfh | offline


@router.post("/check-in")
async def check_in(user: dict = Depends(get_current_user)):
    db = get_db()
    today = _today_str()
    now = _now_iso()
    existing = await db.attendance.find_one({"user_id": user["id"], "date": today}, {"_id": 0})
    if existing and existing.get("check_in") and not existing.get("check_out"):
        raise HTTPException(status_code=400, detail="Already checked in today")
    if existing and existing.get("check_out"):
        raise HTTPException(
            status_code=400,
            detail="You already checked out today. Use Re-Check-In to reopen your day.",
        )

    cid = company_id_of(user)
    emp_doc = await db.employees.find_one({"user_id": user["id"], "company_id": cid}, {"_id": 0, "id": 1})
    shift = await resolve_shift_config(company_id=cid, employee_id=(emp_doc or {}).get("id"))
    tz_name = await _company_tz(cid)
    late = is_check_in_late(now, shift["shift_start_time"], shift["late_grace_minutes"], tz_name)

    doc = {
        "id": existing["id"] if existing else str(uuid.uuid4()),
        "user_id": user["id"],
        "company_id": cid,
        "date": today,
        "check_in": now,
        "check_out": None,
        "sessions": [{"in": now, "out": None}],
        "status": "present",
        "current_status": "active",
        "breaks": [],
        "is_late": late,
        "via": "web",
        "shift_start_time": shift["shift_start_time"],
        "shift_source": shift["source"],
    }
    await db.attendance.update_one({"user_id": user["id"], "date": today}, {"$set": doc}, upsert=True)
    await log_event(company_id=cid, user_id=user["id"], date=today,
                    event_type="check_in", ts=now, via="web",
                    meta={"is_late": late, "shift_start_time": shift["shift_start_time"]})
    return doc


@router.post("/check-out")
async def check_out(user: dict = Depends(get_current_user)):
    db = get_db()
    today = _today_str()
    rec = await db.attendance.find_one({"user_id": user["id"], "date": today}, {"_id": 0})
    if not rec or not rec.get("check_in"):
        raise HTTPException(status_code=400, detail="You haven't checked in yet")
    if rec.get("check_out"):
        raise HTTPException(status_code=400, detail="Already checked out today")

    now = _now_iso()
    sessions = rec.get("sessions") or [{"in": rec["check_in"], "out": None}]
    if sessions and sessions[-1].get("out") is None:
        sessions[-1]["out"] = now
    duration_seconds = sum_session_seconds(sessions)

    await db.attendance.update_one(
        {"user_id": user["id"], "date": today},
        {"$set": {
            "check_out": now,
            "current_status": "offline",
            "duration_seconds": duration_seconds,
            "sessions": sessions,
        }},
    )
    await log_event(company_id=company_id_of(user), user_id=user["id"], date=today,
                    event_type="check_out", ts=now, via="web",
                    meta={"session_index": len(sessions) - 1, "duration_seconds": duration_seconds})
    await notify_checkin_checkout(
        company_id=company_id_of(user),
        employee_user_id=user["id"],
        action="Checked Out",
        ts_iso=now,
    )
    updated = await db.attendance.find_one({"user_id": user["id"], "date": today}, {"_id": 0})
    return updated


@router.post("/re-check-in")
async def re_check_in(user: dict = Depends(get_current_user)):
    """Reopen the day after an accidental check-out.

    * Only allowed if the employee has ALREADY checked out today.
    * Appends a new open session; the audit log preserves the previous
      checkout for transparency.
    """
    db = get_db()
    today = _today_str()
    rec = await db.attendance.find_one({"user_id": user["id"], "date": today}, {"_id": 0})
    if not rec or not rec.get("check_in"):
        raise HTTPException(status_code=400, detail="You haven't checked in today yet")
    if not rec.get("check_out"):
        raise HTTPException(status_code=400, detail="You are still checked in — nothing to reopen")

    now = _now_iso()
    sessions = rec.get("sessions") or [{"in": rec["check_in"], "out": rec.get("check_out")}]
    sessions.append({"in": now, "out": None})

    await db.attendance.update_one(
        {"user_id": user["id"], "date": today},
        {"$set": {
            "sessions": sessions,
            "check_out": None,          # day is open again
            "current_status": "active",
            "status": "present",
        }},
    )
    await log_event(company_id=company_id_of(user), user_id=user["id"], date=today,
                    event_type="re_check_in", ts=now, via="web",
                    meta={"session_index": len(sessions) - 1,
                          "previous_check_out": rec.get("check_out")})
    updated = await db.attendance.find_one({"user_id": user["id"], "date": today}, {"_id": 0})
    return updated


@router.post("/status")
async def set_status(body: StatusUpdate, user: dict = Depends(get_current_user)):
    db = get_db()
    today = _today_str()
    await db.attendance.update_one(
        {"user_id": user["id"], "date": today},
        {"$set": {"current_status": body.status, "last_active": _now_iso()}},
        upsert=True,
    )
    await log_event(company_id=company_id_of(user), user_id=user["id"], date=today,
                    event_type="status_change", via="web", meta={"status": body.status})
    await notify_status_update(
        company_id=company_id_of(user),
        employee_user_id=user["id"],
        new_status=body.status,
    )
    return {"success": True, "status": body.status}


@router.get("/events")
async def my_events(
    user: dict = Depends(get_current_user),
    days: int = 1,
):
    """Recent check-in/out/re-check-in audit trail for the calling user."""
    db = get_db()
    since = (datetime.now(timezone.utc).date() - timedelta(days=max(0, days - 1))).isoformat()
    events = await db.attendance_events.find(
        {"user_id": user["id"], "date": {"$gte": since}},
        {"_id": 0},
    ).sort("ts", -1).to_list(200)
    return events


@router.get("/history")
async def my_history(user: dict = Depends(get_current_user), days: int = 30):
    db = get_db()
    since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    items = await db.attendance.find(
        {"user_id": user["id"], "date": {"$gte": since}},
        {"_id": 0},
    ).sort("date", -1).to_list(200)
    return items


@router.get("/monitor")
async def monitor(admin: dict = Depends(require_roles("super_admin", "hr", "manager")), day: Optional[str] = None):
    """Return attendance for everyone for a specific day (default today).

    Scope:
      • super_admin / hr — every active employee in the company.
      • manager — only the manager's own direct reports (employees whose
        `manager_id` equals the manager's employee record id).
    """
    db = get_db()
    cid = company_id_of(admin)
    target = day or _today_str()

    emp_query: dict = {"status": "active", "company_id": cid}
    if admin.get("role") == "manager":
        me = await db.employees.find_one(
            {"user_id": admin["id"], "company_id": cid}, {"_id": 0, "id": 1}
        )
        # If the manager has no employee record OR no direct reports we still
        # return an empty rows list rather than 500.
        emp_query["manager_id"] = me["id"] if me else "__none__"

    employees = await db.employees.find(emp_query, {"_id": 0}).to_list(500)
    user_ids = [e["user_id"] for e in employees]
    attendance = await db.attendance.find({"user_id": {"$in": user_ids}, "date": target}, {"_id": 0}).to_list(500)
    a_map = {a["user_id"]: a for a in attendance}

    on_leave = await db.leave_requests.find({
        "company_id": cid,
        "status": "approved",
        "start_date": {"$lte": target},
        "end_date": {"$gte": target},
    }, {"_id": 0}).to_list(500)
    leave_users = {l["user_id"] for l in on_leave}

    on_wfh = await db.wfh_requests.find({
        "company_id": cid,
        "status": "approved",
        "date": target,
    }, {"_id": 0}).to_list(500)
    wfh_users = {w["user_id"] for w in on_wfh}

    rows = []
    for emp in employees:
        a = a_map.get(emp["user_id"])
        if emp["user_id"] in leave_users:
            status = "on_leave"
        elif emp["user_id"] in wfh_users:
            status = a.get("current_status", "remote") if a else "remote"
            if status not in ("remote", "in_meeting", "on_break"):
                status = "remote"
        elif a and a.get("check_in"):
            status = a.get("current_status", "active") or "active"
            if status == "active":
                status = "present"
        else:
            status = "absent"

        rows.append({
            "employee_id": emp["id"],
            "user_id": emp["user_id"],
            "name": emp["name"],
            "avatar_url": emp.get("avatar_url"),
            "department": emp.get("department"),
            "designation": emp.get("designation"),
            "check_in": a.get("check_in") if a else None,
            "check_out": a.get("check_out") if a else None,
            "sessions_count": len(a.get("sessions") or []) if a else 0,
            "is_late": a.get("is_late", False) if a else False,
            "status": status,
        })
    return {"date": target, "rows": rows}


# ─────────────────────────── export ───────────────────────────

_EXPORT_HEADERS = [
    "Date", "Employee Code", "Name", "Department", "Designation", "Email",
    "First Check-in", "Last Check-out", "Sessions",
    "Total Hours", "Late", "Late Minutes", "Early Departure Minutes",
    "Overtime Hours", "Status", "Notes",
]


@router.get("/export")
async def export_attendance(
    start: str,
    end: str,
    department: Optional[str] = None,
    admin: dict = Depends(require_roles("super_admin", "hr")),
):
    """Stream a CSV export of attendance for every employee across the range."""
    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except Exception:
        raise HTTPException(status_code=400, detail="start/end must be YYYY-MM-DD")
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end must be on or after start")
    if (end_d - start_d).days > 366:
        raise HTTPException(status_code=400, detail="Range cannot exceed 366 days")

    db = get_db()
    cid = company_id_of(admin)
    tz_name = await _company_tz(cid)

    # Fetch employees (optionally filtered by department)
    emp_query: dict = {"company_id": cid}
    if department and department != "all":
        emp_query["department"] = department
    employees = await db.employees.find(
        emp_query,
        {"_id": 0, "id": 1, "user_id": 1, "name": 1, "email": 1, "department": 1,
         "designation": 1, "employee_code": 1, "shift_start_time": 1, "late_grace_minutes": 1},
    ).sort("name", 1).to_list(2000)
    user_ids = [e["user_id"] for e in employees]

    start_iso = start_d.isoformat()
    end_iso = end_d.isoformat()

    # Bulk load attendance across the range
    attendance = await db.attendance.find(
        {"user_id": {"$in": user_ids}, "date": {"$gte": start_iso, "$lte": end_iso}},
        {"_id": 0},
    ).to_list(20000)
    a_key = {(a["user_id"], a["date"]): a for a in attendance}

    # Approved leaves overlapping the range
    leaves = await db.leave_requests.find({
        "company_id": cid, "status": "approved",
        "user_id": {"$in": user_ids},
        "start_date": {"$lte": end_iso}, "end_date": {"$gte": start_iso},
    }, {"_id": 0, "user_id": 1, "start_date": 1, "end_date": 1, "leave_type": 1}).to_list(5000)

    # WFH approved
    wfh = await db.wfh_requests.find({
        "company_id": cid, "status": "approved",
        "user_id": {"$in": user_ids},
        "date": {"$gte": start_iso, "$lte": end_iso},
    }, {"_id": 0, "user_id": 1, "date": 1}).to_list(5000)
    wfh_set = {(w["user_id"], w["date"]) for w in wfh}

    def _is_on_leave(uid: str, d: str) -> Optional[str]:
        for l in leaves:
            if l["user_id"] == uid and l["start_date"] <= d <= l["end_date"]:
                return l.get("leave_type", "Leave")
        return None

    # Resolve shift config once per employee
    from face_service import resolve_shift_config  # local import to avoid cycles

    shifts = {}
    for e in employees:
        s = await resolve_shift_config(company_id=cid, employee_id=e["id"])
        shifts[e["id"]] = s
    # Company-level end time (fallback to 18:00)
    company = await db.companies.find_one({"id": cid}, {"_id": 0, "shift_end_time": 1}) or {}
    company_shift_end = company.get("shift_end_time") or "18:00"

    # Build rows
    def _iter_dates(s, e):
        cur = s
        while cur <= e:
            yield cur
            cur = cur + timedelta(days=1)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_EXPORT_HEADERS)

    for emp in employees:
        shift = shifts.get(emp["id"], {})
        shift_start_time = shift.get("shift_start_time") or "09:00"
        grace = shift.get("late_grace_minutes") or 0
        shift_end_time = shift.get("shift_end_time") or company_shift_end

        for d in _iter_dates(start_d, end_d):
            d_iso = d.isoformat()
            rec = a_key.get((emp["user_id"], d_iso))
            leave_type = _is_on_leave(emp["user_id"], d_iso)
            is_wfh_day = (emp["user_id"], d_iso) in wfh_set

            if rec and rec.get("check_in"):
                stats = compute_stats(rec,
                                      shift_start_time=shift_start_time,
                                      shift_end_time=shift_end_time,
                                      grace_minutes=grace, tz_name=tz_name)
                if leave_type:
                    status = f"On Leave · {leave_type}"
                elif is_wfh_day:
                    status = "WFH"
                else:
                    status = "Present"
                notes = ""
                if stats["sessions_count"] > 1:
                    notes = f"{stats['sessions_count']} sessions (re-check-in)"
                writer.writerow([
                    d_iso, emp.get("employee_code", ""), emp["name"],
                    emp.get("department", ""), emp.get("designation", ""), emp.get("email", ""),
                    stats["first_check_in_local"], stats["last_check_out_local"],
                    stats["sessions_count"],
                    f"{stats['total_hours']:.2f}",
                    "Yes" if stats["is_late"] else "No",
                    stats["late_minutes"],
                    stats["early_departure_minutes"],
                    f"{stats['overtime_hours']:.2f}",
                    status, notes,
                ])
            else:
                # No attendance record
                if leave_type:
                    status = f"On Leave · {leave_type}"
                elif is_wfh_day:
                    status = "WFH (not signed in)"
                elif d.weekday() >= 5:
                    status = "Weekly Off"
                else:
                    status = "Absent"
                writer.writerow([
                    d_iso, emp.get("employee_code", ""), emp["name"],
                    emp.get("department", ""), emp.get("designation", ""), emp.get("email", ""),
                    "", "", 0, "0.00", "No", 0, 0, "0.00", status, "",
                ])

    buf.seek(0)
    filename = f"attendance_{start_iso}_to_{end_iso}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
