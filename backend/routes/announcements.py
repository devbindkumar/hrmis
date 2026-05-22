import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user, require_roles
from db import get_db
from email_service import send_email, render

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


class AnnouncementCreate(BaseModel):
    title: str
    body: str
    notify_email: bool = False


@router.get("")
async def list_announcements(user: dict = Depends(get_current_user), limit: int = 50):
    db = get_db()
    items = await db.announcements.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return items


@router.post("")
async def create_announcement(body: AnnouncementCreate, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    doc = {
        "id": str(uuid.uuid4()),
        "title": body.title,
        "body": body.body,
        "author_name": admin["name"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.announcements.insert_one(doc)
    # notifications
    users = await db.users.find({"status": "active"}, {"_id": 0, "id": 1, "email": 1, "name": 1}).to_list(1000)
    for u in users:
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": u["id"],
            "type": "announcement",
            "title": body.title,
            "body": body.body[:160],
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    if body.notify_email:
        for u in users:
            await send_email(u["email"], body.title, render(body.title, f"<p>Hi {u['name']},</p><p>{body.body}</p>"))
    doc.pop("_id", None)
    return doc
