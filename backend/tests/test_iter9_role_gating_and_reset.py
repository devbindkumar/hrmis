"""Iteration 9 tests: WhatsApp super_admin gating + Employee password reset.

Covers:
- All /api/whatsapp/* routes are super_admin only (200 for admin, 403 for hr/manager/employee)
- POST /api/employees/{id}/reset-password: happy path, validation, authz, 404, email flag
- Password reset does NOT wipe other fields
- Cleanup: restores maya@acme.com password to Demo@123
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

CREDS = {
    "admin": ("admin@acme.com", "Admin@123"),
    "hr": ("jordan@acme.com", "Demo@123"),
    "manager": ("alex@acme.com", "Demo@123"),
    "employee": ("maya@acme.com", "Demo@123"),
}


def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tokens():
    return {k: _login(*v) for k, v in CREDS.items()}


@pytest.fixture(scope="module")
def maya_emp_id(tokens):
    """Find maya's employee id via admin listing."""
    r = requests.get(f"{BASE_URL}/api/employees", headers=_h(tokens["admin"]), timeout=15)
    assert r.status_code == 200
    for e in r.json():
        if e.get("email") == "maya@acme.com":
            return e["id"]
    pytest.skip("maya employee not found")


# --------------- WhatsApp gating ---------------

WA_READ_ENDPOINTS = [
    ("GET", "/api/whatsapp/config"),
    ("GET", "/api/whatsapp/outbox"),
    ("GET", "/api/whatsapp/templates"),
]


@pytest.mark.parametrize("method,path", WA_READ_ENDPOINTS)
def test_whatsapp_read_super_admin_200(tokens, method, path):
    r = requests.request(method, f"{BASE_URL}{path}", headers=_h(tokens["admin"]), timeout=15)
    assert r.status_code == 200, f"{method} {path} → {r.status_code} {r.text}"


@pytest.mark.parametrize("method,path", WA_READ_ENDPOINTS)
@pytest.mark.parametrize("who", ["hr", "manager", "employee"])
def test_whatsapp_read_non_super_admin_403(tokens, method, path, who):
    r = requests.request(method, f"{BASE_URL}{path}", headers=_h(tokens[who]), timeout=15)
    assert r.status_code == 403, f"{who} {method} {path} → {r.status_code} {r.text}"


def test_whatsapp_put_config_non_super_admin_403(tokens):
    for who in ("hr", "manager", "employee"):
        r = requests.put(
            f"{BASE_URL}/api/whatsapp/config",
            headers=_h(tokens[who]),
            json={"enabled": False},
            timeout=15,
        )
        assert r.status_code == 403, f"{who} PUT /whatsapp/config → {r.status_code}"


def test_whatsapp_test_send_non_super_admin_403(tokens):
    for who in ("hr", "manager", "employee"):
        r = requests.post(
            f"{BASE_URL}/api/whatsapp/test",
            headers=_h(tokens[who]),
            json={"to": "+911234567890", "template_key": "status_update"},
            timeout=15,
        )
        assert r.status_code == 403, f"{who} POST /whatsapp/test → {r.status_code}"


# --------------- Reset password ---------------

def test_reset_password_authz_non_super_admin_403(tokens, maya_emp_id):
    for who in ("hr", "manager", "employee"):
        r = requests.post(
            f"{BASE_URL}/api/employees/{maya_emp_id}/reset-password",
            headers=_h(tokens[who]),
            json={"new_password": "TempPassword@2026", "notify_employee": False},
            timeout=15,
        )
        assert r.status_code == 403, f"{who} → {r.status_code} {r.text}"


def test_reset_password_validation_too_short(tokens, maya_emp_id):
    r = requests.post(
        f"{BASE_URL}/api/employees/{maya_emp_id}/reset-password",
        headers=_h(tokens["admin"]),
        json={"new_password": "abc"},
        timeout=15,
    )
    assert r.status_code == 422


def test_reset_password_validation_missing_field(tokens, maya_emp_id):
    r = requests.post(
        f"{BASE_URL}/api/employees/{maya_emp_id}/reset-password",
        headers=_h(tokens["admin"]),
        json={},
        timeout=15,
    )
    assert r.status_code == 422


def test_reset_password_not_found(tokens):
    r = requests.post(
        f"{BASE_URL}/api/employees/does-not-exist-id/reset-password",
        headers=_h(tokens["admin"]),
        json={"new_password": "TempPassword@2026", "notify_employee": False},
        timeout=15,
    )
    assert r.status_code == 404
    assert "not found" in r.text.lower()


def test_reset_password_happy_path_and_login(tokens, maya_emp_id):
    new_pw = "TempPassword@2026"
    # snapshot employee first
    before = requests.get(
        f"{BASE_URL}/api/employees/{maya_emp_id}", headers=_h(tokens["admin"]), timeout=15
    ).json()

    r = requests.post(
        f"{BASE_URL}/api/employees/{maya_emp_id}/reset-password",
        headers=_h(tokens["admin"]),
        json={"new_password": new_pw, "notify_employee": False},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True
    assert data["email"] == "maya@acme.com"
    assert data["notified"] is False

    # new password works
    lr = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "maya@acme.com", "password": new_pw}, timeout=15)
    assert lr.status_code == 200, f"login with new pw failed: {lr.status_code} {lr.text}"
    assert "token" in lr.json()

    # employee fields unchanged
    after = requests.get(
        f"{BASE_URL}/api/employees/{maya_emp_id}", headers=_h(tokens["admin"]), timeout=15
    ).json()
    for key in ("name", "department", "designation", "location", "phone", "manager_id", "email"):
        assert after.get(key) == before.get(key), f"field {key} changed: {before.get(key)} → {after.get(key)}"


def test_reset_password_notify_true_still_200(tokens, maya_emp_id):
    """notify_employee=true should still succeed even if email transport isn't configured."""
    r = requests.post(
        f"{BASE_URL}/api/employees/{maya_emp_id}/reset-password",
        headers=_h(tokens["admin"]),
        json={"new_password": "AnotherTemp@2026", "notify_employee": True},
        timeout=25,
    )
    assert r.status_code == 200, r.text
    assert r.json()["notified"] is True


# --------------- CLEANUP: restore maya's password ---------------

def test_zzz_restore_maya_password(tokens, maya_emp_id):
    r = requests.post(
        f"{BASE_URL}/api/employees/{maya_emp_id}/reset-password",
        headers=_h(tokens["admin"]),
        json={"new_password": "Demo@123", "notify_employee": False},
        timeout=15,
    )
    assert r.status_code == 200
    # verify seeded creds work again
    lr = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "maya@acme.com", "password": "Demo@123"}, timeout=15)
    assert lr.status_code == 200, "Failed to restore maya's password!"
