import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from auth import get_current_user, require_roles, hash_password
from db import get_db

router = APIRouter(prefix="/api/companies", tags=["companies"])


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2)
    slug: str = Field(min_length=2, pattern=r"^[a-z0-9-]+$")
    escalation_hours: int = 48
    admin_email: EmailStr
    admin_name: str
    admin_password: str = Field(default="Admin@123", min_length=6)


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    escalation_hours: Optional[int] = None
    status: Optional[str] = None  # active | suspended


def _slugify(name: str) -> str:
    base = "".join(c.lower() if c.isalnum() else "-" for c in name)
    base = "-".join([p for p in base.split("-") if p])
    return base or "company"


@router.get("")
async def list_companies(user: dict = Depends(get_current_user)):
    """super_admin sees all companies; everyone else sees just their own."""
    db = get_db()
    if user.get("role") == "super_admin":
        items = await db.companies.find({}, {"_id": 0}).sort("created_at", 1).to_list(200)
    else:
        cid = user.get("company_id")
        if not cid:
            return []
        items = await db.companies.find({"id": cid}, {"_id": 0}).to_list(1)
    # attach headcount
    for c in items:
        c["employee_count"] = await db.employees.count_documents({"company_id": c["id"], "status": "active"})
    return items


@router.post("")
async def create_company(body: CompanyCreate, admin: dict = Depends(require_roles("super_admin"))):
    db = get_db()
    slug = body.slug.strip().lower()
    if await db.companies.find_one({"slug": slug}):
        raise HTTPException(status_code=400, detail="Slug already exists")
    if await db.users.find_one({"email": body.admin_email.lower()}):
        raise HTTPException(status_code=400, detail="That admin email is already in use")

    now = datetime.now(timezone.utc).isoformat()
    company_id = str(uuid.uuid4())
    company = {
        "id": company_id,
        "name": body.name,
        "slug": slug,
        "escalation_hours": max(body.escalation_hours, 1),
        "status": "active",
        "created_at": now,
        "created_by": admin["id"],
    }
    await db.companies.insert_one(company)

    # Seed the company's first admin user
    admin_user_id = str(uuid.uuid4())
    await db.users.insert_one({
        "id": admin_user_id,
        "email": body.admin_email.lower(),
        "name": body.admin_name,
        "role": "super_admin",
        "status": "active",
        "company_id": company_id,
        "password_hash": hash_password(body.admin_password),
        "created_at": now,
    })
    # Seed their employee record
    await db.employees.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": admin_user_id,
        "company_id": company_id,
        "employee_code": f"{slug.upper()[:3]}-0001",
        "name": body.admin_name,
        "email": body.admin_email.lower(),
        "department": "Executive",
        "designation": "Founder / Admin",
        "manager_id": None,
        "location": "HQ",
        "shift": "General (9:00 – 18:00)",
        "phone": None,
        "avatar_url": f"https://api.dicebear.com/7.x/initials/svg?seed={body.admin_name}",
        "status": "active",
        "joined_at": datetime.now(timezone.utc).date().isoformat(),
        "created_at": now,
    })
    # Seed default leave balances
    for lt, qty in [("Casual", 12), ("Sick", 8), ("Earned", 15), ("WFH Quota", 60)]:
        await db.leave_balances.insert_one({
            "id": str(uuid.uuid4()),
            "company_id": company_id,
            "user_id": admin_user_id,
            "leave_type": lt,
            "total": qty,
            "used": 0,
        })
    return {"company": company, "admin_user_id": admin_user_id}


@router.patch("/{company_id}")
async def update_company(company_id: str, body: CompanyUpdate, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    # Only super_admin can touch other companies; hr can only touch their own
    if admin.get("role") != "super_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="You can only edit your own company")

    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "escalation_hours" in update:
        update["escalation_hours"] = max(int(update["escalation_hours"]), 1)
    res = await db.companies.update_one({"id": company_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    return await db.companies.find_one({"id": company_id}, {"_id": 0})


@router.get("/mine")
async def my_company(user: dict = Depends(get_current_user)):
    db = get_db()
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(status_code=404, detail="No company")
    company = await db.companies.find_one({"id": cid}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company
