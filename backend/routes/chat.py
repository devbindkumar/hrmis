import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db import get_db
from tenant import company_id_of

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _room_id(a: str, b: str) -> str:
    return ":".join(sorted([a, b]))


class SendMessage(BaseModel):
    to_user_id: str
    body: str


@router.get("/contacts")
async def contacts(user: dict = Depends(get_current_user)):
    """List employees plus most recent message preview."""
    db = get_db()
    employees = await db.employees.find({"status": "active"}, {"_id": 0}).to_list(500)
    out = []
    for e in employees:
        if e["user_id"] == user["id"]:
            continue
        rid = _room_id(user["id"], e["user_id"])
        last = await db.chat_messages.find_one({"room_id": rid}, {"_id": 0}, sort=[("created_at", -1)])
        unread = await db.chat_messages.count_documents({
            "room_id": rid,
            "to_user_id": user["id"],
            "read": False,
        })
        # presence: check attendance current_status
        today = datetime.now(timezone.utc).date().isoformat()
        att = await db.attendance.find_one({"user_id": e["user_id"], "date": today}, {"_id": 0})
        presence = att.get("current_status") if att else "offline"
        if att and att.get("check_out"):
            presence = "offline"
        out.append({
            "user_id": e["user_id"],
            "name": e["name"],
            "avatar_url": e.get("avatar_url"),
            "designation": e.get("designation"),
            "department": e.get("department"),
            "presence": presence or "offline",
            "last_message": last.get("body") if last else None,
            "last_message_at": last.get("created_at") if last else None,
            "unread": unread,
        })
    # sort: by last_message_at desc, then name
    out.sort(key=lambda x: (x["last_message_at"] or "", x["name"]), reverse=True)
    return out


@router.get("/messages/{other_user_id}")
async def messages(other_user_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    rid = _room_id(user["id"], other_user_id)
    msgs = await db.chat_messages.find({"room_id": rid}, {"_id": 0}).sort("created_at", 1).to_list(500)
    # mark inbound as read
    await db.chat_messages.update_many(
        {"room_id": rid, "to_user_id": user["id"], "read": False},
        {"$set": {"read": True}},
    )
    return msgs


@router.post("/send")
async def send(body: SendMessage, user: dict = Depends(get_current_user)):
    db = get_db()
    if not body.body.strip():
        raise HTTPException(status_code=400, detail="Empty message")
    rid = _room_id(user["id"], body.to_user_id)
    doc = {
        "id": str(uuid.uuid4()),
        "room_id": rid,
        "company_id": company_id_of(user),
        "from_user_id": user["id"],
        "from_name": user["name"],
        "to_user_id": body.to_user_id,
        "body": body.body.strip(),
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.chat_messages.insert_one(doc)
    doc.pop("_id", None)
    return doc
