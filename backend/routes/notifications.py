from fastapi import APIRouter, Depends
from auth import get_current_user
from db import get_db

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(user: dict = Depends(get_current_user), limit: int = 30):
    db = get_db()
    # personal + audience-based for admins
    query = {"$or": [{"user_id": user["id"]}]}
    if user["role"] in ("super_admin", "hr"):
        query["$or"].append({"audience": "admin"})
    items = await db.notifications.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return items


@router.post("/{notif_id}/read")
async def mark_read(notif_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    await db.notifications.update_one({"id": notif_id}, {"$set": {"read": True}})
    return {"success": True}


@router.post("/read-all")
async def mark_all_read(user: dict = Depends(get_current_user)):
    db = get_db()
    query = {"$or": [{"user_id": user["id"]}]}
    if user["role"] in ("super_admin", "hr"):
        query["$or"].append({"audience": "admin"})
    await db.notifications.update_many(query, {"$set": {"read": True}})
    return {"success": True}
