"""Admin routes for WhatsApp Business integration.

Endpoints (all require super_admin/hr role within the tenant):
- GET    /api/whatsapp/config         → current config (token masked)
- PUT    /api/whatsapp/config         → upsert config
- POST   /api/whatsapp/test           → send a test template to a phone
- GET    /api/whatsapp/outbox         → recent send attempts (audit)
- GET    /api/whatsapp/templates      → meta-approval template specs (read-only)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_roles
from tenant import company_id_of
from whatsapp_service import (
    DEFAULT_EVENTS_ENABLED,
    DEFAULT_STATUS_FILTERS,
    DEFAULT_TEMPLATES,
    get_config_public,
    list_outbox,
    send_template,
    upsert_config,
)

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


# ---------- payloads ----------

class WhatsAppConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    provider: Optional[str] = None
    access_token: Optional[str] = None
    phone_number_id: Optional[str] = None
    business_account_id: Optional[str] = None
    default_country_code: Optional[str] = None
    api_base_url: Optional[str] = None
    payload_extras: Optional[Any] = None
    templates: Optional[Dict[str, str]] = None
    events_enabled: Optional[Dict[str, bool]] = None
    status_filters: Optional[List[str]] = None


class TestSend(BaseModel):
    to: str = Field(min_length=5)
    template_key: str = Field(default="status_update")  # which template to test


# ---------- routes ----------

@router.get("/config")
async def get_whatsapp_config(admin: dict = Depends(require_roles("super_admin", "hr"))):
    return await get_config_public(company_id_of(admin))


@router.put("/config")
async def update_whatsapp_config(
    body: WhatsAppConfigUpdate,
    admin: dict = Depends(require_roles("super_admin", "hr")),
):
    # Use exclude_unset (not exclude_none) so an explicit `null` value from the
    # client is forwarded to the upsert layer — this lets the admin clear
    # fields like `payload_extras` by sending null.
    payload = body.model_dump(exclude_unset=True)
    return await upsert_config(company_id_of(admin), payload)


@router.post("/test")
async def test_send(
    body: TestSend,
    admin: dict = Depends(require_roles("super_admin", "hr")),
):
    cid = company_id_of(admin)
    cfg = await get_config_public(cid)
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="WhatsApp is not enabled. Save credentials and enable it first.")
    template_name = (cfg.get("templates") or {}).get(body.template_key)
    if not template_name:
        raise HTTPException(status_code=400, detail=f"Unknown template key: {body.template_key}")
    # Build sample params per template so the test mirrors production payload shape
    sample_params = _sample_params_for(body.template_key, admin.get("name", "Manager"))
    result = await send_template(cid, body.to, template_name, sample_params)
    if not result.get("sent"):
        raise HTTPException(status_code=400, detail=result.get("error", "Send failed"))
    return result


@router.get("/outbox")
async def outbox(admin: dict = Depends(require_roles("super_admin", "hr")), limit: int = 50):
    return await list_outbox(company_id_of(admin), limit=limit)


@router.get("/templates")
async def template_specs(_: dict = Depends(require_roles("super_admin", "hr"))):
    """Return the Meta-approval template specs the customer must create.

    The customer copies these *exactly* into Meta WhatsApp Manager → Message
    Templates. Category: UTILITY. Language: English (en_US).
    """
    return {
        "language": "en_US",
        "category": "UTILITY",
        "templates": [
            {
                "key": "status_update",
                "name": DEFAULT_TEMPLATES["status_update"],
                "body": "Hi {{1}}, {{2}} has updated their work status to *{{3}}* at {{4}}.\n\n— HRMIS",
                "variables": ["Manager name", "Employee name", "Status", "Time"],
                "example": {
                    "body_text": [["Alex", "Maya Chen", "On Break", "12 Feb 2026, 11:30 UTC"]]
                },
            },
            {
                "key": "leave_request",
                "name": DEFAULT_TEMPLATES["leave_request"],
                "body": (
                    "Hi {{1}}, {{2}} has applied for *{{3}}* leave from {{4}} to {{5}}.\n"
                    "Reason: {{6}}\n\nLogin to HRMIS to approve or reject."
                ),
                "variables": ["Manager name", "Employee name", "Leave type", "Start date", "End date", "Reason"],
                "example": {
                    "body_text": [["Alex", "Maya Chen", "Casual", "2026-02-14", "2026-02-16", "Family event"]]
                },
            },
            {
                "key": "wfh_request",
                "name": DEFAULT_TEMPLATES["wfh_request"],
                "body": (
                    "Hi {{1}}, {{2}} has requested Work From Home on {{3}}.\n"
                    "Reason: {{4}}\n\nLogin to HRMIS to approve or reject."
                ),
                "variables": ["Manager name", "Employee name", "Date", "Reason"],
                "example": {
                    "body_text": [["Alex", "Maya Chen", "2026-02-14", "Plumber visiting at home"]]
                },
            },
            {
                "key": "meeting_scheduled",
                "name": DEFAULT_TEMPLATES["meeting_scheduled"],
                "body": (
                    "Hi {{1}}, {{2}} has scheduled a meeting *{{3}}* on {{4}} at {{5}}.\n\n"
                    "Login to HRMIS to view details."
                ),
                "variables": ["Attendee name", "Organizer name", "Meeting title", "Date", "Time / Location"],
                "example": {
                    "body_text": [["Maya Chen", "Alex Carter", "Sprint Planning", "2026-02-14", "10:30"]]
                },
            },
            {
                "key": "checkin_checkout",
                "name": DEFAULT_TEMPLATES["checkin_checkout"],
                "body": "Hi {{1}}, {{2}} has *{{3}}* at {{4}}.\n\n— HRMIS",
                "variables": ["Manager name", "Employee name", "Action (Checked In / Checked Out)", "Time"],
                "example": {
                    "body_text": [["Alex", "Maya Chen", "Checked In", "12 Feb 2026, 09:05 UTC"]]
                },
            },
        ],
        "defaults": {
            "events_enabled": DEFAULT_EVENTS_ENABLED,
            "status_filters": DEFAULT_STATUS_FILTERS,
        },
    }


def _sample_params_for(key: str, manager_name: str) -> List[str]:
    if key == "status_update":
        return [manager_name, "Test Employee", "On Break", "12 Feb 2026, 11:30 UTC"]
    if key == "leave_request":
        return [manager_name, "Test Employee", "Casual", "2026-02-14", "2026-02-16", "Test reason"]
    if key == "wfh_request":
        return [manager_name, "Test Employee", "2026-02-14", "Test reason"]
    if key == "meeting_scheduled":
        return ["Test Employee", manager_name, "HRMIS Test Meeting", "2026-02-14", "10:30"]
    if key == "checkin_checkout":
        return [manager_name, "Test Employee", "Checked In", "12 Feb 2026, 09:05 UTC"]
    return [manager_name, "Test Employee", "Event", "now"]
