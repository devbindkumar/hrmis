"""Lightweight payroll module: salary structures + monthly payslip runs."""
import uuid
import io
import csv
import calendar
from datetime import datetime, timezone, date, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth import get_current_user, require_roles
from db import get_db
from email_service import send_email, render
from tenant import company_id_of

router = APIRouter(prefix="/api/payroll", tags=["payroll"])


# ---------------- Models ----------------

class Allowances(BaseModel):
    hra: float = 0
    transport: float = 0
    special: float = 0


class SalaryStructureUpsert(BaseModel):
    user_id: str
    base_salary: float = Field(ge=0)  # monthly base
    allowances: Allowances = Allowances()
    pf_pct: float = Field(default=6.0, ge=0, le=50)  # % of base
    tax_pct: float = Field(default=10.0, ge=0, le=60)  # % of (gross - pf)
    currency: str = "USD"


class RunPayroll(BaseModel):
    period: str  # YYYY-MM


def _calc_payslip(struct: dict, lop_days: int = 0, working_days: int = 22) -> dict:
    base = float(struct.get("base_salary", 0) or 0)
    al = struct.get("allowances") or {}
    hra = float(al.get("hra", 0) or 0)
    transport = float(al.get("transport", 0) or 0)
    special = float(al.get("special", 0) or 0)
    gross = base + hra + transport + special
    pf_amount = round(base * (struct.get("pf_pct", 0) or 0) / 100, 2)
    tax_amount = round((gross - pf_amount) * (struct.get("tax_pct", 0) or 0) / 100, 2)
    # Loss-of-pay: per-day rate applied to LOP days. Use base as the per-day rate basis.
    per_day_rate = round(base / working_days, 2) if working_days else 0
    lop_amount = round(per_day_rate * lop_days, 2)
    total_deductions = round(pf_amount + tax_amount + lop_amount, 2)
    net = round(gross - total_deductions, 2)
    return {
        "base_salary": round(base, 2),
        "hra": round(hra, 2),
        "transport": round(transport, 2),
        "special": round(special, 2),
        "gross": round(gross, 2),
        "pf_amount": pf_amount,
        "tax_amount": tax_amount,
        "lop_days": lop_days,
        "lop_amount": lop_amount,
        "per_day_rate": per_day_rate,
        "working_days": working_days,
        "total_deductions": total_deductions,
        "net": net,
        "currency": struct.get("currency", "USD"),
        "pf_pct": struct.get("pf_pct"),
        "tax_pct": struct.get("tax_pct"),
    }


def _working_days_in_period(period: str) -> int:
    """Count Mon-Fri days in a YYYY-MM period."""
    year, month = map(int, period.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    count = 0
    for d in range(1, last_day + 1):
        if date(year, month, d).weekday() < 5:
            count += 1
    return count


async def _compute_lop(db, company_id: str, user_id: str, period: str) -> dict:
    """Calculate LOP (unpaid) days for a user in a given period."""
    year, month = map(int, period.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    period_start = date(year, month, 1)
    period_end = date(year, month, last_day)
    start_iso = period_start.isoformat()
    end_iso = period_end.isoformat()

    paid_dates: set = set()

    # Days with check-in count as worked
    attendance = await db.attendance.find(
        {"user_id": user_id, "date": {"$gte": start_iso, "$lte": end_iso}},
        {"_id": 0, "date": 1, "check_in": 1},
    ).to_list(100)
    for a in attendance:
        if a.get("check_in"):
            try: paid_dates.add(date.fromisoformat(a["date"]))
            except Exception: pass

    # Build is_paid map for leave types in this company
    leave_types = await db.leave_types.find({"company_id": company_id}, {"_id": 0, "name": 1, "is_paid": 1}).to_list(100)
    is_paid_map = {lt["name"]: bool(lt.get("is_paid", True)) for lt in leave_types}

    # Approved leave (any overlap within the period). Only PAID types count as worked days.
    leaves = await db.leave_requests.find(
        {"user_id": user_id, "company_id": company_id, "status": "approved",
         "start_date": {"$lte": end_iso}, "end_date": {"$gte": start_iso}},
        {"_id": 0, "start_date": 1, "end_date": 1, "leave_type": 1},
    ).to_list(200)
    for l in leaves:
        # Default to paid if leave type is unknown (back-compat for legacy data)
        if not is_paid_map.get(l.get("leave_type"), True):
            continue  # unpaid leave -> let those days count as LOP
        try:
            ls = max(date.fromisoformat(l["start_date"]), period_start)
            le = min(date.fromisoformat(l["end_date"]), period_end)
            d = ls
            while d <= le:
                paid_dates.add(d)
                d += timedelta(days=1)
        except Exception: pass

    # Approved WFH days
    wfh = await db.wfh_requests.find(
        {"user_id": user_id, "company_id": company_id, "status": "approved",
         "date": {"$gte": start_iso, "$lte": end_iso}},
        {"_id": 0, "date": 1},
    ).to_list(100)
    for w in wfh:
        try: paid_dates.add(date.fromisoformat(w["date"]))
        except Exception: pass

    # Only count working days (Mon-Fri)
    paid_workdays = sum(1 for d in paid_dates if d.weekday() < 5)
    working_days = _working_days_in_period(period)
    lop_days = max(working_days - paid_workdays, 0)
    return {"working_days": working_days, "paid_workdays": paid_workdays, "lop_days": lop_days}


# ---------------- Salary Structures ----------------

@router.get("/structures")
async def list_structures(user: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    cid = company_id_of(user)
    structs = await db.salary_structures.find({"company_id": cid}, {"_id": 0}).to_list(500)
    s_by_user = {s["user_id"]: s for s in structs}
    # Join with all active employees
    employees = await db.employees.find({"company_id": cid, "status": "active"}, {"_id": 0}).sort("name", 1).to_list(500)
    out = []
    for e in employees:
        s = s_by_user.get(e["user_id"])
        out.append({
            "user_id": e["user_id"],
            "employee_id": e["id"],
            "name": e["name"],
            "designation": e.get("designation"),
            "department": e.get("department"),
            "avatar_url": e.get("avatar_url"),
            "structure": s,
            "calc": _calc_payslip(s) if s else None,
        })
    return out


@router.get("/structures/me")
async def my_structure(user: dict = Depends(get_current_user)):
    db = get_db()
    s = await db.salary_structures.find_one({"user_id": user["id"], "company_id": company_id_of(user)}, {"_id": 0})
    if not s:
        return None
    s["calc"] = _calc_payslip(s)
    return s


@router.put("/structures/{user_id}")
async def upsert_structure(user_id: str, body: SalaryStructureUpsert, admin: dict = Depends(require_roles("super_admin", "hr"))):
    db = get_db()
    cid = company_id_of(admin)
    # confirm target user belongs to same company
    target = await db.users.find_one({"id": user_id, "company_id": cid}, {"_id": 0, "id": 1})
    if not target:
        raise HTTPException(status_code=404, detail="Employee not in your company")
    now = datetime.now(timezone.utc).isoformat()
    update = {
        "company_id": cid,
        "user_id": user_id,
        "base_salary": body.base_salary,
        "allowances": body.allowances.model_dump(),
        "pf_pct": body.pf_pct,
        "tax_pct": body.tax_pct,
        "currency": body.currency,
        "updated_at": now,
    }
    existing = await db.salary_structures.find_one({"user_id": user_id, "company_id": cid})
    if existing:
        await db.salary_structures.update_one({"user_id": user_id, "company_id": cid}, {"$set": update})
    else:
        update["id"] = str(uuid.uuid4())
        update["created_at"] = now
        await db.salary_structures.insert_one(update)
    saved = await db.salary_structures.find_one({"user_id": user_id, "company_id": cid}, {"_id": 0})
    saved["calc"] = _calc_payslip(saved)
    return saved


# ---------------- Payslips ----------------

@router.post("/run")
async def run_payroll(body: RunPayroll, admin: dict = Depends(require_roles("super_admin", "hr"))):
    """Generate payslips for the period for everyone with a structure. Idempotent on (user_id, period)."""
    db = get_db()
    cid = company_id_of(admin)
    period = body.period.strip()
    if len(period) != 7 or period[4] != "-":
        raise HTTPException(status_code=400, detail="Period must be YYYY-MM")

    structs = await db.salary_structures.find({"company_id": cid}, {"_id": 0}).to_list(500)
    if not structs:
        raise HTTPException(status_code=400, detail="No salary structures configured. Set them first.")

    user_ids = [s["user_id"] for s in structs]
    employees = await db.employees.find({"user_id": {"$in": user_ids}, "company_id": cid}, {"_id": 0, "user_id": 1, "name": 1, "email": 1, "designation": 1, "employee_code": 1}).to_list(500)
    emp_map = {e["user_id"]: e for e in employees}

    now = datetime.now(timezone.utc).isoformat()
    created = 0
    skipped = 0
    updated = 0
    for s in structs:
        emp = emp_map.get(s["user_id"])
        if not emp:
            continue
        # Compute LOP for this user in this period
        lop_info = await _compute_lop(db, cid, s["user_id"], period)
        calc = _calc_payslip(s, lop_days=lop_info["lop_days"], working_days=lop_info["working_days"])
        calc["paid_workdays"] = lop_info["paid_workdays"]
        existing = await db.payslips.find_one({"company_id": cid, "user_id": s["user_id"], "period": period})
        if existing and existing.get("status") in ("finalized", "paid"):
            skipped += 1
            continue
        doc = {
            "company_id": cid,
            "user_id": s["user_id"],
            "user_name": emp["name"],
            "employee_code": emp.get("employee_code"),
            "designation": emp.get("designation"),
            "period": period,
            "components": calc,
            "status": "draft",
            "generated_by": admin["name"],
            "generated_at": now,
        }
        if existing:
            await db.payslips.update_one({"id": existing["id"]}, {"$set": doc})
            updated += 1
        else:
            doc["id"] = str(uuid.uuid4())
            await db.payslips.insert_one(doc)
            created += 1
    return {"period": period, "created": created, "updated": updated, "skipped": skipped, "total_structures": len(structs)}


@router.get("/payslips")
async def list_payslips(user: dict = Depends(require_roles("super_admin", "hr", "manager")), period: Optional[str] = None, status: Optional[str] = None):
    db = get_db()
    q: dict = {"company_id": company_id_of(user)}
    if period:
        q["period"] = period
    if status and status != "all":
        q["status"] = status
    items = await db.payslips.find(q, {"_id": 0}).sort([("period", -1), ("user_name", 1)]).to_list(2000)
    return items


@router.get("/payslips/mine")
async def my_payslips(user: dict = Depends(get_current_user)):
    db = get_db()
    items = await db.payslips.find(
        {"user_id": user["id"], "company_id": company_id_of(user), "status": {"$ne": "draft"}},
        {"_id": 0},
    ).sort("period", -1).to_list(200)
    return items


@router.get("/payslips/{payslip_id}")
async def get_payslip(payslip_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    ps = await db.payslips.find_one({"id": payslip_id, "company_id": company_id_of(user)}, {"_id": 0})
    if not ps:
        raise HTTPException(status_code=404, detail="Payslip not found")
    # Employees can only view their own; admins/HR can view anyone in their company
    is_admin = user.get("role") in ("super_admin", "hr", "manager")
    if not is_admin and ps["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not allowed")
    return ps


@router.post("/payslips/{payslip_id}/finalize")
async def finalize_payslip(payslip_id: str, admin: dict = Depends(require_roles("super_admin"))):
    db = get_db()
    ps = await db.payslips.find_one({"id": payslip_id, "company_id": company_id_of(admin)}, {"_id": 0})
    if not ps:
        raise HTTPException(status_code=404, detail="Payslip not found")
    if ps.get("status") == "paid":
        raise HTTPException(status_code=400, detail="Already paid")
    await db.payslips.update_one(
        {"id": payslip_id},
        {"$set": {"status": "finalized", "finalized_at": datetime.now(timezone.utc).isoformat(), "finalized_by": admin["name"]}},
    )
    # notify employee
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "company_id": ps["company_id"],
        "user_id": ps["user_id"],
        "type": "payslip_finalized",
        "title": f"Payslip for {ps['period']} is ready",
        "body": f"Your {ps['period']} payslip has been finalized. Net pay: {ps['components']['currency']} {ps['components']['net']:.2f}",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    user = await db.users.find_one({"id": ps["user_id"]}, {"_id": 0})
    if user:
        c = ps["components"]
        await send_email(
            user["email"],
            f"Payslip available for {ps['period']}",
            render(
                f"Your {ps['period']} payslip is ready",
                f"<p>Hi {user['name']},</p>"
                f"<p>Your payslip for <b>{ps['period']}</b> has been finalized.</p>"
                f"<p><b>Gross:</b> {c['currency']} {c['gross']:.2f}<br/>"
                f"<b>Deductions:</b> {c['currency']} {c['total_deductions']:.2f}<br/>"
                f"<b>Net pay:</b> <b>{c['currency']} {c['net']:.2f}</b></p>"
                f"<p>You can view it in your HR workspace under Payslips.</p>",
            ),
        )
    return {"success": True}


@router.post("/payslips/{payslip_id}/mark-paid")
async def mark_paid(payslip_id: str, admin: dict = Depends(require_roles("super_admin"))):
    db = get_db()
    ps = await db.payslips.find_one({"id": payslip_id, "company_id": company_id_of(admin)}, {"_id": 0})
    if not ps:
        raise HTTPException(status_code=404, detail="Payslip not found")
    if ps.get("status") not in ("finalized", "paid"):
        raise HTTPException(status_code=400, detail="Finalize first")
    await db.payslips.update_one(
        {"id": payslip_id},
        {"$set": {"status": "paid", "paid_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"success": True}


@router.get("/summary")
async def summary(admin: dict = Depends(require_roles("super_admin", "hr"))):
    """Admin dashboard summary: monthly cost, coverage, recent runs."""
    db = get_db()
    cid = company_id_of(admin)
    structs = await db.salary_structures.find({"company_id": cid}, {"_id": 0}).to_list(500)
    employee_count = await db.employees.count_documents({"company_id": cid, "status": "active"})
    monthly_cost = sum(_calc_payslip(s)["gross"] for s in structs)
    currency = structs[0]["currency"] if structs else "USD"

    # last finalized period
    last = await db.payslips.find_one({"company_id": cid, "status": {"$in": ["finalized", "paid"]}}, {"_id": 0}, sort=[("period", -1)])
    last_period = last["period"] if last else None

    # period stats
    period_stats = []
    if last_period:
        pipeline = await db.payslips.aggregate([
            {"$match": {"company_id": cid}},
            {"$group": {"_id": "$period", "count": {"$sum": 1}, "total_net": {"$sum": "$components.net"}, "total_gross": {"$sum": "$components.gross"}}},
            {"$sort": {"_id": -1}},
            {"$limit": 6},
        ]).to_list(6)
        period_stats = [{"period": p["_id"], "count": p["count"], "total_net": round(p["total_net"], 2), "total_gross": round(p["total_gross"], 2)} for p in pipeline]

    return {
        "currency": currency,
        "monthly_cost": round(monthly_cost, 2),
        "employees_with_structure": len(structs),
        "employee_count": employee_count,
        "coverage_pct": round((len(structs) / employee_count) * 100, 1) if employee_count else 0,
        "last_run_period": last_period,
        "period_stats": period_stats,
    }



# ---------------- Period approval (Super Admin gate) ----------------

class ApproveMonthBody(BaseModel):
    period: str  # YYYY-MM


@router.get("/period-status")
async def period_status(period: str, user: dict = Depends(require_roles("super_admin", "hr", "manager"))):
    """Summary of a specific pay period: counts, totals, who can approve."""
    db = get_db()
    cid = company_id_of(user)
    docs = await db.payslips.find({"company_id": cid, "period": period}, {"_id": 0}).to_list(2000)
    drafts = [d for d in docs if d["status"] == "draft"]
    finalized = [d for d in docs if d["status"] == "finalized"]
    paid = [d for d in docs if d["status"] == "paid"]
    total_draft_net = round(sum(d["components"]["net"] for d in drafts), 2)
    total_draft_gross = round(sum(d["components"]["gross"] for d in drafts), 2)
    total_finalized_net = round(sum(d["components"]["net"] for d in finalized + paid), 2)
    currency = docs[0]["components"]["currency"] if docs else "USD"
    return {
        "period": period,
        "draft_count": len(drafts),
        "finalized_count": len(finalized),
        "paid_count": len(paid),
        "total_count": len(docs),
        "total_draft_net": total_draft_net,
        "total_draft_gross": total_draft_gross,
        "total_finalized_net": total_finalized_net,
        "currency": currency,
        "needs_approval": len(drafts) > 0,
        "approver_role": "super_admin",
    }


@router.post("/approve-month")
async def approve_month(body: ApproveMonthBody, admin: dict = Depends(require_roles("super_admin"))):
    """Super-admin approval: finalize every draft payslip for the period in one shot.
    Sends an in-app notification + email to each employee whose payslip is being finalized."""
    db = get_db()
    cid = company_id_of(admin)
    period = body.period.strip()
    drafts = await db.payslips.find({"company_id": cid, "period": period, "status": "draft"}, {"_id": 0}).to_list(2000)
    if not drafts:
        raise HTTPException(status_code=400, detail="No draft payslips for that period")

    now = datetime.now(timezone.utc).isoformat()
    finalized_total = 0
    for ps in drafts:
        await db.payslips.update_one(
            {"id": ps["id"]},
            {"$set": {
                "status": "finalized",
                "finalized_at": now,
                "finalized_by": admin["name"],
                "approved_by": admin["name"],
                "approved_at": now,
            }},
        )
        # in-app notify the employee
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "company_id": cid,
            "user_id": ps["user_id"],
            "type": "payslip_finalized",
            "title": f"Payslip for {ps['period']} is ready",
            "body": f"Your {ps['period']} payslip has been approved. Net pay: {ps['components']['currency']} {ps['components']['net']:.2f}",
            "read": False,
            "created_at": now,
        })
        # email best-effort
        user = await db.users.find_one({"id": ps["user_id"]}, {"_id": 0})
        if user:
            c = ps["components"]
            await send_email(
                user["email"],
                f"Payslip available for {ps['period']}",
                render(
                    f"Your {ps['period']} payslip is ready",
                    f"<p>Hi {user['name']},</p>"
                    f"<p>Your <b>{ps['period']}</b> payslip has been approved by <b>{admin['name']}</b>.</p>"
                    f"<p><b>Gross:</b> {c['currency']} {c['gross']:.2f}<br/>"
                    f"<b>Deductions:</b> {c['currency']} {c['total_deductions']:.2f}<br/>"
                    f"<b>Net pay:</b> <b>{c['currency']} {c['net']:.2f}</b></p>"
                    f"<p>You can view the full payslip in your HR workspace under Payslips.</p>",
                ),
            )
        finalized_total += 1

    # Record a payroll-batch audit doc
    total_net = round(sum(d["components"]["net"] for d in drafts), 2)
    total_gross = round(sum(d["components"]["gross"] for d in drafts), 2)
    await db.payroll_runs.insert_one({
        "id": str(uuid.uuid4()),
        "company_id": cid,
        "period": period,
        "approved_by": admin["name"],
        "approved_at": now,
        "count": finalized_total,
        "total_net": total_net,
        "total_gross": total_gross,
        "currency": drafts[0]["components"]["currency"],
    })
    return {"period": period, "finalized": finalized_total, "total_net": total_net, "total_gross": total_gross}


@router.get("/runs")
async def list_runs(admin: dict = Depends(require_roles("super_admin", "hr"))):
    """Audit log of payroll approval batches."""
    db = get_db()
    items = await db.payroll_runs.find({"company_id": company_id_of(admin)}, {"_id": 0}).sort("approved_at", -1).to_list(200)
    return items


# ---------------- CSV export ----------------

@router.get("/payslips/export.csv")
async def export_payslips_csv(
    user: dict = Depends(require_roles("super_admin", "hr")),
    period: Optional[str] = None,
    status: Optional[str] = None,
):
    db = get_db()
    q: dict = {"company_id": company_id_of(user)}
    if period:
        q["period"] = period
    if status and status != "all":
        q["status"] = status
    items = await db.payslips.find(q, {"_id": 0}).sort([("period", -1), ("user_name", 1)]).to_list(5000)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Period", "Employee", "Code", "Designation", "Currency",
        "Base", "HRA", "Transport", "Special", "Gross",
        "PF %", "PF amount", "Tax %", "Tax amount", "Total deductions", "Net",
        "Status", "Generated at", "Finalized at", "Paid at",
    ])
    for ps in items:
        c = ps.get("components", {})
        writer.writerow([
            ps.get("period", ""),
            ps.get("user_name", ""),
            ps.get("employee_code", ""),
            ps.get("designation", ""),
            c.get("currency", ""),
            c.get("base_salary", ""),
            c.get("hra", ""),
            c.get("transport", ""),
            c.get("special", ""),
            c.get("gross", ""),
            c.get("pf_pct", ""),
            c.get("pf_amount", ""),
            c.get("tax_pct", ""),
            c.get("tax_amount", ""),
            c.get("total_deductions", ""),
            c.get("net", ""),
            ps.get("status", ""),
            ps.get("generated_at", ""),
            ps.get("finalized_at", ""),
            ps.get("paid_at", ""),
        ])
    buf.seek(0)
    filename = f"payslips-{period or 'all'}-{datetime.now(timezone.utc).date().isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
