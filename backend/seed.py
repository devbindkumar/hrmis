import os
import uuid
from datetime import datetime, timezone, timedelta

from auth import hash_password, verify_password
from db import get_db


async def ensure_indexes():
    db = get_db()
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.users.create_index("company_id")
    await db.employees.create_index("user_id", unique=True)
    await db.employees.create_index("company_id")
    await db.companies.create_index("slug", unique=True)
    await db.companies.create_index("id", unique=True)
    await db.attendance.create_index([("user_id", 1), ("date", 1)], unique=True)
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=3600)
    await db.login_attempts.create_index("key", unique=True)
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.chat_messages.create_index([("room_id", 1), ("created_at", 1)])
    await db.jobs.create_index("status")
    await db.jobs.create_index("company_id")
    await db.applications.create_index([("job_id", 1), ("email", 1)], unique=True)
    await db.departments.create_index([("company_id", 1), ("name", 1)])
    await db.leave_requests.create_index([("company_id", 1), ("status", 1)])
    await db.wfh_requests.create_index([("company_id", 1), ("status", 1)])
    await db.meetings.create_index("company_id")
    await db.announcements.create_index("company_id")


async def _ensure_default_company(db) -> str:
    default = await db.companies.find_one({"slug": "acme"})
    if not default:
        default_id = str(uuid.uuid4())
        default = {
            "id": default_id,
            "name": os.environ.get("COMPANY_NAME", "Acme Corp"),
            "slug": "acme",
            "escalation_hours": int(os.environ.get("ESCALATION_HOURS", "48")),
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": "system",
        }
        await db.companies.insert_one(default)
    default_id = default["id"]
    # Backfill company_id on every relevant collection
    for coll in (
        "users", "employees", "departments", "leave_requests", "leave_balances",
        "wfh_requests", "meetings", "chat_messages", "announcements",
        "notifications", "jobs", "applications", "attendance",
    ):
        await db[coll].update_many(
            {"$or": [{"company_id": {"$exists": False}}, {"company_id": None}]},
            {"$set": {"company_id": default_id}},
        )
    return default_id


async def seed_admin_and_demo():
    db = get_db()
    default_company_id = await _ensure_default_company(db)
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@acme.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "Admin@123")

    # ---- admin ----
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        admin_id = str(uuid.uuid4())
        await db.users.insert_one({
            "id": admin_id,
            "email": admin_email,
            "name": "Sarah Chen",
            "role": "super_admin",
            "status": "active",
            "company_id": default_company_id,
            "password_hash": hash_password(admin_password),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await db.employees.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": admin_id,
            "company_id": default_company_id,
            "employee_code": "ACM-0001",
            "name": "Sarah Chen",
            "email": admin_email,
            "department": "Executive",
            "designation": "Chief People Officer",
            "manager_id": None,
            "location": "HQ - San Francisco",
            "shift": "General (9:00 – 18:00)",
            "joined_at": (datetime.now(timezone.utc) - timedelta(days=720)).date().isoformat(),
            "phone": "+1 (415) 555-0100",
            "avatar_url": "https://images.unsplash.com/photo-1573496130141-209d200cebd8?crop=entropy&cs=srgb&fm=jpg&w=200",
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_password)}})

    # ---- demo employees ----
    seed_jobs = await db.jobs.count_documents({}) == 0
    if await db.users.count_documents({"role": {"$ne": "super_admin"}}) > 0:
        # Even if users already exist, ensure jobs and salary structures are present
        if seed_jobs:
            await _seed_sample_jobs(db)
        await _seed_sample_salaries(db, default_company_id)
        await _seed_leave_types(db, default_company_id)
        return  # demo already seeded

    departments = [
        {"id": str(uuid.uuid4()), "name": "Engineering", "head": "Alex Rivera"},
        {"id": str(uuid.uuid4()), "name": "Design", "head": "Priya Sharma"},
        {"id": str(uuid.uuid4()), "name": "People Ops", "head": "Sarah Chen"},
        {"id": str(uuid.uuid4()), "name": "Sales", "head": "Marcus Webb"},
    ]
    await db.departments.insert_many([{**d, "created_at": datetime.now(timezone.utc).isoformat()} for d in departments])

    avatars = [
        "https://images.unsplash.com/photo-1666867936058-de34bfd5b320?crop=entropy&cs=srgb&fm=jpg&w=200",
        "https://images.unsplash.com/photo-1573496130141-209d200cebd8?crop=entropy&cs=srgb&fm=jpg&w=200",
        "https://images.pexels.com/photos/7658241/pexels-photo-7658241.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=200&w=200",
    ]

    demo = [
        ("Alex Rivera", "alex@acme.com", "manager", "Engineering", "Engineering Manager"),
        ("Priya Sharma", "priya@acme.com", "manager", "Design", "Design Lead"),
        ("Marcus Webb", "marcus@acme.com", "manager", "Sales", "Sales Director"),
        ("Jordan Kim", "jordan@acme.com", "hr", "People Ops", "HR Business Partner"),
        ("Maya Patel", "maya@acme.com", "employee", "Engineering", "Senior Backend Engineer"),
        ("Diego Santos", "diego@acme.com", "employee", "Engineering", "Frontend Engineer"),
        ("Lena Park", "lena@acme.com", "employee", "Design", "Product Designer"),
        ("Omar Hassan", "omar@acme.com", "employee", "Sales", "Account Executive"),
        ("Riya Mehta", "riya@acme.com", "employee", "Engineering", "ML Engineer"),
        ("Tom Becker", "tom@acme.com", "employee", "Sales", "SDR"),
    ]
    code_seq = 2
    leave_types = [
        ("Casual", 12),
        ("Sick", 8),
        ("Earned", 15),
        ("WFH Quota", 60),
    ]
    for i, (name, email, role, dept, desig) in enumerate(demo):
        user_id = str(uuid.uuid4())
        await db.users.insert_one({
            "id": user_id,
            "email": email.lower(),
            "name": name,
            "role": role,
            "status": "active",
            "password_hash": hash_password("Demo@123"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await db.employees.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "employee_code": f"ACM-{code_seq:04d}",
            "name": name,
            "email": email.lower(),
            "department": dept,
            "designation": desig,
            "manager_id": None,
            "location": "HQ - San Francisco" if i % 2 == 0 else "Remote",
            "shift": "General (9:00 – 18:00)",
            "joined_at": (datetime.now(timezone.utc) - timedelta(days=120 + i * 30)).date().isoformat(),
            "phone": f"+1 (415) 555-{1000 + i:04d}",
            "avatar_url": avatars[i % len(avatars)],
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # leave balances
        for lt, qty in leave_types:
            await db.leave_balances.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "leave_type": lt,
                "total": qty,
                "used": 0,
            })
        code_seq += 1

    # Also seed leave balances for admin
    admin_user = await db.users.find_one({"email": admin_email}, {"_id": 0})
    if admin_user:
        for lt, qty in leave_types:
            existing_bal = await db.leave_balances.find_one({"user_id": admin_user["id"], "leave_type": lt})
            if not existing_bal:
                await db.leave_balances.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": admin_user["id"],
                    "leave_type": lt,
                    "total": qty,
                    "used": 0,
                })

    # Sample jobs (public careers page)
    await _seed_sample_jobs(db)
    # Sample salary structures
    await _seed_sample_salaries(db, default_company_id)

    # Sample announcement
    await db.announcements.insert_one({
        "id": str(uuid.uuid4()),
        "title": "Welcome to HRMIS",
        "body": "Hi team — our new HR platform is live. You can now check-in/out, apply for leave or WFH, and message colleagues right from here.",
        "author_name": "Sarah Chen",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })



async def _seed_sample_jobs(db):
    """Idempotent insert of sample job postings."""
    sample = [
        {
            "title": "Senior Product Designer",
            "department": "Design",
            "location": "San Francisco / Hybrid",
            "employment_type": "Full-time",
            "description": "We're looking for a senior product designer to shape end-to-end experiences across our enterprise dashboard. You'll partner with engineering and PM to ship polished, opinionated UI.",
            "requirements": "5+ years of product design experience\nStrong portfolio showcasing dashboard / data-dense work\nFluency in Figma\nExcellent written communication",
            "salary_range": "$140k – $185k",
        },
        {
            "title": "Backend Engineer (Python / FastAPI)",
            "department": "Engineering",
            "location": "Remote (US / EU)",
            "employment_type": "Full-time",
            "description": "Join the platform team to build scalable APIs that power our HR and people-ops products. You'll own systems end-to-end.",
            "requirements": "4+ years building production Python services\nDeep experience with FastAPI / async Python\nMongoDB / Postgres at scale\nBias for clarity & testing",
            "salary_range": "$160k – $210k",
        },
        {
            "title": "People Operations Specialist",
            "department": "People Ops",
            "location": "San Francisco",
            "employment_type": "Full-time",
            "description": "Help us build the operational backbone of a fast-growing company — onboarding, benefits, compliance, and culture programs.",
            "requirements": "3+ years in People Ops / HR Ops\nFamiliar with US labour law basics\nObsessive about good employee experience",
            "salary_range": "$95k – $125k",
        },
        {
            "title": "Sales Development Representative",
            "department": "Sales",
            "location": "Remote",
            "employment_type": "Full-time",
            "description": "Help us grow our customer base by qualifying inbound leads and prospecting outbound to companies that would benefit from a modern HR platform.",
            "requirements": "1-3 years of SDR experience (SaaS preferred)\nClear written communication\nResilient and curious",
            "salary_range": "$70k base + commission",
        },
    ]
    for s in sample:
        existing = await db.jobs.find_one({"title": s["title"]})
        if existing:
            continue
        await db.jobs.insert_one({
            "id": str(uuid.uuid4()),
            **s,
            "status": "open",
            "applicant_count": 0,
            "created_by": "Sarah Chen",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })


async def _seed_sample_salaries(db, company_id: str):
    """Idempotent seed of salary structures for demo users in the default company."""
    role_pay = {
        "super_admin": {"base": 14000, "hra": 2800, "transport": 500, "special": 1200, "pf_pct": 6, "tax_pct": 18},
        "manager":     {"base": 11000, "hra": 2200, "transport": 400, "special": 900,  "pf_pct": 6, "tax_pct": 15},
        "hr":          {"base":  9500, "hra": 1900, "transport": 400, "special": 700,  "pf_pct": 6, "tax_pct": 12},
        "employee":    {"base":  7500, "hra": 1500, "transport": 350, "special": 500,  "pf_pct": 6, "tax_pct": 10},
    }
    users = await db.users.find({"company_id": company_id}, {"_id": 0, "id": 1, "role": 1}).to_list(500)
    for u in users:
        existing = await db.salary_structures.find_one({"user_id": u["id"], "company_id": company_id})
        if existing:
            continue
        pay = role_pay.get(u.get("role"), role_pay["employee"])
        now = datetime.now(timezone.utc).isoformat()
        await db.salary_structures.insert_one({
            "id": str(uuid.uuid4()),
            "company_id": company_id,
            "user_id": u["id"],
            "base_salary": pay["base"],
            "allowances": {"hra": pay["hra"], "transport": pay["transport"], "special": pay["special"]},
            "pf_pct": pay["pf_pct"],
            "tax_pct": pay["tax_pct"],
            "currency": "USD",
            "created_at": now,
            "updated_at": now,
        })


async def _seed_leave_types(db, company_id: str):
    """Seed default leave types if missing."""
    defaults = [
        ("Casual", 12, True),
        ("Sick", 8, True),
        ("Earned", 15, True),
        ("WFH Quota", 60, True),
        ("Unpaid Leave", 30, False),
    ]
    for name, quota, is_paid in defaults:
        existing = await db.leave_types.find_one({"company_id": company_id, "name": name})
        if not existing:
            await db.leave_types.insert_one({
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "name": name,
                "default_quota": quota,
                "is_paid": is_paid,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
