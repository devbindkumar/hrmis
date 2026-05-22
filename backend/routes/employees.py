import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from auth import get_current_user, hash_password, require_roles
from db import get_db
from email_service import send_email, render

router = APIRouter(prefix="/api/employees", tags=["employees"])


class EmployeeCreate(BaseModel):
    name: str
    email: EmailStr
    department: str
    designation: str
    role: str = "employee"  # employee | manager | hr
    location: str = "HQ"
    shift: str = "General (9:00 – 18:00)"
    phone: Optional[str] = None
    manager_id: Optional[str] = None
    password: str = Field(default="Demo@123", min_length=6)


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    location: Optional[str] = None
    shift: Optional[str] = None
    phone: Optional[str] = None
    manager_id: Optional[str] = None
    status: Optional[str] = None
    avatar_url: Optional[str] = None


@router.get("")
async def list_employees(
    user: dict = Depends(get_current_user),
    department: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
):
    db = get_db()
    query: dict = {}
    if department and department != "all":
        query["department"] = department
    if status and status != "all":
        query["status"] = status
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
            {"employee_code": {"$regex": q, "$options": "i"}},
        ]
    items = await db.employees.find(query, {"_id": 0}).sort("name", 1).to_list(500)
    # attach role
    user_ids = [e["user_id"] for e in items]
    users = await db.users.find({"id": {"$in": user_ids}}, {"_id": 0, "id": 1, "role": 1, "status": 1}).to_list(500)
    role_map = {u["id"]: u for u in users}
    # attach manager name (manager_id stores an employee id)
    manager_ids = [e.get("manager_id") for e in items if e.get("manager_id")]
    managers = await db.employees.find({"id": {"$in": manager_ids}}, {"_id": 0, "id": 1, "name": 1, "designation": 1}).to_list(500) if manager_ids else []
    mgr_map = {m["id"]: m for m in managers}
    for e in items:
        e["role"] = role_map.get(e["user_id"], {}).get("role", "employee")
        mgr = mgr_map.get(e.get("manager_id")) if e.get("manager_id") else None
        e["manager_name"] = mgr["name"] if mgr else None
        e["manager_designation"] = mgr["designation"] if mgr else None
    return items


@router.get("/managers")
async def list_potential_managers(user: dict = Depends(get_current_user)):
    """Return employees who can be selected as a 'reports to' (managers, HR, super_admin)."""
    db = get_db()
    eligible_users = await db.users.find(
        {"role": {"$in": ["super_admin", "hr", "manager"]}, "status": "active"},
        {"_id": 0, "id": 1, "role": 1},
    ).to_list(500)
    user_ids = [u["id"] for u in eligible_users]
    role_map = {u["id"]: u["role"] for u in eligible_users}
    emps = await db.employees.find(
        {"user_id": {"$in": user_ids}, "status": "active"},
        {"_id": 0, "id": 1, "name": 1, "designation": 1, "department": 1, "user_id": 1, "avatar_url": 1},
    ).sort("name", 1).to_list(500)
    for e in emps:
        e["role"] = role_map.get(e["user_id"], "employee")
    return emps


@router.get("/{employee_id}/reports")
async def list_direct_reports(employee_id: str, user: dict = Depends(get_current_user)):
    """Direct reports of the given employee (people whose manager_id == this employee.id)."""
    db = get_db()
    reports = await db.employees.find(
        {"manager_id": employee_id, "status": "active"},
        {"_id": 0, "id": 1, "name": 1, "designation": 1, "department": 1, "avatar_url": 1, "email": 1},
    ).sort("name", 1).to_list(500)
    return reports



@router.get("/me")
async def my_employee(user: dict = Depends(get_current_user)):
    db = get_db()
    emp = await db.employees.find_one({"user_id": user["id"]}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee record not found")
    emp["role"] = user["role"]
    if emp.get("manager_id"):
        mgr = await db.employees.find_one({"id": emp["manager_id"]}, {"_id": 0, "name": 1, "designation": 1, "avatar_url": 1, "email": 1, "id": 1})
        if mgr:
            emp["manager_name"] = mgr["name"]
            emp["manager_designation"] = mgr.get("designation")
            emp["manager_avatar_url"] = mgr.get("avatar_url")
            emp["manager_email"] = mgr.get("email")
    return emp


@router.get("/{employee_id}")
async def get_employee(employee_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    emp = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    u = await db.users.find_one({"id": emp["user_id"]}, {"_id": 0, "role": 1, "status": 1})
    emp["role"] = u["role"] if u else "employee"
    if emp.get("manager_id"):
        mgr = await db.employees.find_one({"id": emp["manager_id"]}, {"_id": 0, "name": 1, "designation": 1})
        if mgr:
            emp["manager_name"] = mgr["name"]
            emp["manager_designation"] = mgr.get("designation")
    return emp


@router.post("")
async def create_employee(body: EmployeeCreate, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already exists")

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.users.insert_one({
        "id": user_id,
        "email": email,
        "name": body.name,
        "role": body.role,
        "status": "active",
        "password_hash": hash_password(body.password),
        "created_at": now,
    })

    count = await db.employees.count_documents({})
    emp = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "employee_code": f"ACM-{count + 1:04d}",
        "name": body.name,
        "email": email,
        "department": body.department,
        "designation": body.designation,
        "manager_id": body.manager_id,
        "location": body.location,
        "shift": body.shift,
        "phone": body.phone,
        "avatar_url": f"https://api.dicebear.com/7.x/initials/svg?seed={body.name}",
        "status": "active",
        "joined_at": datetime.now(timezone.utc).date().isoformat(),
        "created_at": now,
    }
    await db.employees.insert_one(emp)

    # Seed leave balances
    for lt, qty in [("Casual", 12), ("Sick", 8), ("Earned", 15), ("WFH Quota", 60)]:
        await db.leave_balances.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "leave_type": lt,
            "total": qty,
            "used": 0,
        })

    # Welcome email (non-blocking)
    body_html = (
        f"<p>Hi {body.name},</p>"
        f"<p>Your HRMIS account has been created. Use the credentials below to sign in for the first time, then update your password.</p>"
        f"<p><b>Email:</b> {email}<br/><b>Temporary password:</b> {body.password}</p>"
    )
    await send_email(email, "Welcome to your HRMIS workspace", render("Welcome aboard", body_html, "Sign in", os.environ.get('FRONTEND_URL', '')))

    emp.pop("_id", None)
    emp["role"] = body.role
    return emp


@router.patch("/{employee_id}")
async def update_employee(employee_id: str, body: EmployeeUpdate, admin: dict = Depends(require_roles("super_admin", "hr", "manager"))):
    db = get_db()
    emp = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if update:
        await db.employees.update_one({"id": employee_id}, {"$set": update})
        # mirror status to user
        if "status" in update:
            await db.users.update_one({"id": emp["user_id"]}, {"$set": {"status": update["status"]}})
    updated = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    return updated


@router.delete("/{employee_id}")
async def deactivate_employee(employee_id: str, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    emp = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    await db.employees.update_one({"id": employee_id}, {"$set": {"status": "inactive"}})
    await db.users.update_one({"id": emp["user_id"]}, {"$set": {"status": "inactive"}})
    return {"success": True}


# fix import order issue
import os  # noqa: E402
