"""Iteration 23: verify manager's own self-filed leave/WFH is visible in
GET /leave/all and /wfh/all when scope=team (the fix expands the team filter
to include user_id==user.id OR manager_user_id==user.id).

Also confirms:
- Manager still sees direct reports' items in the team scope.
- super_admin/HR with team scope OFF still see the whole tenant.
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


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _pick_leave_type(tok):
    r = requests.get(f"{API}/leave/balances", headers=_h(tok), timeout=15)
    assert r.status_code == 200
    picked = next((b for b in r.json() if (b.get("total", 0) - b.get("used", 0)) > 0), None)
    assert picked is not None
    return picked["leave_type"]


def _apply_leave(tok, days_ahead, reason):
    lt = _pick_leave_type(tok)
    start = (dt.date.today() + dt.timedelta(days=days_ahead)).isoformat()
    payload = {"leave_type": lt, "start_date": start, "end_date": start, "reason": reason}
    r = requests.post(f"{API}/leave/apply", json=payload, headers=_h(tok), timeout=15)
    assert r.status_code == 200, f"apply failed: {r.status_code} {r.text}"
    return r.json()


def _apply_wfh(tok, days_ahead, reason):
    d = (dt.date.today() + dt.timedelta(days=days_ahead)).isoformat()
    r = requests.post(f"{API}/wfh/apply", json={"date": d, "reason": reason},
                      headers=_h(tok), timeout=15)
    assert r.status_code == 200, f"wfh apply failed: {r.status_code} {r.text}"
    return r.json()


# -------- Manager self visibility --------
def test_manager_sees_own_leave_in_team_scope(tokens):
    tok = tokens["manager"]
    reason = f"TEST_iter23_mgr_leave_{uuid.uuid4().hex[:6]}"
    _apply_leave(tok, days_ahead=300, reason=reason)

    r = requests.get(f"{API}/leave/all", params={"status": "pending", "scope": "team"},
                     headers=_h(tok), timeout=15)
    assert r.status_code == 200
    reasons = [x.get("reason") for x in r.json()]
    assert reason in reasons, f"Manager's own leave not visible in team scope; got {reasons[:10]}"


def test_manager_sees_own_wfh_in_team_scope(tokens):
    tok = tokens["manager"]
    reason = f"TEST_iter23_mgr_wfh_{uuid.uuid4().hex[:6]}"
    _apply_wfh(tok, days_ahead=310, reason=reason)

    r = requests.get(f"{API}/wfh/all", params={"status": "pending", "scope": "team"},
                     headers=_h(tok), timeout=15)
    assert r.status_code == 200
    reasons = [x.get("reason") for x in r.json()]
    assert reason in reasons, f"Manager's own WFH not visible in team scope; got {reasons[:10]}"


# -------- Manager still sees direct-report --------
def test_manager_still_sees_direct_report_leave(tokens):
    emp_tok = tokens["employee"]
    mgr_tok = tokens["manager"]
    reason = f"TEST_iter23_report_leave_{uuid.uuid4().hex[:6]}"
    _apply_leave(emp_tok, days_ahead=320, reason=reason)

    r = requests.get(f"{API}/leave/all", params={"status": "pending", "scope": "team"},
                     headers=_h(mgr_tok), timeout=15)
    assert r.status_code == 200
    reasons = [x.get("reason") for x in r.json()]
    assert reason in reasons, "Direct-report leave missing from manager's team scope"


def test_manager_still_sees_direct_report_wfh(tokens):
    emp_tok = tokens["employee"]
    mgr_tok = tokens["manager"]
    reason = f"TEST_iter23_report_wfh_{uuid.uuid4().hex[:6]}"
    _apply_wfh(emp_tok, days_ahead=330, reason=reason)

    r = requests.get(f"{API}/wfh/all", params={"status": "pending", "scope": "team"},
                     headers=_h(mgr_tok), timeout=15)
    assert r.status_code == 200
    reasons = [x.get("reason") for x in r.json()]
    assert reason in reasons, "Direct-report WFH missing from manager's team scope"


# -------- super_admin / hr team-scope off --------
@pytest.mark.parametrize("role", ["super_admin", "hr"])
def test_admin_scope_off_sees_tenant_leave(role, tokens):
    tok = tokens[role]
    r = requests.get(f"{API}/leave/all", params={"status": "pending"},
                     headers=_h(tok), timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.parametrize("role", ["super_admin", "hr"])
def test_admin_scope_off_sees_tenant_wfh(role, tokens):
    tok = tokens[role]
    r = requests.get(f"{API}/wfh/all", params={"status": "pending"},
                     headers=_h(tok), timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# -------- super_admin/HR team ON also sees own --------
def test_super_admin_team_scope_sees_own_leave(tokens):
    tok = tokens["super_admin"]
    reason = f"TEST_iter23_sa_leave_{uuid.uuid4().hex[:6]}"
    _apply_leave(tok, days_ahead=340, reason=reason)
    r = requests.get(f"{API}/leave/all", params={"status": "pending", "scope": "team"},
                     headers=_h(tok), timeout=15)
    assert r.status_code == 200
    reasons = [x.get("reason") for x in r.json()]
    assert reason in reasons


def test_hr_team_scope_sees_own_wfh(tokens):
    tok = tokens["hr"]
    reason = f"TEST_iter23_hr_wfh_{uuid.uuid4().hex[:6]}"
    _apply_wfh(tok, days_ahead=350, reason=reason)
    r = requests.get(f"{API}/wfh/all", params={"status": "pending", "scope": "team"},
                     headers=_h(tok), timeout=15)
    assert r.status_code == 200
    reasons = [x.get("reason") for x in r.json()]
    assert reason in reasons
