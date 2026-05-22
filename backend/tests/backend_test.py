"""
Comprehensive HRMIS backend API tests.
Covers auth, dashboards, employees, departments, attendance, leave, WFH,
meetings, chat, announcements, notifications.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://workforce-central-43.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@acme.com", "password": "Admin@123"}
EMP = {"email": "maya@acme.com", "password": "Demo@123"}
EMP2 = {"email": "diego@acme.com", "password": "Demo@123"}


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def emp_token():
    r = requests.post(f"{API}/auth/login", json=EMP, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def emp2_token():
    r = requests.post(f"{API}/auth/login", json=EMP2, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def auth_h(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- Auth ----------
class TestAuth:
    def test_admin_login(self):
        r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "token" in data and "user" in data
        assert data["user"]["email"] == ADMIN["email"]
        assert data["user"]["role"] == "super_admin"

    def test_employee_login(self):
        r = requests.post(f"{API}/auth/login", json=EMP, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["role"] == "employee"

    def test_login_wrong_password(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN["email"], "password": "wrong"}, timeout=15)
        assert r.status_code == 401

    def test_me(self, admin_token):
        r = requests.get(f"{API}/auth/me", headers=auth_h(admin_token), timeout=15)
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN["email"]

    def test_me_no_token(self):
        r = requests.get(f"{API}/auth/me", timeout=15)
        assert r.status_code in (401, 403)


# ---------- Dashboards ----------
class TestDashboards:
    def test_admin_dashboard(self, admin_token):
        r = requests.get(f"{API}/dashboard/admin", headers=auth_h(admin_token), timeout=15)
        assert r.status_code == 200
        data = r.json()
        for k in ["kpi", "trend_7d", "department_counts", "pending_leaves", "pending_wfhs"]:
            assert k in data, f"missing key {k}"

    def test_admin_dashboard_forbidden_for_employee(self, emp_token):
        r = requests.get(f"{API}/dashboard/admin", headers=auth_h(emp_token), timeout=15)
        assert r.status_code == 403

    def test_employee_dashboard(self, emp_token):
        r = requests.get(f"{API}/dashboard/employee", headers=auth_h(emp_token), timeout=15)
        assert r.status_code == 200
        data = r.json()
        for k in ["today_attendance", "balances", "upcoming_meetings", "announcements"]:
            assert k in data, f"missing key {k}"


# ---------- Employees & Departments ----------
class TestEmployees:
    def test_list_employees(self, admin_token):
        r = requests.get(f"{API}/employees", headers=auth_h(admin_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) > 0

    def test_employees_me(self, emp_token):
        r = requests.get(f"{API}/employees/me", headers=auth_h(emp_token), timeout=15)
        assert r.status_code == 200
        assert r.json()["email"] == EMP["email"]

    def test_create_employee_admin(self, admin_token):
        suffix = uuid.uuid4().hex[:6]
        payload = {
            "email": f"test_{suffix}@acme.com",
            "name": f"TEST User {suffix}",
            "password": "Demo@123",
            "role": "employee",
            "department": "Engineering",
            "designation": "Tester",
        }
        r = requests.post(f"{API}/employees", json=payload, headers=auth_h(admin_token), timeout=15)
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body.get("email") == payload["email"]


class TestDepartments:
    def test_list_departments(self, admin_token):
        r = requests.get(f"{API}/departments", headers=auth_h(admin_token), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            # headcount expected
            assert any("headcount" in d or "head_count" in d for d in data)

    def test_create_department(self, admin_token):
        name = f"TEST_Dept_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/departments", json={"name": name}, headers=auth_h(admin_token), timeout=15)
        assert r.status_code in (200, 201), r.text


# ---------- Attendance ----------
class TestAttendance:
    def test_attendance_flow(self, emp2_token):
        # Use emp2 so check-in/out doesn't conflict with other tests using emp
        # Try check-in (may return 400 if already checked-in today)
        r = requests.post(f"{API}/attendance/check-in", headers=auth_h(emp2_token), timeout=15)
        assert r.status_code in (200, 201, 400), r.text

        # GET today should now return a record
        r = requests.get(f"{API}/attendance/today", headers=auth_h(emp2_token), timeout=15)
        assert r.status_code == 200, r.text
        today = r.json()
        assert today is not None

        # Second check-in must fail
        r2 = requests.post(f"{API}/attendance/check-in", headers=auth_h(emp2_token), timeout=15)
        assert r2.status_code == 400

    def test_status_update(self, emp2_token):
        r = requests.post(f"{API}/attendance/status", json={"status": "available"}, headers=auth_h(emp2_token), timeout=15)
        assert r.status_code in (200, 201), r.text

    def test_monitor_admin(self, admin_token):
        r = requests.get(f"{API}/attendance/monitor", headers=auth_h(admin_token), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "rows" in data and isinstance(data["rows"], list)


# ---------- Leave ----------
class TestLeave:
    def test_balances(self, emp_token):
        r = requests.get(f"{API}/leave/balances", headers=auth_h(emp_token), timeout=15)
        assert r.status_code == 200
        balances = r.json()
        # Expect 4 types
        assert isinstance(balances, list)
        assert len(balances) >= 4

    def test_apply_approve_flow(self, emp_token, admin_token):
        start = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
        payload = {"leave_type": "Casual", "start_date": start, "end_date": end, "reason": "TEST leave"}
        r = requests.post(f"{API}/leave/apply", json=payload, headers=auth_h(emp_token), timeout=15)
        assert r.status_code in (200, 201), r.text
        leave_id = r.json().get("id") or r.json().get("_id")
        assert leave_id

        # Approve via admin
        r2 = requests.post(f"{API}/leave/{leave_id}/approve", json={"note": "ok"}, headers=auth_h(admin_token), timeout=15)
        assert r2.status_code in (200, 201), r2.text

    def test_apply_reject_flow(self, emp_token, admin_token):
        start = (datetime.now(timezone.utc) + timedelta(days=60)).date().isoformat()
        payload = {"leave_type": "Sick", "start_date": start, "end_date": start, "reason": "TEST reject"}
        r = requests.post(f"{API}/leave/apply", json=payload, headers=auth_h(emp_token), timeout=15)
        assert r.status_code in (200, 201)
        leave_id = r.json().get("id") or r.json().get("_id")
        r2 = requests.post(f"{API}/leave/{leave_id}/reject", json={"note": "no"}, headers=auth_h(admin_token), timeout=15)
        assert r2.status_code in (200, 201)


# ---------- WFH ----------
class TestWFH:
    def test_wfh_flow(self, emp_token, admin_token):
        # use a far-future date to avoid collision with prior tests
        import random
        offset = random.randint(100, 300)
        start = (datetime.now(timezone.utc) + timedelta(days=offset)).date().isoformat()
        payload = {"date": start, "reason": "TEST wfh"}
        r = requests.post(f"{API}/wfh/apply", json=payload, headers=auth_h(emp_token), timeout=15)
        assert r.status_code in (200, 201), r.text
        wfh_id = r.json().get("id") or r.json().get("_id")
        assert wfh_id
        r2 = requests.post(f"{API}/wfh/{wfh_id}/approve", json={"note": "ok"}, headers=auth_h(admin_token), timeout=15)
        assert r2.status_code in (200, 201), r2.text

    def test_wfh_today(self, admin_token):
        r = requests.get(f"{API}/wfh/today", headers=auth_h(admin_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------- Meetings ----------
class TestMeetings:
    def test_create_list_cancel(self, emp_token, emp2_token):
        # Need attendee id - fetch via /employees/me of emp2
        r = requests.get(f"{API}/employees/me", headers=auth_h(emp2_token), timeout=15)
        emp2_id = r.json()["id"]

        start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat()
        payload = {
            "title": "TEST meeting",
            "starts_at": start,
            "ends_at": end,
            "attendee_user_ids": [emp2_id],
            "description": "TEST",
        }
        r = requests.post(f"{API}/meetings", json=payload, headers=auth_h(emp_token), timeout=20)
        assert r.status_code in (200, 201), r.text
        mid = r.json().get("id") or r.json().get("_id")
        assert mid

        r2 = requests.get(f"{API}/meetings", headers=auth_h(emp_token), timeout=15)
        assert r2.status_code == 200
        assert isinstance(r2.json(), list)

        r3 = requests.delete(f"{API}/meetings/{mid}", headers=auth_h(emp_token), timeout=15)
        assert r3.status_code in (200, 204)


# ---------- Chat ----------
class TestChat:
    def test_contacts(self, emp_token):
        r = requests.get(f"{API}/chat/contacts", headers=auth_h(emp_token), timeout=15)
        assert r.status_code == 200
        contacts = r.json()
        assert isinstance(contacts, list)
        # self should not be in list
        emails = [c.get("email") for c in contacts]
        assert EMP["email"] not in emails

    def test_send_and_receive(self, emp_token, emp2_token):
        r = requests.get(f"{API}/employees/me", headers=auth_h(emp2_token), timeout=15)
        other_id = r.json()["id"]

        msg = f"TEST_{uuid.uuid4().hex[:6]}"
        r2 = requests.post(
            f"{API}/chat/send",
            json={"to_user_id": other_id, "body": msg},
            headers=auth_h(emp_token),
            timeout=15,
        )
        assert r2.status_code in (200, 201), r2.text

        r3 = requests.get(f"{API}/chat/messages/{other_id}", headers=auth_h(emp_token), timeout=15)
        assert r3.status_code == 200
        messages = r3.json()
        assert any(msg in m.get("body", "") for m in messages)


# ---------- Announcements ----------
class TestAnnouncements:
    def test_create_and_list(self, admin_token, emp_token):
        title = f"TEST_ann_{uuid.uuid4().hex[:6]}"
        r = requests.post(
            f"{API}/announcements",
            json={"title": title, "body": "TEST announcement body", "audience": "all"},
            headers=auth_h(admin_token),
            timeout=15,
        )
        assert r.status_code in (200, 201), r.text

        r2 = requests.get(f"{API}/announcements", headers=auth_h(emp_token), timeout=15)
        assert r2.status_code == 200
        assert any(a.get("title") == title for a in r2.json())


# ---------- Notifications ----------
class TestNotifications:
    def test_list_and_read_all(self, emp_token):
        r = requests.get(f"{API}/notifications", headers=auth_h(emp_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

        r2 = requests.post(f"{API}/notifications/read-all", headers=auth_h(emp_token), timeout=15)
        assert r2.status_code in (200, 201, 204)
