import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user, require_roles
from db import get_db
from tenant import company_id_of

router = APIRouter(prefix="/api/departments", tags=["departments"])


class DeptCreate(BaseModel):
    name: str
    head: str = ""


@router.get("")
async def list_departments(user: dict = Depends(get_current_user)):
    db = get_db()
    cid = company_id_of(user)
    items = await db.departments.find({"company_id": cid}, {"_id": 0}).sort("name", 1).to_list(200)
    for d in items:
        d["headcount"] = await db.employees.count_documents({"department": d["name"], "status": "active", "company_id": cid})
    return items


@router.post("")
async def create_department(body: DeptCreate, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    cid = company_id_of(admin)
    if await db.departments.find_one({"name": body.name, "company_id": cid}):
        raise HTTPException(status_code=400, detail="Department already exists")
    doc = {
        "id": str(uuid.uuid4()),
        "company_id": cid,
        "name": body.name,
        "head": body.head,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.departments.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/{dept_id}")
async def delete_department(dept_id: str, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    res = await db.departments.delete_one({"id": dept_id, "company_id": company_id_of(admin)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Department not found")
    return {"success": True}
