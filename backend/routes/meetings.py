import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user, require_roles
from db import get_db
from email_service import send_email, render
from notification_service import notify_meeting_scheduled
from tenant import company_id_of

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

# Bookings longer than this need HR approval. Recurring meetings always need it.
LONG_MEETING_THRESHOLD_MINUTES = 120


class MeetingCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    starts_at: str  # ISO datetime
    ends_at: str
    location: Optional[str] = "Online"
    attendee_user_ids: List[str] = []
    room_id: Optional[str] = None
    is_recurring: Optional[bool] = False
    recurrence: Optional[dict] = None  # {frequency: 'weekly'|'daily'|'monthly', count: int}


class DecisionBody(BaseModel):
    note: Optional[str] = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_minutes(starts_at: str, ends_at: str) -> int:
    try:
        s = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        e = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
        return max(0, int((e - s).total_seconds() // 60))
    except Exception:
        return 0


async def _has_conflict(db, *, cid: str, room_id: str, starts_at: str, ends_at: str,
                        exclude_meeting_id: Optional[str] = None) -> Optional[dict]:
    q: dict = {
        "company_id": cid, "room_id": room_id,
        "status": {"$ne": "cancelled"},
        "approval_status": {"$ne": "rejected"},
        "starts_at": {"$lt": ends_at},
        "ends_at": {"$gt": starts_at},
    }
    if exclude_meeting_id:
        q["id"] = {"$ne": exclude_meeting_id}
    return await db.meetings.find_one(q, {
        "_id": 0, "id": 1, "title": 1, "starts_at": 1, "ends_at": 1,
        "created_by_name": 1,
    })


async def _notify_and_email(db, doc: dict, organiser: dict, *, subject_prefix: str = "Invite"):
    for uid in doc.get("attendee_user_ids", []):
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": uid,
            "type": "meeting_invite",
            "title": "Meeting invite",
            "body": f"{organiser['name']} invited you to: {doc['title']}",
            "read": False,
            "created_at": _now_iso(),
        })
        attendee = await db.users.find_one({"id": uid}, {"_id": 0})
        if attendee:
            room_line = f"<br/>Room: <b>{doc.get('room_name')}</b>" if doc.get("room_name") else ""
            html = render(
                f"You're invited to a meeting",
                f"<p>Hi {attendee['name']},</p><p><b>{organiser['name']}</b> invited you to:</p>"
                f"<p><b>{doc['title']}</b><br/>{doc['starts_at']} → {doc['ends_at']}<br/>{doc.get('location','')}"
                f"{room_line}</p><p>{doc.get('description','')}</p>",
            )
            await send_email(attendee["email"], f"{subject_prefix}: {doc['title']}", html)
    # WhatsApp
    await notify_meeting_scheduled(
        company_id=doc["company_id"],
        organizer_name=organiser["name"],
        title=doc["title"],
        starts_at=doc["starts_at"],
        ends_at=doc["ends_at"],
        location=doc.get("room_name") or doc.get("location") or "Online",
        attendee_user_ids=doc.get("attendee_user_ids", []),
    )


@router.get("")
async def list_meetings(user: dict = Depends(get_current_user), scope: str = "mine"):
    db = get_db()
    cid = company_id_of(user)
    if scope == "all":
        items = await db.meetings.find({"company_id": cid}, {"_id": 0}).sort("starts_at", 1).to_list(500)
    else:
        items = await db.meetings.find({
            "company_id": cid,
            "$or": [
                {"created_by": user["id"]},
                {"attendee_user_ids": user["id"]},
            ],
        }, {"_id": 0}).sort("starts_at", 1).to_list(500)
    return items


@router.get("/pending-approval")
async def pending_approval(admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    items = await db.meetings.find({
        "company_id": company_id_of(admin),
        "approval_status": "pending",
        "status": {"$ne": "cancelled"},
    }, {"_id": 0}).sort("starts_at", 1).to_list(200)
    return items


@router.post("")
async def create_meeting(body: MeetingCreate, user: dict = Depends(get_current_user)):
    db = get_db()
    cid = company_id_of(user)

    if body.ends_at <= body.starts_at:
        raise HTTPException(status_code=400, detail="End time must be after start time")

    room_name = None
    room_capacity = None
    if body.room_id:
        room = await db.meeting_rooms.find_one(
            {"id": body.room_id, "company_id": cid, "active": True},
            {"_id": 0, "id": 1, "name": 1, "capacity": 1},
        )
        if not room:
            raise HTTPException(status_code=400, detail="Selected meeting room is not available")
        room_name = room["name"]
        room_capacity = room["capacity"]

        # Conflict check: block if another non-cancelled meeting overlaps
        conflict = await _has_conflict(db, cid=cid, room_id=body.room_id,
                                       starts_at=body.starts_at, ends_at=body.ends_at)
        if conflict:
            s = datetime.fromisoformat(conflict["starts_at"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(conflict["ends_at"].replace("Z", "+00:00"))
            raise HTTPException(
                status_code=409,
                detail={
                    "message": f"{room_name} is already booked from "
                               f"{s.strftime('%H:%M')} to {e.strftime('%H:%M')} "
                               f"for \"{conflict['title']}\" by {conflict.get('created_by_name','a colleague')}.",
                    "conflict": conflict,
                },
            )

    duration = _duration_minutes(body.starts_at, body.ends_at)
    is_recurring = bool(body.is_recurring)
    needs_approval = duration > LONG_MEETING_THRESHOLD_MINUTES or is_recurring
    # Super admin & HR auto-approve their own bookings
    if needs_approval and user.get("role") in ("super_admin", "hr"):
        approval_status = "approved"
        approved_by = user["name"]
        approved_at = _now_iso()
    elif needs_approval:
        approval_status = "pending"
        approved_by = None
        approved_at = None
    else:
        approval_status = "auto_approved"
        approved_by = None
        approved_at = None

    doc = {
        "id": str(uuid.uuid4()),
        "company_id": cid,
        "title": body.title,
        "description": body.description or "",
        "starts_at": body.starts_at,
        "ends_at": body.ends_at,
        "duration_minutes": duration,
        "location": body.location or ("Online" if not room_name else room_name),
        "room_id": body.room_id,
        "room_name": room_name,
        "room_capacity": room_capacity,
        "is_recurring": is_recurring,
        "recurrence": body.recurrence if is_recurring else None,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "attendee_user_ids": body.attendee_user_ids,
        "status": "scheduled",
        "approval_status": approval_status,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "rejection_reason": None,
        "created_at": _now_iso(),
    }
    await db.meetings.insert_one(doc)

    # Notify HR / super_admin about pending approvals via in-app notification
    if approval_status == "pending":
        hr_users = await db.users.find(
            {"company_id": cid, "role": {"$in": ["super_admin", "hr"]}},
            {"_id": 0, "id": 1},
        ).to_list(100)
        for hr in hr_users:
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": hr["id"],
                "type": "meeting_approval_request",
                "title": "Meeting approval needed",
                "body": f"{user['name']} booked {room_name or 'a meeting'} "
                        f"({'recurring' if is_recurring else str(duration) + 'm'})",
                "read": False,
                "created_at": _now_iso(),
            })

    # Only fire attendee invites / WhatsApp when the meeting is confirmed
    if approval_status in ("auto_approved", "approved"):
        await _notify_and_email(db, doc, user)

    doc.pop("_id", None)
    return doc


@router.post("/{meeting_id}/approve")
async def approve_meeting(meeting_id: str, body: DecisionBody,
                          admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    cid = company_id_of(admin)
    m = await db.meetings.find_one({"id": meeting_id, "company_id": cid}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if m.get("approval_status") != "pending":
        raise HTTPException(status_code=400, detail="Already decided")

    # Re-check room conflict at approval time (something could have been booked in the meantime)
    if m.get("room_id"):
        conflict = await _has_conflict(
            db, cid=cid, room_id=m["room_id"],
            starts_at=m["starts_at"], ends_at=m["ends_at"],
            exclude_meeting_id=meeting_id,
        )
        if conflict:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot approve — {m.get('room_name')} is now booked by another meeting.",
            )

    await db.meetings.update_one({"id": meeting_id}, {"$set": {
        "approval_status": "approved",
        "approved_by": admin["name"],
        "approved_at": _now_iso(),
        "rejection_reason": None,
    }})

    # Fire the invites + WhatsApp now that it's confirmed
    organiser = await db.users.find_one({"id": m["created_by"]}, {"_id": 0}) or {"name": m.get("created_by_name", "")}
    await _notify_and_email(db, m, organiser, subject_prefix="Confirmed")

    # Ping the organiser
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": m["created_by"],
        "type": "meeting_approved",
        "title": "Meeting approved",
        "body": f"{admin['name']} approved \"{m['title']}\".",
        "read": False,
        "created_at": _now_iso(),
    })
    return {"success": True}


@router.post("/{meeting_id}/reject")
async def reject_meeting(meeting_id: str, body: DecisionBody,
                         admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    cid = company_id_of(admin)
    m = await db.meetings.find_one({"id": meeting_id, "company_id": cid}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if m.get("approval_status") != "pending":
        raise HTTPException(status_code=400, detail="Already decided")
    await db.meetings.update_one({"id": meeting_id}, {"$set": {
        "approval_status": "rejected",
        "approved_by": admin["name"],
        "approved_at": _now_iso(),
        "rejection_reason": body.note or "",
    }})
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": m["created_by"],
        "type": "meeting_rejected",
        "title": "Meeting not approved",
        "body": f"{admin['name']} rejected \"{m['title']}\". Reason: {body.note or 'not provided'}",
        "read": False,
        "created_at": _now_iso(),
    })
    return {"success": True}


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
