"""Telephone extension directory.

Every employee can hold a phone-extension record. Super-admin/HR can create,
update and delete rows. All authenticated users in the tenant can view the
full directory (read-only). Records are auto-linked to an employee so name
and department stay in sync with the master employee list.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user, require_roles
from db import get_db
from tenant import company_id_of

router = APIRouter(prefix="/api/extensions", tags=["extensions"])


class ExtensionCreate(BaseModel):
    employee_id: Optional[str] = None
    employee_name: Optional[str] = Field(default=None, max_length=120)
    department: Optional[str] = Field(default=None, max_length=120)
    extension: str = Field(min_length=1, max_length=32)
    direct_dial: Optional[str] = Field(default=None, max_length=32)
    mobile: Optional[str] = Field(default=None, max_length=32)


class ExtensionUpdate(BaseModel):
    employee_id: Optional[str] = None
    employee_name: Optional[str] = Field(default=None, max_length=120)
    department: Optional[str] = Field(default=None, max_length=120)
    extension: Optional[str] = Field(default=None, min_length=1, max_length=32)
    direct_dial: Optional[str] = Field(default=None, max_length=32)
    mobile: Optional[str] = Field(default=None, max_length=32)


async def _load_employee(db, employee_id: str, cid: str) -> dict:
    emp = await db.employees.find_one(
        {"id": employee_id, "company_id": cid},
        {"_id": 0, "id": 1, "name": 1, "department": 1, "designation": 1, "avatar_url": 1, "email": 1, "user_id": 1},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp


def _clean(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v or None


@router.get("")
async def list_extensions(user: dict = Depends(get_current_user)):
    """Return every extension in the caller's company.

    Any authenticated user may call this — the directory is read-only for
    non-admins on the client side.
    """
    db = get_db()
    cid = company_id_of(user)
    items = await db.extensions.find({"company_id": cid}, {"_id": 0}).sort("extension", 1).to_list(1000)
    if not items:
        return []

    emp_ids = list({e.get("employee_id") for e in items if e.get("employee_id")})
    emps = await db.employees.find(
        {"id": {"$in": emp_ids}, "company_id": cid},
        {"_id": 0, "id": 1, "name": 1, "department": 1, "designation": 1, "email": 1, "avatar_url": 1, "user_id": 1},
    ).to_list(1000) if emp_ids else []
    emp_map = {e["id"]: e for e in emps}

    for it in items:
        e = emp_map.get(it.get("employee_id")) or {}
        it["employee_name"] = e.get("name") or it.get("employee_name") or "—"
        it["department"] = e.get("department") or it.get("department") or None
        it["designation"] = e.get("designation")
        it["email"] = e.get("email")
        it["avatar_url"] = e.get("avatar_url")
    return items


@router.post("")
async def create_extension(
    body: ExtensionCreate,
    admin: dict = Depends(require_roles("super_admin", "hr")),
):
    db = get_db()
    cid = company_id_of(admin)

    extension = body.extension.strip()
    if not extension:
        raise HTTPException(status_code=400, detail="Extension cannot be empty")

    # Extension must be unique within the tenant
    clash = await db.extensions.find_one({"company_id": cid, "extension": extension})
    if clash:
        raise HTTPException(status_code=400, detail=f"Extension '{extension}' is already assigned")

    # If an employee is linked → pull authoritative name & department from the master
    # record and enforce one-extension-per-employee. If no employee is linked, the
    # row represents a guest/vendor/contact and requires an explicit custom name.
    employee_id = body.employee_id or None
    if employee_id:
        emp = await _load_employee(db, employee_id, cid)
        dupe_emp = await db.extensions.find_one({"company_id": cid, "employee_id": employee_id})
        if dupe_emp:
            raise HTTPException(status_code=400, detail="This employee already has an extension. Edit it instead.")
        name = emp.get("name")
        department = emp.get("department")
        user_id = emp.get("user_id")
    else:
        name = _clean(body.employee_name)
        if not name:
            raise HTTPException(status_code=400, detail="Please provide a name for the extension (or pick an employee)")
        department = _clean(body.department)
        user_id = None

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "company_id": cid,
        "employee_id": employee_id,
        "user_id": user_id,
        "employee_name": name,
        "department": department,
        "extension": extension,
        "direct_dial": _clean(body.direct_dial),
        "mobile": _clean(body.mobile),
        "is_custom": employee_id is None,
        "created_at": now,
        "created_by": admin.get("name"),
    }
    await db.extensions.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/{ext_id}")
async def update_extension(
    ext_id: str,
    body: ExtensionUpdate,
    admin: dict = Depends(require_roles("super_admin", "hr")),
):
    db = get_db()
    cid = company_id_of(admin)
    existing = await db.extensions.find_one({"id": ext_id, "company_id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Extension not found")

    patch = body.model_dump(exclude_unset=True)
    update: dict = {}

    if "employee_id" in patch:
        new_eid = patch["employee_id"] or None
        if new_eid != existing.get("employee_id"):
            if new_eid:
                emp = await _load_employee(db, new_eid, cid)
                dupe = await db.extensions.find_one(
                    {"company_id": cid, "employee_id": new_eid, "id": {"$ne": ext_id}}
                )
                if dupe:
                    raise HTTPException(status_code=400, detail="This employee already has an extension.")
                update["employee_id"] = new_eid
                update["user_id"] = emp.get("user_id")
                update["employee_name"] = emp.get("name")
                update["department"] = emp.get("department")
                update["is_custom"] = False
            else:
                update["employee_id"] = None
                update["user_id"] = None
                update["is_custom"] = True

    # Allow explicit override of name / department only when the row is custom
    # (not linked to a master employee). For linked rows the fields stay in sync.
    linked_after_patch = update.get("employee_id", existing.get("employee_id")) is not None
    if "employee_name" in patch and not linked_after_patch:
        name = _clean(patch["employee_name"])
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        update["employee_name"] = name
    if "department" in patch and not linked_after_patch:
        update["department"] = _clean(patch["department"])

    if "extension" in patch and patch["extension"]:
        new_ext = patch["extension"].strip()
        if new_ext != existing.get("extension"):
            clash = await db.extensions.find_one(
                {"company_id": cid, "extension": new_ext, "id": {"$ne": ext_id}}
            )
            if clash:
                raise HTTPException(status_code=400, detail=f"Extension '{new_ext}' is already assigned")
        update["extension"] = new_ext

    if "direct_dial" in patch:
        update["direct_dial"] = _clean(patch["direct_dial"])
    if "mobile" in patch:
        update["mobile"] = _clean(patch["mobile"])

    if not update:
        return existing

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    update["updated_by"] = admin.get("name")
    await db.extensions.update_one({"id": ext_id, "company_id": cid}, {"$set": update})
    doc = await db.extensions.find_one({"id": ext_id, "company_id": cid}, {"_id": 0})
    return doc


@router.delete("/{ext_id}")
async def delete_extension(
    ext_id: str,
    admin: dict = Depends(require_roles("super_admin", "hr")),
):
    db = get_db()
    res = await db.extensions.delete_one({"id": ext_id, "company_id": company_id_of(admin)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Extension not found")
    return {"success": True}
