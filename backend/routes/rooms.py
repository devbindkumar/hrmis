"""Meeting-room management + booking conflict checks.

Endpoints
---------
GET    /api/rooms                     — list active rooms (any authenticated user)
POST   /api/rooms                     — create a room (super_admin / hr)
PATCH  /api/rooms/{id}                — edit (super_admin / hr)
DELETE /api/rooms/{id}                — soft-delete (super_admin / hr)
GET    /api/rooms/{id}/bookings       — meetings booked into this room in a window
POST   /api/rooms/check-conflict      — { room_id, starts_at, ends_at, exclude_meeting_id } → { available, conflict }
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user, require_roles
from db import get_db
from tenant import company_id_of

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


# ─────────────────────────── models ───────────────────────────

VALID_FEATURES = {"tv", "whiteboard", "video_conference", "projector", "phone", "wifi"}


class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    capacity: int = Field(ge=1, le=500)
    features: List[str] = Field(default_factory=list)
    location: Optional[str] = ""


class RoomUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    capacity: Optional[int] = Field(default=None, ge=1, le=500)
    features: Optional[List[str]] = None
    location: Optional[str] = None
    active: Optional[bool] = None


class ConflictCheck(BaseModel):
    room_id: str
    starts_at: str  # ISO
    ends_at: str
    exclude_meeting_id: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_features(features: List[str]) -> List[str]:
    out = []
    for f in features or []:
        key = f.strip().lower().replace(" ", "_").replace("-", "_")
        if key in VALID_FEATURES and key not in out:
            out.append(key)
    return out


def _strip(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


# ─────────────────────────── seeding ───────────────────────────

async def ensure_default_rooms(company_id: str) -> None:
    """Idempotently seed the initial 2 rooms per company."""
    db = get_db()
    existing = await db.meeting_rooms.count_documents({"company_id": company_id})
    if existing > 0:
        return
    defaults = [
        {"name": "Conference Room A", "capacity": 8,
         "features": ["tv", "video_conference", "whiteboard", "wifi"],
         "location": "1st floor"},
        {"name": "Conference Room B", "capacity": 4,
         "features": ["tv", "whiteboard", "wifi"],
         "location": "1st floor"},
    ]
    now = _now_iso()
    for r in defaults:
        await db.meeting_rooms.insert_one({
            "id": str(uuid.uuid4()),
            "company_id": company_id,
            "active": True,
            "created_at": now,
            **r,
        })


# ─────────────────────────── routes ───────────────────────────

@router.get("")
async def list_rooms(user: dict = Depends(get_current_user), include_inactive: bool = False):
    db = get_db()
    cid = company_id_of(user)
    await ensure_default_rooms(cid)
    q: dict = {"company_id": cid}
    if not include_inactive:
        q["active"] = True
    items = await db.meeting_rooms.find(q, {"_id": 0}).sort("name", 1).to_list(200)
    return items


@router.post("")
async def create_room(body: RoomCreate, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    cid = company_id_of(admin)
    # unique name per company
    dup = await db.meeting_rooms.find_one({"company_id": cid, "name": body.name})
    if dup:
        raise HTTPException(status_code=400, detail="A room with this name already exists")
    doc = {
        "id": str(uuid.uuid4()),
        "company_id": cid,
        "name": body.name.strip(),
        "capacity": body.capacity,
        "features": _clean_features(body.features),
        "location": (body.location or "").strip(),
        "active": True,
        "created_at": _now_iso(),
    }
    await db.meeting_rooms.insert_one(doc)
    return _strip(doc)


@router.patch("/{room_id}")
async def update_room(room_id: str, body: RoomUpdate,
                      admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    cid = company_id_of(admin)
    room = await db.meeting_rooms.find_one({"id": room_id, "company_id": cid}, {"_id": 0})
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    update = body.model_dump(exclude_unset=True)
    if "features" in update:
        update["features"] = _clean_features(update["features"])
    if "name" in update and update["name"] != room["name"]:
        dup = await db.meeting_rooms.find_one({
            "company_id": cid, "name": update["name"], "id": {"$ne": room_id},
        })
        if dup:
            raise HTTPException(status_code=400, detail="A room with this name already exists")
    if update:
        await db.meeting_rooms.update_one({"id": room_id}, {"$set": update})
    updated = await db.meeting_rooms.find_one({"id": room_id}, {"_id": 0})
    return updated


@router.delete("/{room_id}")
async def delete_room(room_id: str, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    cid = company_id_of(admin)
    room = await db.meeting_rooms.find_one({"id": room_id, "company_id": cid}, {"_id": 0})
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    # Soft-delete: mark inactive so past bookings still resolve room name
    await db.meeting_rooms.update_one({"id": room_id}, {"$set": {"active": False}})
    return {"success": True}


@router.get("/day-schedule")
async def day_schedule(date: str, user: dict = Depends(get_current_user)):
    """All active rooms + their bookings for the given date — powers the availability grid."""
    db = get_db()
    cid = company_id_of(user)
    await ensure_default_rooms(cid)
    # Build ISO range for the entire day in UTC (server-side is UTC; the UI localises)
    try:
        datetime.strptime(date, "%Y-%m-%d")
        start = f"{date}T00:00:00+00:00"
        end = f"{date}T23:59:59.999999+00:00"
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    rooms = await db.meeting_rooms.find(
        {"company_id": cid, "active": True}, {"_id": 0},
    ).sort("name", 1).to_list(200)
    ids = [r["id"] for r in rooms]

    bookings = await db.meetings.find({
        "company_id": cid, "room_id": {"$in": ids},
        "status": {"$ne": "cancelled"},
        "approval_status": {"$ne": "rejected"},
        "starts_at": {"$lt": end},
        "ends_at": {"$gt": start},
    }, {
        "_id": 0, "id": 1, "title": 1, "starts_at": 1, "ends_at": 1,
        "created_by_name": 1, "approval_status": 1, "room_id": 1,
    }).sort("starts_at", 1).to_list(500)

    by_room: dict = {rid: [] for rid in ids}
    for b in bookings:
        by_room.setdefault(b["room_id"], []).append(b)

    return {
        "date": date,
        "rooms": [{**r, "bookings": by_room.get(r["id"], [])} for r in rooms],
    }


@router.get("/{room_id}/bookings")
async def list_bookings(
    room_id: str,
    start: str,
    end: str,
    user: dict = Depends(get_current_user),
):
    """Meetings booked in this room whose window overlaps [start, end]."""
    db = get_db()
    cid = company_id_of(user)
    room = await db.meeting_rooms.find_one({"id": room_id, "company_id": cid}, {"_id": 0})
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    # Overlap query: meeting.starts_at < end AND meeting.ends_at > start
    items = await db.meetings.find({
        "company_id": cid, "room_id": room_id,
        "status": {"$ne": "cancelled"},
        "approval_status": {"$ne": "rejected"},
        "starts_at": {"$lt": end},
        "ends_at": {"$gt": start},
    }, {
        "_id": 0, "id": 1, "title": 1, "starts_at": 1, "ends_at": 1,
        "created_by": 1, "created_by_name": 1, "approval_status": 1,
    }).sort("starts_at", 1).to_list(200)
    return items


@router.post("/check-conflict")
async def check_conflict(body: ConflictCheck, user: dict = Depends(get_current_user)):
    db = get_db()
    cid = company_id_of(user)
    # Validate the room belongs to the company
    room = await db.meeting_rooms.find_one({"id": body.room_id, "company_id": cid}, {"_id": 0})
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    q: dict = {
        "company_id": cid, "room_id": body.room_id,
        "status": {"$ne": "cancelled"},
        "approval_status": {"$ne": "rejected"},
        "starts_at": {"$lt": body.ends_at},
        "ends_at": {"$gt": body.starts_at},
    }
    if body.exclude_meeting_id:
        q["id"] = {"$ne": body.exclude_meeting_id}
    conflict = await db.meetings.find_one(q, {
        "_id": 0, "id": 1, "title": 1, "starts_at": 1, "ends_at": 1,
        "created_by_name": 1, "approval_status": 1,
    })
    return {
        "available": conflict is None,
        "conflict": conflict,
        "room": {"id": room["id"], "name": room["name"], "capacity": room["capacity"]},
    }
