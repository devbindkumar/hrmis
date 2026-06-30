import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user, require_roles
from db import get_db
from email_service import send_email, render
from notification_service import notify_wfh_request
from tenant import company_id_of

router = APIRouter(prefix="/api/wfh", tags=["wfh"])


class WFHApply(BaseModel):
    date: str  # YYYY-MM-DD
    reason: str


class WFHDecision(BaseModel):
    note: Optional[str] = ""


@router.get("/mine")
async def my_wfh(user: dict = Depends(get_current_user)):
    db = get_db()
    items = await db.wfh_requests.find({"user_id": user["id"], "company_id": company_id_of(user)}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return items


@router.get("/all")
async def all_wfh(
    user: dict = Depends(require_roles("super_admin", "hr", "manager")),
    status: Optional[str] = None,
    scope: Optional[str] = None,
):
    db = get_db()
    q: dict = {"company_id": company_id_of(user)}
    if status and status != "all":
        q["status"] = status
    if scope == "team":
        q["manager_user_id"] = user["id"]
    items = await db.wfh_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return items


@router.get("/today")
async def today_wfh(user: dict = Depends(get_current_user)):
    """Who is WFH today (approved)."""
    db = get_db()
    today = datetime.now(timezone.utc).date().isoformat()
    items = await db.wfh_requests.find({"status": "approved", "date": today, "company_id": company_id_of(user)}, {"_id": 0}).to_list(200)
    return items


@router.post("/apply")
async def apply_wfh(body: WFHApply, user: dict = Depends(get_current_user)):
    db = get_db()
    cid = company_id_of(user)
    if await db.wfh_requests.find_one({"user_id": user["id"], "date": body.date, "company_id": cid}):
        raise HTTPException(status_code=400, detail="You already have a WFH request for that date")

    # Resolve direct manager
    emp = await db.employees.find_one({"user_id": user["id"], "company_id": cid}, {"_id": 0, "manager_id": 1})
    manager_user_id = None
    manager_record = None
    if emp and emp.get("manager_id"):
        manager_emp = await db.employees.find_one({"id": emp["manager_id"], "company_id": cid}, {"_id": 0, "user_id": 1, "name": 1})
        if manager_emp:
            manager_user_id = manager_emp["user_id"]
            manager_record = manager_emp

    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "user_name": user["name"],
        "company_id": cid,
        "date": body.date,
        "reason": body.reason,
        "status": "pending",
        "manager_user_id": manager_user_id,
        "manager_name": manager_record["name"] if manager_record else None,
        "decision_note": "",
        "decided_by": None,
        "decided_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.wfh_requests.insert_one(doc)

    if manager_user_id:
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": manager_user_id,
            "type": "wfh_request",
            "title": "New WFH request",
            "body": f"{user['name']} requested WFH on {body.date}",
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        manager_user = await db.users.find_one({"id": manager_user_id}, {"_id": 0})
        if manager_user:
            await send_email(
                manager_user["email"],
                f"WFH request from {user['name']}",
                render(
                    "WFH request needs your decision",
                    f"<p>Hi {manager_user['name']},</p>"
                    f"<p><b>{user['name']}</b> requested work-from-home on <b>{body.date}</b>.</p>"
                    f"<p><i>Reason:</i> {body.reason}</p>",
                ),
            )
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": "admin",
        "audience": "admin",
        "type": "wfh_request",
        "title": "New WFH request",
        "body": f"{user['name']} requested WFH on {body.date}",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # WhatsApp to reporting manager
    await notify_wfh_request(
        company_id=cid,
        employee_user_id=user["id"],
        employee_name=user["name"],
        date_str=body.date,
        reason=body.reason,
    )

    doc.pop("_id", None)
    return doc


@router.post("/{request_id}/approve")
async def approve_wfh(request_id: str, body: WFHDecision, admin: dict = Depends(require_roles("super_admin", "hr", "manager"))):
    db = get_db()
    req = await db.wfh_requests.find_one({"id": request_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already decided")
    await db.wfh_requests.update_one({"id": request_id}, {"$set": {
        "status": "approved",
        "decision_note": body.note or "",
        "decided_by": admin["name"],
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }})
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": req["user_id"],
        "type": "wfh_approved",
        "title": "WFH approved",
        "body": f"Your WFH request on {req['date']} was approved.",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    user = await db.users.find_one({"id": req["user_id"]}, {"_id": 0})
    if user:
        await send_email(user["email"], "Work from home approved",
                         render("WFH approved", f"<p>Hi {user['name']},</p><p>Your work-from-home for <b>{req['date']}</b> has been approved.</p>"))
    return {"success": True}


@router.post("/{request_id}/reject")
async def reject_wfh(request_id: str, body: WFHDecision, admin: dict = Depends(require_roles("super_admin", "hr", "manager"))):
    db = get_db()
    req = await db.wfh_requests.find_one({"id": request_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already decided")
    await db.wfh_requests.update_one({"id": request_id}, {"$set": {
        "status": "rejected",
        "decision_note": body.note or "",
        "decided_by": admin["name"],
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }})
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": req["user_id"],
        "type": "wfh_rejected",
        "title": "WFH rejected",
        "body": f"Your WFH on {req['date']} was rejected.",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    user = await db.users.find_one({"id": req["user_id"]}, {"_id": 0})
    if user:
        await send_email(user["email"], "WFH decision",
                         render("WFH not approved", f"<p>Hi {user['name']},</p><p>Your work-from-home for <b>{req['date']}</b> was not approved.</p>"))
    return {"success": True}
