"""Background job that escalates pending leave/wfh requests older than a threshold.

Runs every 30 minutes. Looks at requests that have been pending for more than
ESCALATION_HOURS and adds an `escalated: True` flag + creates an admin/HR
notification + sends an email to HR + super_admin once.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
import uuid

from db import get_db
from email_service import send_email, render

logger = logging.getLogger(__name__)

ESCALATION_HOURS = int(os.environ.get("ESCALATION_HOURS", "48"))
CHECK_INTERVAL_SECONDS = int(os.environ.get("ESCALATION_CHECK_SECONDS", "1800"))  # 30 min


async def _hr_and_admin_users(db):
    users = await db.users.find(
        {"role": {"$in": ["super_admin", "hr"]}, "status": "active"},
        {"_id": 0, "id": 1, "email": 1, "name": 1},
    ).to_list(200)
    return users


async def _escalate_collection(db, collection_name: str, kind_label: str):
    """Escalate stale pending requests in a given collection."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=ESCALATION_HOURS)).isoformat()
    coll = db[collection_name]
    pending = await coll.find({
        "status": "pending",
        "escalated": {"$ne": True},
        "created_at": {"$lte": cutoff},
        "manager_user_id": {"$ne": None},  # only escalate when a manager was assigned
    }, {"_id": 0}).to_list(200)

    if not pending:
        return 0

    admins = await _hr_and_admin_users(db)
    admin_ids = [a["id"] for a in admins]

    escalated_count = 0
    for req in pending:
        # mark
        await coll.update_one(
            {"id": req["id"]},
            {"$set": {"escalated": True, "escalated_at": datetime.now(timezone.utc).isoformat()}},
        )
        body_preview = (
            f"{req.get('user_name', 'An employee')}'s {kind_label} request "
            f"has been pending more than {ESCALATION_HOURS}h. "
            f"Manager: {req.get('manager_name') or 'unassigned'}."
        )
        # in-app notification for each admin/HR
        for uid in admin_ids:
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": uid,
                "type": f"{kind_label}_escalated",
                "title": f"{kind_label.capitalize()} request escalated",
                "body": body_preview,
                "read": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        # one email per admin/HR
        for a in admins:
            html = render(
                f"{kind_label.capitalize()} request needs attention",
                f"<p>Hi {a['name']},</p>"
                f"<p>{body_preview}</p>"
                f"<p>Please review it in the admin console.</p>",
            )
            await send_email(a["email"], f"Escalated: {kind_label} request from {req.get('user_name')}", html)
        escalated_count += 1
    if escalated_count:
        logger.info(f"Escalated {escalated_count} stale {kind_label} request(s)")
    return escalated_count


async def run_once():
    db = get_db()
    await _escalate_collection(db, "leave_requests", "leave")
    await _escalate_collection(db, "wfh_requests", "wfh")


async def escalation_loop():
    # small delay so startup logs settle
    await asyncio.sleep(20)
    while True:
        try:
            await run_once()
        except Exception as e:
            logger.error(f"Escalation loop error: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
