"""Iter27 — WhatsApp meeting_updated / meeting_cancelled templates and smart routing.

Covers:
 1. GET /api/whatsapp/templates returns both new template cards with correct vars count.
 2. POST /api/whatsapp/test for both new template keys writes an outbox row with the
    expected number of non-empty params (send itself may fail against real AzMarq).
 3. PATCH /api/meetings/{id} smart routing: retained → meeting_updated (6 params),
    added → meeting_scheduled (5 params) + in-app meeting_invite,
    removed → meeting_cancelled (5 params) + in-app meeting_cancelled.
 4. DELETE /api/meetings/{id} → every attendee with phone gets meeting_cancelled (5 params)
    + in-app meeting_cancelled.
 5. Disabling events_enabled.meeting_updated / meeting_cancelled stops the WA sends.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://workforce-central-43.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@acme.com", "Admin@123")
ALEX = ("alex@acme.com", "Demo@123")

# Users known to have phone numbers (from employees collection)
MAYA_EMAIL = "maya@acme.com"      # +919812345678
DIEGO_EMAIL = "diego@acme.com"    # +919812345679
LENA_EMAIL = "lena@acme.com"      # +1 (415) 555-1006
MARCUS_EMAIL = "marcus@acme.com"  # +1 (415) 555-1002


# ---------- fixtures ----------

def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def alex_token() -> str:
    return _login(*ALEX)


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def alex_headers(alex_token):
    return {"Authorization": f"Bearer {alex_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def users_by_email(admin_headers):
    """Fetch /employees and index by email → user_id."""
    r = requests.get(f"{API}/employees", headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    out = {}
    for e in r.json():
        if e.get("email") and e.get("user_id"):
            out[e["email"]] = e["user_id"]
    return out


def _future_iso(hours_from_now: int, minutes: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(hours=hours_from_now, minutes=minutes)
    # make it a naive-looking string (what the form sends) WITHOUT Z — but
    # backend accepts both. Keep Z form for sortability.
    return dt.strftime("%Y-%m-%dT%H:%M:00")


def _recent_outbox(admin_headers, since_ts: str, template: str = None, to: str = None):
    r = requests.get(f"{API}/whatsapp/outbox?limit=200", headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    items = r.json()
    out = []
    for it in items:
        if it.get("created_at", "") < since_ts:
            continue
        if template and it.get("template") != template:
            continue
        if to and (it.get("to") or "").lstrip("+") != to.lstrip("+"):
            continue
        out.append(it)
    return out


# ---------- 1. templates endpoint ----------

class TestTemplatesEndpoint:
    def test_templates_include_meeting_updated_and_cancelled(self, admin_headers):
        r = requests.get(f"{API}/whatsapp/templates", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        by_key = {t["key"]: t for t in data["templates"]}

        assert "meeting_updated" in by_key
        tu = by_key["meeting_updated"]
        assert tu["name"] == "hrmis_meeting_updated"
        assert len(tu["variables"]) == 7
        assert "{{6}}" in tu["body"]
        assert len(tu["example"]["body_text"][0]) == 7

        assert "meeting_cancelled" in by_key
        tc = by_key["meeting_cancelled"]
        assert tc["name"] == "hrmis_meeting_cancelled"
        assert len(tc["variables"]) == 5
        assert "{{5}}" in tc["body"]
        assert "{{6}}" not in tc["body"]
        assert len(tc["example"]["body_text"][0]) == 5


# ---------- 2. /whatsapp/test outbox params ----------

class TestWhatsAppTestSend:
    def test_test_send_meeting_updated_logs_6_params(self, admin_headers):
        since = datetime.now(timezone.utc).isoformat()
        payload = {"to": "+919812345678", "template_key": "meeting_updated"}
        r = requests.post(f"{API}/whatsapp/test", headers=admin_headers, json=payload, timeout=30)
        # Real provider may reject (400). Either way outbox must be written.
        assert r.status_code in (200, 400), r.text
        time.sleep(0.5)
        rows = _recent_outbox(admin_headers, since, template="hrmis_meeting_updated")
        assert rows, "expected an outbox row for hrmis_meeting_updated"
        latest = rows[0]
        params = latest.get("params") or []
        assert len(params) == 7, f"expected 7 params, got {len(params)}: {params}"
        assert all(bool(str(p).strip()) for p in params), f"empty param present: {params}"

    def test_test_send_meeting_cancelled_logs_5_params(self, admin_headers):
        since = datetime.now(timezone.utc).isoformat()
        payload = {"to": "+919812345678", "template_key": "meeting_cancelled"}
        r = requests.post(f"{API}/whatsapp/test", headers=admin_headers, json=payload, timeout=30)
        assert r.status_code in (200, 400), r.text
        time.sleep(0.5)
        rows = _recent_outbox(admin_headers, since, template="hrmis_meeting_cancelled")
        assert rows, "expected an outbox row for hrmis_meeting_cancelled"
        latest = rows[0]
        params = latest.get("params") or []
        assert len(params) == 5, f"expected 5 params, got {len(params)}: {params}"
        assert all(bool(str(p).strip()) for p in params), f"empty param present: {params}"


# ---------- 3. smart routing on PATCH ----------

@pytest.fixture
def confirmed_meeting(alex_headers, users_by_email):
    """Create a short confirmed meeting (auto_approved) organised by alex with
    maya + diego as attendees. Yields (meeting_dict, ids_dict). Cleans up."""
    starts = _future_iso(240)  # ~10 days out, unique window
    ends_dt = datetime.strptime(starts, "%Y-%m-%dT%H:%M:00") + timedelta(minutes=30)
    ends = ends_dt.strftime("%Y-%m-%dT%H:%M:00")
    maya = users_by_email[MAYA_EMAIL]
    diego = users_by_email[DIEGO_EMAIL]
    body = {
        "title": f"TEST_ITER27_{uuid.uuid4().hex[:6]}",
        "description": "iter27 smart routing",
        "starts_at": starts,
        "ends_at": ends,
        "location": "Online",
        "attendee_user_ids": [maya, diego],
    }
    r = requests.post(f"{API}/meetings", headers=alex_headers, json=body, timeout=20)
    assert r.status_code == 200, f"create meeting failed: {r.status_code} {r.text}"
    m = r.json()
    assert m.get("approval_status") == "auto_approved", m
    yield m, {"maya": maya, "diego": diego}
    # cleanup
    try:
        requests.delete(f"{API}/meetings/{m['id']}", headers=alex_headers, timeout=15)
    except Exception:
        pass


class TestMeetingPatchSmartRouting:
    def test_patch_routes_added_removed_kept(self, alex_headers, admin_headers,
                                             users_by_email, confirmed_meeting):
        m, ids = confirmed_meeting
        mid = m["id"]
        maya, diego = ids["maya"], ids["diego"]
        lena = users_by_email[LENA_EMAIL]

        # move the meeting +1h and swap diego → lena, keep maya
        new_starts_dt = datetime.strptime(m["starts_at"], "%Y-%m-%dT%H:%M:00") + timedelta(hours=1)
        new_ends_dt = new_starts_dt + timedelta(minutes=30)
        new_starts = new_starts_dt.strftime("%Y-%m-%dT%H:%M:00")
        new_ends = new_ends_dt.strftime("%Y-%m-%dT%H:%M:00")

        since = datetime.now(timezone.utc).isoformat()
        patch = {
            "starts_at": new_starts,
            "ends_at": new_ends,
            "attendee_user_ids": [maya, lena],
        }
        r = requests.patch(f"{API}/meetings/{mid}", headers=alex_headers, json=patch, timeout=20)
        assert r.status_code == 200, f"patch failed: {r.status_code} {r.text}"

        time.sleep(1.5)  # allow fire-and-forget tasks

        # KEPT (maya) → hrmis_meeting_updated, 6 params, 6th should mention 'start' or participants
        kept_rows = _recent_outbox(admin_headers, since, template="hrmis_meeting_updated", to="919812345678")
        assert kept_rows, "expected hrmis_meeting_updated outbox row for retained attendee maya"
        kept = kept_rows[0]
        kparams = kept["params"]
        assert len(kparams) == 7, f"retained params: {kparams}"
        assert all(str(p).strip() for p in kparams), f"empty param in retained: {kparams}"
        # 6th param = change summary — must mention something that actually changed
        change_summary = str(kparams[5]).lower()
        assert ("start" in change_summary) or ("end" in change_summary) or ("participants" in change_summary), \
            f"change summary didn't reflect change: {change_summary!r}"
        # organizer (2nd param) is alex's name
        assert "alex" in str(kparams[1]).lower(), f"organizer param: {kparams[1]!r}"

        # REMOVED (diego) → hrmis_meeting_cancelled, 5 params, 5th = editor's name
        removed_rows = _recent_outbox(admin_headers, since, template="hrmis_meeting_cancelled", to="919812345679")
        assert removed_rows, "expected hrmis_meeting_cancelled outbox row for removed attendee diego"
        rparams = removed_rows[0]["params"]
        assert len(rparams) == 5, f"removed params: {rparams}"
        assert all(str(p).strip() for p in rparams), f"empty param in removed: {rparams}"
        assert "alex" in str(rparams[4]).lower(), f"cancelled_by param: {rparams[4]!r}"

        # ADDED (lena) → hrmis_meeting_scheduled, 5 params
        added_rows = _recent_outbox(admin_headers, since, template="hrmis_meeting_scheduled")
        # Lena's phone starts with +1 (415) — digits only
        added_lena = [r for r in added_rows if "4155551006" in (r.get("to") or "").replace(" ", "").replace("(", "").replace(")", "").replace("-", "")]
        assert added_lena, f"expected hrmis_meeting_scheduled outbox row for added attendee lena. Rows seen: {[r.get('to') for r in added_rows]}"
        aparams = added_lena[0]["params"]
        assert len(aparams) == 6, f"added params: {aparams}"
        assert all(str(p).strip() for p in aparams), f"empty param in added: {aparams}"

        # in-app notifications check
        # removed attendee (diego) should get meeting_cancelled type notification
        # added attendee (lena) should get meeting_invite notification
        # In-app notification sanity check — query DB directly because
        # /api/notifications filters by company_id and meetings.py currently
        # creates notifications WITHOUT company_id (bug reported separately).
        import os as _os
        from dotenv import load_dotenv as _ld
        _ld("/app/backend/.env", override=False)
        from motor.motor_asyncio import AsyncIOMotorClient
        _mongo = _os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
        _dbname = _os.environ.get("DB_NAME") or "hrmis_database"
        _c = AsyncIOMotorClient(_mongo)
        import asyncio as _aio
        title_prefix = m["title"]
        async def _check():
            db = _c[_dbname]
            diego_notif = await db.notifications.find_one(
                {"user_id": ids["diego"], "type": "meeting_cancelled",
                 "title": "Removed from meeting", "body": {"$regex": title_prefix}}
            )
            lena_notif = await db.notifications.find_one(
                {"user_id": users_by_email[LENA_EMAIL], "type": "meeting_invite",
                 "body": {"$regex": title_prefix}}
            )
            maya_notif = await db.notifications.find_one(
                {"user_id": ids["maya"], "type": "meeting_updated",
                 "body": {"$regex": title_prefix}}
            )
            return diego_notif, lena_notif, maya_notif
        _loop = _aio.new_event_loop()
        try:
            diego_notif, lena_notif, maya_notif = _loop.run_until_complete(_check())
        finally:
            _loop.close()
            _c.close()
        assert diego_notif, "No in-app meeting_cancelled 'Removed from meeting' notif for diego in DB"
        assert lena_notif, "No in-app meeting_invite notif for lena in DB"
        assert maya_notif, "No in-app meeting_updated notif for maya in DB"


# ---------- 4. cancel sends to all attendees ----------

class TestMeetingCancelFanOut:
    def test_delete_meeting_sends_cancelled_to_all_attendees(
        self, alex_headers, admin_headers, users_by_email,
    ):
        starts = _future_iso(400)
        ends_dt = datetime.strptime(starts, "%Y-%m-%dT%H:%M:00") + timedelta(minutes=30)
        ends = ends_dt.strftime("%Y-%m-%dT%H:%M:00")
        body = {
            "title": f"TEST_ITER27_CANCEL_{uuid.uuid4().hex[:6]}",
            "description": "iter27 cancel",
            "starts_at": starts,
            "ends_at": ends,
            "location": "Online",
            "attendee_user_ids": [users_by_email[MAYA_EMAIL], users_by_email[DIEGO_EMAIL]],
        }
        r = requests.post(f"{API}/meetings", headers=alex_headers, json=body, timeout=20)
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["approval_status"] == "auto_approved"

        since = datetime.now(timezone.utc).isoformat()
        r = requests.delete(f"{API}/meetings/{m['id']}", headers=alex_headers, timeout=20)
        assert r.status_code == 200, r.text

        time.sleep(1.5)

        for phone_digits, email in (
            ("919812345678", MAYA_EMAIL),
            ("919812345679", DIEGO_EMAIL),
        ):
            rows = _recent_outbox(admin_headers, since, template="hrmis_meeting_cancelled", to=phone_digits)
            assert rows, f"no cancelled outbox row for {email} ({phone_digits})"
            params = rows[0]["params"]
            assert len(params) == 5, f"{email}: cancelled params {params}"
            assert all(str(p).strip() for p in params), f"{email}: empty param {params}"
            # title (param 2) matches meeting title
            assert m["title"] in str(params[1]), f"{email}: title param {params[1]!r} vs {m['title']}"
            # cancelled_by (param 5) is alex's name
            assert "alex" in str(params[4]).lower(), f"{email}: cancelled_by {params[4]!r}"


# ---------- 5. events_enabled toggle ----------

class TestEventsEnabledToggle:
    def test_disabled_events_stop_wa_sends(self, admin_headers, alex_headers, users_by_email):
        # 1) Disable meeting_updated + meeting_cancelled
        r = requests.put(f"{API}/whatsapp/config", headers=admin_headers,
                         json={"events_enabled": {"meeting_updated": False, "meeting_cancelled": False}},
                         timeout=15)
        assert r.status_code == 200, r.text

        try:
            # create confirmed meeting
            starts = _future_iso(460)
            ends_dt = datetime.strptime(starts, "%Y-%m-%dT%H:%M:00") + timedelta(minutes=30)
            ends = ends_dt.strftime("%Y-%m-%dT%H:%M:00")
            body = {
                "title": f"TEST_ITER27_OFF_{uuid.uuid4().hex[:6]}",
                "starts_at": starts, "ends_at": ends,
                "location": "Online",
                "attendee_user_ids": [users_by_email[MAYA_EMAIL]],
            }
            cr = requests.post(f"{API}/meetings", headers=alex_headers, json=body, timeout=20)
            assert cr.status_code == 200, cr.text
            m = cr.json()

            since = datetime.now(timezone.utc).isoformat()
            # 2) PATCH title (kept attendee) → should NOT produce meeting_updated outbox
            pr = requests.patch(f"{API}/meetings/{m['id']}", headers=alex_headers,
                                json={"title": m["title"] + "_edited"}, timeout=20)
            assert pr.status_code == 200, pr.text
            time.sleep(1.0)
            upd_rows = _recent_outbox(admin_headers, since, template="hrmis_meeting_updated", to="919812345678")
            assert not upd_rows, f"meeting_updated was sent despite being disabled: {upd_rows}"

            # 3) DELETE → should NOT produce meeting_cancelled outbox
            since2 = datetime.now(timezone.utc).isoformat()
            dr = requests.delete(f"{API}/meetings/{m['id']}", headers=alex_headers, timeout=15)
            assert dr.status_code == 200
            time.sleep(1.0)
            canc_rows = _recent_outbox(admin_headers, since2, template="hrmis_meeting_cancelled", to="919812345678")
            assert not canc_rows, f"meeting_cancelled was sent despite being disabled: {canc_rows}"
        finally:
            # restore
            requests.put(f"{API}/whatsapp/config", headers=admin_headers,
                         json={"events_enabled": {"meeting_updated": True, "meeting_cancelled": True}},
                         timeout=15)
