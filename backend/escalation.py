"""Background job that escalates pending leave/wfh requests older than threshold.

Reads `escalation_hours` per company from the companies collection. Runs every 30 min.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
import uuid

from db import get_db
from email_service import send_email, render

logger = logging.getLogger(__name__)

DEFAULT_ESCALATION_HOURS = int(os.environ.get("ESCALATION_HOURS", "48"))
CHECK_INTERVAL_SECONDS = int(os.environ.get("ESCALATION_CHECK_SECONDS", "1800"))


async def _hr_and_admin_users(db, company_id: str):
    users = await db.users.find(
        {"role": {"$in": ["super_admin", "hr"]}, "status": "active", "company_id": company_id},
        {"_id": 0, "id": 1, "email": 1, "name": 1},
    ).to_list(200)
    return users


async def _escalate_collection(db, collection_name: str, kind_label: str, company_id: str, escalation_hours: int):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=escalation_hours)).isoformat()
    coll = db[collection_name]
    pending = await coll.find({
        "company_id": company_id,
        "status": "pending",
        "escalated": {"$ne": True},
        "created_at": {"$lte": cutoff},
        "manager_user_id": {"$ne": None},
    }, {"_id": 0}).to_list(200)

    if not pending:
        return 0

    admins = await _hr_and_admin_users(db, company_id)
    admin_ids = [a["id"] for a in admins]
    escalated_count = 0
    for req in pending:
        await coll.update_one(
            {"id": req["id"]},
            {"$set": {"escalated": True, "escalated_at": datetime.now(timezone.utc).isoformat()}},
        )
        body_preview = (
            f"{req.get('user_name', 'An employee')}'s {kind_label} request "
            f"has been pending more than {escalation_hours}h. "
            f"Manager: {req.get('manager_name') or 'unassigned'}."
        )
        for uid in admin_ids:
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "user_id": uid,
                "type": f"{kind_label}_escalated",
                "title": f"{kind_label.capitalize()} request escalated",
                "body": body_preview,
                "read": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
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
        logger.info(f"[company={company_id}] Escalated {escalated_count} stale {kind_label} request(s)")
    return escalated_count


async def run_once():
    db = get_db()
    # Iterate every active company and use its escalation_hours
    companies = await db.companies.find({"status": {"$ne": "suspended"}}, {"_id": 0, "id": 1, "escalation_hours": 1}).to_list(500)
    for c in companies:
        hours = c.get("escalation_hours") or DEFAULT_ESCALATION_HOURS
        await _escalate_collection(db, "leave_requests", "leave", c["id"], hours)
        await _escalate_collection(db, "wfh_requests", "wfh", c["id"], hours)


async def escalation_loop():
    await asyncio.sleep(20)
    while True:
        try:
            await run_once()
        except Exception as e:
            logger.error(f"Escalation loop error: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
