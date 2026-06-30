"""Verify partial PUT to /api/whatsapp/config preserves untouched fields.

This is the secondary scenario of the exclude_unset fix in routes/whatsapp.py.
A client sending only {"enabled": true} must NOT overwrite provider, access_token,
phone_number_id, payload_extras, etc., to None.
"""
from __future__ import annotations

import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@acme.com"
ADMIN_PASSWORD = "Admin@123"


@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


def _put(h, body):
    return requests.put(f"{API}/whatsapp/config", headers=h, json=body, timeout=15)


def _get(h):
    return requests.get(f"{API}/whatsapp/config", headers=h, timeout=15)


def test_partial_put_enabled_only_preserves_other_fields(admin_headers):
    # 1) Set full config including payload_extras
    full = {
        "enabled": True,
        "provider": "azmarq",
        "access_token": "TEST_partial_token_xyz",
        "phone_number_id": "261186630417690",
        "business_account_id": "125892728400090",
        "api_base_url": "https://api.azmarq.com/v1/whatsapp",
        "default_country_code": "91",
        "payload_extras": {"campaignName": "PARTIAL_TEST", "x": 1},
    }
    r = _put(admin_headers, full)
    assert r.status_code == 200, r.text

    before = _get(admin_headers).json()
    assert before["provider"] == "azmarq"
    assert before["phone_number_id"] == "261186630417690"
    assert before["business_account_id"] == "125892728400090"
    assert before["api_base_url"] == "https://api.azmarq.com/v1/whatsapp"
    assert before["default_country_code"] == "91"
    assert before["payload_extras"] == {"campaignName": "PARTIAL_TEST", "x": 1}
    assert before["enabled"] is True

    # 2) Partial PUT with only "enabled": True (toggle test — sending the SAME value)
    r2 = _put(admin_headers, {"enabled": True})
    assert r2.status_code == 200, r2.text

    after = _get(admin_headers).json()

    # All other fields preserved
    assert after["enabled"] is True
    assert after["provider"] == "azmarq", f"provider wiped! after={after}"
    assert after["phone_number_id"] == "261186630417690", f"phone_number_id wiped! after={after}"
    assert after["business_account_id"] == "125892728400090", f"business_account_id wiped! after={after}"
    assert after["api_base_url"] == "https://api.azmarq.com/v1/whatsapp", f"api_base_url wiped! after={after}"
    assert after["default_country_code"] == "91", f"cc wiped! after={after}"
    assert after["payload_extras"] == {"campaignName": "PARTIAL_TEST", "x": 1}, f"payload_extras wiped! after={after}"


def test_partial_put_toggle_disabled_then_enabled_preserves_creds(admin_headers):
    # Disable only
    r = _put(admin_headers, {"enabled": False})
    assert r.status_code == 200
    mid = _get(admin_headers).json()
    assert mid["enabled"] is False
    assert mid["provider"] == "azmarq"
    assert mid["phone_number_id"] == "261186630417690"

    # Re-enable only
    r = _put(admin_headers, {"enabled": True})
    assert r.status_code == 200
    after = _get(admin_headers).json()
    assert after["enabled"] is True
    assert after["provider"] == "azmarq"
    assert after["phone_number_id"] == "261186630417690"
    assert after["payload_extras"] == {"campaignName": "PARTIAL_TEST", "x": 1}


def test_final_restore_clean_state(admin_headers):
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
    assert cfg["payload_extras"] is None
    assert cfg["provider"] == "azmarq"
    assert cfg["api_base_url"] == "https://api.azmarq.com/v1/whatsapp"
    assert cfg["enabled"] is True
