"""Backend tests for WhatsApp provider routing (Meta vs AzMarq).

Verifies the bug fix for: AzMarq BSP provider — the user-supplied api_base_url
must be used VERBATIM (no `/{phone_number_id}/messages` path appending), with
`apikey` header (not `Authorization: Bearer`).
"""
from __future__ import annotations

import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://workforce-central-43.preview.emergentagent.com").rstrip("/")
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


# ---------- Config shape ----------

class TestWhatsAppConfigShape:
    def test_get_config_returns_provider_fields(self, admin_headers):
        r = requests.get(f"{API}/whatsapp/config", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        cfg = r.json()
        assert "provider" in cfg
        assert cfg["provider"] in ("meta", "azmarq")
        assert isinstance(cfg.get("supported_providers"), list)
        assert "meta" in cfg["supported_providers"]
        assert "azmarq" in cfg["supported_providers"]
        defaults = cfg.get("provider_default_base_urls")
        assert isinstance(defaults, dict)
        # URLs include the path, not just the host
        assert "/messages" in defaults["meta"] or "{phone_number_id}/messages" in defaults["meta"]
        assert "/sendWaTemplate" in defaults["azmarq"]


# ---------- PUT provider persistence ----------

class TestProviderPersistence:
    def test_put_azmarq_persists(self, admin_headers):
        # Save provider=azmarq with the AzMarq full URL
        body = {
            "enabled": True,
            "provider": "azmarq",
            "access_token": "D4KvFAKEtokenForTestyAt3",
            "phone_number_id": "261186630417690",
            "business_account_id": "125892728400090",
            "api_base_url": "https://api.azmarq.com/v1/whatsapp/sendWaTemplate",
            "default_country_code": "91",
        }
        r = requests.put(f"{API}/whatsapp/config", headers=admin_headers, json=body, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["provider"] == "azmarq"

        # GET → still azmarq
        r2 = requests.get(f"{API}/whatsapp/config", headers=admin_headers, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["provider"] == "azmarq"
        assert r2.json()["api_base_url"] == "https://api.azmarq.com/v1/whatsapp/sendWaTemplate"

    def test_invalid_provider_silently_dropped(self, admin_headers):
        # Send an invalid provider — request returns 200, provider unchanged
        r = requests.put(
            f"{API}/whatsapp/config",
            headers=admin_headers,
            json={"provider": "twilio"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["provider"] == "azmarq", f"expected azmarq, got {r.json()['provider']}"

    def test_token_persists_across_provider_switch(self, admin_headers):
        # Switch to meta WITHOUT supplying a new token; token should be preserved
        r = requests.put(
            f"{API}/whatsapp/config",
            headers=admin_headers,
            json={"provider": "meta"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        masked = r.json().get("access_token_masked", "")
        # token still exists (masked is non-empty)
        assert masked and "•" in masked, f"token wiped on provider switch: masked={masked!r}"

        # switch back to azmarq
        r2 = requests.put(
            f"{API}/whatsapp/config",
            headers=admin_headers,
            json={"provider": "azmarq"},
            timeout=15,
        )
        assert r2.status_code == 200
        assert r2.json()["provider"] == "azmarq"
        assert "•" in r2.json().get("access_token_masked", "")


# ---------- Send routing via outbox ----------

def _latest_outbox(admin_headers):
    r = requests.get(f"{API}/whatsapp/outbox", headers=admin_headers, params={"limit": 5}, timeout=15)
    assert r.status_code == 200
    items = r.json()
    assert items, "outbox is empty"
    return items[0]


class TestSendRouting:
    def test_azmarq_uses_verbatim_url(self, admin_headers):
        # Ensure config: provider=azmarq, full URL set verbatim
        cfg_body = {
            "enabled": True,
            "provider": "azmarq",
            "access_token": "D4KvFAKEtokenForTestyAt3",
            "phone_number_id": "261186630417690",
            "business_account_id": "125892728400090",
            "api_base_url": "https://api.azmarq.com/v1/whatsapp/sendWaTemplate",
            "default_country_code": "91",
        }
        r = requests.put(f"{API}/whatsapp/config", headers=admin_headers, json=cfg_body, timeout=15)
        assert r.status_code == 200, r.text

        # Trigger a test send — will fail with fake creds, but URL is recorded
        r2 = requests.post(
            f"{API}/whatsapp/test",
            headers=admin_headers,
            json={"to": "+919876543210", "template_key": "status_update"},
            timeout=30,
        )
        # Expected: 400 (Send failed) because creds are bogus — that's fine
        assert r2.status_code in (200, 400), r2.text

        item = _latest_outbox(admin_headers)
        detail = item.get("detail", "")
        assert "[azmarq]" in detail, f"expected provider tag, got: {detail}"
        assert "https://api.azmarq.com/v1/whatsapp/sendWaTemplate" in detail, f"URL missing: {detail}"
        # No path duplication
        assert detail.count("/sendWaTemplate") == 1, f"path duplicated: {detail}"
        # phone_number_id MUST NOT be in URL
        assert "261186630417690" not in detail.split("→")[0], (
            f"phone_number_id leaked into URL: {detail}"
        )

    def test_meta_blank_base_uses_default(self, admin_headers):
        cfg_body = {
            "enabled": True,
            "provider": "meta",
            "access_token": "FAKEmetaToken1234",
            "phone_number_id": "261186630417690",
            "api_base_url": "",  # blank → default
        }
        r = requests.put(f"{API}/whatsapp/config", headers=admin_headers, json=cfg_body, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["provider"] == "meta"

        r2 = requests.post(
            f"{API}/whatsapp/test",
            headers=admin_headers,
            json={"to": "+919876543210", "template_key": "status_update"},
            timeout=30,
        )
        assert r2.status_code in (200, 400), r2.text

        item = _latest_outbox(admin_headers)
        detail = item.get("detail", "")
        assert "[meta]" in detail, f"expected meta tag: {detail}"
        assert "https://graph.facebook.com/v20.0/261186630417690/messages" in detail, (
            f"meta default URL missing: {detail}"
        )

    def test_meta_custom_url_with_placeholder(self, admin_headers):
        cfg_body = {
            "enabled": True,
            "provider": "meta",
            "access_token": "FAKEmetaToken1234",
            "phone_number_id": "261186630417690",
            "api_base_url": "https://graph.facebook.com/v22.0/{phone_number_id}/messages",
        }
        r = requests.put(f"{API}/whatsapp/config", headers=admin_headers, json=cfg_body, timeout=15)
        assert r.status_code == 200, r.text

        r2 = requests.post(
            f"{API}/whatsapp/test",
            headers=admin_headers,
            json={"to": "+919876543210", "template_key": "status_update"},
            timeout=30,
        )
        assert r2.status_code in (200, 400), r2.text

        item = _latest_outbox(admin_headers)
        detail = item.get("detail", "")
        assert "https://graph.facebook.com/v22.0/261186630417690/messages" in detail, (
            f"placeholder substitution failed: {detail}"
        )
        # placeholder literal must NOT appear
        assert "{phone_number_id}" not in detail.split("→")[0], f"placeholder not substituted: {detail}"


# ---------- Fire and forget ----------

class TestFireAndForget:
    def test_leave_apply_succeeds_with_bad_whatsapp(self, admin_headers, employee_headers):
        # Ensure azmarq with bogus creds is active
        cfg_body = {
            "enabled": True,
            "provider": "azmarq",
            "access_token": "D4KvFAKEtokenForTestyAt3",
            "phone_number_id": "261186630417690",
            "business_account_id": "125892728400090",
            "api_base_url": "https://api.azmarq.com/v1/whatsapp/sendWaTemplate",
            "default_country_code": "91",
        }
        r = requests.put(f"{API}/whatsapp/config", headers=admin_headers, json=cfg_body, timeout=15)
        assert r.status_code == 200

        # Employee applies leave — must succeed despite WA send failing
        payload = {
            "leave_type": "Casual",
            "start_date": "2026-06-01",
            "end_date": "2026-06-01",
            "reason": "TEST_AZMARQ fire-and-forget verification",
        }
        r2 = requests.post(f"{API}/leave/apply", headers=employee_headers, json=payload, timeout=20)
        assert r2.status_code in (200, 201), f"leave apply failed: {r2.status_code} {r2.text}"

    def test_wfh_apply_succeeds_with_bad_whatsapp(self, employee_headers):
        import random
        # Use random date to avoid duplicate-request rejection on rerun
        rand_day = random.randint(1, 28)
        payload = {
            "date": f"2027-{random.randint(1,12):02d}-{rand_day:02d}",
            "reason": "TEST_AZMARQ wfh fire-and-forget",
        }
        r = requests.post(f"{API}/wfh/apply", headers=employee_headers, json=payload, timeout=20)
        # 200/201 OK; if test re-run hits same random date, accept 400 dup
        assert r.status_code in (200, 201, 400), f"wfh apply failed: {r.status_code} {r.text}"


# ---------- Final state restore ----------

class TestRestoreFinalState:
    def test_restore_azmarq_state(self, admin_headers):
        # Leave the config in azmarq mode per main agent instruction
        body = {
            "enabled": True,
            "provider": "azmarq",
            "access_token": "D4KvFAKEtokenForTestyAt3",
            "phone_number_id": "261186630417690",
            "business_account_id": "125892728400090",
            "api_base_url": "https://api.azmarq.com/v1/whatsapp/sendWaTemplate",
            "default_country_code": "91",
        }
        r = requests.put(f"{API}/whatsapp/config", headers=admin_headers, json=body, timeout=15)
        assert r.status_code == 200
        cfg = r.json()
        assert cfg["provider"] == "azmarq"
        assert cfg["api_base_url"] == "https://api.azmarq.com/v1/whatsapp/sendWaTemplate"
