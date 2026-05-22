"""Lightweight payroll module: salary structures + monthly payslip runs."""
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
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


def _calc_payslip(struct: dict) -> dict:
    base = float(struct.get("base_salary", 0) or 0)
    al = struct.get("allowances") or {}
    hra = float(al.get("hra", 0) or 0)
    transport = float(al.get("transport", 0) or 0)
    special = float(al.get("special", 0) or 0)
    gross = base + hra + transport + special
    pf_amount = round(base * (struct.get("pf_pct", 0) or 0) / 100, 2)
    tax_amount = round((gross - pf_amount) * (struct.get("tax_pct", 0) or 0) / 100, 2)
    total_deductions = round(pf_amount + tax_amount, 2)
    net = round(gross - total_deductions, 2)
    return {
        "base_salary": round(base, 2),
        "hra": round(hra, 2),
        "transport": round(transport, 2),
        "special": round(special, 2),
        "gross": round(gross, 2),
        "pf_amount": pf_amount,
        "tax_amount": tax_amount,
        "total_deductions": total_deductions,
        "net": net,
        "currency": struct.get("currency", "USD"),
        "pf_pct": struct.get("pf_pct"),
        "tax_pct": struct.get("tax_pct"),
    }


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
        calc = _calc_payslip(s)
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
async def finalize_payslip(payslip_id: str, admin: dict = Depends(require_roles("super_admin", "hr"))):
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
async def mark_paid(payslip_id: str, admin: dict = Depends(require_roles("super_admin", "hr"))):
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
