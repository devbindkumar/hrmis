"""Tests for admin roles (super_admin/hr/manager) applying for leave and WFH.

Covers:
- POST /api/leave/apply for admin@acme.com, jordan@acme.com, alex@acme.com
- POST /api/wfh/apply for the same three admin roles
- Non-regression: employee (maya) apply flows still work
- Non-regression: manager still sees pending requests in /leave/all and /wfh/all
- Backend regression: exceeding balances still returns 400
"""
import os
import uuid
import datetime as dt
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "super_admin": ("admin@acme.com", "Admin@123"),
    "hr": ("jordan@acme.com", "Demo@123"),
    "manager": ("alex@acme.com", "Demo@123"),
    "employee": ("maya@acme.com", "Demo@123"),
}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"Cannot login {email}: {r.status_code} {r.text}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def tokens():
    return {role: _login(email, pw) for role, (email, pw) in CREDS.items()}


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _future_range(days_ahead=30, span=1):
    start = dt.date.today() + dt.timedelta(days=days_ahead)
    end = start + dt.timedelta(days=span - 1)
    return start.isoformat(), end.isoformat()


# ---------------- Leave apply ----------------
@pytest.mark.parametrize("role", ["super_admin", "hr", "manager"])
def test_admin_role_can_apply_for_leave(role, tokens):
    tok = tokens[role]

    # Pick a leave type with balance
    bres = requests.get(f"{API}/leave/balances", headers=_headers(tok), timeout=15)
    assert bres.status_code == 200, f"balances failed: {bres.status_code} {bres.text}"
    balances = bres.json()
    assert isinstance(balances, list) and len(balances) > 0, f"No balances returned for {role}"
    picked = next((b for b in balances if (b.get("total", 0) - b.get("used", 0)) > 0), None)
    assert picked is not None, f"No leave type with remaining balance for {role}"

    # Random future range so we don't collide with existing requests
    offset = 60 + abs(hash(role)) % 60
    start, end = _future_range(days_ahead=offset, span=1)
    reason = f"TEST_admin_apply_{role}_{uuid.uuid4().hex[:6]}"

    payload = {"leave_type": picked["leave_type"], "start_date": start, "end_date": end, "reason": reason}
    r = requests.post(f"{API}/leave/apply", json=payload, headers=_headers(tok), timeout=15)
    assert r.status_code == 200, f"[{role}] leave/apply failed: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("reason") == reason
    assert body.get("status") in ("pending", "approved")

    # Verify persistence via /leave/mine
    m = requests.get(f"{API}/leave/mine", headers=_headers(tok), timeout=15)
    assert m.status_code == 200
    assert any(x.get("reason") == reason for x in m.json()), f"[{role}] applied leave not present in /leave/mine"


# ---------------- WFH apply ----------------
@pytest.mark.parametrize("role", ["super_admin", "hr", "manager"])
def test_admin_role_can_apply_for_wfh(role, tokens):
    tok = tokens[role]
    offset = 60 + abs(hash("wfh_" + role)) % 60
    date_str = (dt.date.today() + dt.timedelta(days=offset)).isoformat()
    reason = f"TEST_admin_wfh_{role}_{uuid.uuid4().hex[:6]}"

    r = requests.post(f"{API}/wfh/apply", json={"date": date_str, "reason": reason},
                      headers=_headers(tok), timeout=15)
    assert r.status_code == 200, f"[{role}] wfh/apply failed: {r.status_code} {r.text}"

    m = requests.get(f"{API}/wfh/mine", headers=_headers(tok), timeout=15)
    assert m.status_code == 200
    assert any(x.get("reason") == reason for x in m.json()), f"[{role}] applied WFH not present in /wfh/mine"


# ---------------- Employee non-regression ----------------
def test_employee_leave_apply_still_works(tokens):
    tok = tokens["employee"]
    bres = requests.get(f"{API}/leave/balances", headers=_headers(tok), timeout=15)
    assert bres.status_code == 200
    picked = next((b for b in bres.json() if (b.get("total", 0) - b.get("used", 0)) > 0), None)
    assert picked is not None
    start, end = _future_range(days_ahead=90, span=1)
    reason = f"TEST_emp_leave_{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/leave/apply", json={
        "leave_type": picked["leave_type"], "start_date": start, "end_date": end, "reason": reason
    }, headers=_headers(tok), timeout=15)
    assert r.status_code == 200, f"employee leave apply failed: {r.status_code} {r.text}"


def test_employee_wfh_apply_still_works(tokens):
    tok = tokens["employee"]
    date_str = (dt.date.today() + dt.timedelta(days=95)).isoformat()
    reason = f"TEST_emp_wfh_{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/wfh/apply", json={"date": date_str, "reason": reason},
                      headers=_headers(tok), timeout=15)
    assert r.status_code == 200, f"employee wfh apply failed: {r.status_code} {r.text}"


# ---------------- Approve/reject regression ----------------
def test_manager_can_list_pending_leave(tokens):
    tok = tokens["manager"]
    r = requests.get(f"{API}/leave/all", params={"status": "pending", "scope": "team"},
                     headers=_headers(tok), timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_manager_can_list_pending_wfh(tokens):
    tok = tokens["manager"]
    r = requests.get(f"{API}/wfh/all", params={"status": "pending", "scope": "team"},
                     headers=_headers(tok), timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------------- Balance-exceeding leave regression ----------------
def test_admin_leave_exceeding_balance_returns_400(tokens):
    tok = tokens["manager"]
    bres = requests.get(f"{API}/leave/balances", headers=_headers(tok), timeout=15)
    assert bres.status_code == 200
    balances = bres.json()
    if not balances:
        pytest.skip("no balances")
    b = balances[0]
    remaining = b.get("total", 0) - b.get("used", 0)
    # Ask for way more than remaining
    span_days = remaining + 30
    start = dt.date.today() + dt.timedelta(days=200)
    end = start + dt.timedelta(days=span_days - 1)
    payload = {"leave_type": b["leave_type"], "start_date": start.isoformat(),
               "end_date": end.isoformat(), "reason": "TEST_overflow"}
    r = requests.post(f"{API}/leave/apply", json=payload, headers=_headers(tok), timeout=15)
    assert r.status_code == 400, f"expected 400 for exceeding balance, got {r.status_code}: {r.text}"
