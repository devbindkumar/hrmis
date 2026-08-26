"""Iter 20 – Privacy fix for GET /api/expenses/all & /summary.

Manager must only see claims from their direct reports.
Super_admin and HR keep company-wide visibility.
"""
import os
import requests
import pytest

def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _load_backend_url()

ADMIN = ("admin@acme.com", "Admin@123")
HR = ("jordan@acme.com", "Demo@123")
MANAGER = ("alex@acme.com", "Demo@123")
REPORT1 = ("maya@acme.com", "Demo@123")
REPORT2 = ("diego@acme.com", "Demo@123")


def _login(email: str, password: str) -> dict:
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    body = r.json()
    return {"token": body["token"], "user": body["user"]}


def _headers(sess):
    return {"Authorization": f"Bearer {sess['token']}", "Content-Type": "application/json"}


def _create_claim(sess, desc="TEST_privacy claim"):
    r = requests.post(
        f"{BASE_URL}/api/expenses",
        json={
            "category": "Travel",
            "amount": 50,
            "currency": "USD",
            "date_incurred": "2026-08-25",
            "description": desc,
        },
        headers=_headers(sess),
        timeout=15,
    )
    assert r.status_code == 200, f"create claim failed: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def sessions():
    return {
        "admin": _login(*ADMIN),
        "hr": _login(*HR),
        "manager": _login(*MANAGER),
        "maya": _login(*REPORT1),
        "diego": _login(*REPORT2),
    }


@pytest.fixture(scope="module")
def seeded(sessions):
    """Seed 4 claims and clean them up at teardown."""
    created = []
    # direct reports to Alex
    created.append(("maya", _create_claim(sessions["maya"], "TEST_privacy_maya")["id"]))
    created.append(("diego", _create_claim(sessions["diego"], "TEST_privacy_diego")["id"]))
    # non direct reports
    created.append(("hr", _create_claim(sessions["hr"], "TEST_privacy_hr")["id"]))
    created.append(("admin", _create_claim(sessions["admin"], "TEST_privacy_admin")["id"]))
    yield created
    # cleanup as admin (has full delete rights)
    for _who, cid in created:
        try:
            requests.delete(f"{BASE_URL}/api/expenses/{cid}", headers=_headers(sessions["admin"]), timeout=10)
        except Exception:
            pass


# -------- Privacy assertions ---------------------------------------------

def test_manager_all_scoped_to_direct_reports_only(sessions, seeded):
    mgr = sessions["manager"]
    r = requests.get(f"{BASE_URL}/api/expenses/all", headers=_headers(mgr), timeout=15)
    assert r.status_code == 200, r.text
    items = r.json()
    # every row must be for Alex's manager_user_id
    for row in items:
        assert row.get("manager_user_id") == mgr["user"]["id"], (
            f"Leak: row {row.get('id')} belongs to manager {row.get('manager_user_id')} not Alex"
        )
    # seeded direct-report claims must be present
    ids = {r["id"] for r in items}
    seeded_map = dict(seeded)
    assert seeded_map["maya"] in ids, "maya's claim missing from Alex's team view"
    assert seeded_map["diego"] in ids, "diego's claim missing from Alex's team view"
    # non direct-report claims must NOT leak
    assert seeded_map["hr"] not in ids, "HR's claim leaked into manager's list"
    assert seeded_map["admin"] not in ids, "admin's claim leaked into manager's list"


def test_manager_all_equals_team_scope(sessions, seeded):
    mgr = sessions["manager"]
    r1 = requests.get(f"{BASE_URL}/api/expenses/all", headers=_headers(mgr), timeout=15)
    r2 = requests.get(f"{BASE_URL}/api/expenses/all?scope=team", headers=_headers(mgr), timeout=15)
    assert r1.status_code == 200 and r2.status_code == 200
    a_ids = sorted(x["id"] for x in r1.json())
    b_ids = sorted(x["id"] for x in r2.json())
    assert a_ids == b_ids, "Manager /all should equal /all?scope=team"


def test_manager_summary_matches_all_count(sessions, seeded):
    mgr = sessions["manager"]
    all_rows = requests.get(f"{BASE_URL}/api/expenses/all", headers=_headers(mgr), timeout=15).json()
    summary = requests.get(f"{BASE_URL}/api/expenses/summary", headers=_headers(mgr), timeout=15).json()
    total = sum(v["count"] for v in summary.values())
    assert total == len(all_rows), f"summary count {total} != /all length {len(all_rows)}"


def test_super_admin_all_shows_org_wide(sessions, seeded):
    admin = sessions["admin"]
    mgr = sessions["manager"]
    a_rows = requests.get(f"{BASE_URL}/api/expenses/all", headers=_headers(admin), timeout=15).json()
    m_rows = requests.get(f"{BASE_URL}/api/expenses/all", headers=_headers(mgr), timeout=15).json()
    assert len(a_rows) > len(m_rows), (
        f"admin ({len(a_rows)}) should see strictly more than manager ({len(m_rows)}) given non-direct-report seed claims"
    )
    ids = {x["id"] for x in a_rows}
    seeded_map = dict(seeded)
    for k in ("maya", "diego", "hr", "admin"):
        assert seeded_map[k] in ids, f"admin missing seeded claim {k}"


def test_super_admin_summary_org_wide(sessions, seeded):
    admin = sessions["admin"]
    mgr = sessions["manager"]
    a_sum = requests.get(f"{BASE_URL}/api/expenses/summary", headers=_headers(admin), timeout=15).json()
    m_sum = requests.get(f"{BASE_URL}/api/expenses/summary", headers=_headers(mgr), timeout=15).json()
    a_total = sum(v["count"] for v in a_sum.values())
    m_total = sum(v["count"] for v in m_sum.values())
    assert a_total > m_total, f"admin summary total {a_total} should exceed manager {m_total}"


def test_hr_sees_org_wide(sessions, seeded):
    hr = sessions["hr"]
    rows = requests.get(f"{BASE_URL}/api/expenses/all", headers=_headers(hr), timeout=15).json()
    ids = {x["id"] for x in rows}
    seeded_map = dict(seeded)
    # HR should see all seeded claims (including non direct-report ones)
    for k in ("maya", "diego", "hr", "admin"):
        assert seeded_map[k] in ids, f"HR missing seeded claim {k}"


def test_hr_all_ignores_scope_team_or_returns_org_wide(sessions, seeded):
    """HR uses scope=team? Backend uses manager_user_id==hr.id for scope=team.
    Just verify default (no scope) is org-wide for HR."""
    hr = sessions["hr"]
    rows = requests.get(f"{BASE_URL}/api/expenses/all", headers=_headers(hr), timeout=15).json()
    # should include admin-authored seeded claim (proves org-wide)
    seeded_map = dict(seeded)
    ids = {x["id"] for x in rows}
    assert seeded_map["admin"] in ids
