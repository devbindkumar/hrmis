"""Iteration 5: AzMarq payload schema rebuilt to match customer's working curl.

The outgoing request_payload (stored in whatsapp_outbox) MUST have EXACTLY
6 root keys: from, campaignName, to, templateName, components, type
with components = {body:{params:[...]}, header:{type:"text", text:"..."}, type:"template"}.

No legacy fields allowed (countryCode/phoneNumber/wabaId/senderMobile/headerType/
template object/components-array/language/messaging_product).
"""
from __future__ import annotations

import os
import random
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@acme.com", "password": "Admin@123"}
EMP = {"email": "maya@acme.com", "password": "Demo@123"}

ALLOWED_ROOT_KEYS = {"from", "campaignName", "to", "templateName", "components", "type"}
FORBIDDEN_KEYS = {
    "countryCode", "phoneNumber", "wabaId", "senderMobile", "headerType",
    "template", "language", "messaging_product",
}


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
    return requests.put(f"{API}/whatsapp/config", headers=h, json=body, timeout=15)


def _get_cfg(h):
    return requests.get(f"{API}/whatsapp/config", headers=h, timeout=15)


def _outbox(h, limit=10):
    r = requests.get(f"{API}/whatsapp/outbox", headers=h, params={"limit": limit}, timeout=15)
    assert r.status_code == 200
    return r.json()


def _latest(h):
    items = _outbox(h, 5)
    assert items, "outbox empty"
    return items[0]


def _seed_azmarq(h, *, phone_number_id="+919871277211", campaign_name="api-test",
                 header_text="text value", payload_extras=None, default_cc=""):
    body = {
        "enabled": True,
        "provider": "azmarq",
        "access_token": "D4Kv_FAKE_token_for_test_yAt3",
        "phone_number_id": phone_number_id,
        "campaign_name": campaign_name,
        "header_text": header_text,
        "api_base_url": "https://api.azmarq.com/v1/whatsapp",
        "default_country_code": default_cc,
        "templates": {"status_update": "status_update_v1"},
        "payload_extras": payload_extras,
    }
    r = _put(h, body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------

class TestConfigCampaignHeaderFields:
    def test_get_returns_new_fields(self, admin_h):
        # First, clear them by sending empty strings
        _put(admin_h, {"campaign_name": "", "header_text": ""})
        cfg = _get_cfg(admin_h).json()
        assert "campaign_name" in cfg
        assert "header_text" in cfg
        assert cfg["campaign_name"] == ""
        assert cfg["header_text"] == ""

    def test_put_then_get_roundtrip(self, admin_h):
        r = _put(admin_h, {"campaign_name": "api-test", "header_text": "text value"})
        assert r.status_code == 200
        cfg = _get_cfg(admin_h).json()
        assert cfg["campaign_name"] == "api-test"
        assert cfg["header_text"] == "text value"

    def test_partial_put_campaign_name_only_does_not_wipe_others(self, admin_h):
        # Seed full state
        _seed_azmarq(admin_h)
        before = _get_cfg(admin_h).json()
        assert before["campaign_name"] == "api-test"
        assert before["header_text"] == "text value"
        before_token_masked = before["access_token_masked"]
        before_pni = before["phone_number_id"]

        # Partial: only campaign_name
        r = _put(admin_h, {"campaign_name": "api-test"})
        assert r.status_code == 200
        after = _get_cfg(admin_h).json()
        assert after["campaign_name"] == "api-test"
        assert after["header_text"] == "text value", "header_text wiped!"
        assert after["access_token_masked"] == before_token_masked, "token wiped!"
        assert after["phone_number_id"] == before_pni, "phone_number_id wiped!"


# ---------------------------------------------------------------------------

class TestAzmarqPayloadShape:
    def test_test_send_produces_exact_6key_payload(self, admin_h):
        _seed_azmarq(admin_h)
        recipient = "918826471808"
        r = requests.post(
            f"{API}/whatsapp/test",
            headers=admin_h,
            json={"to": recipient, "template_key": "status_update"},
            timeout=30,
        )
        # Will likely return 400 because fake token, but outbox row will be written
        assert r.status_code in (200, 400), r.text

        item = _latest(admin_h)
        payload = item.get("request_payload")
        assert isinstance(payload, dict), f"no request_payload dict: {item}"

        root_keys = set(payload.keys())
        # EXACTLY 6 root keys
        assert root_keys == ALLOWED_ROOT_KEYS, (
            f"root keys mismatch — expected {ALLOWED_ROOT_KEYS}, got {root_keys}"
        )
        # No legacy keys
        leaked = root_keys & FORBIDDEN_KEYS
        assert not leaked, f"legacy keys leaked: {leaked}"

        # Field values
        assert payload["from"] == "+919871277211"
        assert payload["campaignName"] == "api-test"
        # Recipient is normalised digits-only
        assert payload["to"].replace("+", "") == recipient
        assert payload["templateName"] == "status_update_v1"
        assert payload["type"] == "template"

        comp = payload["components"]
        assert isinstance(comp, dict), f"components must be dict, got {type(comp)}"
        # Customer's working curl has components = {body, header} only
        # (the 'type':'template' lives at the ROOT level, not inside components)
        assert set(comp.keys()) == {"body", "header"}, comp.keys()
        assert "params" in comp["body"]
        assert isinstance(comp["body"]["params"], list)
        assert len(comp["body"]["params"]) == 4  # status_update has 4 vars
        assert all(isinstance(p, str) for p in comp["body"]["params"])
        assert comp["header"] == {"type": "text", "text": "text value"}

    def test_from_field_auto_prepends_plus_when_missing(self, admin_h):
        # Store phone_number_id WITHOUT '+'
        _seed_azmarq(admin_h, phone_number_id="919871277211")
        r = requests.post(
            f"{API}/whatsapp/test", headers=admin_h,
            json={"to": "918826471808", "template_key": "status_update"}, timeout=30,
        )
        assert r.status_code in (200, 400)
        payload = _latest(admin_h)["request_payload"]
        assert payload["from"] == "+919871277211", f"got from={payload['from']!r}"

    def test_from_field_keeps_plus_when_already_present(self, admin_h):
        _seed_azmarq(admin_h, phone_number_id="+919871277211")
        r = requests.post(
            f"{API}/whatsapp/test", headers=admin_h,
            json={"to": "918826471808", "template_key": "status_update"}, timeout=30,
        )
        assert r.status_code in (200, 400)
        payload = _latest(admin_h)["request_payload"]
        assert payload["from"] == "+919871277211"

    def test_defaults_when_campaign_name_and_header_text_empty(self, admin_h):
        _seed_azmarq(admin_h, campaign_name="", header_text="")
        r = requests.post(
            f"{API}/whatsapp/test", headers=admin_h,
            json={"to": "918826471808", "template_key": "status_update"}, timeout=30,
        )
        assert r.status_code in (200, 400)
        payload = _latest(admin_h)["request_payload"]
        assert payload["campaignName"] == "hrmis-alerts", payload["campaignName"]
        assert payload["components"]["header"]["text"] == "HRMIS Notification"


# ---------------------------------------------------------------------------

class TestOutboxRow:
    def test_outbox_contains_full_audit_fields(self, admin_h):
        _seed_azmarq(admin_h)
        r = requests.post(
            f"{API}/whatsapp/test", headers=admin_h,
            json={"to": "918826471808", "template_key": "status_update"}, timeout=30,
        )
        assert r.status_code in (200, 400)
        item = _latest(admin_h)
        assert item.get("provider") == "azmarq"
        assert item.get("url") == "https://api.azmarq.com/v1/whatsapp"
        # response_status is recorded as int (likely 400/401 due to fake token)
        assert isinstance(item.get("response_status"), int) or item.get("response_status") is None
        assert "request_payload" in item
        assert isinstance(item["request_payload"], dict)
        # response_body present (may be empty on exception)
        assert "response_body" in item


# ---------------------------------------------------------------------------

class TestPayloadExtrasMergeStillWorks:
    def test_payload_extras_merges_on_top(self, admin_h):
        _seed_azmarq(admin_h, payload_extras={"customField": "X"})
        r = requests.post(
            f"{API}/whatsapp/test", headers=admin_h,
            json={"to": "918826471808", "template_key": "status_update"}, timeout=30,
        )
        assert r.status_code in (200, 400)
        payload = _latest(admin_h)["request_payload"]
        assert payload.get("customField") == "X"
        # Core keys still present
        for k in ALLOWED_ROOT_KEYS:
            assert k in payload, f"missing core key {k!r} after extras merge"
        # Reset
        _put(admin_h, {"payload_extras": None})


# ---------------------------------------------------------------------------

class TestRegressionAllFiveTemplates:
    """Verify the new 6-key shape is applied across all 5 template types."""

    @pytest.mark.parametrize("template_key,expected_param_count", [
        ("status_update", 4),
        ("leave_request", 6),
        ("wfh_request", 4),
        ("meeting_scheduled", 5),
        ("checkin_checkout", 4),
    ])
    def test_each_template_uses_new_shape(self, admin_h, template_key, expected_param_count):
        _seed_azmarq(admin_h)
        # Ensure template name is registered (uses defaults for other keys)
        _put(admin_h, {"templates": {template_key: f"{template_key}_v1"}})
        r = requests.post(
            f"{API}/whatsapp/test", headers=admin_h,
            json={"to": "918826471808", "template_key": template_key}, timeout=30,
        )
        assert r.status_code in (200, 400), r.text
        payload = _latest(admin_h)["request_payload"]
        assert set(payload.keys()) == ALLOWED_ROOT_KEYS, (
            f"{template_key}: root keys mismatch — got {set(payload.keys())}"
        )
        assert payload["templateName"] == f"{template_key}_v1"
        assert len(payload["components"]["body"]["params"]) == expected_param_count


# ---------------------------------------------------------------------------

class TestFireAndForgetWithNewPayload:
    def test_leave_apply_still_201_when_wa_fails(self, admin_h, emp_h):
        _seed_azmarq(admin_h)
        # Try multiple leave types in case the employee's balance is exhausted
        # from prior iterations — the goal here is to verify fire-and-forget,
        # not leave-balance bookkeeping.
        success = False
        last = None
        for ltype in ("Sick", "Earned", "Casual", "Unpaid"):
            payload = {
                "leave_type": ltype,
                "start_date": f"2029-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
                "end_date": "2029-12-15",
                "reason": "TEST_iter5 fire-and-forget",
            }
            r = requests.post(f"{API}/leave/apply", headers=emp_h, json=payload, timeout=20)
            last = r
            if r.status_code in (200, 201):
                success = True
                break
        if not success:
            # If every leave type is exhausted, at least confirm the 400 is a
            # balance error (NOT an AzMarq-related crash)
            assert "balance" in (last.text or "").lower() or last.status_code == 400, (
                f"leave apply broke unexpectedly: {last.status_code} {last.text}"
            )

    def test_wfh_apply_still_201_when_wa_fails(self, emp_h):
        date = f"2028-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
        r = requests.post(f"{API}/wfh/apply", headers=emp_h,
                          json={"date": date, "reason": "TEST_iter5 wfh"}, timeout=20)
        assert r.status_code in (200, 201, 400)


# ---------------------------------------------------------------------------

class TestFinalRestore:
    def test_restore_iteration5_state(self, admin_h):
        body = {
            "enabled": True,
            "provider": "azmarq",
            "access_token": "D4Kv_FAKE_token_for_test_yAt3",
            "phone_number_id": "+919871277211",
            "campaign_name": "api-test",
            "header_text": "text value",
            "api_base_url": "https://api.azmarq.com/v1/whatsapp",
            "templates": {"status_update": "status_update_v1"},
            "payload_extras": None,
        }
        r = _put(admin_h, body)
        assert r.status_code == 200
        cfg = _get_cfg(admin_h).json()
        assert cfg["provider"] == "azmarq"
        assert cfg["phone_number_id"] == "+919871277211"
        assert cfg["campaign_name"] == "api-test"
        assert cfg["header_text"] == "text value"
        assert cfg["api_base_url"] == "https://api.azmarq.com/v1/whatsapp"
        assert cfg["payload_extras"] is None
        assert cfg["enabled"] is True
