"""Iteration 12 backend tests — Employee shift override UI backend + WhatsApp default.

Follow-up on iter11:
1. Verify PATCH /api/employees/{id} supports partial shift_start_time / late_grace_minutes
   updates (payload strips empties on FE — backend uses exclude_none).
2. Verify DEFAULT_EVENTS_ENABLED['checkin_checkout'] is now True → new/empty tenants
   get events_enabled.checkin_checkout=true out of the box.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

ADMIN = ("admin@acme.com", "Admin@123")
EMPLOYEE = ("maya@acme.com", "Demo@123")


def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok() -> str:
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def maya_id(admin_tok) -> str:
    r = requests.get(f"{BASE_URL}/api/employees", headers=_headers(admin_tok), timeout=15)
    assert r.status_code == 200
    for e in r.json():
        if e.get("email") == EMPLOYEE[0]:
            return e["id"]
    pytest.skip("maya not found")


# --------- 1. Shift override PATCH behavior (matches UI payload) ---------

class TestShiftOverridePatch:

    def test_both_values_persisted(self, admin_tok, maya_id):
        """UI sends both fields with values → GET reflects them."""
        r = requests.patch(f"{BASE_URL}/api/employees/{maya_id}", headers=_headers(admin_tok),
                           json={"shift_start_time": "10:15", "late_grace_minutes": 20}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["shift_start_time"] == "10:15"
        assert d["late_grace_minutes"] == 20

        # GET verification
        g = requests.get(f"{BASE_URL}/api/employees/{maya_id}", headers=_headers(admin_tok), timeout=15)
        assert g.status_code == 200
        gd = g.json()
        assert gd["shift_start_time"] == "10:15"
        assert gd["late_grace_minutes"] == 20

    def test_only_shift_start_partial_no_wipe_grace(self, admin_tok, maya_id):
        """UI sends only shift_start_time (grace blank stripped) → grace remains at previous value."""
        # First seed both
        requests.patch(f"{BASE_URL}/api/employees/{maya_id}", headers=_headers(admin_tok),
                       json={"shift_start_time": "10:15", "late_grace_minutes": 20}, timeout=15)
        # Now UI sends only shift_start_time (grace blank stripped)
        r = requests.patch(f"{BASE_URL}/api/employees/{maya_id}", headers=_headers(admin_tok),
                           json={"shift_start_time": "11:00"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["shift_start_time"] == "11:00"
        # regression: grace should NOT have been wiped
        assert d["late_grace_minutes"] == 20, f"grace wiped: {d.get('late_grace_minutes')}"

    def test_only_grace_partial_no_wipe_shift(self, admin_tok, maya_id):
        """UI sends only late_grace_minutes (shift blank stripped) → shift_start_time remains."""
        # seed to 11:00/20 first (in case previous test order)
        requests.patch(f"{BASE_URL}/api/employees/{maya_id}", headers=_headers(admin_tok),
                       json={"shift_start_time": "11:00", "late_grace_minutes": 20}, timeout=15)
        # Now send only grace
        r = requests.patch(f"{BASE_URL}/api/employees/{maya_id}", headers=_headers(admin_tok),
                           json={"late_grace_minutes": 45}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["late_grace_minutes"] == 45
        assert d["shift_start_time"] == "11:00", f"shift wiped: {d.get('shift_start_time')}"

    def test_empty_payload_strips_both_no_change(self, admin_tok, maya_id):
        """UI leaves both blank → both stripped from payload → nothing changes."""
        # seed values
        requests.patch(f"{BASE_URL}/api/employees/{maya_id}", headers=_headers(admin_tok),
                       json={"shift_start_time": "10:00", "late_grace_minutes": 25}, timeout=15)
        # UI-mimicking blank save (only name+department+designation stay in payload)
        before = requests.get(f"{BASE_URL}/api/employees/{maya_id}", headers=_headers(admin_tok), timeout=15).json()
        r = requests.patch(f"{BASE_URL}/api/employees/{maya_id}", headers=_headers(admin_tok),
                           json={"name": before.get("name"), "department": before.get("department"),
                                 "designation": before.get("designation")}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        # unchanged (still 10:00 / 25 from seed)
        assert d["shift_start_time"] == "10:00"
        assert d["late_grace_minutes"] == 25

    def test_invalid_shift_format_422(self, admin_tok, maya_id):
        r = requests.patch(f"{BASE_URL}/api/employees/{maya_id}", headers=_headers(admin_tok),
                           json={"shift_start_time": "notatime"}, timeout=15)
        assert r.status_code == 422

    def test_grace_out_of_range_422(self, admin_tok, maya_id):
        r = requests.patch(f"{BASE_URL}/api/employees/{maya_id}", headers=_headers(admin_tok),
                           json={"late_grace_minutes": 999}, timeout=15)
        assert r.status_code == 422


# --------- 2. WhatsApp default: checkin_checkout=True out of the box ---------

class TestWhatsAppDefaults:

    def test_default_checkin_checkout_true_for_fresh_tenant(self, admin_tok):
        """Fetch whatsapp/config. events_enabled.checkin_checkout should be True by default.

        We can't easily create a brand-new tenant in a test, but if the current tenant
        has no persisted events_enabled config, the API merges DEFAULT_EVENTS_ENABLED
        which should now include checkin_checkout=True.
        """
        r = requests.get(f"{BASE_URL}/api/whatsapp/config", headers=_headers(admin_tok), timeout=15)
        assert r.status_code == 200
        cfg = r.json()
        events = cfg.get("events_enabled") or {}
        # The default MUST be True — this is what iter12 changed
        assert events.get("checkin_checkout") is True, (
            f"Expected checkin_checkout=True (default). Got events_enabled={events}. "
            "Note: tenant may have persisted an old override. Reset via PUT with events_enabled excluding checkin_checkout."
        )

    def test_default_module_constants_verify_via_upsert_wipe(self, admin_tok):
        """Verify the default merges from the module constant.

        1) Save events_enabled without checkin_checkout key.
        2) GET must still return checkin_checkout=True because of DEFAULT_EVENTS_ENABLED merge.
        """
        # Fetch current
        current = requests.get(f"{BASE_URL}/api/whatsapp/config", headers=_headers(admin_tok), timeout=15).json()
        original_events = dict(current.get("events_enabled") or {})

        try:
            # Push a config without checkin_checkout to force the default merge on GET
            partial = {k: v for k, v in original_events.items() if k != "checkin_checkout"}
            # ensure at least one event stays so we don't send empty dict
            partial.setdefault("status_update", True)
            put = requests.put(f"{BASE_URL}/api/whatsapp/config", headers=_headers(admin_tok),
                               json={"events_enabled": partial}, timeout=15)
            assert put.status_code == 200

            r = requests.get(f"{BASE_URL}/api/whatsapp/config", headers=_headers(admin_tok), timeout=15)
            assert r.status_code == 200
            events = r.json().get("events_enabled") or {}
            assert events.get("checkin_checkout") is True, (
                f"After stripping key from payload, GET should merge default True. Got {events}"
            )
        finally:
            # Restore
            requests.put(f"{BASE_URL}/api/whatsapp/config", headers=_headers(admin_tok),
                         json={"events_enabled": original_events}, timeout=15)


# --------- 3. Restore state ---------

def test_zzz_restore(admin_tok, maya_id):
    """Restore Maya's shift override to null-ish (best-effort — exclude_none blocks true clear)."""
    # We cannot clear to None via PATCH (exclude_none). Restore to iter11 defaults.
    requests.patch(f"{BASE_URL}/api/employees/{maya_id}", headers=_headers(admin_tok),
                   json={"shift_start_time": "09:30", "late_grace_minutes": 15}, timeout=15)
    # restore company shift too
    cm = requests.get(f"{BASE_URL}/api/companies/mine", headers=_headers(admin_tok), timeout=15).json()
    requests.patch(f"{BASE_URL}/api/companies/{cm['id']}", headers=_headers(admin_tok),
                   json={"shift_start_time": "09:30", "late_grace_minutes": 15, "kiosk_enabled": True}, timeout=15)
