"""Expense claims / reimbursement API.

Employees submit expense claims with amount, category, date and an optional
receipt image. Managers/HR/Super-admins approve or reject. Super-admins can
mark approved claims as "paid" once reimbursement is disbursed.

Endpoints
---------
POST   /api/expenses                   — submit a claim
GET    /api/expenses/mine              — my claims
GET    /api/expenses/all               — team/company claims (managers+)
GET    /api/expenses/summary           — totals per status for the dashboard
POST   /api/expenses/{id}/approve      — approver decision
POST   /api/expenses/{id}/reject       — approver decision
POST   /api/expenses/{id}/mark-paid    — super-admin marks reimbursed
GET    /api/expenses/{id}/receipt      — download receipt image
"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from auth import get_current_user, require_roles
from db import get_db
from tenant import company_id_of
from storage import put_object, get_object

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


DEFAULT_CATEGORIES = ["Travel", "Meals", "Office supplies", "Client entertainment", "Software", "Other"]
VALID_STATUSES = {"pending", "approved", "rejected", "paid"}
MAX_RECEIPT_BYTES = 5 * 1024 * 1024  # 5 MB


class ExpenseCreate(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    amount: float = Field(gt=0, le=10_000_000)
    currency: str = Field(default="INR", min_length=3, max_length=8)
    date_incurred: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    description: str = Field(min_length=1, max_length=1000)
    receipt_b64: Optional[str] = None  # data URL or raw base64 JPEG/PNG/PDF

    @field_validator("category")
    @classmethod
    def _clean_cat(cls, v: str) -> str:
        return v.strip()


class ExpenseDecision(BaseModel):
    note: Optional[str] = ""


class ExpenseUpdate(BaseModel):
    category: Optional[str] = Field(default=None, min_length=1, max_length=64)
    amount: Optional[float] = Field(default=None, gt=0, le=10_000_000)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=8)
    date_incurred: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    description: Optional[str] = Field(default=None, min_length=1, max_length=1000)
    receipt_b64: Optional[str] = None  # supply new base64 to replace; empty string to remove
    remove_receipt: Optional[bool] = False

    @field_validator("category")
    @classmethod
    def _clean_cat(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v


def _receipt_path(cid: str, expense_id: str, ext: str) -> str:
    return f"receipts/{cid}/{expense_id}.{ext.lstrip('.')}"


def _detect_ext_and_mime(b64: str) -> tuple[str, str, bytes]:
    """Return (extension, mime, raw_bytes) from a data URL or raw b64 string."""
    mime = "application/octet-stream"
    data = b64
    if isinstance(b64, str) and b64.startswith("data:") and "," in b64:
        head, data = b64.split(",", 1)
        # e.g. data:image/jpeg;base64,....
        if ";" in head:
            mime = head[5:].split(";", 1)[0] or mime
    try:
        raw = base64.b64decode(data, validate=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid receipt payload: {e}")
    if len(raw) > MAX_RECEIPT_BYTES:
        raise HTTPException(status_code=400, detail="Receipt file exceeds 5 MB limit")
    ext_map = {
        "image/jpeg": "jpg", "image/jpg": "jpg",
        "image/png": "png", "image/webp": "webp",
        "image/heic": "heic", "image/heif": "heif",
        "application/pdf": "pdf",
    }
    ext = ext_map.get(mime, "bin")
    return ext, mime, raw


def _strip(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


@router.get("/categories")
async def list_categories(user: dict = Depends(get_current_user)):
    """Configurable per-company expense categories (falls back to defaults)."""
    db = get_db()
    company = await db.companies.find_one(
        {"id": company_id_of(user)}, {"_id": 0, "expense_categories": 1}
    ) or {}
    cats = company.get("expense_categories") or DEFAULT_CATEGORIES
    return {"categories": cats}


@router.get("/mine")
async def my_claims(
    user: dict = Depends(get_current_user),
    status: Optional[str] = None,
):
    db = get_db()
    q: dict = {"user_id": user["id"], "company_id": company_id_of(user)}
    if status and status != "all":
        q["status"] = status
    items = await db.expense_claims.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return items


@router.get("/all")
async def all_claims(
    user: dict = Depends(require_roles("super_admin", "hr", "manager")),
    status: Optional[str] = None,
    scope: Optional[str] = None,  # kept for compatibility — managers are always scoped to their team
):
    db = get_db()
    q: dict = {"company_id": company_id_of(user)}
    if status and status != "all":
        q["status"] = status
    # Privacy rule: a manager may only see claims filed by their own direct
    # reports — never the whole company. Super_admin & HR still see everything.
    if user.get("role") == "manager":
        q["manager_user_id"] = user["id"]
    elif scope == "team":
        q["manager_user_id"] = user["id"]
    items = await db.expense_claims.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return items


@router.get("/summary")
async def summary(user: dict = Depends(require_roles("super_admin", "hr", "manager"))):
    """Counts + totals per status for a dashboard card.

    Managers see totals for their direct reports only; super_admin / HR see
    the whole company.
    """
    db = get_db()
    cid = company_id_of(user)
    match: dict = {"company_id": cid}
    if user.get("role") == "manager":
        match["manager_user_id"] = user["id"]
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
            "total": {"$sum": "$amount"},
        }},
    ]
    rows = await db.expense_claims.aggregate(pipeline).to_list(50)
    out = {s: {"count": 0, "total": 0.0} for s in VALID_STATUSES}
    for r in rows:
        s = r.get("_id") or "pending"
        if s in out:
            out[s] = {"count": r["count"], "total": round(r["total"] or 0.0, 2)}
    return out


@router.post("")
async def submit_claim(body: ExpenseCreate, user: dict = Depends(get_current_user)):
    db = get_db()
    cid = company_id_of(user)

    if body.category not in DEFAULT_CATEGORIES:
        # allow any category the company configured
        company = await db.companies.find_one({"id": cid}, {"_id": 0, "expense_categories": 1}) or {}
        allowed = set((company.get("expense_categories") or DEFAULT_CATEGORIES))
        if body.category not in allowed:
            raise HTTPException(status_code=400, detail=f"Unknown category '{body.category}'")

    # Resolve direct manager for routing
    emp = await db.employees.find_one({"user_id": user["id"], "company_id": cid}, {"_id": 0, "id": 1, "manager_id": 1})
    manager_user_id = None
    manager_name = None
    if emp and emp.get("manager_id"):
        mgr = await db.employees.find_one({"id": emp["manager_id"], "company_id": cid}, {"_id": 0, "user_id": 1, "name": 1})
        if mgr:
            manager_user_id = mgr["user_id"]
            manager_name = mgr["name"]

    expense_id = str(uuid.uuid4())
    receipt_path = None
    receipt_mime = None
    if body.receipt_b64:
        ext, mime, raw = _detect_ext_and_mime(body.receipt_b64)
        rp = _receipt_path(cid, expense_id, ext)
        put_object(rp, raw, mime)
        receipt_path = rp
        receipt_mime = mime

    doc = {
        "id": expense_id,
        "company_id": cid,
        "user_id": user["id"],
        "user_name": user["name"],
        "employee_id": emp["id"] if emp else None,
        "category": body.category,
        "amount": round(float(body.amount), 2),
        "currency": body.currency.upper(),
        "date_incurred": body.date_incurred,
        "description": body.description,
        "receipt_path": receipt_path,
        "receipt_mime": receipt_mime,
        "has_receipt": bool(receipt_path),
        "status": "pending",
        "manager_user_id": manager_user_id,
        "manager_name": manager_name,
        "decision_note": "",
        "decided_by": None,
        "decided_at": None,
        "paid_at": None,
        "paid_by": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.expense_claims.insert_one(doc)

    # notification feed for manager / admin pool
    if manager_user_id:
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": manager_user_id,
            "type": "expense_request",
            "title": "New expense claim",
            "body": f"{user['name']} submitted {doc['currency']} {doc['amount']} · {doc['category']}",
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": "admin",
        "audience": "admin",
        "type": "expense_request",
        "title": "New expense claim",
        "body": f"{user['name']} submitted {doc['currency']} {doc['amount']} · {doc['category']}",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return _strip(doc)


async def _load_claim(db, expense_id: str, cid: str) -> dict:
    claim = await db.expense_claims.find_one({"id": expense_id, "company_id": cid}, {"_id": 0})
    if not claim:
        raise HTTPException(status_code=404, detail="Expense claim not found")
    return claim


def _manager_can_touch(user: dict, claim: dict) -> bool:
    """Privacy rule for managers: they may only view/approve/reject claims
    submitted by their own direct reports or by themselves. Super_admin & HR
    are unrestricted; employees are handled by the calling endpoint."""
    if user.get("role") != "manager":
        return True
    return (
        claim.get("manager_user_id") == user["id"]
        or claim.get("user_id") == user["id"]
    )


@router.get("/{expense_id}")
async def get_claim(expense_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    claim = await _load_claim(db, expense_id, company_id_of(user))
    role = user.get("role")
    if role in ("super_admin", "hr"):
        return claim
    if role == "manager":
        if not _manager_can_touch(user, claim):
            raise HTTPException(status_code=403, detail="Not allowed")
        return claim
    if claim["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not allowed")
    return claim


@router.post("/{expense_id}/approve")
async def approve_claim(
    expense_id: str,
    body: ExpenseDecision,
    admin: dict = Depends(require_roles("super_admin", "hr", "manager")),
):
    db = get_db()
    cid = company_id_of(admin)
    claim = await _load_claim(db, expense_id, cid)
    if not _manager_can_touch(admin, claim):
        raise HTTPException(status_code=403, detail="You can only approve claims from your direct reports")
    # Only super_admin can approve their own claim (or any manager/HR self-claim).
    # Managers & HR may never approve claims they submitted themselves.
    if claim["user_id"] == admin["id"] and admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="You cannot approve your own claim")
    if claim["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already decided")
    now = datetime.now(timezone.utc).isoformat()
    await db.expense_claims.update_one({"id": expense_id}, {"$set": {
        "status": "approved",
        "decision_note": body.note or "",
        "decided_by": admin["name"],
        "decided_at": now,
    }})
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": claim["user_id"],
        "type": "expense_approved",
        "title": "Expense approved",
        "body": f"Your {claim['currency']} {claim['amount']} claim for {claim['category']} was approved.",
        "read": False,
        "created_at": now,
    })
    return {"success": True}


@router.post("/{expense_id}/reject")
async def reject_claim(
    expense_id: str,
    body: ExpenseDecision,
    admin: dict = Depends(require_roles("super_admin", "hr", "manager")),
):
    db = get_db()
    cid = company_id_of(admin)
    claim = await _load_claim(db, expense_id, cid)
    if not _manager_can_touch(admin, claim):
        raise HTTPException(status_code=403, detail="You can only reject claims from your direct reports")
    if claim["user_id"] == admin["id"] and admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="You cannot reject your own claim")
    if claim["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already decided")
    now = datetime.now(timezone.utc).isoformat()
    await db.expense_claims.update_one({"id": expense_id}, {"$set": {
        "status": "rejected",
        "decision_note": body.note or "",
        "decided_by": admin["name"],
        "decided_at": now,
    }})
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": claim["user_id"],
        "type": "expense_rejected",
        "title": "Expense rejected",
        "body": f"Your {claim['currency']} {claim['amount']} claim for {claim['category']} was rejected.",
        "read": False,
        "created_at": now,
    })
    return {"success": True}


@router.post("/{expense_id}/mark-paid")
async def mark_paid(
    expense_id: str,
    admin: dict = Depends(require_roles("super_admin", "hr")),
):
    db = get_db()
    cid = company_id_of(admin)
    claim = await _load_claim(db, expense_id, cid)
    if claim["status"] != "approved":
        raise HTTPException(status_code=400, detail="Only approved claims can be marked paid")
    now = datetime.now(timezone.utc).isoformat()
    await db.expense_claims.update_one({"id": expense_id}, {"$set": {
        "status": "paid",
        "paid_by": admin["name"],
        "paid_at": now,
    }})
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": claim["user_id"],
        "type": "expense_paid",
        "title": "Expense reimbursed",
        "body": f"Your {claim['currency']} {claim['amount']} reimbursement has been processed.",
        "read": False,
        "created_at": now,
    })
    return {"success": True}


@router.get("/{expense_id}/receipt")
async def get_receipt(expense_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    cid = company_id_of(user)
    claim = await _load_claim(db, expense_id, cid)
    role = user.get("role")
    if role in ("super_admin", "hr"):
        pass  # full access
    elif role == "manager":
        if not _manager_can_touch(user, claim):
            raise HTTPException(status_code=403, detail="Not allowed")
    elif claim["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not allowed")
    if not claim.get("receipt_path"):
        raise HTTPException(status_code=404, detail="No receipt attached")
    try:
        data, content_type = get_object(claim["receipt_path"])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Receipt file missing on disk")
    ct = claim.get("receipt_mime") or content_type or "application/octet-stream"
    return Response(content=data, media_type=ct)


@router.patch("/{expense_id}")
async def update_claim(
    expense_id: str,
    body: ExpenseUpdate,
    user: dict = Depends(get_current_user),
):
    """Edit a pending expense claim.

    Rules:
      • Only the submitter (or super_admin/HR) can edit.
      • Only claims in the "pending" status can be edited — once approved,
        rejected, or paid, the record becomes immutable.
    """
    db = get_db()
    cid = company_id_of(user)
    claim = await _load_claim(db, expense_id, cid)

    is_admin = user.get("role") in ("super_admin", "hr")
    if claim["user_id"] != user["id"] and not is_admin:
        raise HTTPException(status_code=403, detail="You can only edit your own claim")
    if claim["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending claims can be edited")

    patch = body.model_dump(exclude_unset=True)

    if patch.get("category") is not None:
        cat = patch["category"]
        if cat not in DEFAULT_CATEGORIES:
            company = await db.companies.find_one({"id": cid}, {"_id": 0, "expense_categories": 1}) or {}
            allowed = set((company.get("expense_categories") or DEFAULT_CATEGORIES))
            if cat not in allowed:
                raise HTTPException(status_code=400, detail=f"Unknown category '{cat}'")

    update: dict = {}
    if "category" in patch:      update["category"] = patch["category"]
    if "amount" in patch:        update["amount"] = round(float(patch["amount"]), 2)
    if "currency" in patch:      update["currency"] = patch["currency"].upper()
    if "date_incurred" in patch: update["date_incurred"] = patch["date_incurred"]
    if "description" in patch:   update["description"] = patch["description"]

    # Optional receipt replacement / removal
    new_b64 = patch.get("receipt_b64")
    if new_b64:
        ext, mime, raw = _detect_ext_and_mime(new_b64)
        rp = _receipt_path(cid, expense_id, ext)
        put_object(rp, raw, mime)
        update["receipt_path"] = rp
        update["receipt_mime"] = mime
        update["has_receipt"] = True
    elif patch.get("remove_receipt"):
        update["receipt_path"] = None
        update["receipt_mime"] = None
        update["has_receipt"] = False

    if not update:
        return _strip(claim)

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.expense_claims.update_one({"id": expense_id}, {"$set": update})
    updated = await db.expense_claims.find_one({"id": expense_id}, {"_id": 0})
    return updated


@router.delete("/{expense_id}")
async def delete_claim(expense_id: str, user: dict = Depends(get_current_user)):
    """Employees can delete their own pending claims. Admins can always delete."""
    db = get_db()
    cid = company_id_of(user)
    claim = await _load_claim(db, expense_id, cid)
    is_admin = user.get("role") in ("super_admin", "hr")
    if not is_admin:
        if claim["user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Not allowed")
        if claim["status"] != "pending":
            raise HTTPException(status_code=400, detail="Only pending claims can be deleted")
    await db.expense_claims.delete_one({"id": expense_id})
    return {"success": True}
