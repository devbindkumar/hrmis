import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from fastapi.responses import StreamingResponse
import io
import csv
from pydantic import BaseModel, EmailStr, Field

from auth import get_current_user, require_roles
from db import get_db
from email_service import send_email, render
from storage import put_object, get_object, APP_NAME

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
    resume_path: Optional[str] = None
    resume_filename: Optional[str] = None


# -------------------- PUBLIC --------------------

@public_router.get("/jobs")
async def public_list_jobs(department: Optional[str] = None, q: Optional[str] = None, company: Optional[str] = None):
    db = get_db()
    slug = (company or "acme").lower()
    comp = await db.companies.find_one({"slug": slug}, {"_id": 0, "id": 1})
    if not comp:
        return []
    query: dict = {"status": "open", "company_id": comp["id"]}
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
        "company_id": job.get("company_id"),
        "job_id": body.job_id,
        "job_title": job["title"],
        "name": body.name,
        "email": body.email.lower(),
        "phone": body.phone,
        "linkedin": body.linkedin,
        "portfolio": body.portfolio,
        "cover_letter": body.cover_letter,
        "resume_path": body.resume_path,
        "resume_filename": body.resume_filename,
        "stage": "new",  # new | reviewing | interview | offered | hired | rejected
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.applications.insert_one(doc)

    # bump job applicant count
    await db.jobs.update_one({"id": body.job_id}, {"$inc": {"applicant_count": 1}})

    # notify HR/admins of the right company
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "company_id": job.get("company_id"),
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
    q: dict = {"company_id": company_id_of(user)}
    if status and status != "all":
        q["status"] = status
    items = await db.jobs.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return items


@admin_router.post("")
async def create_job(body: JobCreate, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    doc = {
        "id": str(uuid.uuid4()),
        "company_id": company_id_of(admin),
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
    q: dict = {"company_id": company_id_of(user)}
    if job_id and job_id != "all":
        q["job_id"] = job_id
    if stage and stage != "all":
        q["stage"] = stage
    items = await db.applications.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return items


class StageUpdate(BaseModel):
    stage: str  # new | reviewing | interview | offered | hired | rejected
    notify_candidate: bool = True


STAGE_EMAILS = {
    "reviewing": {
        "subject": "Your application is under review",
        "title": "We're reviewing your application",
        "body": "Hi {name},<br/><br/>Good news — our recruiting team is reviewing your application for the <b>{job_title}</b> role. We'll be in touch with next steps shortly.<br/><br/>Thanks for your patience.",
    },
    "interview": {
        "subject": "Interview round — {job_title}",
        "title": "We'd love to talk",
        "body": "Hi {name},<br/><br/>Thanks for applying for <b>{job_title}</b>. We were impressed and would love to schedule an interview to learn more about you.<br/><br/>Our recruiting team will reach out shortly with scheduling details.",
    },
    "offered": {
        "subject": "An offer is on its way 🎉 — {job_title}",
        "title": "Offer extended",
        "body": "Hi {name},<br/><br/>We're delighted to extend an offer for the <b>{job_title}</b> role. You'll receive the formal offer letter and details from our People Ops team within one business day.<br/><br/>Welcome (almost) to the team!",
    },
    "hired": {
        "subject": "Welcome to Acme Corp",
        "title": "Welcome aboard",
        "body": "Hi {name},<br/><br/>It's official — welcome to the team! We're thrilled to have you joining as <b>{job_title}</b>. Your onboarding details will follow shortly.",
    },
    "rejected": {
        "subject": "Update on your application",
        "title": "An update on your application",
        "body": "Hi {name},<br/><br/>Thank you for your interest in the <b>{job_title}</b> role and for taking the time to apply. After careful consideration, we won't be moving forward with your application at this time.<br/><br/>We genuinely appreciate the effort you put in and wish you the very best.",
    },
}


@admin_router.patch("/applications/{application_id}")
async def update_application(application_id: str, body: StageUpdate, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    app_doc = await db.applications.find_one({"id": application_id}, {"_id": 0})
    if not app_doc:
        raise HTTPException(status_code=404, detail="Application not found")

    prev_stage = app_doc.get("stage")
    await db.applications.update_one({"id": application_id}, {"$set": {"stage": body.stage}})

    # Email the candidate on stage transition (not on no-op)
    if body.notify_candidate and body.stage != prev_stage and body.stage in STAGE_EMAILS:
        tmpl = STAGE_EMAILS[body.stage]
        subject = tmpl["subject"].format(job_title=app_doc["job_title"])
        body_html = tmpl["body"].format(name=app_doc["name"], job_title=app_doc["job_title"])
        await send_email(app_doc["email"], subject, render(tmpl["title"], body_html))

    return await db.applications.find_one({"id": application_id}, {"_id": 0})


# ----------------- Resume upload / download -----------------

@public_router.post("/resume")
async def upload_resume(file: UploadFile = File(...)):
    """Public: upload a resume PDF before submitting an application."""
    allowed = {"application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    content_type = file.content_type or "application/octet-stream"
    if content_type not in allowed:
        raise HTTPException(status_code=400, detail="Please upload a PDF or Word document.")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (10 MB max).")
    ext = "pdf"
    if "." in (file.filename or ""):
        ext = file.filename.rsplit(".", 1)[-1].lower()
    path = f"{APP_NAME}/resumes/{uuid.uuid4()}.{ext}"
    try:
        result = put_object(path, data, content_type)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Storage unavailable: {e}")
    return {
        "path": result["path"],
        "filename": file.filename,
        "size": result.get("size", len(data)),
        "content_type": content_type,
    }


@admin_router.get("/applications/{application_id}/resume")
async def download_resume(application_id: str, admin: dict = Depends(require_roles("super_admin", "hr", "manager"))):
    db = get_db()
    app_doc = await db.applications.find_one({"id": application_id}, {"_id": 0})
    if not app_doc or not app_doc.get("resume_path"):
        raise HTTPException(status_code=404, detail="No resume on this application")
    try:
        data, content_type = get_object(app_doc["resume_path"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Couldn't fetch resume: {e}")
    filename = app_doc.get("resume_filename") or "resume.pdf"
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ----------------- CSV export -----------------

@admin_router.get("/applications/export.csv")
async def export_applications_csv(
    admin: dict = Depends(require_roles("super_admin", "hr")),
    job_id: Optional[str] = None,
    stage: Optional[str] = None,
):
    db = get_db()
    q: dict = {}
    if job_id and job_id != "all":
        q["job_id"] = job_id
    if stage and stage != "all":
        q["stage"] = stage
    items = await db.applications.find(q, {"_id": 0}).sort("created_at", -1).to_list(5000)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Applied at", "Name", "Email", "Phone", "LinkedIn", "Portfolio", "Job", "Stage", "Cover letter"])
    for a in items:
        writer.writerow([
            a.get("created_at", ""),
            a.get("name", ""),
            a.get("email", ""),
            a.get("phone", ""),
            a.get("linkedin", ""),
            a.get("portfolio", ""),
            a.get("job_title", ""),
            a.get("stage", ""),
            (a.get("cover_letter") or "").replace("\n", " "),
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="applicants-{datetime.now(timezone.utc).date().isoformat()}.csv"'},
    )
