"""WhatsApp Business Cloud API service.

Sends template-based notifications to reporting managers and other recipients.
Configuration is per-tenant (company), stored in MongoDB `whatsapp_configs`.

Never raises in user flows — always logs and returns False on failure so it
does NOT break the parent HR action (apply leave, check in, etc.).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from db import get_db

logger = logging.getLogger("hrmis.whatsapp")

GRAPH_API_VERSION = "v20.0"
GRAPH_BASE_URL = "https://graph.facebook.com"
DEFAULT_API_BASE_URL = f"{GRAPH_BASE_URL}/{GRAPH_API_VERSION}"

DEFAULT_TEMPLATES = {
    "status_update": "hrmis_status_update",
    "leave_request": "hrmis_leave_request",
    "wfh_request": "hrmis_wfh_request",
    "meeting_scheduled": "hrmis_meeting_scheduled",
    "checkin_checkout": "hrmis_checkin_checkout",
}

DEFAULT_EVENTS_ENABLED = {
    "status_update": True,
    "leave_request": True,
    "wfh_request": True,
    "meeting_scheduled": True,
    "checkin_checkout": True,
}

# Only these statuses trigger a WA notification when "status_update" is enabled
DEFAULT_STATUS_FILTERS = ["on_break", "in_meeting", "remote", "wfh"]

# Supported providers
PROVIDER_META = "meta"
PROVIDER_AZMARQ = "azmarq"
SUPPORTED_PROVIDERS = [PROVIDER_META, PROVIDER_AZMARQ]
DEFAULT_PROVIDER = PROVIDER_META

# Default full send URLs per provider (used when tenant leaves api_base_url blank).
# For Meta the `{phone_number_id}` placeholder is substituted at send-time.
PROVIDER_DEFAULT_SEND_URLS = {
    PROVIDER_META: "https://graph.facebook.com/v20.0/{phone_number_id}/messages",
    PROVIDER_AZMARQ: "https://api.azmarq.com/v1/whatsapp/sendWaTemplate",
}

# Display-only base URL hints (shown in UI as the "default" for each provider)
PROVIDER_DEFAULT_BASE_URLS = {
    PROVIDER_META: "https://graph.facebook.com/v20.0/{phone_number_id}/messages",
    PROVIDER_AZMARQ: "https://api.azmarq.com/v1/whatsapp/sendWaTemplate",
}


def _mask_token(token: Optional[str]) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "•" * len(token)
    return token[:4] + "•" * (len(token) - 8) + token[-4:]


def _clean_phone(raw: Optional[str], default_cc: Optional[str] = None) -> Optional[str]:
    """Return a digits-only international phone (no '+', no spaces).

    If the number lacks a country code and `default_cc` is provided, prepend it.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if default_cc:
        cc = re.sub(r"\D", "", default_cc)
        if cc and not digits.startswith(cc) and len(digits) <= 10:
            digits = cc + digits
    return digits


async def get_config(company_id: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    cfg = await db.whatsapp_configs.find_one({"company_id": company_id}, {"_id": 0})
    return cfg


async def get_config_public(company_id: str) -> Dict[str, Any]:
    """Same as get_config but masks the access token (for safe API responses)."""
    cfg = await get_config(company_id)
    if not cfg:
        return {
            "company_id": company_id,
            "enabled": False,
            "provider": DEFAULT_PROVIDER,
            "supported_providers": SUPPORTED_PROVIDERS,
            "access_token": "",
            "access_token_masked": "",
            "phone_number_id": "",
            "business_account_id": "",
            "default_country_code": "",
            "api_base_url": "",
            "default_api_base_url": DEFAULT_API_BASE_URL,
            "provider_default_base_urls": PROVIDER_DEFAULT_BASE_URLS,
            "templates": DEFAULT_TEMPLATES.copy(),
            "events_enabled": DEFAULT_EVENTS_ENABLED.copy(),
            "status_filters": DEFAULT_STATUS_FILTERS.copy(),
        }
    tok = cfg.get("access_token") or ""
    return {
        "company_id": company_id,
        "enabled": bool(cfg.get("enabled", False)),
        "provider": cfg.get("provider") or DEFAULT_PROVIDER,
        "supported_providers": SUPPORTED_PROVIDERS,
        "access_token": "",  # never expose
        "access_token_masked": _mask_token(tok),
        "phone_number_id": cfg.get("phone_number_id", ""),
        "business_account_id": cfg.get("business_account_id", ""),
        "default_country_code": cfg.get("default_country_code", ""),
        "api_base_url": cfg.get("api_base_url", ""),
        "default_api_base_url": DEFAULT_API_BASE_URL,
        "provider_default_base_urls": PROVIDER_DEFAULT_BASE_URLS,
        "templates": {**DEFAULT_TEMPLATES, **(cfg.get("templates") or {})},
        "events_enabled": {**DEFAULT_EVENTS_ENABLED, **(cfg.get("events_enabled") or {})},
        "status_filters": cfg.get("status_filters") or DEFAULT_STATUS_FILTERS.copy(),
    }


async def upsert_config(company_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    db = get_db()
    existing = await db.whatsapp_configs.find_one({"company_id": company_id}, {"_id": 0}) or {}

    update: Dict[str, Any] = {"company_id": company_id}
    for k in ("enabled", "provider", "phone_number_id", "business_account_id", "default_country_code", "api_base_url"):
        if k in payload and payload[k] is not None:
            val = payload[k]
            # normalise api_base_url: strip trailing slash, allow empty to reset to default
            if k == "api_base_url" and isinstance(val, str):
                val = val.strip().rstrip("/")
            if k == "provider" and isinstance(val, str):
                val = val.strip().lower()
                if val not in SUPPORTED_PROVIDERS:
                    continue
            update[k] = val

    # Only overwrite token if a new one is supplied AND it is not the masked placeholder
    new_tok = payload.get("access_token")
    if new_tok and "•" not in new_tok:
        update["access_token"] = new_tok
    elif "access_token" in existing:
        update["access_token"] = existing["access_token"]

    if "templates" in payload and isinstance(payload["templates"], dict):
        merged = {**DEFAULT_TEMPLATES, **(existing.get("templates") or {}), **payload["templates"]}
        update["templates"] = merged
    if "events_enabled" in payload and isinstance(payload["events_enabled"], dict):
        merged = {**DEFAULT_EVENTS_ENABLED, **(existing.get("events_enabled") or {}), **payload["events_enabled"]}
        update["events_enabled"] = merged
    if "status_filters" in payload and isinstance(payload["status_filters"], list):
        update["status_filters"] = payload["status_filters"]

    await db.whatsapp_configs.update_one(
        {"company_id": company_id},
        {"$set": update},
        upsert=True,
    )
    return await get_config_public(company_id)


def _build_meta_payload(
    to_number: str,
    template_name: str,
    params: List[str],
    language_code: str = "en_US",
) -> Dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in params],
                }
            ],
        },
    }


def _build_azmarq_payload(
    to_number: str,
    template_name: str,
    params: List[str],
    language_code: str,
    sender_id: str,
    waba_id: str,
) -> Dict[str, Any]:
    return {
        "to": to_number,
        "from": sender_id,
        "template_name": template_name,
        "language": language_code,
        "components": [
            {
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in params],
            }
        ],
        "wabaId": waba_id,
    }


def _extract_message_id(provider: str, data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    if provider == PROVIDER_META:
        messages = data.get("messages") or []
        if messages and isinstance(messages, list):
            return messages[0].get("id")
    if provider == PROVIDER_AZMARQ:
        # AzMarq responses commonly use message_id or messageId
        return data.get("message_id") or data.get("messageId") or data.get("id")
    return None


async def send_template(
    company_id: str,
    to_number: str,
    template_name: str,
    params: List[str],
    language_code: str = "en_US",
) -> Dict[str, Any]:
    """Send a WhatsApp template message via the tenant's configured provider.

    Supports two providers (selected via `provider` field in config):
      - "meta"   → Meta Cloud API (Graph API)
      - "azmarq" → AzMarq BSP gateway

    Does NOT raise on failure — always logs and returns {"sent": False, "error": ...}.
    """
    cfg = await get_config(company_id)
    if not cfg or not cfg.get("enabled"):
        return {"sent": False, "error": "WhatsApp not enabled for this company"}

    provider = (cfg.get("provider") or DEFAULT_PROVIDER).lower()
    if provider not in SUPPORTED_PROVIDERS:
        return {"sent": False, "error": f"Unsupported provider: {provider}"}

    token = cfg.get("access_token")
    phone_number_id = cfg.get("phone_number_id")
    if not token:
        return {"sent": False, "error": "Missing access_token / API key"}
    if not phone_number_id:
        return {"sent": False, "error": "Missing phone_number_id / sender ID"}

    to_clean = _clean_phone(to_number, cfg.get("default_country_code"))
    if not to_clean:
        return {"sent": False, "error": "Invalid recipient phone"}

    # Resolve the FULL send URL.
    # User-provided `api_base_url` (if any) is used VERBATIM as the destination —
    # we only substitute the `{phone_number_id}` placeholder. This way the super
    # admin can paste the exact endpoint their BSP told them to hit, e.g.
    #   https://api.azmarq.com/v1/whatsapp/sendWaTemplate
    # or for Meta:
    #   https://graph.facebook.com/v20.0/{phone_number_id}/messages
    custom_url = (cfg.get("api_base_url") or "").strip()
    if custom_url:
        url = custom_url.replace("{phone_number_id}", phone_number_id)
    else:
        default_url = PROVIDER_DEFAULT_SEND_URLS.get(provider) or PROVIDER_DEFAULT_SEND_URLS[PROVIDER_META]
        url = default_url.replace("{phone_number_id}", phone_number_id)

    if provider == PROVIDER_META:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = _build_meta_payload(to_clean, template_name, params, language_code)
    elif provider == PROVIDER_AZMARQ:
        headers = {
            "apikey": token,
            "Content-Type": "application/json",
        }
        payload = _build_azmarq_payload(
            to_clean,
            template_name,
            params,
            language_code,
            sender_id=phone_number_id,
            waba_id=cfg.get("business_account_id") or "",
        )
    else:
        return {"sent": False, "error": f"Unsupported provider: {provider}"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            ok = resp.status_code < 400
            # AzMarq sometimes returns 200 with {"status":"error"} — treat as failure
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}
            if ok and isinstance(data, dict) and provider == PROVIDER_AZMARQ:
                status_val = str(data.get("status", "")).lower()
                if status_val and status_val not in ("success", "ok", "sent", "queued", "submitted"):
                    ok = False
            if not ok:
                logger.error(
                    f"[whatsapp:{provider}] send_template failed status={resp.status_code} "
                    f"body={resp.text} url={url} template={template_name} to={to_clean}"
                )
                await _log_outbox(
                    company_id, to_clean, template_name, params, "failed",
                    f"[{provider}] {url} → {resp.status_code} {resp.text}",
                )
                return {"sent": False, "status": resp.status_code, "error": resp.text}
            msg_id = _extract_message_id(provider, data)
            logger.info(f"[whatsapp:{provider}] sent template={template_name} to={to_clean} id={msg_id}")
            await _log_outbox(
                company_id, to_clean, template_name, params, "sent",
                f"[{provider}] id={msg_id or '-'}",
            )
            return {"sent": True, "message_id": msg_id, "provider": provider, "raw": data}
    except Exception as e:
        logger.error(f"[whatsapp:{provider}] send_template exception: {e}")
        await _log_outbox(
            company_id, to_clean, template_name, params, "exception",
            f"[{provider}] {url} → {e}",
        )
        return {"sent": False, "error": str(e)}


async def _log_outbox(
    company_id: str,
    to_number: str,
    template_name: str,
    params: List[str],
    status: str,
    detail: str,
) -> None:
    """Persist every send attempt for audit/troubleshooting."""
    try:
        import uuid
        from datetime import datetime, timezone
        db = get_db()
        await db.whatsapp_outbox.insert_one({
            "id": str(uuid.uuid4()),
            "company_id": company_id,
            "to": to_number,
            "template": template_name,
            "params": params,
            "status": status,
            "detail": detail[:2000] if detail else "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error(f"[whatsapp] outbox log failed: {e}")


async def list_outbox(company_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    db = get_db()
    items = await db.whatsapp_outbox.find(
        {"company_id": company_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(limit)
    return items
