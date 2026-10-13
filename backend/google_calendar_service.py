"""Google Calendar / Meet integration (one company Google account per tenant)."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
import jwt

from db import get_db
from notification_service import _parse_meeting_dt, _tenant_tz

logger = logging.getLogger("hrmis.google")

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
USERINFO_URI = "https://www.googleapis.com/oauth2/v2/userinfo"
EVENTS_URI = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/calendar"]


def redirect_uri() -> str:
    return os.environ.get("GOOGLE_REDIRECT_URI", "")


async def _app_creds(company_id: str) -> Dict[str, str]:
    """Tenant-saved OAuth client, falling back to server env keys."""
    doc = await get_db().google_app_credentials.find_one({"company_id": company_id}, {"_id": 0}) or {}
    if doc.get("client_id") and doc.get("client_secret"):
        return {"client_id": doc["client_id"], "client_secret": doc["client_secret"], "source": "settings"}
    cid, sec = os.environ.get("GOOGLE_CLIENT_ID", ""), os.environ.get("GOOGLE_CLIENT_SECRET", "")
    return {"client_id": cid, "client_secret": sec, "source": "env" if cid and sec else ""}


async def is_configured(company_id: str) -> bool:
    c = await _app_creds(company_id)
    return bool(c["client_id"] and c["client_secret"] and redirect_uri())


async def save_app_creds(company_id: str, client_id: str, client_secret: Optional[str]) -> None:
    db = get_db()
    update: Dict[str, Any] = {"company_id": company_id, "client_id": client_id.strip(),
                              "updated_at": datetime.now(timezone.utc).isoformat()}
    if client_secret:
        update["client_secret"] = client_secret.strip()
    existing = await db.google_app_credentials.find_one({"company_id": company_id}, {"_id": 0, "client_id": 1})
    await db.google_app_credentials.update_one({"company_id": company_id}, {"$set": update}, upsert=True)
    # A different OAuth client invalidates the existing connection
    if existing and existing.get("client_id") != update["client_id"]:
        await db.google_integrations.delete_one({"company_id": company_id})


async def clear_app_creds(company_id: str) -> None:
    db = get_db()
    await db.google_app_credentials.delete_one({"company_id": company_id})
    await db.google_integrations.delete_one({"company_id": company_id})


async def build_auth_url(company_id: str, user_id: str) -> str:
    creds = await _app_creds(company_id)
    state = jwt.encode(
        {"cid": company_id, "uid": user_id, "exp": datetime.now(timezone.utc) + timedelta(minutes=10)},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    return AUTH_URI + "?" + urlencode({
        "client_id": creds["client_id"],
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    })


def decode_state(state: str) -> Dict[str, Any]:
    return jwt.decode(state, os.environ["JWT_SECRET"], algorithms=["HS256"])


async def exchange_code(company_id: str, user_id: str, code: str) -> str:
    creds = await _app_creds(company_id)
    async with httpx.AsyncClient(timeout=20) as c:
        tok = (await c.post(TOKEN_URI, data={
            "code": code, "client_id": creds["client_id"], "client_secret": creds["client_secret"],
            "redirect_uri": redirect_uri(), "grant_type": "authorization_code",
        })).json()
        if "access_token" not in tok:
            raise ValueError(tok.get("error_description") or tok.get("error") or "Token exchange failed")
        info = (await c.get(USERINFO_URI, headers={"Authorization": f"Bearer {tok['access_token']}"})).json()
    email = info.get("email", "")
    await get_db().google_integrations.update_one(
        {"company_id": company_id},
        {"$set": {
            "company_id": company_id,
            "email": email,
            "access_token": tok["access_token"],
            "refresh_token": tok.get("refresh_token"),
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)) - 60)).isoformat(),
            "connected_by": user_id,
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return email


async def get_status(company_id: str) -> Dict[str, Any]:
    doc = await get_db().google_integrations.find_one({"company_id": company_id}, {"_id": 0, "email": 1, "connected_at": 1})
    creds = await _app_creds(company_id)
    configured = await is_configured(company_id)
    sec = creds["client_secret"]
    return {
        "configured": configured,
        "connected": bool(doc) and configured,
        "creds_source": creds["source"],
        "client_id": creds["client_id"] if creds["source"] == "settings" else "",
        "client_secret_masked": ("••••" + sec[-4:]) if creds["source"] == "settings" and sec else "",
        "email": (doc or {}).get("email"),
        "connected_at": (doc or {}).get("connected_at"),
        "redirect_uri": redirect_uri(),
    }


async def disconnect(company_id: str) -> None:
    db = get_db()
    doc = await db.google_integrations.find_one({"company_id": company_id}, {"_id": 0})
    if doc and doc.get("refresh_token"):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post("https://oauth2.googleapis.com/revoke", params={"token": doc["refresh_token"]})
        except Exception as e:
            logger.warning(f"google revoke failed: {e}")
    await db.google_integrations.delete_one({"company_id": company_id})


async def _access_token(company_id: str) -> Optional[str]:
    if not await is_configured(company_id):
        return None
    creds = await _app_creds(company_id)
    db = get_db()
    doc = await db.google_integrations.find_one({"company_id": company_id}, {"_id": 0})
    if not doc:
        return None
    if doc.get("expires_at", "") > datetime.now(timezone.utc).isoformat():
        return doc["access_token"]
    if not doc.get("refresh_token"):
        return None
    async with httpx.AsyncClient(timeout=20) as c:
        tok = (await c.post(TOKEN_URI, data={
            "client_id": creds["client_id"], "client_secret": creds["client_secret"],
            "refresh_token": doc["refresh_token"], "grant_type": "refresh_token",
        })).json()
    if "access_token" not in tok:
        logger.error(f"google token refresh failed: {tok}")
        return None
    await db.google_integrations.update_one({"company_id": company_id}, {"$set": {
        "access_token": tok["access_token"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)) - 60)).isoformat(),
    }})
    return tok["access_token"]


async def _attendee_emails(company_id: str, user_ids: List[str]) -> List[Dict[str, str]]:
    if not user_ids:
        return []
    users = await get_db().users.find(
        {"id": {"$in": user_ids}, "company_id": company_id}, {"_id": 0, "email": 1, "name": 1},
    ).to_list(500)
    return [{"email": u["email"], "displayName": u.get("name", "")} for u in users if u.get("email")]


async def _event_body(meeting: Dict[str, Any]) -> Dict[str, Any]:
    tz = await _tenant_tz(meeting["company_id"])
    start = _parse_meeting_dt(meeting["starts_at"], tz)
    end = _parse_meeting_dt(meeting["ends_at"], tz)
    desc = meeting.get("description") or ""
    organizer = meeting.get("created_by_name") or ""
    if organizer:
        desc = f"Organised by {organizer} via HRMIS.\n\n{desc}".strip()
    location = meeting.get("room_name") or (meeting.get("location") if meeting.get("location") != "Online" else "")
    return {
        "summary": meeting.get("title", "Meeting"),
        "description": desc,
        "location": location or "",
        "start": {"dateTime": start.isoformat(), "timeZone": tz},
        "end": {"dateTime": end.isoformat(), "timeZone": tz},
        "attendees": await _attendee_emails(meeting["company_id"], meeting.get("attendee_user_ids") or []),
    }


def _extract_meet(ev: Dict[str, Any]) -> Optional[str]:
    if ev.get("hangoutLink"):
        return ev["hangoutLink"]
    for ep in (ev.get("conferenceData") or {}).get("entryPoints", []):
        if ep.get("entryPointType") == "video":
            return ep.get("uri")
    return None


async def create_event(meeting: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Create a Calendar event with a Meet link. Google emails every attendee."""
    try:
        token = await _access_token(meeting["company_id"])
        if not token:
            return None
        body = await _event_body(meeting)
        body["conferenceData"] = {"createRequest": {
            "requestId": str(uuid.uuid4()),
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }}
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(EVENTS_URI, params={"conferenceDataVersion": 1, "sendUpdates": "all"},
                             json=body, headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 300:
            logger.error(f"google create_event failed {r.status_code}: {r.text}")
            return None
        ev = r.json()
        return {"google_event_id": ev["id"], "meet_link": _extract_meet(ev), "google_event_link": ev.get("htmlLink")}
    except Exception as e:
        logger.error(f"google create_event exception: {e}")
        return None


async def update_event(meeting: Dict[str, Any]) -> bool:
    try:
        token = await _access_token(meeting["company_id"])
        if not token or not meeting.get("google_event_id"):
            return False
        body = await _event_body(meeting)
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.patch(f"{EVENTS_URI}/{meeting['google_event_id']}",
                              params={"conferenceDataVersion": 1, "sendUpdates": "all"},
                              json=body, headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 300:
            logger.error(f"google update_event failed {r.status_code}: {r.text}")
            return False
        return True
    except Exception as e:
        logger.error(f"google update_event exception: {e}")
        return False


async def cancel_event(meeting: Dict[str, Any]) -> bool:
    try:
        token = await _access_token(meeting["company_id"])
        if not token or not meeting.get("google_event_id"):
            return False
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.delete(f"{EVENTS_URI}/{meeting['google_event_id']}",
                               params={"sendUpdates": "all"},
                               headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 300 and r.status_code != 410:
            logger.error(f"google cancel_event failed {r.status_code}: {r.text}")
            return False
        return True
    except Exception as e:
        logger.error(f"google cancel_event exception: {e}")
        return False
