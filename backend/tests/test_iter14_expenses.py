"""Iteration 14 — Expense claims / reimbursements API tests.

Covers:
  • POST /api/expenses (create + manager routing)
  • POST /api/expenses with receipt_b64 (data URL) → has_receipt=true; oversize rejected
  • GET  /api/expenses/mine + /all (RBAC + status filters)
  • GET  /api/expenses/summary (RBAC + shape)
  • POST /api/expenses/{id}/approve + /reject (state transitions, "already decided")
  • POST /api/expenses/{id}/mark-paid (only super_admin/hr on approved)
  • DELETE /api/expenses/{id} (owner-pending vs admin-any)
  • GET  /api/expenses/categories (defaults)
"""
from __future__ import annotations

import base64
import os
import uuid
from datetime import date

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set in the environment"

ADMIN = ("admin@acme.com", "Admin@123")
HR = ("jordan@acme.com", "Demo@123")
MANAGER = ("alex@acme.com", "Demo@123")
EMPLOYEE = ("maya@acme.com", "Demo@123")   # reports to Alex Rivera
EMPLOYEE2 = ("diego@acme.com", "Demo@123")


# ---------- helpers -----------------------------------------------------------

def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["token"]


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def hr_token():
    return _login(*HR)


@pytest.fixture(scope="module")
def manager_token():
    return _login(*MANAGER)


@pytest.fixture(scope="module")
def employee_token():
    return _login(*EMPLOYEE)


@pytest.fixture(scope="module")
def employee2_token():
    return _login(*EMPLOYEE2)


# tracks created claim ids so we can teardown
_CREATED_IDS: list[str] = []


@pytest.fixture(scope="module", autouse=True)
def _cleanup(admin_token):
    yield
    for cid in _CREATED_IDS:
        try:
            requests.delete(f"{BASE_URL}/api/expenses/{cid}", headers=_hdr(admin_token), timeout=10)
        except Exception:
            pass


def _mk_payload(**overrides) -> dict:
    p = {
        "category": "Travel",
        "amount": 1234.50,
        "currency": "INR",
        "date_incurred": date.today().isoformat(),
        "description": "TEST_iter14 cab to client site",
    }
    p.update(overrides)
    return p


# ---------- 1. Categories -----------------------------------------------------

def test_categories_defaults(employee_token):
    r = requests.get(f"{BASE_URL}/api/expenses/categories", headers=_hdr(employee_token), timeout=15)
    assert r.status_code == 200
    cats = r.json()["categories"]
    for expected in ["Travel", "Meals", "Office supplies", "Client entertainment", "Software", "Other"]:
        assert expected in cats, f"missing category {expected}"


def test_categories_requires_auth():
    r = requests.get(f"{BASE_URL}/api/expenses/categories", timeout=15)
    assert r.status_code in (401, 403)


# ---------- 2. Create + manager routing ---------------------------------------

def test_create_claim_and_manager_routing(employee_token):
    body = _mk_payload(description="TEST_iter14 create+route")
    r = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token), json=body, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    _CREATED_IDS.append(data["id"])
    assert data["status"] == "pending"
    assert data["amount"] == 1234.50
    assert data["currency"] == "INR"
    assert data["category"] == "Travel"
    assert data["has_receipt"] is False
    assert data["user_name"]
    # Maya reports to Alex Rivera per seed
    assert data["manager_user_id"], "manager_user_id should be resolved for maya"
    assert data["manager_name"], "manager_name should be resolved for maya"


def test_create_claim_persists_and_appears_in_mine(employee_token):
    body = _mk_payload(description="TEST_iter14 persist check", amount=42.0)
    r = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token), json=body, timeout=20)
    assert r.status_code == 200
    cid = r.json()["id"]
    _CREATED_IDS.append(cid)

    g = requests.get(f"{BASE_URL}/api/expenses/mine", headers=_hdr(employee_token), timeout=15)
    assert g.status_code == 200
    ids = [row["id"] for row in g.json()]
    assert cid in ids


def test_create_rejects_bad_input(employee_token):
    for bad in [
        _mk_payload(amount=-5),
        _mk_payload(amount=0),
        _mk_payload(description=""),
        _mk_payload(date_incurred="2025/01/01"),
        _mk_payload(category=""),
    ]:
        r = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token), json=bad, timeout=15)
        assert r.status_code in (400, 422), f"expected 4xx for {bad}, got {r.status_code}"


def test_create_rejects_unknown_category(employee_token):
    r = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token),
                      json=_mk_payload(category="Hovercraft"), timeout=15)
    assert r.status_code == 400
    assert "Unknown category" in r.text


# ---------- 3. Receipt upload -------------------------------------------------

_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def test_receipt_upload_stores_and_serves(employee_token):
    receipt = "data:image/png;base64," + base64.b64encode(_PNG_1x1).decode()
    body = _mk_payload(description="TEST_iter14 with receipt", receipt_b64=receipt)
    r = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token), json=body, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    _CREATED_IDS.append(data["id"])
    assert data["has_receipt"] is True
    assert data["receipt_path"]
    # Fetch the receipt back
    g = requests.get(f"{BASE_URL}/api/expenses/{data['id']}/receipt",
                     headers={"Authorization": _hdr(employee_token)["Authorization"]}, timeout=15)
    assert g.status_code == 200
    assert g.headers.get("content-type", "").startswith("image/")
    assert g.content == _PNG_1x1


def test_receipt_upload_rejects_over_5mb(employee_token):
    big = b"\x00" * (5 * 1024 * 1024 + 1024)
    receipt = "data:image/png;base64," + base64.b64encode(big).decode()
    body = _mk_payload(description="TEST_iter14 oversize", receipt_b64=receipt)
    r = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token), json=body, timeout=30)
    assert r.status_code == 400
    assert "5 MB" in r.text or "5MB" in r.text or "exceeds" in r.text.lower()


# ---------- 4. /mine and /all RBAC + filters ----------------------------------

def test_mine_returns_only_own(employee_token, employee2_token):
    # maya creates one, diego creates one
    a = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token),
                      json=_mk_payload(description="TEST_iter14 maya own"), timeout=15).json()
    b = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee2_token),
                      json=_mk_payload(description="TEST_iter14 diego own"), timeout=15).json()
    _CREATED_IDS.extend([a["id"], b["id"]])

    m = requests.get(f"{BASE_URL}/api/expenses/mine", headers=_hdr(employee_token), timeout=15).json()
    ids = {row["id"] for row in m}
    assert a["id"] in ids
    assert b["id"] not in ids


def test_all_requires_manager_plus(employee_token, manager_token, admin_token):
    # employee: 403
    r = requests.get(f"{BASE_URL}/api/expenses/all", headers=_hdr(employee_token), timeout=15)
    assert r.status_code == 403
    # manager: 200
    r = requests.get(f"{BASE_URL}/api/expenses/all", headers=_hdr(manager_token), timeout=15)
    assert r.status_code == 200
    # admin: 200
    r = requests.get(f"{BASE_URL}/api/expenses/all", headers=_hdr(admin_token), timeout=15)
    assert r.status_code == 200


@pytest.mark.parametrize("st", ["pending", "approved", "rejected", "paid", "all"])
def test_all_status_filter(admin_token, st):
    r = requests.get(f"{BASE_URL}/api/expenses/all", headers=_hdr(admin_token),
                     params={"status": st}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    if st != "all":
        for row in data:
            assert row["status"] == st


# ---------- 5. Summary --------------------------------------------------------

def test_summary_shape_and_rbac(employee_token, admin_token):
    r = requests.get(f"{BASE_URL}/api/expenses/summary", headers=_hdr(employee_token), timeout=15)
    assert r.status_code == 403

    r = requests.get(f"{BASE_URL}/api/expenses/summary", headers=_hdr(admin_token), timeout=15)
    assert r.status_code == 200
    data = r.json()
    for k in ("pending", "approved", "rejected", "paid"):
        assert k in data
        assert "count" in data[k]
        assert "total" in data[k]


# ---------- 6. Approve / reject / mark-paid -----------------------------------

def test_approve_flow_and_already_decided(employee_token, admin_token):
    created = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token),
                            json=_mk_payload(description="TEST_iter14 approve flow"), timeout=15).json()
    cid = created["id"]
    _CREATED_IDS.append(cid)

    r = requests.post(f"{BASE_URL}/api/expenses/{cid}/approve", headers=_hdr(admin_token),
                      json={"note": "ok"}, timeout=15)
    assert r.status_code == 200

    # Fetch and confirm persisted
    g = requests.get(f"{BASE_URL}/api/expenses/{cid}", headers=_hdr(admin_token), timeout=15).json()
    assert g["status"] == "approved"
    assert g["decision_note"] == "ok"
    assert g["decided_by"]
    assert g["decided_at"]

    # Second approve → 400
    r2 = requests.post(f"{BASE_URL}/api/expenses/{cid}/approve", headers=_hdr(admin_token),
                       json={"note": ""}, timeout=15)
    assert r2.status_code == 400
    assert "Already decided" in r2.text


def test_reject_flow(employee_token, admin_token):
    created = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token),
                            json=_mk_payload(description="TEST_iter14 reject flow"), timeout=15).json()
    cid = created["id"]
    _CREATED_IDS.append(cid)

    r = requests.post(f"{BASE_URL}/api/expenses/{cid}/reject", headers=_hdr(admin_token),
                      json={"note": "not eligible"}, timeout=15)
    assert r.status_code == 200
    g = requests.get(f"{BASE_URL}/api/expenses/{cid}", headers=_hdr(admin_token), timeout=15).json()
    assert g["status"] == "rejected"
    assert g["decision_note"] == "not eligible"


def test_mark_paid_only_admin_or_hr_and_only_approved(employee_token, manager_token, hr_token, admin_token):
    # Create + approve
    created = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token),
                            json=_mk_payload(description="TEST_iter14 pay flow"), timeout=15).json()
    cid = created["id"]
    _CREATED_IDS.append(cid)

    # Manager attempting to mark-paid before approval → 403 (manager not in allowed roles)
    r_mgr = requests.post(f"{BASE_URL}/api/expenses/{cid}/mark-paid",
                          headers=_hdr(manager_token), timeout=15)
    assert r_mgr.status_code == 403

    # Mark-paid before approval by admin → 400 (only approved)
    r_early = requests.post(f"{BASE_URL}/api/expenses/{cid}/mark-paid",
                            headers=_hdr(admin_token), timeout=15)
    assert r_early.status_code == 400

    # Approve then mark-paid by HR → 200
    requests.post(f"{BASE_URL}/api/expenses/{cid}/approve", headers=_hdr(admin_token),
                  json={"note": ""}, timeout=15)
    r_ok = requests.post(f"{BASE_URL}/api/expenses/{cid}/mark-paid",
                         headers=_hdr(hr_token), timeout=15)
    assert r_ok.status_code == 200

    g = requests.get(f"{BASE_URL}/api/expenses/{cid}", headers=_hdr(admin_token), timeout=15).json()
    assert g["status"] == "paid"
    assert g["paid_by"]
    assert g["paid_at"]


# ---------- 7. Delete permissions ---------------------------------------------

def test_employee_can_delete_own_pending_only(employee_token, admin_token):
    # Create then delete as owner
    created = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token),
                            json=_mk_payload(description="TEST_iter14 delete-own"), timeout=15).json()
    cid = created["id"]
    r = requests.delete(f"{BASE_URL}/api/expenses/{cid}", headers=_hdr(employee_token), timeout=15)
    assert r.status_code == 200

    # Verify 404 afterwards
    g = requests.get(f"{BASE_URL}/api/expenses/{cid}", headers=_hdr(admin_token), timeout=15)
    assert g.status_code == 404


def test_employee_cannot_delete_after_approval(employee_token, admin_token):
    created = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token),
                            json=_mk_payload(description="TEST_iter14 no-delete-after-approve"), timeout=15).json()
    cid = created["id"]
    _CREATED_IDS.append(cid)
    requests.post(f"{BASE_URL}/api/expenses/{cid}/approve", headers=_hdr(admin_token),
                  json={"note": ""}, timeout=15)
    r = requests.delete(f"{BASE_URL}/api/expenses/{cid}", headers=_hdr(employee_token), timeout=15)
    assert r.status_code == 400


def test_admin_can_delete_any(employee_token, admin_token):
    created = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee_token),
                            json=_mk_payload(description="TEST_iter14 admin-delete"), timeout=15).json()
    cid = created["id"]
    r = requests.delete(f"{BASE_URL}/api/expenses/{cid}", headers=_hdr(admin_token), timeout=15)
    assert r.status_code == 200


def test_employee_cannot_delete_someone_elses(employee_token, employee2_token):
    created = requests.post(f"{BASE_URL}/api/expenses", headers=_hdr(employee2_token),
                            json=_mk_payload(description="TEST_iter14 cross-owner-delete"), timeout=15).json()
    cid = created["id"]
    _CREATED_IDS.append(cid)
    r = requests.delete(f"{BASE_URL}/api/expenses/{cid}", headers=_hdr(employee_token), timeout=15)
    assert r.status_code == 403


# ---------- 8. Auth required --------------------------------------------------

def test_unauth_endpoints_return_401_or_403():
    for path in ("/api/expenses/mine", "/api/expenses/all", "/api/expenses/summary", "/api/expenses/categories"):
        r = requests.get(f"{BASE_URL}{path}", timeout=15)
        assert r.status_code in (401, 403), f"{path} → {r.status_code}"
