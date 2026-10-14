import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user, require_roles
from db import get_db
from email_service import send_email, render
from notification_service import (
    notify_meeting_scheduled,
    notify_meeting_updated,
    notify_meeting_cancelled,
)
from tenant import company_id_of
import google_calendar_service as gcal

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
    add_google_meet: Optional[bool] = False


class MeetingUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    location: Optional[str] = None
    attendee_user_ids: Optional[List[str]] = None
    room_id: Optional[str] = None  # pass empty string "" to clear the room
    is_recurring: Optional[bool] = None
    recurrence: Optional[dict] = None
    add_google_meet: Optional[bool] = None


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


async def _google_create(db, doc: dict) -> None:
    if not doc.get("add_google_meet") or doc.get("google_event_id"):
        return
    res = await gcal.create_event(doc)
    if res:
        await db.meetings.update_one({"id": doc["id"]}, {"$set": res})
        doc.update(res)


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
            if doc.get("meet_link"):
                room_line += f"<br/>Google Meet: <a href=\"{doc['meet_link']}\">{doc['meet_link']}</a>"
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
        meet_link=doc.get("meet_link"),
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
        "add_google_meet": bool(body.add_google_meet),
        "google_event_id": None,
        "meet_link": None,
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
        await _google_create(db, doc)
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
    await _google_create(db, m)
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


@router.patch("/{meeting_id}")
async def update_meeting(
    meeting_id: str,
    body: MeetingUpdate,
    user: dict = Depends(get_current_user),
):
    """Edit a scheduled meeting and notify every active participant.

    Rules:
      • Only the organizer or super_admin / HR may edit.
      • Cancelled meetings are immutable.
      • Changing room / time re-runs the room conflict check.
      • A WhatsApp update ping is sent to every attendee (plus a summary of
        which fields changed) when the meeting is in a confirmed state
        (auto-approved or approved).
    """
    db = get_db()
    existing = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if existing["created_by"] != user["id"] and user.get("role") not in ("super_admin", "hr"):
        raise HTTPException(status_code=403, detail="Only the organizer can edit this meeting")
    if existing.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Cancelled meetings cannot be edited")

    patch = body.model_dump(exclude_unset=True)
    update: dict = {}

    # Times — must stay valid together
    new_starts = patch.get("starts_at", existing["starts_at"])
    new_ends = patch.get("ends_at", existing["ends_at"])
    if new_ends <= new_starts:
        raise HTTPException(status_code=400, detail="End time must be after start time")
    if "starts_at" in patch: update["starts_at"] = patch["starts_at"]
    if "ends_at" in patch:   update["ends_at"] = patch["ends_at"]
    if "starts_at" in patch or "ends_at" in patch:
        update["duration_minutes"] = _duration_minutes(new_starts, new_ends)

    # Room (empty string clears)
    cid = existing["company_id"]
    new_room_id = patch["room_id"] if "room_id" in patch else existing.get("room_id")
    new_room_id = new_room_id or None
    if "room_id" in patch:
        if new_room_id:
            room = await db.meeting_rooms.find_one(
                {"id": new_room_id, "company_id": cid, "active": True},
                {"_id": 0, "id": 1, "name": 1, "capacity": 1},
            )
            if not room:
                raise HTTPException(status_code=400, detail="Selected meeting room is not available")
            update["room_id"] = new_room_id
            update["room_name"] = room["name"]
            update["room_capacity"] = room["capacity"]
        else:
            update["room_id"] = None
            update["room_name"] = None
            update["room_capacity"] = None

    # Room conflict check (either room or time changed, and room is set)
    final_room_id = update.get("room_id", existing.get("room_id"))
    if final_room_id and ("room_id" in patch or "starts_at" in patch or "ends_at" in patch):
        conflict = await _has_conflict(
            db, cid=cid, room_id=final_room_id,
            starts_at=new_starts, ends_at=new_ends,
            exclude_meeting_id=meeting_id,
        )
        if conflict:
            s = datetime.fromisoformat(conflict["starts_at"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(conflict["ends_at"].replace("Z", "+00:00"))
            raise HTTPException(
                status_code=409,
                detail={
                    "message": f"That room is already booked from "
                               f"{s.strftime('%H:%M')} to {e.strftime('%H:%M')} "
                               f"for \"{conflict['title']}\".",
                    "conflict": conflict,
                },
            )

    for k in ("title", "description", "location", "is_recurring", "recurrence", "add_google_meet"):
        if k in patch:
            update[k] = patch[k]
    if "attendee_user_ids" in patch:
        update["attendee_user_ids"] = patch["attendee_user_ids"] or []

    # If the edit lengthens a short meeting past the long-threshold or flips
    # on recurrence, HR approval must be re-earned. Only applies to meetings
    # that were previously auto-approved — super_admin/HR edits stay confirmed
    # because they already have approval authority.
    final_duration = update.get("duration_minutes", existing.get("duration_minutes", 0))
    final_recurring = update.get("is_recurring", existing.get("is_recurring", False))
    needs_approval_now = final_duration > LONG_MEETING_THRESHOLD_MINUTES or bool(final_recurring)
    approval_was = existing.get("approval_status")
    reverted_to_pending = False
    if (
        needs_approval_now
        and approval_was == "auto_approved"
        and user.get("role") not in ("super_admin", "hr")
    ):
        update["approval_status"] = "pending"
        update["approved_by"] = None
        update["approved_at"] = None
        reverted_to_pending = True

    # Build human-readable change summary BEFORE the update, so attendees know
    # what moved. Keep it short — one line.
    change_bits: list = []
    def _fmt_dt(s: str) -> str:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%d %b %H:%M")
        except Exception:
            return s
    if "title" in patch and patch["title"] != existing.get("title"):
        change_bits.append(f"title → {patch['title']}")
    if "starts_at" in patch and patch["starts_at"] != existing.get("starts_at"):
        change_bits.append(f"start → {_fmt_dt(patch['starts_at'])}")
    if "ends_at" in patch and patch["ends_at"] != existing.get("ends_at"):
        change_bits.append(f"end → {_fmt_dt(patch['ends_at'])}")
    if "room_id" in patch and update.get("room_name") != existing.get("room_name"):
        change_bits.append(f"room → {update.get('room_name') or 'none'}")
    if "location" in patch and patch["location"] != existing.get("location"):
        change_bits.append(f"location → {patch['location']}")
    if "attendee_user_ids" in patch:
        before = set(existing.get("attendee_user_ids") or [])
        after = set(update.get("attendee_user_ids") or [])
        if before != after:
            change_bits.append(f"participants updated ({len(after)} total)")
    change_summary = "; ".join(change_bits) or "details updated"

    if not update:
        return existing

    update["updated_at"] = _now_iso()
    update["updated_by"] = user["name"]
    await db.meetings.update_one({"id": meeting_id}, {"$set": update})
    merged = {**existing, **update}

    # If the edit downgraded a confirmed meeting back to 'pending' (needs
    # HR approval), skip the WA fan-out and instead poke HR for approval.
    if reverted_to_pending:
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
                "body": f"{user['name']} extended \"{merged.get('title')}\" past the long-meeting threshold — needs approval.",
                "read": False,
                "created_at": _now_iso(),
            })
        merged.pop("_id", None)
        return merged

    # Smart routing (only for confirmed meetings): added → invite,
    # removed → cancelled, retained → updated.
    if merged.get("approval_status") in ("auto_approved", "approved"):
        if merged.get("google_event_id"):
            if merged.get("add_google_meet") is False:
                await gcal.cancel_event(merged)
                clear = {"google_event_id": None, "meet_link": None, "google_event_link": None}
                await db.meetings.update_one({"id": meeting_id}, {"$set": clear})
                merged.update(clear)
            else:
                await gcal.update_event(merged)
        else:
            await _google_create(db, merged)

        before_ids = existing.get("attendee_user_ids") or []
        after_ids = merged.get("attendee_user_ids") or []
        added = [u for u in after_ids if u not in before_ids]
        removed = [u for u in before_ids if u not in after_ids]
        kept = [u for u in after_ids if u in before_ids]
        organizer_name = merged.get("created_by_name") or user["name"]

        if added:
            await _notify_and_email(
                db, {**merged, "attendee_user_ids": added}, {"name": organizer_name},
            )

        for uid in removed:
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": uid,
                "type": "meeting_cancelled",
                "title": "Removed from meeting",
                "body": f"You were removed from \"{existing.get('title')}\" by {user['name']}.",
                "read": False,
                "created_at": _now_iso(),
            })
        if removed:
            await notify_meeting_cancelled(
                company_id=cid,
                cancelled_by=user["name"],
                title=existing.get("title", ""),
                starts_at=existing.get("starts_at", ""),
                ends_at=existing.get("ends_at"),
                attendee_user_ids=removed,
            )

        for uid in kept:
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": uid,
                "type": "meeting_updated",
                "title": "Meeting updated",
                "body": f"{merged.get('title')}: {change_summary}",
                "read": False,
                "created_at": _now_iso(),
            })
        if kept:
            await notify_meeting_updated(
                company_id=cid,
                organizer_name=organizer_name,
                title=merged.get("title", ""),
                starts_at=merged.get("starts_at", ""),
                ends_at=merged.get("ends_at"),
                attendee_user_ids=kept,
                change_summary=change_summary,
                meet_link=merged.get("meet_link"),
            )

    merged.pop("_id", None)
    return merged


@router.delete("/{meeting_id}")
async def cancel_meeting(meeting_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    meeting = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    if not meeting:
        raise HTTPException(status_code=404, detail="Not found")
    if meeting["created_by"] != user["id"] and user["role"] not in ("super_admin", "hr"):
        raise HTTPException(status_code=403, detail="Not allowed")
    if meeting.get("status") == "cancelled":
        return {"success": True}
    if meeting.get("google_event_id"):
        await gcal.cancel_event(meeting)
    await db.meetings.update_one({"id": meeting_id}, {"$set": {
        "status": "cancelled",
        "cancelled_at": _now_iso(),
        "cancelled_by": user["name"],
    }})
    # Fire WhatsApp + in-app notification only if the meeting was previously
    # confirmed (otherwise participants never saw it).
    if meeting.get("approval_status") in ("auto_approved", "approved"):
        for uid in meeting.get("attendee_user_ids", []):
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": uid,
                "type": "meeting_cancelled",
                "title": "Meeting cancelled",
                "body": f"\"{meeting['title']}\" was cancelled by {user['name']}.",
                "read": False,
                "created_at": _now_iso(),
            })
        await notify_meeting_cancelled(
            company_id=meeting["company_id"],
            cancelled_by=user["name"],
            title=meeting.get("title", ""),
            starts_at=meeting.get("starts_at", ""),
            ends_at=meeting.get("ends_at"),
            attendee_user_ids=meeting.get("attendee_user_ids", []),
        )
    return {"success": True}
