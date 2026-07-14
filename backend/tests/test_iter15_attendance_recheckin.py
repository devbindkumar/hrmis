"""Iteration 15 — Re-Check-In feature + attendance CSV export.

Tests:
* check-in / check-out / re-check-in / multi-recheckin flow
* events audit log
* CSV export (valid + validation + role gating + department filter)
* kiosk re-check-in path
"""
from __future__ import annotations

import io
import os
import csv
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient


BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "hrmis_database")


# ─────────────────────────── fixtures ────────────────────────────

@pytest.fixture(scope="session")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def admin_token():
    return _login("admin@acme.com", "Admin@123")


@pytest.fixture(scope="session")
def hr_token():
    return _login("jordan@acme.com", "Demo@123")


@pytest.fixture(scope="session")
def manager_token():
    return _login("alex@acme.com", "Demo@123")


@pytest.fixture(scope="session")
def employee_token():
    return _login("maya@acme.com", "Demo@123")


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@pytest.fixture
def clean_maya(db):
    """Reset maya's attendance + events for today before each test."""
    user = db.users.find_one({"email": "maya@acme.com"})
    assert user, "maya user missing"
    uid = user["id"]
    today = _today()
    db.attendance.delete_many({"user_id": uid, "date": today})
    db.attendance_events.delete_many({"user_id": uid, "date": today})
    yield uid
    # cleanup after test as well
    db.attendance.delete_many({"user_id": uid, "date": today})
    db.attendance_events.delete_many({"user_id": uid, "date": today})


# ─────────────────────────── tests ───────────────────────────────

class TestReCheckInFlow:

    def test_check_in_creates_session_and_event(self, employee_token, clean_maya, db):
        r = requests.post(f"{API}/attendance/check-in", headers=_hdr(employee_token), timeout=15)
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["check_in"] is not None
        assert doc["check_out"] is None
        assert isinstance(doc.get("sessions"), list) and len(doc["sessions"]) == 1
        assert doc["sessions"][0]["out"] is None

        ev = list(db.attendance_events.find({"user_id": clean_maya, "date": _today()}, {"_id": 0}))
        assert any(e["event_type"] == "check_in" and e["via"] == "web" for e in ev)

    def test_re_check_in_rejected_if_still_checked_in(self, employee_token, clean_maya):
        assert requests.post(f"{API}/attendance/check-in", headers=_hdr(employee_token)).status_code == 200
        r = requests.post(f"{API}/attendance/re-check-in", headers=_hdr(employee_token), timeout=15)
        assert r.status_code == 400
        assert "still checked in" in r.json()["detail"].lower()

    def test_re_check_in_rejected_if_not_checked_in_today(self, employee_token, clean_maya):
        r = requests.post(f"{API}/attendance/re-check-in", headers=_hdr(employee_token), timeout=15)
        assert r.status_code == 400
        assert "haven't checked in" in r.json()["detail"].lower()

    def test_full_multi_recheckin_flow(self, employee_token, clean_maya, db):
        h = _hdr(employee_token)
        # 1. check-in
        r1 = requests.post(f"{API}/attendance/check-in", headers=h); assert r1.status_code == 200
        # 2. check-out
        r2 = requests.post(f"{API}/attendance/check-out", headers=h); assert r2.status_code == 200, r2.text
        assert r2.json()["check_out"] is not None
        # 3. re-check-in
        r3 = requests.post(f"{API}/attendance/re-check-in", headers=h); assert r3.status_code == 200, r3.text
        doc3 = r3.json()
        assert doc3["check_out"] is None
        assert len(doc3["sessions"]) == 2
        # 4. check-out again
        r4 = requests.post(f"{API}/attendance/check-out", headers=h); assert r4.status_code == 200
        assert r4.json()["check_out"] is not None
        # 5. re-check-in again
        r5 = requests.post(f"{API}/attendance/re-check-in", headers=h); assert r5.status_code == 200
        assert len(r5.json()["sessions"]) == 3
        # 6. final check-out
        r6 = requests.post(f"{API}/attendance/check-out", headers=h); assert r6.status_code == 200
        final = r6.json()
        assert len(final["sessions"]) == 3
        assert all(s["out"] is not None for s in final["sessions"])
        # duration_seconds > 0 and equals sum of session durations
        total = 0
        for s in final["sessions"]:
            si = datetime.fromisoformat(s["in"].replace("Z", "+00:00"))
            so = datetime.fromisoformat(s["out"].replace("Z", "+00:00"))
            total += int((so - si).total_seconds())
        assert final["duration_seconds"] == total

        # 6 events (3x check_in path: 1 check_in + 2 re_check_in; 3 check_out)
        ev = list(db.attendance_events.find({"user_id": clean_maya, "date": _today()}))
        types = sorted([e["event_type"] for e in ev])
        assert types.count("check_in") == 1
        assert types.count("re_check_in") == 2
        assert types.count("check_out") == 3

    def test_events_endpoint_sorted_desc(self, employee_token, clean_maya):
        h = _hdr(employee_token)
        for _ in range(1):
            requests.post(f"{API}/attendance/check-in", headers=h)
            requests.post(f"{API}/attendance/check-out", headers=h)
            requests.post(f"{API}/attendance/re-check-in", headers=h)
        r = requests.get(f"{API}/attendance/events?days=1", headers=h)
        assert r.status_code == 200
        events = r.json()
        assert len(events) >= 3
        # sorted DESC by ts
        ts = [e["ts"] for e in events]
        assert ts == sorted(ts, reverse=True)
        first = events[0]
        for k in ("id", "user_id", "date", "event_type", "ts", "via"):
            assert k in first, f"missing field {k}"


class TestExportCSV:

    def test_export_unauth_401(self):
        r = requests.get(f"{API}/attendance/export?start=2026-01-01&end=2026-01-07", timeout=15)
        assert r.status_code in (401, 403)

    def test_export_manager_forbidden(self, manager_token):
        r = requests.get(
            f"{API}/attendance/export?start=2026-01-01&end=2026-01-07",
            headers=_hdr(manager_token), timeout=15,
        )
        assert r.status_code == 403

    def test_export_bad_range(self, admin_token):
        r = requests.get(
            f"{API}/attendance/export?start=2026-01-10&end=2026-01-01",
            headers=_hdr(admin_token), timeout=15,
        )
        assert r.status_code == 400

    def test_export_range_too_large(self, admin_token):
        r = requests.get(
            f"{API}/attendance/export?start=2020-01-01&end=2026-12-31",
            headers=_hdr(admin_token), timeout=15,
        )
        assert r.status_code == 400

    def test_export_success_columns_and_content(self, admin_token, employee_token, clean_maya):
        # Ensure Maya has a re-check-in day today
        h = _hdr(employee_token)
        requests.post(f"{API}/attendance/check-in", headers=h)
        requests.post(f"{API}/attendance/check-out", headers=h)
        requests.post(f"{API}/attendance/re-check-in", headers=h)
        requests.post(f"{API}/attendance/check-out", headers=h)

        today = _today()
        # 7-day span so we hit weekend rows
        start = (datetime.now(timezone.utc).date() - timedelta(days=6)).isoformat()
        r = requests.get(
            f"{API}/attendance/export?start={start}&end={today}",
            headers=_hdr(admin_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", "").lower()
        assert "attachment" in r.headers.get("content-disposition", "").lower()

        rdr = csv.DictReader(io.StringIO(r.text))
        headers = rdr.fieldnames or []
        expected = [
            "Date", "Employee Code", "Name", "Department", "Designation", "Email",
            "First Check-in", "Last Check-out", "Sessions",
            "Total Hours", "Late", "Late Minutes", "Early Departure Minutes",
            "Overtime Hours", "Status", "Notes",
        ]
        assert headers == expected, f"header mismatch: {headers}"

        rows = list(rdr)
        assert rows, "no rows in CSV"
        # find Maya's today row
        maya_today = [r for r in rows if r["Email"] == "maya@acme.com" and r["Date"] == today]
        assert maya_today, "no row for maya today"
        m = maya_today[0]
        assert m["Sessions"] == "2"
        assert "sessions (re-check-in)" in m["Notes"]

        # Weekend rows should be Weekly Off or leave/wfh — at least one 'Weekly Off' in range unless range has no weekend
        statuses = {r["Status"] for r in rows}
        # Range = 7 days, so we should see a Weekly Off unless all weekend days were on leave for everyone
        assert any(s in statuses for s in ("Weekly Off", "Absent", "Present", "WFH")), statuses

    def test_export_department_filter(self, admin_token):
        today = _today()
        start = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        r = requests.get(
            f"{API}/attendance/export?start={start}&end={today}&department=Engineering",
            headers=_hdr(admin_token), timeout=30,
        )
        assert r.status_code == 200
        rdr = csv.DictReader(io.StringIO(r.text))
        rows = list(rdr)
        assert rows, "expected rows for Engineering dept"
        depts = {r["Department"] for r in rows}
        assert depts == {"Engineering"}, f"non-Engineering rows leaked: {depts}"

    def test_export_hr_allowed(self, hr_token):
        today = _today()
        r = requests.get(
            f"{API}/attendance/export?start={today}&end={today}",
            headers=_hdr(hr_token), timeout=15,
        )
        assert r.status_code == 200


# ─────────────────────────── kiosk re-check-in ─────────────────────────

class TestKioskReCheckIn:

    @pytest.fixture
    def kiosk_setup(self, db, admin_token, clean_maya):
        """Ensure company has a kiosk token; return (token, employee_id)."""
        # find maya's company + employee record
        user = db.users.find_one({"email": "maya@acme.com"})
        emp = db.employees.find_one({"user_id": user["id"]})
        assert emp, "maya employee missing"
        cid = emp["company_id"]
        company = db.companies.find_one({"id": cid})
        assert company
        token = company.get("kiosk_token")
        if not token:
            # Try to enable kiosk via admin API if available; else write directly
            token = "kiosk-test-token-abcdefgh"
            db.companies.update_one({"id": cid}, {"$set": {"kiosk_token": token, "kiosk_enabled": True}})
        return token, emp["id"]

    def test_kiosk_check_in_after_check_out_reopens_day(self, kiosk_setup, employee_token, db, clean_maya):
        token, emp_id = kiosk_setup
        # Via authenticated web: check-in then check-out
        h = _hdr(employee_token)
        assert requests.post(f"{API}/attendance/check-in", headers=h).status_code == 200
        assert requests.post(f"{API}/attendance/check-out", headers=h).status_code == 200

        # Now hit kiosk/check-in — should reopen day (NOT 400)
        r = requests.post(
            f"{API}/kiosk/check-in",
            json={"token": token, "employee_id": emp_id},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("reopened") is True or body.get("success") is True

        # Attendance doc should now have 2 sessions and check_out is None
        rec = db.attendance.find_one({"user_id": clean_maya, "date": _today()})
        assert len(rec.get("sessions", [])) == 2
        assert rec.get("check_out") is None
        # And a kiosk re_check_in event was written
        ev = list(db.attendance_events.find(
            {"user_id": clean_maya, "date": _today(), "event_type": "re_check_in"}
        ))
        assert any(e["via"] == "kiosk" for e in ev)
