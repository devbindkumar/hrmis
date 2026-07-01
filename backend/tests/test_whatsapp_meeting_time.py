"""Iteration 10: Meeting time formatting for WhatsApp notifications.

Verifies the fix to `notify_meeting_scheduled` which now:
- accepts `ends_at`
- treats naive `datetime-local` strings as tenant-tz wall-clock
- honours explicit UTC offsets by converting to tenant tz
- produces exactly 5 template params:
    [attendee_name, organizer_name, title, date_str, time_range]
  with date_str="01 Jul 2026 (Wed)" and
  time_range="04:00 pm → 04:30 pm IST"

Also tests: tz override (UTC), missing ends_at, garbage timestamp,
leading-zero AM/PM formatting (unit test via internal helper import).
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@acme.com", "password": "Admin@123"}
EMP = {"email": "maya@acme.com", "password": "Demo@123"}

ARROW = "\u2192"  # →


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def admin_login():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def emp_login():
    return _login(EMP)


@pytest.fixture(scope="module")
def admin_h(admin_login):
    return {"Authorization": f"Bearer {admin_login['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def emp_h(emp_login):
    return {"Authorization": f"Bearer {emp_login['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def maya_uid(emp_login):
    return emp_login["user"]["id"]


def _put_cfg(h, body):
    r = requests.put(f"{API}/whatsapp/config", headers=h, json=body, timeout=15)
    assert r.status_code == 200, f"PUT config failed: {r.status_code} {r.text}"
    return r.json()


def _get_cfg(h):
    r = requests.get(f"{API}/whatsapp/config", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _set_tz(admin_h, tz):
    _put_cfg(admin_h, {
        "enabled": True,
        "provider": "azmarq",
        "access_token": "FAKE_apikey_iter10_test",
        "phone_number_id": "+919871277211",
        "campaign_name": "api-test",
        "header_text": "text value",
        "api_base_url": "https://api.azmarq.com/v1/whatsapp",
        "templates": {"meeting_scheduled": "meeting_scheduled_v1"},
        "timezone": tz,
    })


def _outbox_find_meeting_by_title(admin_h, title, limit=50):
    """Return most recent outbox row whose params contain `title`."""
    r = requests.get(f"{API}/whatsapp/outbox", headers=admin_h, params={"limit": limit}, timeout=15)
    assert r.status_code == 200
    for it in r.json():
        if it.get("template") != "meeting_scheduled_v1":
            continue
        params = ((it.get("request_payload") or {}).get("components") or {}).get("body", {}).get("params") or []
        if title in params:
            return it
    return None


def _ensure_maya_phone(admin_h, maya_uid):
    """Ensure Maya has a phone so outbox row is written."""
    r = requests.get(f"{API}/employees", headers=admin_h, timeout=15)
    assert r.status_code == 200
    for emp in r.json():
        if emp.get("user_id") == maya_uid:
            if emp.get("phone"):
                return
            eid = emp["id"]
            r2 = requests.patch(f"{API}/employees/{eid}", headers=admin_h,
                                json={"phone": "+919999999999"}, timeout=15)
            assert r2.status_code in (200, 201), r2.text
            return
    pytest.fail("Maya employee not found")


def _schedule_meeting(emp_h, maya_uid, starts_at, ends_at, title):
    payload = {
        "title": title,
        "description": "TEST_meeting_tz",
        "starts_at": starts_at,
        "ends_at": ends_at,
        "location": "Zoom",
        "attendee_user_ids": [maya_uid],
    }
    r = requests.post(f"{API}/meetings", headers=emp_h, json=payload, timeout=20)
    return r


# ---------------- Setup ----------------

class TestSetup:
    def test_ensure_ist_and_phone(self, admin_h, maya_uid):
        _set_tz(admin_h, "Asia/Kolkata")
        _ensure_maya_phone(admin_h, maya_uid)
        cfg = _get_cfg(admin_h)
        assert cfg["timezone"] == "Asia/Kolkata"
        assert cfg["templates"]["meeting_scheduled"] == "meeting_scheduled_v1"


# ---------------- (a) 4:00pm–4:30pm IST naive input ----------------

class TestNaiveInputIST:
    def test_naive_ist_4pm_to_430pm(self, admin_h, emp_h, maya_uid):
        _set_tz(admin_h, "Asia/Kolkata")
        title = f"TEST_naive_IST_{uuid.uuid4().hex[:6]}"
        r = _schedule_meeting(
            emp_h, maya_uid,
            starts_at="2026-07-01T16:00",
            ends_at="2026-07-01T16:30",
            title=title,
        )
        assert r.status_code in (200, 201), r.text
        time.sleep(1.5)
        row = _outbox_find_meeting_by_title(admin_h, title)
        assert row is not None, "outbox row not found for naive IST meeting"
        params = row["request_payload"]["components"]["body"]["params"]
        assert len(params) == 5, f"expected 5 params, got {len(params)}: {params}"
        _, organizer_name, title_p, date_str, time_range = params
        assert title_p == title
        assert date_str == "01 Jul 2026 (Wed)", date_str
        assert time_range == f"04:00 pm {ARROW} 04:30 pm IST", time_range


# ---------------- (b) UTC-offset explicit input ----------------

class TestUTCOffsetInput:
    def test_utc_offset_input_converts_to_ist(self, admin_h, emp_h, maya_uid):
        _set_tz(admin_h, "Asia/Kolkata")
        title = f"TEST_utc_offset_{uuid.uuid4().hex[:6]}"
        r = _schedule_meeting(
            emp_h, maya_uid,
            starts_at="2026-07-01T10:30:00+00:00",
            ends_at="2026-07-01T11:00:00+00:00",
            title=title,
        )
        assert r.status_code in (200, 201), r.text
        time.sleep(1.5)
        row = _outbox_find_meeting_by_title(admin_h, title)
        assert row is not None
        params = row["request_payload"]["components"]["body"]["params"]
        assert len(params) == 5
        _, _, _, date_str, time_range = params
        assert date_str == "01 Jul 2026 (Wed)"
        assert time_range == f"04:00 pm {ARROW} 04:30 pm IST", time_range


# ---------------- (c) tz=UTC override ----------------

class TestTimezoneOverrideUTC:
    def test_utc_tz_override_keeps_wall_clock(self, admin_h, emp_h, maya_uid):
        _set_tz(admin_h, "UTC")
        title = f"TEST_utc_tz_{uuid.uuid4().hex[:6]}"
        try:
            r = _schedule_meeting(
                emp_h, maya_uid,
                starts_at="2026-07-01T16:00",
                ends_at="2026-07-01T16:30",
                title=title,
            )
            assert r.status_code in (200, 201), r.text
            time.sleep(1.5)
            row = _outbox_find_meeting_by_title(admin_h, title)
            assert row is not None
            params = row["request_payload"]["components"]["body"]["params"]
            assert len(params) == 5
            _, _, _, date_str, time_range = params
            assert date_str == "01 Jul 2026 (Wed)"
            assert time_range == f"04:00 pm {ARROW} 04:30 pm UTC", time_range
        finally:
            _set_tz(admin_h, "Asia/Kolkata")


# ---------------- (d) missing ends_at ----------------

class TestMissingEndsAt:
    """Directly exercise notify_meeting_scheduled with empty ends_at.

    /api/meetings requires ends_at (Pydantic-str), so we call the helper
    directly to prove no crash + '04:00 pm IST' rendering.
    """
    def test_missing_ends_at_no_crash(self, admin_h, maya_uid):
        _set_tz(admin_h, "Asia/Kolkata")
        import sys
        sys.path.insert(0, "/app/backend")
        # Load backend .env so notification_service -> db.get_db() has MONGO_URL
        try:
            from dotenv import load_dotenv
            load_dotenv("/app/backend/.env")
        except Exception:
            pass
        from notification_service import notify_meeting_scheduled  # type: ignore

        # Resolve Maya's company_id
        r = requests.get(f"{API}/employees", headers=admin_h, timeout=15)
        assert r.status_code == 200
        company_id = None
        for emp in r.json():
            if emp.get("user_id") == maya_uid:
                company_id = emp.get("company_id")
                break
        assert company_id, "could not resolve company_id"

        title = f"TEST_no_end_{uuid.uuid4().hex[:6]}"

        async def _run():
            await notify_meeting_scheduled(
                company_id=company_id,
                organizer_name="Test Organizer",
                title=title,
                starts_at="2026-07-01T16:00",
                ends_at="",
                location="Zoom",
                attendee_user_ids=[maya_uid],
            )
        asyncio.run(_run())
        time.sleep(1.0)
        row = _outbox_find_meeting_by_title(admin_h, title)
        assert row is not None, "outbox row should be written even without ends_at"
        params = row["request_payload"]["components"]["body"]["params"]
        assert len(params) == 5
        _, _, _, date_str, time_range = params
        assert date_str == "01 Jul 2026 (Wed)"
        assert time_range == "04:00 pm IST", time_range
        assert ARROW not in time_range


# ---------------- (e) garbage timestamp ----------------

class TestGarbageTimestamp:
    def test_garbage_starts_at_no_crash(self, admin_h, emp_h, maya_uid):
        _set_tz(admin_h, "Asia/Kolkata")
        title = f"TEST_garbage_{uuid.uuid4().hex[:6]}"
        r = _schedule_meeting(
            emp_h, maya_uid,
            starts_at="garbage",
            ends_at="also-garbage",
            title=title,
        )
        # HR endpoint must still succeed
        assert r.status_code in (200, 201), r.text
        time.sleep(1.5)
        # Outbox row either absent or contains raw strings — no crash
        row = _outbox_find_meeting_by_title(admin_h, title)
        if row is not None:
            params = row["request_payload"]["components"]["body"]["params"]
            assert len(params) == 5
            # date_str and time_range fall back to raw inputs
            assert "garbage" in params[3] or "garbage" in params[4]


# ---------------- (f) leading-zero / midnight / noon formatting ----------------

class TestLeadingZeroFormatting:
    def test_leading_zero_midnight_noon(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from notification_service import _fmt_meeting_range  # type: ignore

        # 09:00 am (leading zero preserved by %I)
        _, tr = _fmt_meeting_range("2026-07-01T09:00", "2026-07-01T09:30", "Asia/Kolkata")
        assert tr == f"09:00 am {ARROW} 09:30 am IST", tr

        # Midnight → 12:00 am
        _, tr = _fmt_meeting_range("2026-07-01T00:00", "2026-07-01T00:30", "Asia/Kolkata")
        assert tr == f"12:00 am {ARROW} 12:30 am IST", tr

        # Noon → 12:00 pm
        _, tr = _fmt_meeting_range("2026-07-01T12:00", "2026-07-01T12:30", "Asia/Kolkata")
        assert tr == f"12:00 pm {ARROW} 12:30 pm IST", tr


# ---------------- Restore ----------------

class TestRestoreFinal:
    def test_restore_ist(self, admin_h):
        _set_tz(admin_h, "Asia/Kolkata")
        assert _get_cfg(admin_h)["timezone"] == "Asia/Kolkata"
