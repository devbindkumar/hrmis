"""Leave type configuration: per-company list of leave types with paid/unpaid flag."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user, require_roles
from db import get_db
from tenant import company_id_of

router = APIRouter(prefix="/api/leave-types", tags=["leave-types"])


class LeaveTypeCreate(BaseModel):
    name: str = Field(min_length=2)
    default_quota: float = Field(ge=0, default=0)
    is_paid: bool = True


class LeaveTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2)
    default_quota: Optional[float] = Field(default=None, ge=0)
    is_paid: Optional[bool] = None


@router.get("")
async def list_types(user: dict = Depends(get_current_user)):
    db = get_db()
    items = await db.leave_types.find({"company_id": company_id_of(user)}, {"_id": 0}).sort([("is_paid", -1), ("name", 1)]).to_list(100)
    return items


@router.post("")
async def create_type(body: LeaveTypeCreate, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    cid = company_id_of(admin)
    if await db.leave_types.find_one({"company_id": cid, "name": body.name}):
        raise HTTPException(status_code=400, detail="Leave type already exists")
    doc = {
        "id": str(uuid.uuid4()),
        "company_id": cid,
        "name": body.name,
        "default_quota": body.default_quota,
        "is_paid": body.is_paid,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.leave_types.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/{type_id}")
async def update_type(type_id: str, body: LeaveTypeUpdate, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    cid = company_id_of(admin)
    existing = await db.leave_types.find_one({"id": type_id, "company_id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Leave type not found")
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if "name" in update and update["name"] != existing["name"]:
        # avoid name collision
        if await db.leave_types.find_one({"company_id": cid, "name": update["name"]}):
            raise HTTPException(status_code=400, detail="Another leave type with that name already exists")
        # also rename balances + requests so historical data stays consistent
        await db.leave_balances.update_many({"company_id": cid, "leave_type": existing["name"]}, {"$set": {"leave_type": update["name"]}})
        await db.leave_requests.update_many({"company_id": cid, "leave_type": existing["name"]}, {"$set": {"leave_type": update["name"]}})
    if update:
        await db.leave_types.update_one({"id": type_id, "company_id": cid}, {"$set": update})
    return await db.leave_types.find_one({"id": type_id, "company_id": cid}, {"_id": 0})


@router.delete("/{type_id}")
async def delete_type(type_id: str, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    cid = company_id_of(admin)
    existing = await db.leave_types.find_one({"id": type_id, "company_id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Leave type not found")
    # block deletion if there are non-zero used balances or any historical requests
    used = await db.leave_balances.find_one({"company_id": cid, "leave_type": existing["name"], "used": {"$gt": 0}})
    requests = await db.leave_requests.find_one({"company_id": cid, "leave_type": existing["name"]})
    if used or requests:
        raise HTTPException(status_code=400, detail="Cannot delete a leave type that has been used. Make it unpaid or rename it instead.")
    await db.leave_balances.delete_many({"company_id": cid, "leave_type": existing["name"]})
    await db.leave_types.delete_one({"id": type_id, "company_id": cid})
    return {"success": True}
