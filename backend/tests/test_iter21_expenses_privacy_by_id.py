"""Iter 21 – Manager scope enforcement on per-claim endpoints.

Verifies GET /{id}, GET /{id}/receipt, POST /{id}/approve, POST /{id}/reject
enforce that a manager can only touch claims where manager_user_id == his id
(or his own submitted claim). Super_admin & HR remain unrestricted.
Also regressions: /all still scoped for manager.
"""
import base64
import os
import requests
import pytest

def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _load_backend_url()

ADMIN = ("admin@acme.com", "Admin@123")
HR = ("jordan@acme.com", "Demo@123")
MANAGER = ("alex@acme.com", "Demo@123")
REPORT = ("maya@acme.com", "Demo@123")

# tiny 1x1 PNG
PNG_B64 = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    body = r.json()
    return {"token": body["token"], "user": body["user"]}


def _h(sess):
    return {"Authorization": f"Bearer {sess['token']}", "Content-Type": "application/json"}


def _create(sess, desc, with_receipt=False):
    payload = {
        "category": "Travel",
        "amount": 42,
        "currency": "USD",
        "date_incurred": "2026-08-25",
        "description": desc,
    }
    if with_receipt:
        payload["receipt_b64"] = PNG_B64
    r = requests.post(f"{BASE_URL}/api/expenses", json=payload,
                      headers=_h(sess), timeout=15)
    assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def sessions():
    return {
        "admin": _login(*ADMIN),
        "hr": _login(*HR),
        "manager": _login(*MANAGER),
        "maya": _login(*REPORT),
    }


@pytest.fixture(scope="module")
def seeded(sessions):
    """Seed claims. maya = direct report to Alex; hr + admin = non reports.
    Create TWO maya pending claims so we can approve one and reject the other."""
    created = []
    maya_c1 = _create(sessions["maya"], "TEST_iter21_maya_approve", with_receipt=True)
    maya_c2 = _create(sessions["maya"], "TEST_iter21_maya_reject", with_receipt=True)
    hr_c = _create(sessions["hr"], "TEST_iter21_hr_nonreport", with_receipt=True)
    admin_c = _create(sessions["admin"], "TEST_iter21_admin_nonreport", with_receipt=True)

    # sanity: maya's claim should be routed to Alex as manager
    assert maya_c1.get("manager_user_id") == sessions["manager"]["user"]["id"], (
        f"maya's claim manager_user_id={maya_c1.get('manager_user_id')} != Alex.id={sessions['manager']['user']['id']}"
    )

    data = {
        "maya_approve": maya_c1["id"],
        "maya_reject": maya_c2["id"],
        "hr": hr_c["id"],
        "admin": admin_c["id"],
    }
    created.extend(data.values())
    yield data
    # cleanup
    for cid in created:
        try:
            requests.delete(f"{BASE_URL}/api/expenses/{cid}",
                            headers=_h(sessions["admin"]), timeout=10)
        except Exception:
            pass


# ---- GET /{id} ----------------------------------------------------------

def test_manager_get_direct_report_claim_ok(sessions, seeded):
    r = requests.get(f"{BASE_URL}/api/expenses/{seeded['maya_approve']}",
                     headers=_h(sessions["manager"]), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == seeded["maya_approve"]


def test_manager_get_non_report_claim_forbidden(sessions, seeded):
    r = requests.get(f"{BASE_URL}/api/expenses/{seeded['hr']}",
                     headers=_h(sessions["manager"]), timeout=15)
    assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"

    r2 = requests.get(f"{BASE_URL}/api/expenses/{seeded['admin']}",
                      headers=_h(sessions["manager"]), timeout=15)
    assert r2.status_code == 403, f"expected 403 got {r2.status_code}: {r2.text}"


# ---- GET /{id}/receipt --------------------------------------------------

def test_manager_get_receipt_direct_report_ok(sessions, seeded):
    r = requests.get(f"{BASE_URL}/api/expenses/{seeded['maya_approve']}/receipt",
                     headers=_h(sessions["manager"]), timeout=15)
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("image/")
    assert len(r.content) > 0


def test_manager_get_receipt_non_report_forbidden(sessions, seeded):
    r = requests.get(f"{BASE_URL}/api/expenses/{seeded['hr']}/receipt",
                     headers=_h(sessions["manager"]), timeout=15)
    assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"

    r2 = requests.get(f"{BASE_URL}/api/expenses/{seeded['admin']}/receipt",
                      headers=_h(sessions["manager"]), timeout=15)
    assert r2.status_code == 403, f"expected 403 got {r2.status_code}: {r2.text}"


# ---- POST /{id}/approve -------------------------------------------------

def test_manager_approve_non_report_forbidden(sessions, seeded):
    r = requests.post(f"{BASE_URL}/api/expenses/{seeded['hr']}/approve",
                      json={"note": "nope"}, headers=_h(sessions["manager"]), timeout=15)
    assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"

    r2 = requests.post(f"{BASE_URL}/api/expenses/{seeded['admin']}/approve",
                       json={"note": "nope"}, headers=_h(sessions["manager"]), timeout=15)
    assert r2.status_code == 403, f"expected 403 got {r2.status_code}: {r2.text}"


def test_manager_approve_direct_report_ok(sessions, seeded):
    r = requests.post(f"{BASE_URL}/api/expenses/{seeded['maya_approve']}/approve",
                      json={"note": "ok"}, headers=_h(sessions["manager"]), timeout=15)
    assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
    assert r.json().get("success") is True
    # verify persisted
    g = requests.get(f"{BASE_URL}/api/expenses/{seeded['maya_approve']}",
                     headers=_h(sessions["manager"]), timeout=15).json()
    assert g["status"] == "approved"


# ---- POST /{id}/reject --------------------------------------------------

def test_manager_reject_non_report_forbidden(sessions, seeded):
    r = requests.post(f"{BASE_URL}/api/expenses/{seeded['hr']}/reject",
                      json={"note": "nope"}, headers=_h(sessions["manager"]), timeout=15)
    assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"

    r2 = requests.post(f"{BASE_URL}/api/expenses/{seeded['admin']}/reject",
                       json={"note": "nope"}, headers=_h(sessions["manager"]), timeout=15)
    assert r2.status_code == 403, f"expected 403 got {r2.status_code}: {r2.text}"


def test_manager_reject_direct_report_ok(sessions, seeded):
    r = requests.post(f"{BASE_URL}/api/expenses/{seeded['maya_reject']}/reject",
                      json={"note": "no"}, headers=_h(sessions["manager"]), timeout=15)
    assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
    assert r.json().get("success") is True
    g = requests.get(f"{BASE_URL}/api/expenses/{seeded['maya_reject']}",
                     headers=_h(sessions["manager"]), timeout=15).json()
    assert g["status"] == "rejected"


# ---- Non-regression: super_admin + HR unrestricted ----------------------

@pytest.mark.parametrize("who", ["admin", "hr"])
def test_privileged_can_get_any_claim(sessions, seeded, who):
    for key in ("maya_approve", "maya_reject", "hr", "admin"):
        r = requests.get(f"{BASE_URL}/api/expenses/{seeded[key]}",
                         headers=_h(sessions[who]), timeout=15)
        assert r.status_code == 200, f"{who} GET {key}: {r.status_code} {r.text}"


@pytest.mark.parametrize("who", ["admin", "hr"])
def test_privileged_can_get_any_receipt(sessions, seeded, who):
    for key in ("maya_approve", "maya_reject", "hr", "admin"):
        r = requests.get(f"{BASE_URL}/api/expenses/{seeded[key]}/receipt",
                         headers=_h(sessions[who]), timeout=15)
        assert r.status_code == 200, f"{who} receipt {key}: {r.status_code} {r.text}"
        assert len(r.content) > 0


def test_admin_can_approve_and_reject_non_report(sessions):
    """Fresh claims for admin to act on: one from HR (non-report to admin acts fine), one from admin? No — admin cannot approve own unless super_admin (allowed).
    Simplest: admin approves an HR-authored fresh claim, rejects another."""
    # create a fresh HR claim to approve as admin
    c1 = _create(sessions["hr"], "TEST_iter21_hr_admin_approve")
    c2 = _create(sessions["hr"], "TEST_iter21_hr_admin_reject")
    try:
        r = requests.post(f"{BASE_URL}/api/expenses/{c1['id']}/approve",
                          json={"note": "ok"}, headers=_h(sessions["admin"]), timeout=15)
        assert r.status_code == 200, r.text
        r = requests.post(f"{BASE_URL}/api/expenses/{c2['id']}/reject",
                          json={"note": "no"}, headers=_h(sessions["admin"]), timeout=15)
        assert r.status_code == 200, r.text
    finally:
        for cid in (c1["id"], c2["id"]):
            requests.delete(f"{BASE_URL}/api/expenses/{cid}",
                            headers=_h(sessions["admin"]), timeout=10)


def test_hr_can_approve_non_authored_claim(sessions):
    """HR should be able to approve a claim they didn't submit (unrestricted)."""
    c = _create(sessions["maya"], "TEST_iter21_maya_hr_approve")
    try:
        r = requests.post(f"{BASE_URL}/api/expenses/{c['id']}/approve",
                          json={"note": "ok"}, headers=_h(sessions["hr"]), timeout=15)
        assert r.status_code == 200, r.text
    finally:
        requests.delete(f"{BASE_URL}/api/expenses/{c['id']}",
                        headers=_h(sessions["admin"]), timeout=10)


# ---- Regression: /all still scoped for manager --------------------------

def test_manager_all_still_scoped(sessions, seeded):
    r = requests.get(f"{BASE_URL}/api/expenses/all",
                     headers=_h(sessions["manager"]), timeout=15)
    assert r.status_code == 200, r.text
    mgr_id = sessions["manager"]["user"]["id"]
    for row in r.json():
        assert row.get("manager_user_id") == mgr_id, (
            f"leak: {row.get('id')} manager_user_id={row.get('manager_user_id')}"
        )
    ids = {row["id"] for row in r.json()}
    assert seeded["hr"] not in ids
    assert seeded["admin"] not in ids
