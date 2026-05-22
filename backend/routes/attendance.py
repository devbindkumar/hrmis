import uuid
from datetime import datetime, timezone, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user, require_roles
from db import get_db

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/today")
async def today_status(user: dict = Depends(get_current_user)):
    db = get_db()
    today = _today_str()
    rec = await db.attendance.find_one({"user_id": user["id"], "date": today}, {"_id": 0})
    return rec or {"user_id": user["id"], "date": today, "check_in": None, "check_out": None, "status": "absent", "breaks": []}


class StatusUpdate(BaseModel):
    status: str  # active | on_break | in_meeting | wfh | offline


@router.post("/check-in")
async def check_in(user: dict = Depends(get_current_user)):
    db = get_db()
    today = _today_str()
    now = _now_iso()
    existing = await db.attendance.find_one({"user_id": user["id"], "date": today}, {"_id": 0})
    if existing and existing.get("check_in"):
        raise HTTPException(status_code=400, detail="Already checked in today")
    doc = {
        "id": existing["id"] if existing else str(uuid.uuid4()),
        "user_id": user["id"],
        "date": today,
        "check_in": now,
        "check_out": None,
        "status": "present",
        "current_status": "active",
        "breaks": [],
        "is_late": datetime.now(timezone.utc).hour >= 9 and datetime.now(timezone.utc).minute > 15,
    }
    await db.attendance.update_one({"user_id": user["id"], "date": today}, {"$set": doc}, upsert=True)
    doc.pop("_id", None)
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
    check_in_dt = datetime.fromisoformat(rec["check_in"])
    now_dt = datetime.now(timezone.utc)
    duration_seconds = int((now_dt - check_in_dt).total_seconds())
    await db.attendance.update_one(
        {"user_id": user["id"], "date": today},
        {"$set": {
            "check_out": _now_iso(),
            "current_status": "offline",
            "duration_seconds": duration_seconds,
        }},
    )
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
    return {"success": True, "status": body.status}


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
    """Return attendance for everyone for a specific day (default today)."""
    db = get_db()
    target = day or _today_str()

    employees = await db.employees.find({"status": "active"}, {"_id": 0}).to_list(500)
    user_ids = [e["user_id"] for e in employees]
    attendance = await db.attendance.find({"user_id": {"$in": user_ids}, "date": target}, {"_id": 0}).to_list(500)
    a_map = {a["user_id"]: a for a in attendance}

    # Identify who is on approved leave / wfh today
    on_leave = await db.leave_requests.find({
        "status": "approved",
        "start_date": {"$lte": target},
        "end_date": {"$gte": target},
    }, {"_id": 0}).to_list(500)
    leave_users = {l["user_id"] for l in on_leave}

    on_wfh = await db.wfh_requests.find({
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
            "is_late": a.get("is_late", False) if a else False,
            "status": status,
        })
    return {"date": target, "rows": rows}
