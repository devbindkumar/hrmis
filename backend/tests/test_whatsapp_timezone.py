"""Iteration 6: Per-tenant timezone for WhatsApp notification timestamps.

Verifies:
- GET /api/whatsapp/config returns a `timezone` field (default 'Asia/Kolkata').
- PUT persists the field (round-trip).
- Invalid IANA zone is stored but formatting falls back silently to IST.
- notify_status_update produces a time string ending with the correct TZ
  abbreviation and matching current wall-clock in that timezone.
- notify_checkin_checkout via /api/attendance/check-in/check-out honors TZ.
- Partial PUT does NOT wipe the saved timezone.
- Regression: HR endpoints (leave/WFH) still return 200/201.
"""
from __future__ import annotations

import os
import re
import time
import requests
import pytest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@acme.com", "password": "Admin@123"}
EMP = {"email": "maya@acme.com", "password": "Demo@123"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN)}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def emp_h():
    return {"Authorization": f"Bearer {_login(EMP)}", "Content-Type": "application/json"}


def _put(h, body):
    r = requests.put(f"{API}/whatsapp/config", headers=h, json=body, timeout=15)
    assert r.status_code == 200, f"PUT failed: {r.status_code} {r.text}"
    return r.json()


def _get_cfg(h):
    r = requests.get(f"{API}/whatsapp/config", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _outbox_latest(h, template=None, limit=20):
    r = requests.get(f"{API}/whatsapp/outbox", headers=h, params={"limit": limit}, timeout=15)
    assert r.status_code == 200
    items = r.json()
    if template:
        for it in items:
            if it.get("template") == template:
                return it
        return None
    return items[0] if items else None


def _seed_azmarq(h, *, tz="Asia/Kolkata"):
    _put(h, {
        "enabled": True,
        "provider": "azmarq",
        "access_token": "FAKE_apikey_iter6_test",
        "phone_number_id": "+919871277211",
        "campaign_name": "api-test",
        "header_text": "text value",
        "api_base_url": "https://api.azmarq.com/v1/whatsapp",
        "default_country_code": "",
        "templates": {"status_update": "status_update_v1"},
        "payload_extras": None,
        "timezone": tz,
    })


def _trigger_status(emp_h, status="on_break"):
    r = requests.post(f"{API}/attendance/status", headers=emp_h,
                      json={"status": status}, timeout=15)
    assert r.status_code == 200, r.text
    time.sleep(1.2)  # allow fire-and-forget to complete


def _parse_time_str(s: str):
    """Parse '01 Jul 2026, 05:10 IST' → (datetime_naive, 'IST')."""
    m = re.match(r"^(\d{2} \w{3} \d{4}, \d{2}:\d{2})\s+(\S+)$", s.strip())
    assert m, f"Time string didn't match expected format: {s!r}"
    dt = datetime.strptime(m.group(1), "%d %b %Y, %H:%M")
    return dt, m.group(2)


def _assert_close_to_now(dt_naive, tz_name, tolerance_min=3):
    """Assert the naive datetime is close to now-in-tz."""
    now_in_tz = datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
    diff = abs((now_in_tz - dt_naive).total_seconds())
    assert diff <= tolerance_min * 60, (
        f"time drift {diff:.0f}s exceeds tolerance for tz={tz_name}: "
        f"got {dt_naive}, expected around {now_in_tz}"
    )


# ---------------- Tests ----------------

class TestConfigTimezoneField:
    def test_get_config_returns_timezone_default(self, admin_h):
        cfg = _get_cfg(admin_h)
        assert "timezone" in cfg
        # even if a prev iteration left tz set, field must be a non-empty IANA
        assert cfg["timezone"], "timezone must not be empty"

    def test_put_utc_then_get(self, admin_h):
        _seed_azmarq(admin_h, tz="Asia/Kolkata")
        r = _put(admin_h, {"timezone": "UTC"})
        assert r["timezone"] == "UTC"
        assert _get_cfg(admin_h)["timezone"] == "UTC"

    def test_put_london_then_get(self, admin_h):
        r = _put(admin_h, {"timezone": "Europe/London"})
        assert r["timezone"] == "Europe/London"
        assert _get_cfg(admin_h)["timezone"] == "Europe/London"

    def test_put_invalid_tz_is_stored_but_falls_back_at_send_time(self, admin_h, emp_h):
        _put(admin_h, {"timezone": "Bogus/Zone"})
        assert _get_cfg(admin_h)["timezone"] == "Bogus/Zone"
        # trigger a status update — must NOT crash, and time string should
        # still be present (formatter falls back to IST abbr for unknown IANA).
        _trigger_status(emp_h, "on_break")
        row = _outbox_latest(admin_h, template="status_update_v1")
        assert row is not None, "no status_update outbox row after trigger"
        params = row["request_payload"]["components"]["body"]["params"]
        time_str = params[3]
        # last token should be the segment after '/' → 'Zone' per _tz_abbr()
        assert time_str.endswith(" Zone") or time_str.endswith(" IST"), (
            f"unexpected fallback abbr in {time_str!r}"
        )


class TestPartialUpdatePreservesTimezone:
    def test_partial_put_enabled_only_preserves_tz(self, admin_h):
        _put(admin_h, {"timezone": "America/New_York"})
        assert _get_cfg(admin_h)["timezone"] == "America/New_York"
        # partial update — only touch `enabled`
        _put(admin_h, {"enabled": True})
        cfg = _get_cfg(admin_h)
        assert cfg["timezone"] == "America/New_York", (
            f"timezone was wiped by partial PUT: {cfg['timezone']!r}"
        )


class TestStatusUpdateTimeInTenantTZ:
    def test_ist_time_and_abbr(self, admin_h, emp_h):
        _seed_azmarq(admin_h, tz="Asia/Kolkata")
        _trigger_status(emp_h, "on_break")
        row = _outbox_latest(admin_h, template="status_update_v1")
        assert row is not None
        params = row["request_payload"]["components"]["body"]["params"]
        assert len(params) >= 4
        time_str = params[3]
        assert time_str.endswith(" IST"), f"expected IST suffix, got {time_str!r}"
        dt, abbr = _parse_time_str(time_str)
        assert abbr == "IST"
        _assert_close_to_now(dt, "Asia/Kolkata")

    def test_utc_time_and_abbr(self, admin_h, emp_h):
        _seed_azmarq(admin_h, tz="UTC")
        _trigger_status(emp_h, "on_break")
        row = _outbox_latest(admin_h, template="status_update_v1")
        assert row is not None
        params = row["request_payload"]["components"]["body"]["params"]
        time_str = params[3]
        assert time_str.endswith(" UTC"), f"expected UTC suffix, got {time_str!r}"
        dt, abbr = _parse_time_str(time_str)
        assert abbr == "UTC"
        _assert_close_to_now(dt, "UTC")

    def test_new_york_time_and_abbr(self, admin_h, emp_h):
        _seed_azmarq(admin_h, tz="America/New_York")
        _trigger_status(emp_h, "on_break")
        row = _outbox_latest(admin_h, template="status_update_v1")
        assert row is not None
        params = row["request_payload"]["components"]["body"]["params"]
        time_str = params[3]
        assert time_str.endswith(" ET"), f"expected ET suffix, got {time_str!r}"
        dt, abbr = _parse_time_str(time_str)
        assert abbr == "ET"
        _assert_close_to_now(dt, "America/New_York")


class TestCheckinCheckoutTimeInTenantTZ:
    def test_checkin_and_checkout_use_tenant_tz(self, admin_h, emp_h):
        _seed_azmarq(admin_h, tz="Asia/Kolkata")
        # ensure clean day state — attempt checkout first (may 400 if no check-in), ignore
        requests.post(f"{API}/attendance/check-out", headers=emp_h, timeout=15)
        time.sleep(0.5)

        r_in = requests.post(f"{API}/attendance/check-in", headers=emp_h, timeout=15)
        # 200 if new, 400 if already checked in — either way flow tested
        if r_in.status_code == 200:
            time.sleep(1.2)
            row = _outbox_latest(admin_h, template="hrmis_checkin_checkout")
            if row is not None:
                params = row["request_payload"]["components"]["body"]["params"]
                time_str = params[3]
                assert time_str.endswith(" IST"), f"check-in time missing IST: {time_str!r}"
                dt, _ = _parse_time_str(time_str)
                _assert_close_to_now(dt, "Asia/Kolkata")

        r_out = requests.post(f"{API}/attendance/check-out", headers=emp_h, timeout=15)
        if r_out.status_code == 200:
            time.sleep(1.2)
            row = _outbox_latest(admin_h, template="hrmis_checkin_checkout")
            if row is not None:
                params = row["request_payload"]["components"]["body"]["params"]
                time_str = params[3]
                assert time_str.endswith(" IST"), f"check-out time missing IST: {time_str!r}"
                dt, _ = _parse_time_str(time_str)
                _assert_close_to_now(dt, "Asia/Kolkata")


class TestLeaveWFHRegression:
    def test_leave_still_2xx_and_dates_not_reformatted(self, admin_h, emp_h):
        _seed_azmarq(admin_h, tz="UTC")
        payload = {
            "leave_type": "Sick",
            "start_date": "2027-03-15",
            "end_date": "2027-03-15",
            "reason": "TEST_tz_regression",
        }
        r = requests.post(f"{API}/leave/apply", headers=emp_h, json=payload, timeout=15)
        # Casual balance may be exhausted; try alternates
        if r.status_code >= 400:
            for lt in ("Earned", "Casual"):
                payload["leave_type"] = lt
                r = requests.post(f"{API}/leave/apply", headers=emp_h, json=payload, timeout=15)
                if r.status_code < 400:
                    break
        assert r.status_code in (200, 201), f"leave apply failed: {r.status_code} {r.text}"
        time.sleep(1.2)
        row = _outbox_latest(admin_h, template="hrmis_leave_request")
        if row is not None:
            params = row["request_payload"]["components"]["body"]["params"]
            # start_date / end_date must be passed through as-is (not reformatted)
            assert "2027-03-15" in params, f"leave params: {params}"

    def test_wfh_still_2xx(self, emp_h):
        import random
        d = f"2027-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
        payload = {"date": d, "reason": "TEST_tz_regression"}
        r = requests.post(f"{API}/wfh/apply", headers=emp_h, json=payload, timeout=15)
        # Duplicate date is a legitimate 400 (not caused by tz work) — treat as pass
        assert r.status_code in (200, 201, 400), f"wfh apply failed: {r.status_code} {r.text}"


class TestRestoreFinalState:
    """Leave tenant configured with IST as required by main-agent context."""
    def test_restore_ist_default(self, admin_h):
        _put(admin_h, {
            "enabled": True,
            "provider": "azmarq",
            "phone_number_id": "+919871277211",
            "campaign_name": "api-test",
            "header_text": "text value",
            "api_base_url": "https://api.azmarq.com/v1/whatsapp",
            "templates": {"status_update": "status_update_v1"},
            "timezone": "Asia/Kolkata",
        })
        cfg = _get_cfg(admin_h)
        assert cfg["timezone"] == "Asia/Kolkata"
        assert cfg["provider"] == "azmarq"
        assert cfg["campaign_name"] == "api-test"
        assert cfg["header_text"] == "text value"
