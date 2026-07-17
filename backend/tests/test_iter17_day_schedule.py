"""
Iteration 17 — Meeting rooms day-schedule (availability grid).

Covers:
- GET /api/rooms/day-schedule?date=YYYY-MM-DD → {date, rooms:[{...room, bookings:[]}]}
- Any authenticated role (employee/manager/hr/super_admin) can access — no 403
- Invalid date format → 400 'date must be YYYY-MM-DD'
- Only bookings for that day are returned; status!=cancelled AND approval_status!=rejected
- Bookings sorted by starts_at
- Bookings spanning midnight / partly outside the day still appear (overlap window)
- A deactivated room is NOT in day-schedule but its historic bookings are still fetched via /api/rooms/{id}/bookings
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

CREDS = {
    "super_admin": ("admin@acme.com", "Admin@123"),
    "hr":          ("jordan@acme.com", "Demo@123"),
    "manager":     ("alex@acme.com", "Demo@123"),
    "employee":    ("maya@acme.com", "Demo@123"),
}


def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def tokens() -> dict:
    return {role: _login(*c) for role, c in CREDS.items()}


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _rooms(tok: str) -> list:
    return requests.get(f"{BASE_URL}/api/rooms", headers=_h(tok), timeout=15).json()


# ─────────────────────────── Basic shape & RBAC ───────────────────────────

class TestDayScheduleShapeAndRBAC:
    def test_missing_date_query_param_400_or_422(self, tokens):
        r = requests.get(
            f"{BASE_URL}/api/rooms/day-schedule",
            headers=_h(tokens["employee"]),
            timeout=15,
        )
        assert r.status_code in (400, 422), r.text

    def test_invalid_date_format_400(self, tokens):
        r = requests.get(
            f"{BASE_URL}/api/rooms/day-schedule",
            headers=_h(tokens["employee"]),
            params={"date": "not-a-date"},
            timeout=15,
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", "")
        assert "YYYY-MM-DD" in detail or "date" in detail.lower()

    def test_response_shape_super_admin(self, tokens):
        target = "2026-08-01"
        r = requests.get(
            f"{BASE_URL}/api/rooms/day-schedule",
            headers=_h(tokens["super_admin"]),
            params={"date": target},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["date"] == target
        assert isinstance(data["rooms"], list)
        assert len(data["rooms"]) >= 2, "expected at least the 2 seeded rooms"
        room = data["rooms"][0]
        # Room fields present
        for key in ("id", "name", "capacity", "features", "active", "bookings"):
            assert key in room, f"missing {key} in room object"
        assert room["active"] is True
        assert isinstance(room["bookings"], list)

    def test_employee_can_access(self, tokens):
        r = requests.get(
            f"{BASE_URL}/api/rooms/day-schedule",
            headers=_h(tokens["employee"]),
            params={"date": "2026-08-01"},
            timeout=15,
        )
        assert r.status_code == 200
        assert "rooms" in r.json()

    def test_manager_can_access(self, tokens):
        r = requests.get(
            f"{BASE_URL}/api/rooms/day-schedule",
            headers=_h(tokens["manager"]),
            params={"date": "2026-08-01"},
            timeout=15,
        )
        assert r.status_code == 200

    def test_hr_can_access(self, tokens):
        r = requests.get(
            f"{BASE_URL}/api/rooms/day-schedule",
            headers=_h(tokens["hr"]),
            params={"date": "2026-08-01"},
            timeout=15,
        )
        assert r.status_code == 200

    def test_no_auth_401(self, tokens):  # tokens fixture only used to ensure warm-up
        r = requests.get(
            f"{BASE_URL}/api/rooms/day-schedule",
            params={"date": "2026-08-01"},
            timeout=15,
        )
        assert r.status_code in (401, 403), r.text


# ─────────────────────────── Bookings inclusion / filtering ───────────────────────────

def _future_day_date(days_from_today: int) -> str:
    d = datetime.now(timezone.utc).date() + timedelta(days=days_from_today)
    return d.isoformat()


class TestBookingsForDay:
    """Create meetings for a specific day, verify they appear (sorted) in day-schedule."""

    def _mk_meeting(self, tok: str, room_id: str, s: datetime, e: datetime, title_prefix: str = "TEST_ds"):
        payload = {
            "title": f"{title_prefix}_{uuid.uuid4().hex[:6]}",
            "starts_at": _iso(s),
            "ends_at": _iso(e),
            "room_id": room_id,
            "attendee_user_ids": [],
        }
        r = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tok), json=payload, timeout=15)
        return r

    def test_bookings_appear_sorted_and_only_for_that_day(self, tokens):
        rooms = _rooms(tokens["super_admin"])
        room_a = next(r for r in rooms if r["name"] == "Conference Room A")

        # Pick a specific future day far away to isolate from other tests
        target_date = _future_day_date(45)  # 45 days from now
        # Two 30-min slots on the target day; one earlier, one later
        day_dt = datetime.fromisoformat(target_date).replace(tzinfo=timezone.utc)
        later_s  = day_dt.replace(hour=14, minute=0)
        later_e  = later_s + timedelta(minutes=30)
        earlier_s = day_dt.replace(hour=10, minute=0)
        earlier_e = earlier_s + timedelta(minutes=30)

        # Insert LATER first to test that the endpoint sorts by starts_at
        r_late = self._mk_meeting(tokens["super_admin"], room_a["id"], later_s, later_e, "TEST_ds_late")
        assert r_late.status_code == 200, r_late.text
        r_early = self._mk_meeting(tokens["super_admin"], room_a["id"], earlier_s, earlier_e, "TEST_ds_early")
        assert r_early.status_code == 200, r_early.text
        late_id  = r_late.json()["id"]
        early_id = r_early.json()["id"]

        try:
            r = requests.get(
                f"{BASE_URL}/api/rooms/day-schedule",
                headers=_h(tokens["super_admin"]),
                params={"date": target_date},
                timeout=15,
            )
            assert r.status_code == 200
            data = r.json()
            assert data["date"] == target_date
            room = next(rm for rm in data["rooms"] if rm["id"] == room_a["id"])
            b_ids = [b["id"] for b in room["bookings"]]
            assert early_id in b_ids
            assert late_id in b_ids
            # sorted ascending by starts_at
            ea_idx = b_ids.index(early_id)
            la_idx = b_ids.index(late_id)
            assert ea_idx < la_idx, f"bookings not sorted: {b_ids}"

            # Fields on booking objects
            b = next(x for x in room["bookings"] if x["id"] == early_id)
            for k in ("id", "title", "starts_at", "ends_at", "approval_status", "room_id"):
                assert k in b, f"booking missing field {k}"

            # A different day should NOT include them
            other_day = _future_day_date(46)
            r2 = requests.get(
                f"{BASE_URL}/api/rooms/day-schedule",
                headers=_h(tokens["super_admin"]),
                params={"date": other_day},
                timeout=15,
            )
            other_room = next(rm for rm in r2.json()["rooms"] if rm["id"] == room_a["id"])
            assert early_id not in [b["id"] for b in other_room["bookings"]]
            assert late_id not in [b["id"] for b in other_room["bookings"]]
        finally:
            requests.delete(f"{BASE_URL}/api/meetings/{early_id}", headers=_h(tokens["super_admin"]), timeout=15)
            requests.delete(f"{BASE_URL}/api/meetings/{late_id}", headers=_h(tokens["super_admin"]), timeout=15)

    def test_cancelled_meeting_excluded(self, tokens):
        rooms = _rooms(tokens["super_admin"])
        room_a = next(r for r in rooms if r["name"] == "Conference Room A")
        target_date = _future_day_date(60)
        day_dt = datetime.fromisoformat(target_date).replace(tzinfo=timezone.utc)
        s = day_dt.replace(hour=11, minute=0)
        e = s + timedelta(minutes=30)
        r = self._mk_meeting(tokens["super_admin"], room_a["id"], s, e, "TEST_ds_cancel")
        assert r.status_code == 200
        mid = r.json()["id"]

        # cancel it
        d = requests.delete(f"{BASE_URL}/api/meetings/{mid}", headers=_h(tokens["super_admin"]), timeout=15)
        assert d.status_code in (200, 204)

        ds = requests.get(
            f"{BASE_URL}/api/rooms/day-schedule",
            headers=_h(tokens["super_admin"]),
            params={"date": target_date},
            timeout=15,
        ).json()
        room = next(rm for rm in ds["rooms"] if rm["id"] == room_a["id"])
        assert mid not in [b["id"] for b in room["bookings"]], "cancelled meeting must not appear"

    def test_rejected_meeting_excluded(self, tokens):
        rooms = _rooms(tokens["super_admin"])
        room_b = next(r for r in rooms if r["name"] == "Conference Room B")
        target_date = _future_day_date(75)
        day_dt = datetime.fromisoformat(target_date).replace(tzinfo=timezone.utc)
        s = day_dt.replace(hour=9, minute=0)
        e = s + timedelta(minutes=180)  # 3h — needs approval by employee

        payload = {
            "title": f"TEST_ds_rej_{uuid.uuid4().hex[:6]}",
            "starts_at": _iso(s), "ends_at": _iso(e),
            "room_id": room_b["id"], "attendee_user_ids": [],
        }
        r = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["employee"]), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        assert r.json()["approval_status"] == "pending"

        # HR rejects it
        rej = requests.post(
            f"{BASE_URL}/api/meetings/{mid}/reject",
            headers=_h(tokens["hr"]), json={"note": "no"}, timeout=15,
        )
        assert rej.status_code == 200, rej.text

        ds = requests.get(
            f"{BASE_URL}/api/rooms/day-schedule",
            headers=_h(tokens["employee"]),
            params={"date": target_date},
            timeout=15,
        ).json()
        room = next(rm for rm in ds["rooms"] if rm["id"] == room_b["id"])
        assert mid not in [b["id"] for b in room["bookings"]], "rejected meeting must not appear"

    def test_pending_meeting_included(self, tokens):
        rooms = _rooms(tokens["super_admin"])
        room_b = next(r for r in rooms if r["name"] == "Conference Room B")
        target_date = _future_day_date(90)
        day_dt = datetime.fromisoformat(target_date).replace(tzinfo=timezone.utc)
        s = day_dt.replace(hour=13, minute=0)
        e = s + timedelta(minutes=180)  # 3h needs approval

        payload = {
            "title": f"TEST_ds_pending_{uuid.uuid4().hex[:6]}",
            "starts_at": _iso(s), "ends_at": _iso(e),
            "room_id": room_b["id"], "attendee_user_ids": [],
        }
        r = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["employee"]), json=payload, timeout=15)
        assert r.status_code == 200
        mid = r.json()["id"]
        assert r.json()["approval_status"] == "pending"

        try:
            ds = requests.get(
                f"{BASE_URL}/api/rooms/day-schedule",
                headers=_h(tokens["employee"]),
                params={"date": target_date},
                timeout=15,
            ).json()
            room = next(rm for rm in ds["rooms"] if rm["id"] == room_b["id"])
            b = next((x for x in room["bookings"] if x["id"] == mid), None)
            assert b is not None, "pending meeting should still appear on the grid"
            assert b["approval_status"] == "pending"
        finally:
            requests.delete(f"{BASE_URL}/api/meetings/{mid}", headers=_h(tokens["hr"]), timeout=15)


# ─────────────────────────── Overlap / midnight bookings ───────────────────────────

class TestOverlap:
    def test_meeting_spanning_midnight_appears_on_both_days(self, tokens):
        """Create a meeting starting on day X 23:00 and ending on day X+1 01:00.

        Both days should return this booking (overlap).
        """
        rooms = _rooms(tokens["super_admin"])
        room_a = next(r for r in rooms if r["name"] == "Conference Room A")
        d1 = datetime.now(timezone.utc).date() + timedelta(days=110)
        d2 = d1 + timedelta(days=1)
        s = datetime.combine(d1, datetime.min.time(), tzinfo=timezone.utc).replace(hour=23, minute=0)
        e = datetime.combine(d2, datetime.min.time(), tzinfo=timezone.utc).replace(hour=1, minute=0)

        payload = {
            "title": f"TEST_ds_mid_{uuid.uuid4().hex[:6]}",
            "starts_at": _iso(s), "ends_at": _iso(e),
            "room_id": room_a["id"], "attendee_user_ids": [],
        }
        # 120 minutes — auto-approved for employee
        r = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["super_admin"]), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        mid = r.json()["id"]

        try:
            for target in (d1.isoformat(), d2.isoformat()):
                ds = requests.get(
                    f"{BASE_URL}/api/rooms/day-schedule",
                    headers=_h(tokens["super_admin"]),
                    params={"date": target},
                    timeout=15,
                ).json()
                room = next(rm for rm in ds["rooms"] if rm["id"] == room_a["id"])
                b_ids = [b["id"] for b in room["bookings"]]
                assert mid in b_ids, f"midnight-spanning meeting missing on day {target}: {b_ids}"
        finally:
            requests.delete(f"{BASE_URL}/api/meetings/{mid}", headers=_h(tokens["super_admin"]), timeout=15)


# ─────────────────────────── Deactivated rooms ───────────────────────────

class TestDeactivatedRoom:
    def test_deactivated_room_hidden_from_day_schedule_but_historic_bookings_via_id(self, tokens):
        # 1. HR creates a temporary room
        name = f"TEST_ds_inact_{uuid.uuid4().hex[:6]}"
        c = requests.post(
            f"{BASE_URL}/api/rooms",
            headers=_h(tokens["hr"]),
            json={"name": name, "capacity": 4, "features": ["tv"]},
            timeout=15,
        )
        assert c.status_code == 200
        rid = c.json()["id"]

        # 2. Book a meeting in that room on a specific target date
        target_date = _future_day_date(125)
        day_dt = datetime.fromisoformat(target_date).replace(tzinfo=timezone.utc)
        s = day_dt.replace(hour=15, minute=0)
        e = s + timedelta(minutes=30)
        payload = {
            "title": f"TEST_ds_hist_{uuid.uuid4().hex[:6]}",
            "starts_at": _iso(s), "ends_at": _iso(e),
            "room_id": rid, "attendee_user_ids": [],
        }
        mr = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["super_admin"]), json=payload, timeout=15)
        assert mr.status_code == 200, mr.text
        mid = mr.json()["id"]

        try:
            # 3. Deactivate room
            d = requests.delete(f"{BASE_URL}/api/rooms/{rid}", headers=_h(tokens["hr"]), timeout=15)
            assert d.status_code == 200

            # 4. day-schedule must NOT include the deactivated room
            ds = requests.get(
                f"{BASE_URL}/api/rooms/day-schedule",
                headers=_h(tokens["super_admin"]),
                params={"date": target_date},
                timeout=15,
            ).json()
            assert not any(rm["id"] == rid for rm in ds["rooms"]), "deactivated room should not be in day-schedule"

            # 5. But historic bookings ARE still fetched via /rooms/{id}/bookings
            start_win = f"{target_date}T00:00:00+00:00"
            end_win = f"{target_date}T23:59:59+00:00"
            hist = requests.get(
                f"{BASE_URL}/api/rooms/{rid}/bookings",
                headers=_h(tokens["super_admin"]),
                params={"start": start_win, "end": end_win},
                timeout=15,
            )
            assert hist.status_code == 200, hist.text
            b_ids = [b["id"] for b in hist.json()]
            assert mid in b_ids, "historic booking should still be retrievable by room id"
        finally:
            requests.delete(f"{BASE_URL}/api/meetings/{mid}", headers=_h(tokens["super_admin"]), timeout=15)
