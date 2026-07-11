"""Iteration 13 backend tests.

Covers:
- Startup migration idempotence for whatsapp_configs.events_enabled.checkin_checkout
- GET /api/kiosk/activity (super_admin + hr; manager/employee 403; limit param; sorted DESC)
- End-to-end kiosk write→read: check-in → check-out → activity contains both events
- Regression: iteration 12 defaults still surface via GET /api/whatsapp/config
"""
from __future__ import annotations

import os
import subprocess
import time
import uuid

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

ADMIN = ("admin@acme.com", "Admin@123")
HR = ("jordan@acme.com", "Demo@123")
MANAGER = ("alex@acme.com", "Demo@123")
EMPLOYEE = ("maya@acme.com", "Demo@123")


# --------- helpers ---------

def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _wait_for_backend(max_seconds: int = 30) -> bool:
    """Wait until /api/auth/login (or a light endpoint) responds after a restart."""
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/api/auth/me", timeout=3)
            # 401 without token is fine — means server is up
            if r.status_code in (200, 401, 403, 422):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


# --------- fixtures ---------

@pytest.fixture(scope="module")
def admin_tok() -> str:
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def hr_tok() -> str:
    return _login(*HR)


@pytest.fixture(scope="module")
def manager_tok() -> str:
    return _login(*MANAGER)


@pytest.fixture(scope="module")
def emp_tok() -> str:
    return _login(*EMPLOYEE)


@pytest.fixture(scope="module")
def company_id(admin_tok) -> str:
    r = requests.get(f"{BASE_URL}/api/companies/mine", headers=_headers(admin_tok), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def maya_employee_id(admin_tok) -> str:
    r = requests.get(f"{BASE_URL}/api/employees", headers=_headers(admin_tok), timeout=15)
    assert r.status_code == 200
    for e in r.json():
        if e.get("email") == EMPLOYEE[0]:
            return e["id"]
    pytest.skip("maya not found")


@pytest.fixture(scope="module")
def maya_user_id(admin_tok) -> str:
    r = requests.get(f"{BASE_URL}/api/employees", headers=_headers(admin_tok), timeout=15)
    for e in r.json():
        if e.get("email") == EMPLOYEE[0]:
            return e["user_id"]
    pytest.skip("maya user_id not found")


# ---------------------------------------------------------------------------
# 1. Startup migration idempotence
# ---------------------------------------------------------------------------

class TestMigrationCheckinCheckoutFlip:
    """Verifies the _flip_checkin_checkout_default migration.

    Approach: (a) put False into the tenant config via PUT /api/whatsapp/config,
    (b) verify GET returns False, (c) restart backend via supervisorctl, (d)
    verify GET returns True and 'flipped' log line was emitted, (e) restart
    again → this time no rows were modified so log line should NOT re-appear.
    """

    def _read_log_tail(self, lines: int = 300) -> str:
        try:
            out = subprocess.run(
                ["bash", "-lc", f"tail -n {lines} /var/log/supervisor/backend.err.log /var/log/supervisor/backend.out.log 2>/dev/null || true"],
                capture_output=True, text=True, timeout=5,
            )
            return (out.stdout or "") + (out.stderr or "")
        except Exception:
            return ""

    def _restart_backend(self) -> None:
        subprocess.run(["sudo", "supervisorctl", "restart", "backend"], capture_output=True, text=True, timeout=30)
        assert _wait_for_backend(), "backend did not come back up after restart"

    def test_flip_and_idempotence(self, admin_tok):
        # 1. Force False via API
        r = requests.put(
            f"{BASE_URL}/api/whatsapp/config",
            headers=_headers(admin_tok),
            json={"events_enabled": {"checkin_checkout": False}},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        cfg = requests.get(f"{BASE_URL}/api/whatsapp/config", headers=_headers(admin_tok), timeout=15).json()
        assert cfg["events_enabled"]["checkin_checkout"] is False, (
            "PUT did not persist checkin_checkout=False"
        )

        # 2. Restart backend → migration runs on startup
        self._restart_backend()

        # 3. GET → now True
        cfg2 = requests.get(f"{BASE_URL}/api/whatsapp/config", headers=_headers(_login(*ADMIN)), timeout=15).json()
        assert cfg2["events_enabled"]["checkin_checkout"] is True, (
            f"migration did not flip False→True. Current cfg: {cfg2}"
        )

        # 4. Log line must have appeared for THIS run
        log_after_flip = self._read_log_tail(400)
        assert "flipped events_enabled.checkin_checkout" in log_after_flip, (
            "migration log line not found — [migration] flipped ... should be present"
        )

        # 5. Restart again — nothing to flip this time (idempotence)
        # Truncate marker: capture current log length as a checkpoint
        before_len = len(log_after_flip)
        self._restart_backend()
        # Small settle to let startup logging finish
        time.sleep(2)
        log_after_second = self._read_log_tail(600)
        # Only inspect the NEW portion of the log
        new_portion = log_after_second[before_len:] if len(log_after_second) > before_len else log_after_second
        # Even if the tail has extra content, look for the specific line count
        first_count = log_after_flip.count("flipped events_enabled.checkin_checkout")
        second_count = log_after_second.count("flipped events_enabled.checkin_checkout")
        assert second_count == first_count, (
            f"migration ran again — expected idempotence. counts: first={first_count}, second={second_count}\n"
            f"new_portion sample: {new_portion[-1000:]}"
        )

        # 6. GET still True
        tok = _login(*ADMIN)
        cfg3 = requests.get(f"{BASE_URL}/api/whatsapp/config", headers=_headers(tok), timeout=15).json()
        assert cfg3["events_enabled"]["checkin_checkout"] is True


# ---------------------------------------------------------------------------
# 2. GET /api/kiosk/activity — authorization
# ---------------------------------------------------------------------------

class TestKioskActivityAuth:

    def test_super_admin_allowed(self, admin_tok):
        r = requests.get(f"{BASE_URL}/api/kiosk/activity", headers=_headers(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "events" in data
        assert "total" in data
        assert isinstance(data["events"], list)
        assert isinstance(data["total"], int)

    def test_hr_allowed(self, hr_tok):
        r = requests.get(f"{BASE_URL}/api/kiosk/activity", headers=_headers(hr_tok), timeout=15)
        assert r.status_code == 200, r.text

    def test_manager_forbidden(self, manager_tok):
        r = requests.get(f"{BASE_URL}/api/kiosk/activity", headers=_headers(manager_tok), timeout=15)
        assert r.status_code == 403

    def test_employee_forbidden(self, emp_tok):
        r = requests.get(f"{BASE_URL}/api/kiosk/activity", headers=_headers(emp_tok), timeout=15)
        assert r.status_code == 403

    def test_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/kiosk/activity", timeout=15)
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 3. Limit query validation
# ---------------------------------------------------------------------------

class TestKioskActivityLimit:

    def test_limit_1(self, admin_tok):
        r = requests.get(f"{BASE_URL}/api/kiosk/activity?limit=1", headers=_headers(admin_tok), timeout=15)
        assert r.status_code == 200
        assert len(r.json()["events"]) <= 1

    def test_limit_100(self, admin_tok):
        r = requests.get(f"{BASE_URL}/api/kiosk/activity?limit=100", headers=_headers(admin_tok), timeout=15)
        assert r.status_code == 200

    def test_limit_101_422(self, admin_tok):
        r = requests.get(f"{BASE_URL}/api/kiosk/activity?limit=101", headers=_headers(admin_tok), timeout=15)
        assert r.status_code == 422

    def test_limit_0_422(self, admin_tok):
        r = requests.get(f"{BASE_URL}/api/kiosk/activity?limit=0", headers=_headers(admin_tok), timeout=15)
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# 4. End-to-end: kiosk check-in + check-out → visible in /activity
# ---------------------------------------------------------------------------

class TestKioskWriteThenRead:

    def _fresh_kiosk_token(self, admin_tok, company_id):
        requests.patch(f"{BASE_URL}/api/companies/{company_id}", headers=_headers(admin_tok),
                       json={"kiosk_enabled": True}, timeout=15)
        r = requests.post(f"{BASE_URL}/api/companies/{company_id}/kiosk-token/rotate",
                          headers=_headers(admin_tok), timeout=15)
        assert r.status_code == 200
        return r.json()["kiosk_token"]

    def _create_temp_employee(self, admin_tok):
        rand = str(uuid.uuid4())[:8]
        create = requests.post(f"{BASE_URL}/api/employees", headers=_headers(admin_tok), json={
            "name": f"TEST_kaudit_{rand}",
            "email": f"test_kaudit_{rand}@acme.com",
            "department": "QA",
            "designation": "Tester",
            "role": "employee",
        }, timeout=15)
        assert create.status_code == 200, create.text
        return create.json()

    def _enroll_face(self, admin_tok, employee_id):
        base = [0.42 + 0.0007 * i for i in range(128)]
        r = requests.post(f"{BASE_URL}/api/employees/{employee_id}/face",
                          headers=_headers(admin_tok), json={"embeddings": [base, base, base]}, timeout=15)
        assert r.status_code == 200, r.text

    def test_end_to_end_kiosk_flow(self, admin_tok, company_id):
        kiosk_token = self._fresh_kiosk_token(admin_tok, company_id)
        emp = self._create_temp_employee(admin_tok)
        emp_id = emp["id"]
        emp_uid = emp["user_id"]

        try:
            # optional: enroll face (activity feed doesn't require it, but iter spec asks for it)
            self._enroll_face(admin_tok, emp_id)

            # check-in
            r_in = requests.post(f"{BASE_URL}/api/kiosk/check-in", json={
                "token": kiosk_token, "employee_id": emp_id,
            }, timeout=15)
            assert r_in.status_code == 200, r_in.text
            assert r_in.json()["via"] == "kiosk"

            # small delay so check_in timestamp < check_out timestamp
            time.sleep(1.2)

            # check-out
            r_out = requests.post(f"{BASE_URL}/api/kiosk/check-out", json={
                "token": kiosk_token, "employee_id": emp_id,
            }, timeout=15)
            assert r_out.status_code == 200, r_out.text
            assert r_out.json()["via"] == "kiosk"

            # small delay for consistency
            time.sleep(0.5)

            # activity feed contains BOTH events for this user
            r_act = requests.get(f"{BASE_URL}/api/kiosk/activity?limit=100",
                                 headers=_headers(admin_tok), timeout=15)
            assert r_act.status_code == 200
            events = r_act.json()["events"]
            mine = [e for e in events if e.get("employee_user_id") == emp_uid]
            actions = {e["action"] for e in mine}
            assert "check_in" in actions, f"check_in event missing. mine={mine}"
            assert "check_out" in actions, f"check_out event missing. mine={mine}"

            # Response fields
            for e in mine:
                assert "employee_user_id" in e
                assert "employee_name" in e
                assert "avatar_url" in e  # may be None
                assert "date" in e
                assert "is_late" in e
                assert "shift_start_time" in e
                assert e["action"] in ("check_in", "check_out")
                assert isinstance(e["at"], str) and len(e["at"]) > 10

            # Sorted DESC by at
            ats = [e["at"] for e in events]
            assert ats == sorted(ats, reverse=True), "events should be sorted by at DESC"

            # Newest at the top corresponds to our recent write
            top_uids = [events[i].get("employee_user_id") for i in range(min(2, len(events)))]
            assert emp_uid in top_uids, (
                f"our just-written events should be at the top. top2={top_uids}"
            )

        finally:
            # cleanup: delete temp employee
            requests.delete(f"{BASE_URL}/api/employees/{emp_id}", headers=_headers(admin_tok), timeout=15)


# ---------------------------------------------------------------------------
# 5. Multi-tenant isolation
# ---------------------------------------------------------------------------

class TestKioskActivityTenantIsolation:
    """A super_admin only sees rows for their own company_id.

    We only have Acme in the seed set, so a positive isolation test requires
    creating a second company + admin. Since public /api/auth/register requires
    super_admin (same company), we can't spin up an isolated tenant cleanly.
    Instead, we verify the query filter statically by asserting every event
    returned belongs to the current admin's company via /companies/mine and
    a spot-check that no employee_user_id belongs to a foreign company.
    """

    def test_events_belong_to_admin_company(self, admin_tok):
        r = requests.get(f"{BASE_URL}/api/kiosk/activity?limit=100",
                         headers=_headers(admin_tok), timeout=15)
        assert r.status_code == 200
        events = r.json()["events"]
        if not events:
            pytest.skip("No kiosk events in acme tenant to verify isolation against")

        # All employee_user_ids should map to employees in the same company
        r_emp = requests.get(f"{BASE_URL}/api/employees", headers=_headers(admin_tok), timeout=15)
        assert r_emp.status_code == 200
        acme_user_ids = {e["user_id"] for e in r_emp.json()}
        # Every event's user must resolve inside acme
        for e in events:
            assert e["employee_user_id"] in acme_user_ids, (
                f"activity leaked user {e['employee_user_id']} not in current tenant"
            )


# ---------------------------------------------------------------------------
# 6. Regression — iteration 12 shift override PATCH still works
# ---------------------------------------------------------------------------

class TestIter12RegressionShiftOverride:

    def test_patch_shift_override_persists(self, admin_tok, maya_employee_id):
        r = requests.patch(f"{BASE_URL}/api/employees/{maya_employee_id}",
                           headers=_headers(admin_tok),
                           json={"shift_start_time": "10:45", "late_grace_minutes": 12},
                           timeout=15)
        assert r.status_code == 200, r.text

        # Re-fetch
        emps = requests.get(f"{BASE_URL}/api/employees", headers=_headers(admin_tok), timeout=15).json()
        maya = next(e for e in emps if e["id"] == maya_employee_id)
        assert maya.get("shift_start_time") == "10:45"
        assert maya.get("late_grace_minutes") == 12

        # cleanup — restore
        requests.patch(f"{BASE_URL}/api/employees/{maya_employee_id}",
                       headers=_headers(admin_tok),
                       json={"shift_start_time": "09:30", "late_grace_minutes": 15},
                       timeout=15)
