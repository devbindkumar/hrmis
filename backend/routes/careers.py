import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from auth import get_current_user, require_roles
from db import get_db
from email_service import send_email, render

# Public router for the careers site (no auth)
public_router = APIRouter(prefix="/api/careers", tags=["careers-public"])

# Admin router for managing jobs + applications
admin_router = APIRouter(prefix="/api/jobs", tags=["jobs-admin"])


class JobCreate(BaseModel):
    title: str
    department: str
    location: str = "Remote"
    employment_type: str = "Full-time"  # Full-time | Part-time | Contract | Internship
    description: str
    requirements: str = ""
    salary_range: Optional[str] = None


class JobUpdate(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    salary_range: Optional[str] = None
    status: Optional[str] = None  # open | closed


class ApplicationCreate(BaseModel):
    job_id: str
    name: str = Field(min_length=2)
    email: EmailStr
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    portfolio: Optional[str] = None
    cover_letter: str = Field(min_length=20)


# -------------------- PUBLIC --------------------

@public_router.get("/jobs")
async def public_list_jobs(department: Optional[str] = None, q: Optional[str] = None):
    db = get_db()
    query: dict = {"status": "open"}
    if department and department != "all":
        query["department"] = department
    if q:
        query["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
            {"department": {"$regex": q, "$options": "i"}},
        ]
    items = await db.jobs.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return items


@public_router.get("/jobs/{job_id}")
async def public_get_job(job_id: str):
    db = get_db()
    job = await db.jobs.find_one({"id": job_id, "status": "open"}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@public_router.post("/apply")
async def public_apply(body: ApplicationCreate):
    db = get_db()
    job = await db.jobs.find_one({"id": body.job_id, "status": "open"}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="This position is no longer open")

    # avoid duplicate applications to same job
    existing = await db.applications.find_one({"job_id": body.job_id, "email": body.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="You've already applied to this position.")

    doc = {
        "id": str(uuid.uuid4()),
        "job_id": body.job_id,
        "job_title": job["title"],
        "name": body.name,
        "email": body.email.lower(),
        "phone": body.phone,
        "linkedin": body.linkedin,
        "portfolio": body.portfolio,
        "cover_letter": body.cover_letter,
        "stage": "new",  # new | reviewing | interview | offered | hired | rejected
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.applications.insert_one(doc)

    # bump job applicant count
    await db.jobs.update_one({"id": body.job_id}, {"$inc": {"applicant_count": 1}})

    # notify HR/admins
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": "admin",
        "audience": "admin",
        "type": "application",
        "title": "New application received",
        "body": f"{body.name} applied for {job['title']}",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # confirmation email to the applicant (best-effort)
    html = render(
        f"We received your application for {job['title']}",
        f"<p>Hi {body.name},</p>"
        f"<p>Thanks for applying to the <b>{job['title']}</b> role at Acme Corp. Our recruiting team will review your profile and follow up if it's a fit.</p>"
        f"<p>You'll always know where you stand — we typically respond within 5 working days.</p>",
    )
    await send_email(body.email, f"Application received: {job['title']}", html)

    doc.pop("_id", None)
    return {"success": True, "application_id": doc["id"]}


# -------------------- ADMIN --------------------

@admin_router.get("")
async def admin_list_jobs(user: dict = Depends(get_current_user), status: Optional[str] = None):
    db = get_db()
    q: dict = {}
    if status and status != "all":
        q["status"] = status
    items = await db.jobs.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return items


@admin_router.post("")
async def create_job(body: JobCreate, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    doc = {
        "id": str(uuid.uuid4()),
        "title": body.title,
        "department": body.department,
        "location": body.location,
        "employment_type": body.employment_type,
        "description": body.description,
        "requirements": body.requirements,
        "salary_range": body.salary_range,
        "status": "open",
        "applicant_count": 0,
        "created_by": admin["name"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.jobs.insert_one(doc)
    doc.pop("_id", None)
    return doc


@admin_router.patch("/{job_id}")
async def update_job(job_id: str, body: JobUpdate, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = await db.jobs.update_one({"id": job_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    return await db.jobs.find_one({"id": job_id}, {"_id": 0})


@admin_router.delete("/{job_id}")
async def delete_job(job_id: str, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    res = await db.jobs.delete_one({"id": job_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"success": True}


@admin_router.get("/applications/list")
async def list_applications(
    user: dict = Depends(require_roles("super_admin", "hr", "manager")),
    job_id: Optional[str] = None,
    stage: Optional[str] = None,
):
    db = get_db()
    q: dict = {}
    if job_id and job_id != "all":
        q["job_id"] = job_id
    if stage and stage != "all":
        q["stage"] = stage
    items = await db.applications.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return items


class StageUpdate(BaseModel):
    stage: str  # new | reviewing | interview | offered | hired | rejected


@admin_router.patch("/applications/{application_id}")
async def update_application(application_id: str, body: StageUpdate, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    res = await db.applications.update_one({"id": application_id}, {"$set": {"stage": body.stage}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Application not found")
    return await db.applications.find_one({"id": application_id}, {"_id": 0})
