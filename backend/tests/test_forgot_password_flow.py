"""Backend tests for Forgot Password (WhatsApp OTP) flow.

Covers:
- /api/auth/forgot-password (unknown email, valid email, cooldown, no user enum)
- /api/auth/verify-otp (wrong 3x invalidates, correct code mints reset_token)
- /api/auth/reset-password (single-use reset_token, login with new pw)
"""
import os
import re
import time
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://workforce-central-43.preview.emergentagent.com").rstrip("/")
MAYA_EMAIL = "maya@acme.com"
ORIGINAL_PW = "Demo@123"

BACKEND_LOG = "/var/log/supervisor/backend.err.log"


def _tail_otp(email: str) -> str:
    """Pull the most recent OTP for `email` from the backend error log."""
    # WhatsApp is disabled so the OTP is logged: "OTP for <email>: 123456"
    try:
        out = subprocess.check_output(["tail", "-n", "500", BACKEND_LOG]).decode()
    except Exception:
        return ""
    matches = re.findall(rf"OTP for {re.escape(email)}: (\d{{6}})", out)
    return matches[-1] if matches else ""


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module", autouse=True)
def _restore_password(api):
    """Ensure Demo@123 is restored at the end of the test session."""
    yield
    # Best-effort restore
    r = api.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": MAYA_EMAIL})
    time.sleep(1.5)
    otp = _tail_otp(MAYA_EMAIL)
    if otp:
        v = api.post(f"{BASE_URL}/api/auth/verify-otp", json={"email": MAYA_EMAIL, "otp": otp})
        if v.status_code == 200:
            rt = v.json().get("reset_token")
            api.post(f"{BASE_URL}/api/auth/reset-password",
                     json={"reset_token": rt, "new_password": ORIGINAL_PW})


# -------- forgot-password --------

class TestForgotPassword:
    def test_unknown_email_returns_200_no_enum(self, api):
        r = api.post(f"{BASE_URL}/api/auth/forgot-password",
                     json={"email": "nobody-xyz@nowhere.com"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["phone_hint"] is None

    def test_valid_email_returns_masked_hint_and_generates_otp(self, api):
        r = api.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": MAYA_EMAIL})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["success"] is True
        assert data["phone_hint"] and data["phone_hint"].endswith("9999")
        assert "•" in data["phone_hint"]
        time.sleep(1.0)
        otp = _tail_otp(MAYA_EMAIL)
        assert re.fullmatch(r"\d{6}", otp or ""), f"OTP not found in backend log: {otp!r}"

    def test_cooldown_within_45s(self, api):
        r = api.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": MAYA_EMAIL})
        assert r.status_code == 200
        data = r.json()
        assert data.get("cooldown") is True, data


# -------- verify-otp + reset-password (full happy-path) --------

class TestVerifyAndReset:
    """Runs sequentially — each step depends on the previous."""

    reset_token = None
    new_password = "NewMaya@123"

    def test_wrong_otp_three_times_invalidates(self, api):
        # Request a fresh OTP first (cooldown means we can't spam; wait it out)
        # The previous test class already sent one <45s ago, so wait.
        time.sleep(46)
        r = api.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": MAYA_EMAIL})
        assert r.status_code == 200
        assert r.json().get("phone_hint")
        time.sleep(1.0)
        real_otp = _tail_otp(MAYA_EMAIL)
        assert real_otp, "Expected OTP in log"

        # 3 wrong attempts
        wrong = "000000" if real_otp != "000000" else "111111"
        msgs = []
        for _ in range(3):
            v = api.post(f"{BASE_URL}/api/auth/verify-otp",
                         json={"email": MAYA_EMAIL, "otp": wrong})
            assert v.status_code == 400
            msgs.append(v.json().get("detail", ""))
        # After third wrong, OTP invalidated → subsequent correct code fails
        v = api.post(f"{BASE_URL}/api/auth/verify-otp",
                     json={"email": MAYA_EMAIL, "otp": real_otp})
        assert v.status_code == 400
        assert "expired" in v.json()["detail"].lower() or "invalid" in v.json()["detail"].lower()
        # And one of the earlier msgs mentions "Too many wrong codes"
        assert any("Too many" in m for m in msgs), msgs

    def test_correct_otp_mints_reset_token(self, api):
        # Fresh OTP again (cooldown wait)
        time.sleep(46)
        r = api.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": MAYA_EMAIL})
        assert r.status_code == 200
        time.sleep(1.0)
        otp = _tail_otp(MAYA_EMAIL)
        assert otp
        v = api.post(f"{BASE_URL}/api/auth/verify-otp",
                     json={"email": MAYA_EMAIL, "otp": otp})
        assert v.status_code == 200, v.text
        data = v.json()
        assert isinstance(data["reset_token"], str) and len(data["reset_token"]) > 30
        assert data["expires_in"] == 900
        TestVerifyAndReset.reset_token = data["reset_token"]

    def test_reset_password_and_reuse_rejected(self, api):
        assert TestVerifyAndReset.reset_token, "Missing reset_token from previous test"
        r = api.post(f"{BASE_URL}/api/auth/reset-password", json={
            "reset_token": TestVerifyAndReset.reset_token,
            "new_password": TestVerifyAndReset.new_password,
        })
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

        # Reuse same token → 400 already used
        r2 = api.post(f"{BASE_URL}/api/auth/reset-password", json={
            "reset_token": TestVerifyAndReset.reset_token,
            "new_password": "AnotherPass@1",
        })
        assert r2.status_code == 400
        assert "already been used" in r2.json()["detail"].lower() or \
               "already used" in r2.json()["detail"].lower()

    def test_login_with_new_password_and_old_fails(self, api):
        # New password works
        ok = api.post(f"{BASE_URL}/api/auth/login", json={
            "email": MAYA_EMAIL, "password": TestVerifyAndReset.new_password,
        })
        assert ok.status_code == 200, ok.text
        assert "token" in ok.json()

        # Old password fails
        bad = api.post(f"{BASE_URL}/api/auth/login", json={
            "email": MAYA_EMAIL, "password": ORIGINAL_PW,
        })
        assert bad.status_code == 401
