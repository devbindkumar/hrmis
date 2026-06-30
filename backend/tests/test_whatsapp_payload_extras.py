"""Tests for WhatsApp payload_extras override, AzMarq payload shape, and outbox observability.

Covers iteration_3 bug fix:
- payload_extras round-trips (dict, JSON string, null, malformed)
- AzMarq payload has all required keys + correct phone split
- Outbox stores provider, url, request_payload, response_body, response_status
- Shallow-merge of payload_extras on top of AzMarq defaults
"""
from __future__ import annotations

import json
import os
import random
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@acme.com"
ADMIN_PASSWORD = "Admin@123"
EMP_EMAIL = "maya@acme.com"
EMP_PASSWORD = "Demo@123"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers():
    tok = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def employee_headers():
    tok = _login(EMP_EMAIL, EMP_PASSWORD)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _put(admin_headers, body):
    return requests.put(f"{API}/whatsapp/config", headers=admin_headers, json=body, timeout=15)


def _get(admin_headers):
    return requests.get(f"{API}/whatsapp/config", headers=admin_headers, timeout=15)


def _latest_outbox(admin_headers):
    r = requests.get(f"{API}/whatsapp/outbox", headers=admin_headers, params={"limit": 5}, timeout=15)
    assert r.status_code == 200
    items = r.json()
    assert items, "outbox empty"
    return items[0]


def _set_azmarq_base(admin_headers, payload_extras=None):
    """Reset to known AzMarq config; pass payload_extras explicitly (None to clear)."""
    body = {
        "enabled": True,
        "provider": "azmarq",
        "access_token": "D4KvFAKEtokenForTestyAt3",
        "phone_number_id": "261186630417690",
        "business_account_id": "125892728400090",
        "api_base_url": "https://api.azmarq.com/v1/whatsapp/sendWaTemplate",
        "default_country_code": "91",
        "payload_extras": payload_extras,
    }
    r = _put(admin_headers, body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- payload_extras round-trip ----------

class TestPayloadExtrasRoundTrip:
    def test_get_returns_payload_extras_field(self, admin_headers):
        # Clear it first
        _set_azmarq_base(admin_headers, payload_extras=None)
        r = _get(admin_headers)
        assert r.status_code == 200
        cfg = r.json()
        assert "payload_extras" in cfg
        assert cfg["payload_extras"] is None

    def test_put_dict_then_get_roundtrip(self, admin_headers):
        extras = {"k": "v", "n": 7, "nested": {"a": 1}}
        r = _put(admin_headers, {"payload_extras": extras})
        assert r.status_code == 200, r.text
        cfg = _get(admin_headers).json()
        assert cfg["payload_extras"] == extras

    def test_put_json_string_parses(self, admin_headers):
        # Send a JSON-formatted STRING
        extras = {"campaignName": "TEST123", "customField": 42}
        r = _put(admin_headers, {"payload_extras": json.dumps(extras)})
        assert r.status_code == 200, r.text
        cfg = _get(admin_headers).json()
        assert cfg["payload_extras"] == extras

    def test_put_null_clears(self, admin_headers):
        # First set something
        _put(admin_headers, {"payload_extras": {"x": 1}})
        # Then clear
        r = _put(admin_headers, {"payload_extras": None})
        assert r.status_code == 200
        cfg = _get(admin_headers).json()
        assert cfg["payload_extras"] is None

    def test_malformed_json_string_does_not_crash(self, admin_headers):
        # Set a known value first
        _put(admin_headers, {"payload_extras": {"keep": "this"}})
        # Send malformed JSON string — request must succeed, value preserved
        r = _put(admin_headers, {"payload_extras": "{not valid json"})
        assert r.status_code == 200, r.text
        cfg = _get(admin_headers).json()
        # Existing value remains (silently ignored malformed input)
        assert cfg["payload_extras"] == {"keep": "this"}


# ---------- AzMarq payload shape & merge ----------

class TestAzMarqPayloadShape:
    """OBSOLETE — Iteration 5 rebuilt the AzMarq payload to match the customer's
    working curl. The new 6-key shape (from/campaignName/to/templateName/components/type)
    is verified in test_whatsapp_azmarq_v2_payload.py. The old shape assertions below
    (countryCode/phoneNumber/wabaId/headerType:NONE/template-object/components-array)
    are intentionally retired — payload schema legitimately changed.
    """
    pytestmark = pytest.mark.skip(reason="Old AzMarq payload shape retired in iteration 5 — see test_whatsapp_azmarq_v2_payload.py")

    def test_default_azmarq_payload_has_required_keys(self, admin_headers):
        _set_azmarq_base(admin_headers, payload_extras=None)
        r = requests.post(
            f"{API}/whatsapp/test",
            headers=admin_headers,
            json={"to": "+918826471808", "template_key": "status_update"},
            timeout=30,
        )
        assert r.status_code in (200, 400), r.text
        item = _latest_outbox(admin_headers)
        payload = item.get("request_payload")
        assert isinstance(payload, dict), f"request_payload missing/invalid: {item}"
        # Root keys
        for key in ("to", "countryCode", "phoneNumber", "from", "senderMobile",
                    "senderMobileNumber", "senderNumber", "wabaId", "headerType",
                    "type", "template"):
            assert key in payload, f"missing root key {key}; payload={payload}"
        assert payload["headerType"] == "NONE"
        assert payload["type"] == "Template"
        # Template subdoc
        tpl = payload["template"]
        assert isinstance(tpl, dict)
        assert "name" in tpl
        assert "languageCode" in tpl
        assert isinstance(tpl.get("language"), dict)
        assert "code" in tpl["language"]
        assert tpl.get("headerType") == "NONE"
        comps = tpl.get("components")
        assert isinstance(comps, list) and len(comps) >= 1
        body_comp = comps[0]
        assert body_comp.get("type") == "BODY"
        bv = body_comp.get("bodyValues")
        assert isinstance(bv, list) and all(isinstance(x, str) for x in bv)

    def test_phone_split_with_default_cc(self, admin_headers):
        _set_azmarq_base(admin_headers, payload_extras=None)
        r = requests.post(
            f"{API}/whatsapp/test",
            headers=admin_headers,
            json={"to": "918826471808", "template_key": "status_update"},
            timeout=30,
        )
        assert r.status_code in (200, 400)
        item = _latest_outbox(admin_headers)
        payload = item["request_payload"]
        assert payload["countryCode"] == "+91", payload
        assert payload["phoneNumber"] == "8826471808", payload

    def test_phone_split_fallback_last_10(self, admin_headers):
        # Clear default_country_code
        _put(admin_headers, {"default_country_code": ""})
        _set_azmarq_base_no_cc = {
            "enabled": True,
            "provider": "azmarq",
            "api_base_url": "https://api.azmarq.com/v1/whatsapp/sendWaTemplate",
            "default_country_code": "",
            "payload_extras": None,
        }
        r = _put(admin_headers, _set_azmarq_base_no_cc)
        assert r.status_code == 200
        r = requests.post(
            f"{API}/whatsapp/test",
            headers=admin_headers,
            json={"to": "+11234567890", "template_key": "status_update"},
            timeout=30,
        )
        assert r.status_code in (200, 400)
        item = _latest_outbox(admin_headers)
        payload = item["request_payload"]
        # last 10 digits go to phoneNumber, rest to countryCode
        assert payload["phoneNumber"] == "1234567890", payload
        assert payload["countryCode"] == "+1", payload
        # restore CC
        _set_azmarq_base(admin_headers, payload_extras=None)

    def test_extras_shallow_merge(self, admin_headers):
        extras = {"campaignName": "TEST123", "customField": 42}
        _set_azmarq_base(admin_headers, payload_extras=extras)
        r = requests.post(
            f"{API}/whatsapp/test",
            headers=admin_headers,
            json={"to": "+918826471808", "template_key": "status_update"},
            timeout=30,
        )
        assert r.status_code in (200, 400)
        item = _latest_outbox(admin_headers)
        payload = item["request_payload"]
        assert payload.get("campaignName") == "TEST123", f"extras not merged: {payload}"
        assert payload.get("customField") == 42, f"extras not merged: {payload}"
        # default keys still present
        assert payload.get("wabaId") == "125892728400090"

    def test_extras_cleared_removes_merge(self, admin_headers):
        # First merge
        _set_azmarq_base(admin_headers, payload_extras={"campaignName": "FOOBAR"})
        # Now clear
        _set_azmarq_base(admin_headers, payload_extras=None)
        r = requests.post(
            f"{API}/whatsapp/test",
            headers=admin_headers,
            json={"to": "+918826471808", "template_key": "status_update"},
            timeout=30,
        )
        assert r.status_code in (200, 400)
        item = _latest_outbox(admin_headers)
        payload = item["request_payload"]
        assert "campaignName" not in payload, f"extras leaked after clear: {payload}"


# ---------- Outbox row enrichment ----------

class TestOutboxFields:
    def test_outbox_has_five_new_fields(self, admin_headers):
        _set_azmarq_base(admin_headers, payload_extras={"obKey": "obVal"})
        r = requests.post(
            f"{API}/whatsapp/test",
            headers=admin_headers,
            json={"to": "+918826471808", "template_key": "status_update"},
            timeout=30,
        )
        assert r.status_code in (200, 400)
        item = _latest_outbox(admin_headers)
        for k in ("provider", "url", "request_payload", "response_body", "response_status"):
            assert k in item, f"outbox missing key {k}; item={item}"
        assert item["provider"] == "azmarq"
        assert "azmarq.com" in (item["url"] or "")
        assert isinstance(item["request_payload"], dict)
        # response_status may be None on exception, int otherwise — accept both
        assert item["response_status"] is None or isinstance(item["response_status"], int)
        # response_body capped at 4000
        rb = item.get("response_body") or ""
        assert len(rb) <= 4000

    def test_request_payload_bson_friendly(self, admin_headers):
        # Ensure dict survives roundtrip (no string-coerced JSON)
        extras = {"strKey": "abc", "intKey": 9, "list": [1, 2, 3]}
        _set_azmarq_base(admin_headers, payload_extras=extras)
        requests.post(
            f"{API}/whatsapp/test",
            headers=admin_headers,
            json={"to": "+918826471808", "template_key": "status_update"},
            timeout=30,
        )
        item = _latest_outbox(admin_headers)
        pl = item["request_payload"]
        assert isinstance(pl, dict)
        assert pl.get("strKey") == "abc"
        assert pl.get("intKey") == 9
        assert pl.get("list") == [1, 2, 3]


# ---------- Fire and forget regression ----------

class TestFireAndForgetRegression:
    def test_wfh_apply_succeeds_with_bogus_azmarq(self, admin_headers, employee_headers):
        _set_azmarq_base(admin_headers, payload_extras={"campaignName": "FNFTEST"})
        rand_day = random.randint(1, 28)
        rand_month = random.randint(1, 12)
        payload = {
            "date": f"2028-{rand_month:02d}-{rand_day:02d}",
            "reason": "TEST fire-and-forget WFH",
        }
        r = requests.post(f"{API}/wfh/apply", headers=employee_headers, json=payload, timeout=20)
        assert r.status_code in (200, 201, 400), f"wfh apply failed: {r.status_code} {r.text}"


# ---------- Final restore ----------

class TestRestoreFinalState:
    def test_restore_clean_state(self, admin_headers):
        # Per main agent: leave provider=azmarq, api_base_url verbatim, payload_extras=null
        body = {
            "enabled": True,
            "provider": "azmarq",
            "access_token": "D4KvFAKEtokenForTestyAt3",
            "phone_number_id": "261186630417690",
            "business_account_id": "125892728400090",
            "api_base_url": "https://api.azmarq.com/v1/whatsapp",
            "default_country_code": "91",
            "payload_extras": None,
        }
        r = _put(admin_headers, body)
        assert r.status_code == 200
        cfg = _get(admin_headers).json()
        assert cfg["provider"] == "azmarq"
        assert cfg["api_base_url"] == "https://api.azmarq.com/v1/whatsapp"
        assert cfg["payload_extras"] is None
