from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os  # noqa: E402
import logging  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

from db import get_db  # noqa: E402
from auth import router as auth_router  # noqa: E402
from routes.employees import router as employees_router  # noqa: E402
from routes.departments import router as departments_router  # noqa: E402
from routes.attendance import router as attendance_router  # noqa: E402
from routes.leave import router as leave_router  # noqa: E402
from routes.wfh import router as wfh_router  # noqa: E402
from routes.meetings import router as meetings_router  # noqa: E402
from routes.chat import router as chat_router  # noqa: E402
from routes.announcements import router as announcements_router  # noqa: E402
from routes.notifications import router as notifications_router  # noqa: E402
from routes.dashboard import router as dashboard_router  # noqa: E402
from routes.careers import public_router as careers_public_router, admin_router as jobs_admin_router  # noqa: E402
from routes.companies import router as companies_router  # noqa: E402
from seed import ensure_indexes, seed_admin_and_demo  # noqa: E402
from storage import init_storage  # noqa: E402
from escalation import escalation_loop  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("hrmis")


app = FastAPI(title="HRMIS API", version="1.0")

# CORS - allow all (same-host preview). credentials false to allow * wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/")
async def root():
    return {"name": "HRMIS API", "status": "ok"}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(employees_router)
app.include_router(departments_router)
app.include_router(attendance_router)
app.include_router(leave_router)
app.include_router(wfh_router)
app.include_router(meetings_router)
app.include_router(chat_router)
app.include_router(announcements_router)
app.include_router(notifications_router)
app.include_router(dashboard_router)
app.include_router(careers_public_router)
app.include_router(jobs_admin_router)
app.include_router(companies_router)


@app.on_event("startup")
async def on_startup():
    try:
        await ensure_indexes()
        await seed_admin_and_demo()
        init_storage()
        # Fire-and-forget background escalation loop
        import asyncio  # local import to avoid top-level dep noise
        asyncio.create_task(escalation_loop())
        logger.info("HRMIS startup: indexes + seed complete")
    except Exception as e:
        logger.error(f"Startup error: {e}")


@app.on_event("shutdown")
async def on_shutdown():
    pass
