import os
import uuid
from datetime import datetime, timezone, date
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user, require_roles
from db import get_db
from email_service import send_email, render
from tenant import company_id_of

router = APIRouter(prefix="/api/leave", tags=["leave"])


class LeaveApply(BaseModel):
    leave_type: str
    start_date: str  # YYYY-MM-DD
    end_date: str
    reason: str


class LeaveDecision(BaseModel):
    note: Optional[str] = ""


def _days_between(s: str, e: str) -> int:
    d1 = date.fromisoformat(s)
    d2 = date.fromisoformat(e)
    return (d2 - d1).days + 1


@router.get("/balances")
async def my_balances(user: dict = Depends(get_current_user)):
    db = get_db()
    items = await db.leave_balances.find({"user_id": user["id"], "company_id": company_id_of(user)}, {"_id": 0}).to_list(50)
    return items


@router.get("/mine")
async def my_requests(user: dict = Depends(get_current_user)):
    db = get_db()
    items = await db.leave_requests.find({"user_id": user["id"], "company_id": company_id_of(user)}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return items


@router.get("/all")
async def all_requests(
    user: dict = Depends(require_roles("super_admin", "hr", "manager")),
    status: Optional[str] = None,
    scope: Optional[str] = None,  # "team" -> only direct reports of `user`
):
    db = get_db()
    q: dict = {"company_id": company_id_of(user)}
    if status and status != "all":
        q["status"] = status
    if scope == "team":
        q["manager_user_id"] = user["id"]
    items = await db.leave_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return items


@router.get("/calendar")
async def leave_calendar(user: dict = Depends(get_current_user), month: Optional[str] = None):
    """Return approved leaves overlapping the given month YYYY-MM (default current)."""
    db = get_db()
    if not month:
        today = datetime.now(timezone.utc).date()
        month = f"{today.year:04d}-{today.month:02d}"
    year, mo = month.split("-")
    first = f"{year}-{mo}-01"
    # naive: any approved leave whose range overlaps that month
    items = await db.leave_requests.find({
        "status": "approved",
        "$or": [
            {"start_date": {"$regex": f"^{year}-{mo}"}},
            {"end_date": {"$regex": f"^{year}-{mo}"}},
        ],
    }, {"_id": 0}).to_list(500)
    return items


@router.post("/apply")
async def apply_leave(body: LeaveApply, user: dict = Depends(get_current_user)):
    db = get_db()
    days = _days_between(body.start_date, body.end_date)
    if days <= 0:
        raise HTTPException(status_code=400, detail="Invalid date range")

    balance = await db.leave_balances.find_one({"user_id": user["id"], "leave_type": body.leave_type, "company_id": company_id_of(user)}, {"_id": 0})
    if not balance:
        raise HTTPException(status_code=400, detail=f"No balance for {body.leave_type}")
    if (balance["total"] - balance["used"]) < days:
        raise HTTPException(status_code=400, detail="Not enough balance")

    # Resolve direct manager so the request is routed first to them
    emp = await db.employees.find_one({"user_id": user["id"], "company_id": company_id_of(user)}, {"_id": 0, "manager_id": 1})
    manager_user_id = None
    manager_record = None
    if emp and emp.get("manager_id"):
        manager_emp = await db.employees.find_one({"id": emp["manager_id"]}, {"_id": 0, "user_id": 1, "name": 1})
        if manager_emp:
            manager_user_id = manager_emp["user_id"]
            manager_record = manager_emp

    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "user_name": user["name"],
        "company_id": company_id_of(user),
        "leave_type": body.leave_type,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "days": days,
        "reason": body.reason,
        "status": "pending",
        "manager_user_id": manager_user_id,
        "manager_name": manager_record["name"] if manager_record else None,
        "decision_note": "",
        "decided_by": None,
        "decided_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.leave_requests.insert_one(doc)

    # Notify manager personally if one is assigned, otherwise notify admin pool
    if manager_user_id:
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": manager_user_id,
            "type": "leave_request",
            "title": "New leave request",
            "body": f"{user['name']} requested {days}d {body.leave_type} ({body.start_date} → {body.end_date})",
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        manager_user = await db.users.find_one({"id": manager_user_id}, {"_id": 0})
        if manager_user:
            await send_email(
                manager_user["email"],
                f"Leave request from {user['name']}",
                render(
                    "Leave request needs your decision",
                    f"<p>Hi {manager_user['name']},</p>"
                    f"<p><b>{user['name']}</b> requested <b>{days} day(s)</b> of <b>{body.leave_type}</b> leave "
                    f"from <b>{body.start_date}</b> to <b>{body.end_date}</b>.</p>"
                    f"<p><i>Reason:</i> {body.reason}</p>",
                ),
            )
    # Always copy admins/HR in the notification feed so they have visibility
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": "admin",
        "audience": "admin",
        "type": "leave_request",
        "title": "New leave request",
        "body": f"{user['name']} requested {days}d {body.leave_type} ({body.start_date} → {body.end_date})",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    doc.pop("_id", None)
    return doc


@router.post("/{request_id}/approve")
async def approve_leave(request_id: str, body: LeaveDecision, admin: dict = Depends(require_roles("super_admin", "hr", "manager"))):
    db = get_db()
    req = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already decided")

    await db.leave_requests.update_one({"id": request_id}, {"$set": {
        "status": "approved",
        "decision_note": body.note or "",
        "decided_by": admin["name"],
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }})
    # Deduct balance
    await db.leave_balances.update_one(
        {"user_id": req["user_id"], "leave_type": req["leave_type"]},
        {"$inc": {"used": req["days"]}},
    )
    # Notify employee
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": req["user_id"],
        "type": "leave_approved",
        "title": "Leave approved",
        "body": f"Your {req['leave_type']} from {req['start_date']} to {req['end_date']} was approved.",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Email
    user = await db.users.find_one({"id": req["user_id"]}, {"_id": 0})
    if user:
        html = render(
            "Your leave was approved",
            f"<p>Hi {user['name']},</p><p>Your <b>{req['leave_type']}</b> leave from <b>{req['start_date']}</b> to <b>{req['end_date']}</b> has been approved.</p>" + (f"<p><i>Note from approver:</i> {body.note}</p>" if body.note else ""),
        )
        await send_email(user["email"], "Leave approved", html)
    return {"success": True}


@router.post("/{request_id}/reject")
async def reject_leave(request_id: str, body: LeaveDecision, admin: dict = Depends(require_roles("super_admin", "hr", "manager"))):
    db = get_db()
    req = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already decided")
    await db.leave_requests.update_one({"id": request_id}, {"$set": {
        "status": "rejected",
        "decision_note": body.note or "",
        "decided_by": admin["name"],
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }})
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": req["user_id"],
        "type": "leave_rejected",
        "title": "Leave rejected",
        "body": f"Your {req['leave_type']} from {req['start_date']} to {req['end_date']} was rejected.",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    user = await db.users.find_one({"id": req["user_id"]}, {"_id": 0})
    if user:
        html = render(
            "Your leave was not approved",
            f"<p>Hi {user['name']},</p><p>Your <b>{req['leave_type']}</b> leave request from <b>{req['start_date']}</b> to <b>{req['end_date']}</b> was not approved.</p>" + (f"<p><i>Note from approver:</i> {body.note}</p>" if body.note else ""),
        )
        await send_email(user["email"], "Leave request decision", html)
    return {"success": True}
