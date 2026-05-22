import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db import get_db
from email_service import send_email, render

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


class MeetingCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    starts_at: str  # ISO datetime
    ends_at: str
    location: Optional[str] = "Online"
    attendee_user_ids: List[str] = []


@router.get("")
async def list_meetings(user: dict = Depends(get_current_user), scope: str = "mine"):
    db = get_db()
    if scope == "all":
        items = await db.meetings.find({}, {"_id": 0}).sort("starts_at", 1).to_list(500)
    else:
        items = await db.meetings.find({
            "$or": [
                {"created_by": user["id"]},
                {"attendee_user_ids": user["id"]},
            ]
        }, {"_id": 0}).sort("starts_at", 1).to_list(500)
    return items


@router.post("")
async def create_meeting(body: MeetingCreate, user: dict = Depends(get_current_user)):
    db = get_db()
    doc = {
        "id": str(uuid.uuid4()),
        "title": body.title,
        "description": body.description or "",
        "starts_at": body.starts_at,
        "ends_at": body.ends_at,
        "location": body.location or "Online",
        "created_by": user["id"],
        "created_by_name": user["name"],
        "attendee_user_ids": body.attendee_user_ids,
        "status": "scheduled",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.meetings.insert_one(doc)

    # notifications + emails to each attendee
    for uid in body.attendee_user_ids:
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": uid,
            "type": "meeting_invite",
            "title": "Meeting invite",
            "body": f"{user['name']} invited you to: {body.title}",
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        attendee = await db.users.find_one({"id": uid}, {"_id": 0})
        if attendee:
            html = render(
                "You're invited to a meeting",
                f"<p>Hi {attendee['name']},</p><p><b>{user['name']}</b> invited you to:</p>"
                f"<p><b>{body.title}</b><br/>{body.starts_at} → {body.ends_at}<br/>{body.location}</p>"
                f"<p>{body.description or ''}</p>",
            )
            await send_email(attendee["email"], f"Invite: {body.title}", html)

    doc.pop("_id", None)
    return doc


@router.delete("/{meeting_id}")
async def cancel_meeting(meeting_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    meeting = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    if not meeting:
        raise HTTPException(status_code=404, detail="Not found")
    if meeting["created_by"] != user["id"] and user["role"] not in ("super_admin", "hr"):
        raise HTTPException(status_code=403, detail="Not allowed")
    await db.meetings.update_one({"id": meeting_id}, {"$set": {"status": "cancelled"}})
    return {"success": True}
