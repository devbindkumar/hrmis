"""Backend regression for /api/attendance endpoints used by CheckInWidget."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://workforce-central-43.preview.emergentagent.com").rstrip("/")


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


def _ensure_checked_out(headers):
    """Ensure user is checked out so tests start from a known state."""
    r = requests.get(f"{BASE_URL}/api/attendance/today", headers=headers, timeout=30)
    if r.status_code == 200:
        t = r.json()
        if t.get("check_in") and not t.get("check_out"):
            requests.post(f"{BASE_URL}/api/attendance/check-out", headers=headers, timeout=30)


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@acme.com", "Admin@123")


@pytest.fixture(scope="module")
def hr_token():
    return _login("jordan@acme.com", "Demo@123")


@pytest.fixture(scope="module")
def manager_token():
    return _login("alex@acme.com", "Demo@123")


def _run_flow(token, role_label):
    headers = {"Authorization": f"Bearer {token}"}
    _ensure_checked_out(headers)

    # today endpoint always responds
    r = requests.get(f"{BASE_URL}/api/attendance/today", headers=headers, timeout=30)
    assert r.status_code == 200, f"[{role_label}] /today failed: {r.status_code} {r.text}"
    body = r.json()
    assert "check_in" in body and "check_out" in body

    # if user already had a completed day today, we can only assert idempotence, not the full flow
    if body.get("check_in") and body.get("check_out"):
        # already completed for the day — verify duplicate check-in is rejected and stop
        r2 = requests.post(f"{BASE_URL}/api/attendance/check-in", headers=headers, timeout=30)
        assert r2.status_code in (400, 409), f"[{role_label}] expected 4xx on re-checkin after day complete, got {r2.status_code}"
        return "already_completed"

    # Fresh check-in
    r = requests.post(f"{BASE_URL}/api/attendance/check-in", headers=headers, timeout=30)
    assert r.status_code in (200, 201), f"[{role_label}] check-in failed: {r.status_code} {r.text}"

    # Duplicate check-in -> 400
    r_dup = requests.post(f"{BASE_URL}/api/attendance/check-in", headers=headers, timeout=30)
    assert r_dup.status_code == 400, f"[{role_label}] expected 400 duplicate check-in, got {r_dup.status_code} {r_dup.text}"

    # today reflects state
    r = requests.get(f"{BASE_URL}/api/attendance/today", headers=headers, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body.get("check_in") and not body.get("check_out"), f"[{role_label}] state after check-in wrong: {body}"

    # status change
    r = requests.post(f"{BASE_URL}/api/attendance/status", headers=headers, json={"status": "on_break"}, timeout=30)
    assert r.status_code in (200, 201), f"[{role_label}] status update failed: {r.status_code} {r.text}"
    r = requests.get(f"{BASE_URL}/api/attendance/today", headers=headers, timeout=30)
    assert r.json().get("current_status") == "on_break"

    # check-out
    r = requests.post(f"{BASE_URL}/api/attendance/check-out", headers=headers, timeout=30)
    assert r.status_code in (200, 201), f"[{role_label}] check-out failed: {r.status_code} {r.text}"

    # final state
    r = requests.get(f"{BASE_URL}/api/attendance/today", headers=headers, timeout=30)
    body = r.json()
    assert body.get("check_in") and body.get("check_out"), f"[{role_label}] final state wrong: {body}"
    return "ok"


def test_admin_attendance_flow(admin_token):
    result = _run_flow(admin_token, "super_admin")
    assert result in ("ok", "already_completed")


def test_hr_attendance_flow(hr_token):
    result = _run_flow(hr_token, "hr")
    assert result in ("ok", "already_completed")


def test_manager_attendance_flow(manager_token):
    result = _run_flow(manager_token, "manager")
    assert result in ("ok", "already_completed")


def test_admin_left_checked_out(admin_token):
    """Post-condition: admin must be in a checked-out state (or not checked in yet)."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    _ensure_checked_out(headers)
    r = requests.get(f"{BASE_URL}/api/attendance/today", headers=headers, timeout=30)
    body = r.json()
    # allow either no-check-in or a completed day
    assert (not body.get("check_in")) or body.get("check_out"), f"admin not checked out: {body}"
