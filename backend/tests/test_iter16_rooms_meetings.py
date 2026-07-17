"""
Iteration 16 — Meeting rooms + approval flow.

Covers:
- GET /api/rooms auto-seed & idempotency
- POST /api/rooms RBAC (super_admin/HR only; manager/employee 403); duplicate name; feature filtering
- PATCH /api/rooms/{id} rename / capacity / features / toggle active (RBAC)
- DELETE /api/rooms/{id} soft-delete lifecycle (default hides inactive; include_inactive shows)
- POST /api/rooms/check-conflict — available true/false
- POST /api/meetings 30-min → auto_approved; same slot same room → 409 with detail.message
- POST /api/meetings >120min or is_recurring by employee → pending; super_admin/HR auto-approve to 'approved'
- GET /api/meetings/pending-approval — RBAC (403 for manager/employee)
- POST /api/meetings/{id}/approve — moves to approved; 400 if already decided
- POST /api/meetings/{id}/reject — stores note; 400 if already decided
- Room from another company / inactive → 400 on meeting create
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


# ─────────────────────────── ROOMS ───────────────────────────

class TestRoomListingAndSeed:
    def test_get_rooms_auto_seed_two_default(self, tokens):
        r = requests.get(f"{BASE_URL}/api/rooms", headers=_h(tokens["super_admin"]), timeout=15)
        assert r.status_code == 200
        rooms = r.json()
        names = {x["name"] for x in rooms}
        assert "Conference Room A" in names, f"seed missing A. got: {names}"
        assert "Conference Room B" in names, f"seed missing B. got: {names}"
        # Feature keys returned
        room_a = next(x for x in rooms if x["name"] == "Conference Room A")
        assert room_a["capacity"] == 8
        assert isinstance(room_a["features"], list)
        assert "tv" in room_a["features"]
        assert room_a.get("location")

    def test_get_rooms_idempotent(self, tokens):
        """Calling GET /api/rooms twice must NOT double-seed."""
        r1 = requests.get(f"{BASE_URL}/api/rooms", headers=_h(tokens["super_admin"]), timeout=15).json()
        r2 = requests.get(f"{BASE_URL}/api/rooms", headers=_h(tokens["super_admin"]), timeout=15).json()
        assert len(r1) == len(r2)
        # At least 2 (the defaults). May have more test-created rooms.
        assert len(r1) >= 2

    def test_get_rooms_employee_can_list(self, tokens):
        r = requests.get(f"{BASE_URL}/api/rooms", headers=_h(tokens["employee"]), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestRoomCRUDRBAC:
    def test_manager_cannot_create_room(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/rooms",
            headers=_h(tokens["manager"]),
            json={"name": f"TEST_mgr_{uuid.uuid4().hex[:6]}", "capacity": 4, "features": ["tv"]},
            timeout=15,
        )
        assert r.status_code == 403

    def test_employee_cannot_create_room(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/rooms",
            headers=_h(tokens["employee"]),
            json={"name": f"TEST_emp_{uuid.uuid4().hex[:6]}", "capacity": 4},
            timeout=15,
        )
        assert r.status_code == 403

    def test_hr_can_create_and_super_admin_can_delete(self, tokens):
        name = f"TEST_room_{uuid.uuid4().hex[:6]}"
        # HR creates
        create = requests.post(
            f"{BASE_URL}/api/rooms",
            headers=_h(tokens["hr"]),
            json={
                "name": name, "capacity": 12,
                "features": ["tv", "whiteboard", "unknown_feat"],  # unknown filtered out
                "location": "3rd floor",
            },
            timeout=15,
        )
        assert create.status_code == 200, create.text
        room = create.json()
        assert room["name"] == name
        assert room["capacity"] == 12
        assert set(room["features"]) == {"tv", "whiteboard"}, room["features"]
        assert room["active"] is True
        room_id = room["id"]

        # Duplicate name → 400
        dup = requests.post(
            f"{BASE_URL}/api/rooms",
            headers=_h(tokens["hr"]),
            json={"name": name, "capacity": 2},
            timeout=15,
        )
        assert dup.status_code == 400

        # PATCH by super_admin
        patch = requests.patch(
            f"{BASE_URL}/api/rooms/{room_id}",
            headers=_h(tokens["super_admin"]),
            json={"capacity": 20, "features": ["projector", "wifi"], "location": "5th floor"},
            timeout=15,
        )
        assert patch.status_code == 200, patch.text
        updated = patch.json()
        assert updated["capacity"] == 20
        assert set(updated["features"]) == {"projector", "wifi"}
        assert updated["location"] == "5th floor"

        # Manager cannot PATCH
        bad_patch = requests.patch(
            f"{BASE_URL}/api/rooms/{room_id}",
            headers=_h(tokens["manager"]),
            json={"capacity": 1},
            timeout=15,
        )
        assert bad_patch.status_code == 403

        # DELETE (soft) by super_admin
        d = requests.delete(f"{BASE_URL}/api/rooms/{room_id}", headers=_h(tokens["super_admin"]), timeout=15)
        assert d.status_code == 200
        assert d.json().get("success") is True

        # GET /api/rooms should NOT include this room by default
        rooms = requests.get(f"{BASE_URL}/api/rooms", headers=_h(tokens["super_admin"]), timeout=15).json()
        assert not any(x["id"] == room_id for x in rooms), "soft-deleted room still visible"

        # include_inactive=true reveals it
        rooms_all = requests.get(
            f"{BASE_URL}/api/rooms",
            headers=_h(tokens["super_admin"]),
            params={"include_inactive": "true"},
            timeout=15,
        ).json()
        found = next((x for x in rooms_all if x["id"] == room_id), None)
        assert found and found["active"] is False, "include_inactive should show soft-deleted room"

    def test_employee_cannot_patch_or_delete(self, tokens):
        # find default Room A
        rooms = requests.get(f"{BASE_URL}/api/rooms", headers=_h(tokens["employee"]), timeout=15).json()
        rid = rooms[0]["id"]
        p = requests.patch(f"{BASE_URL}/api/rooms/{rid}", headers=_h(tokens["employee"]),
                           json={"capacity": 3}, timeout=15)
        assert p.status_code == 403
        d = requests.delete(f"{BASE_URL}/api/rooms/{rid}", headers=_h(tokens["employee"]), timeout=15)
        assert d.status_code == 403


# ─────────────────────────── CONFLICT + MEETING FLOWS ───────────────────────────

def _default_rooms(tok: str) -> list:
    return requests.get(f"{BASE_URL}/api/rooms", headers=_h(tok), timeout=15).json()


def _future_window(hour_offset: int, minutes: int = 30) -> tuple[str, str]:
    base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=7, hours=hour_offset)
    base = base.replace(minute=0, second=0)
    return _iso(base), _iso(base + timedelta(minutes=minutes))


class TestConflictCheck:
    def test_check_conflict_available(self, tokens):
        rooms = _default_rooms(tokens["employee"])
        room = next(r for r in rooms if r["name"] == "Conference Room A")
        s, e = _future_window(hour_offset=100 + int(uuid.uuid4().int % 50), minutes=30)
        r = requests.post(
            f"{BASE_URL}/api/rooms/check-conflict",
            headers=_h(tokens["employee"]),
            json={"room_id": room["id"], "starts_at": s, "ends_at": e},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["available"] is True
        assert data["conflict"] is None
        assert data["room"]["name"] == "Conference Room A"


class TestMeetingCreateAndConflict:
    def test_30min_auto_approved_and_409_on_second(self, tokens):
        rooms = _default_rooms(tokens["employee"])
        room_a = next(r for r in rooms if r["name"] == "Conference Room A")
        # Pick a slot far in the future to avoid other tests colliding
        offset = 200 + int(uuid.uuid4().int % 500)
        s, e = _future_window(hour_offset=offset, minutes=30)
        payload = {
            "title": f"TEST_iter16_short_{uuid.uuid4().hex[:6]}",
            "starts_at": s, "ends_at": e,
            "room_id": room_a["id"],
            "attendee_user_ids": [],
        }
        r1 = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["employee"]), json=payload, timeout=15)
        assert r1.status_code == 200, r1.text
        m1 = r1.json()
        assert m1["approval_status"] == "auto_approved"
        assert m1["room_name"] == "Conference Room A"
        assert m1["duration_minutes"] == 30

        # Same slot → 409 with message
        payload2 = {**payload, "title": f"TEST_iter16_dup_{uuid.uuid4().hex[:6]}"}
        r2 = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["employee"]), json=payload2, timeout=15)
        assert r2.status_code == 409, r2.text
        detail = r2.json().get("detail")
        # detail can be dict or wrapped in dict under 'detail'
        if isinstance(detail, dict):
            msg = detail.get("message", "")
        else:
            msg = str(detail)
        assert "Conference Room A" in msg or "already booked" in msg.lower(), msg

        # Cleanup: cancel m1
        requests.delete(f"{BASE_URL}/api/meetings/{m1['id']}", headers=_h(tokens["employee"]), timeout=15)

    def test_end_before_start_400(self, tokens):
        s, e = _future_window(hour_offset=800)
        payload = {"title": "TEST_bad_time", "starts_at": e, "ends_at": s}
        r = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["employee"]), json=payload, timeout=15)
        assert r.status_code == 400

    def test_invalid_room_id_400(self, tokens):
        s, e = _future_window(hour_offset=810)
        payload = {"title": "TEST_bad_room", "starts_at": s, "ends_at": e,
                   "room_id": "00000000-0000-0000-0000-000000000000"}
        r = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["employee"]), json=payload, timeout=15)
        assert r.status_code == 400

    def test_inactive_room_400(self, tokens):
        # Create a room, then deactivate it, then attempt to book → 400
        name = f"TEST_inact_{uuid.uuid4().hex[:6]}"
        c = requests.post(f"{BASE_URL}/api/rooms", headers=_h(tokens["hr"]),
                          json={"name": name, "capacity": 4, "features": ["tv"]}, timeout=15)
        assert c.status_code == 200
        rid = c.json()["id"]
        requests.delete(f"{BASE_URL}/api/rooms/{rid}", headers=_h(tokens["hr"]), timeout=15)

        s, e = _future_window(hour_offset=820)
        r = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["employee"]),
                          json={"title": "TEST_inact_book", "starts_at": s, "ends_at": e, "room_id": rid},
                          timeout=15)
        assert r.status_code == 400


class TestApprovalFlow:
    def test_recurring_by_employee_pending_then_approve(self, tokens):
        rooms = _default_rooms(tokens["employee"])
        room_b = next(r for r in rooms if r["name"] == "Conference Room B")
        offset = 900 + int(uuid.uuid4().int % 200)
        s, e = _future_window(hour_offset=offset, minutes=30)
        payload = {
            "title": f"TEST_recur_{uuid.uuid4().hex[:6]}",
            "starts_at": s, "ends_at": e,
            "room_id": room_b["id"],
            "is_recurring": True,
            "recurrence": {"frequency": "weekly", "count": 4},
            "attendee_user_ids": [],
        }
        r = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["employee"]), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["approval_status"] == "pending", m
        mid = m["id"]

        # Employee cannot see pending-approval endpoint
        emp = requests.get(f"{BASE_URL}/api/meetings/pending-approval", headers=_h(tokens["employee"]), timeout=15)
        assert emp.status_code == 403
        mgr = requests.get(f"{BASE_URL}/api/meetings/pending-approval", headers=_h(tokens["manager"]), timeout=15)
        assert mgr.status_code == 403

        # HR sees it
        hr = requests.get(f"{BASE_URL}/api/meetings/pending-approval", headers=_h(tokens["hr"]), timeout=15)
        assert hr.status_code == 200
        assert any(x["id"] == mid for x in hr.json()), "pending meeting missing from queue"

        # Employee cannot approve their own
        bad = requests.post(f"{BASE_URL}/api/meetings/{mid}/approve",
                            headers=_h(tokens["employee"]), json={"note": ""}, timeout=15)
        assert bad.status_code == 403

        # HR approves
        appr = requests.post(f"{BASE_URL}/api/meetings/{mid}/approve",
                             headers=_h(tokens["hr"]), json={"note": "ok"}, timeout=15)
        assert appr.status_code == 200, appr.text

        # Approving again → 400
        again = requests.post(f"{BASE_URL}/api/meetings/{mid}/approve",
                              headers=_h(tokens["hr"]), json={"note": ""}, timeout=15)
        assert again.status_code == 400

        # Verify meeting persisted as approved via GET
        listed = requests.get(f"{BASE_URL}/api/meetings", headers=_h(tokens["employee"]),
                              params={"scope": "mine"}, timeout=15).json()
        found = next((x for x in listed if x["id"] == mid), None)
        assert found and found["approval_status"] == "approved"
        assert found.get("approved_by")

        # Cleanup
        requests.delete(f"{BASE_URL}/api/meetings/{mid}", headers=_h(tokens["hr"]), timeout=15)

    def test_long_meeting_reject_with_note(self, tokens):
        rooms = _default_rooms(tokens["employee"])
        room_b = next(r for r in rooms if r["name"] == "Conference Room B")
        offset = 1200 + int(uuid.uuid4().int % 200)
        s = datetime.now(timezone.utc).replace(microsecond=0, second=0, minute=0) + timedelta(days=7, hours=offset)
        e = s + timedelta(minutes=180)  # >120 -> approval required
        payload = {
            "title": f"TEST_long_{uuid.uuid4().hex[:6]}",
            "starts_at": _iso(s), "ends_at": _iso(e),
            "room_id": room_b["id"],
            "attendee_user_ids": [],
        }
        r = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["employee"]), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["approval_status"] == "pending"
        mid = m["id"]

        # HR rejects with a note
        rej = requests.post(f"{BASE_URL}/api/meetings/{mid}/reject",
                            headers=_h(tokens["hr"]), json={"note": "Please split into two shorter slots"},
                            timeout=15)
        assert rej.status_code == 200

        # Re-rejecting → 400
        again = requests.post(f"{BASE_URL}/api/meetings/{mid}/reject",
                              headers=_h(tokens["hr"]), json={"note": ""}, timeout=15)
        assert again.status_code == 400

        # Fetch via /api/meetings to verify persistence
        listed = requests.get(f"{BASE_URL}/api/meetings", headers=_h(tokens["employee"]),
                              params={"scope": "mine"}, timeout=15).json()
        found = next((x for x in listed if x["id"] == mid), None)
        assert found
        assert found["approval_status"] == "rejected"
        assert "split" in (found.get("rejection_reason") or "").lower()

        # The room is now free again (rejected meetings excluded from conflict)
        conf = requests.post(
            f"{BASE_URL}/api/rooms/check-conflict",
            headers=_h(tokens["employee"]),
            json={"room_id": room_b["id"], "starts_at": payload["starts_at"], "ends_at": payload["ends_at"]},
            timeout=15,
        ).json()
        assert conf["available"] is True, "rejected meeting must not block room"

    def test_super_admin_long_meeting_auto_approves(self, tokens):
        rooms = _default_rooms(tokens["super_admin"])
        room_a = next(r for r in rooms if r["name"] == "Conference Room A")
        offset = 1400 + int(uuid.uuid4().int % 200)
        s = datetime.now(timezone.utc).replace(microsecond=0, second=0, minute=0) + timedelta(days=7, hours=offset)
        e = s + timedelta(minutes=180)
        payload = {
            "title": f"TEST_admin_long_{uuid.uuid4().hex[:6]}",
            "starts_at": _iso(s), "ends_at": _iso(e),
            "room_id": room_a["id"],
            "attendee_user_ids": [],
        }
        r = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["super_admin"]), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        m = r.json()
        # For super_admin/HR, needs-approval bookings auto-approve to 'approved'
        assert m["approval_status"] == "approved", m
        # Cleanup
        requests.delete(f"{BASE_URL}/api/meetings/{m['id']}", headers=_h(tokens["super_admin"]), timeout=15)

    def test_hr_recurring_auto_approves(self, tokens):
        rooms = _default_rooms(tokens["hr"])
        room_b = next(r for r in rooms if r["name"] == "Conference Room B")
        offset = 1600 + int(uuid.uuid4().int % 200)
        s, e = _future_window(hour_offset=offset, minutes=30)
        payload = {
            "title": f"TEST_hr_recur_{uuid.uuid4().hex[:6]}",
            "starts_at": s, "ends_at": e,
            "room_id": room_b["id"],
            "is_recurring": True,
            "recurrence": {"frequency": "weekly", "count": 3},
        }
        r = requests.post(f"{BASE_URL}/api/meetings", headers=_h(tokens["hr"]), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["approval_status"] == "approved"
        requests.delete(f"{BASE_URL}/api/meetings/{r.json()['id']}", headers=_h(tokens["hr"]), timeout=15)
