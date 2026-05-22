from datetime import datetime, timezone, timedelta
from collections import defaultdict
from fastapi import APIRouter, Depends

from auth import get_current_user, require_roles
from db import get_db
from tenant import company_id_of

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/admin")
async def admin_overview(admin: dict = Depends(require_roles("super_admin", "hr", "manager"))):
    db = get_db()
    cid = company_id_of(admin)
    today = datetime.now(timezone.utc).date().isoformat()

    employees = await db.employees.find({"status": "active", "company_id": cid}, {"_id": 0}).to_list(500)
    total = len(employees)

    user_ids = [e["user_id"] for e in employees]

    # Today attendance
    attendance = await db.attendance.find({"date": today, "user_id": {"$in": user_ids}}, {"_id": 0}).to_list(500)
    present = sum(1 for a in attendance if a.get("check_in"))

    # On leave
    on_leave_docs = await db.leave_requests.find({
        "company_id": cid,
        "status": "approved",
        "start_date": {"$lte": today},
        "end_date": {"$gte": today},
    }, {"_id": 0}).to_list(500)
    on_leave = len(on_leave_docs)

    # WFH today
    wfh_docs = await db.wfh_requests.find({"company_id": cid, "status": "approved", "date": today}, {"_id": 0}).to_list(500)
    wfh = len(wfh_docs)

    absent = max(total - present - on_leave - wfh, 0)

    # Pending approvals
    pending_leave = await db.leave_requests.count_documents({"company_id": cid, "status": "pending"})
    pending_wfh = await db.wfh_requests.count_documents({"company_id": cid, "status": "pending"})

    # 7-day attendance trend
    trend = []
    for i in range(6, -1, -1):
        day = (datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat()
        att_day = await db.attendance.find({"date": day, "user_id": {"$in": user_ids}}, {"_id": 0}).to_list(500)
        leaves_day = await db.leave_requests.count_documents({
            "company_id": cid,
            "status": "approved",
            "start_date": {"$lte": day},
            "end_date": {"$gte": day},
        })
        wfh_day = await db.wfh_requests.count_documents({"company_id": cid, "status": "approved", "date": day})
        present_day = sum(1 for a in att_day if a.get("check_in"))
        trend.append({
            "date": day,
            "present": present_day,
            "wfh": wfh_day,
            "leave": leaves_day,
            "absent": max(total - present_day - wfh_day - leaves_day, 0),
        })

    # Department breakdown
    dept_counts: dict = defaultdict(int)
    for e in employees:
        dept_counts[e.get("department", "Other")] += 1

    # Recent approvals queue (top 8 pending)
    pending_leaves = await db.leave_requests.find({"company_id": cid, "status": "pending"}, {"_id": 0}).sort("created_at", -1).to_list(8)
    pending_wfhs = await db.wfh_requests.find({"company_id": cid, "status": "pending"}, {"_id": 0}).sort("created_at", -1).to_list(8)

    # latest announcement
    last_announcement = await db.announcements.find_one({"company_id": cid}, {"_id": 0}, sort=[("created_at", -1)])

    return {
        "kpi": {
            "total_employees": total,
            "present_today": present,
            "on_leave": on_leave,
            "wfh": wfh,
            "absent": absent,
            "pending_leave": pending_leave,
            "pending_wfh": pending_wfh,
        },
        "trend_7d": trend,
        "department_counts": [{"name": k, "count": v} for k, v in sorted(dept_counts.items(), key=lambda x: -x[1])],
        "pending_leaves": pending_leaves,
        "pending_wfhs": pending_wfhs,
        "latest_announcement": last_announcement,
    }


@router.get("/employee")
async def employee_overview(user: dict = Depends(get_current_user)):
    db = get_db()
    cid = company_id_of(user)
    today = datetime.now(timezone.utc).date().isoformat()

    attendance = await db.attendance.find_one({"user_id": user["id"], "date": today}, {"_id": 0})
    balances = await db.leave_balances.find({"user_id": user["id"], "company_id": cid}, {"_id": 0}).to_list(50)

    pending_leave = await db.leave_requests.count_documents({"user_id": user["id"], "status": "pending"})
    pending_wfh = await db.wfh_requests.count_documents({"user_id": user["id"], "status": "pending"})

    upcoming = await db.meetings.find({
        "company_id": cid,
        "$or": [{"created_by": user["id"]}, {"attendee_user_ids": user["id"]}],
        "starts_at": {"$gte": datetime.now(timezone.utc).isoformat()},
        "status": "scheduled",
    }, {"_id": 0}).sort("starts_at", 1).limit(5).to_list(5)

    announcements = await db.announcements.find({"company_id": cid}, {"_id": 0}).sort("created_at", -1).limit(3).to_list(3)

    return {
        "today_attendance": attendance,
        "balances": balances,
        "pending_leave": pending_leave,
        "pending_wfh": pending_wfh,
        "upcoming_meetings": upcoming,
        "announcements": announcements,
    }
