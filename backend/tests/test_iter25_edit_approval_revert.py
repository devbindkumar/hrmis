"""Iteration 25: PATCH that lengthens a confirmed short meeting past the
long-meeting threshold must revert approval_status to 'pending', clear
approved_by/approved_at, suppress attendee WA + in-app pings, and instead
notify HR/super_admin with a meeting_approval_request.
"""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://workforce-central-43.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tokens():
    return {
        "admin": _login("admin@acme.com", "Admin@123"),
        "alex": _login("alex@acme.com", "Demo@123"),
        "maya": _login("maya@acme.com", "Demo@123"),
        "diego": _login("diego@acme.com", "Demo@123"),
        "jordan": _login("jordan@acme.com", "Demo@123"),
    }


@pytest.fixture(scope="module")
def users(tokens):
    out = {}
    for who, tok in tokens.items():
        r = requests.get(f"{API}/auth/me", headers=_hdr(tok), timeout=10)
        assert r.status_code == 200, r.text
        out[who] = r.json()
    return out


@pytest.fixture(scope="module")
def db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli[os.environ["DB_NAME"]]


@pytest.fixture(scope="module", autouse=True)
def ensure_wa_enabled(users, db):
    """Ensure WA config is enabled and attendees have phone numbers, so a
    non-revert PATCH DOES fan out WA (regression test depends on it)."""
    cid = users["alex"]["company_id"]
    cfg = db.whatsapp_configs.find_one({"company_id": cid}) or {}
    new_cfg = {
        "company_id": cid,
        "enabled": True,
        "provider": cfg.get("provider") or "azmarq",
        "access_token": cfg.get("access_token") or "TEST_KEY",
        "phone_number_id": cfg.get("phone_number_id") or "+919999999999",
        "business_account_id": cfg.get("business_account_id") or "",
        "default_country_code": cfg.get("default_country_code") or "91",
        "api_base_url": cfg.get("api_base_url") or "",
        "campaign_name": cfg.get("campaign_name") or "hrmis-alerts",
        "header_text": cfg.get("header_text") or "HRMIS",
        "timezone": cfg.get("timezone") or "Asia/Kolkata",
        "templates": {
            "meeting_updated": "hrmis_meeting_updated",
            "meeting_cancelled": "hrmis_meeting_cancelled",
            "meeting_scheduled": "hrmis_meeting_scheduled",
        },
        "events_enabled": {
            "meeting_updated": True,
            "meeting_cancelled": True,
            "meeting_scheduled": True,
        },
    }
    db.whatsapp_configs.update_one({"company_id": cid}, {"$set": new_cfg}, upsert=True)
    for who in ("maya", "diego"):
        db.employees.update_one(
            {"user_id": users[who]["id"], "company_id": cid},
            {"$set": {"phone": "+919812345678" if who == "maya" else "+919812345679"}},
            upsert=False,
        )
    return cid


def _future_slot(hours_from_now=2, duration_min=30):
    start = datetime.now(timezone.utc) + timedelta(hours=hours_from_now)
    end = start + timedelta(minutes=duration_min)
    return start.isoformat(), end.isoformat()


def _create_short_meeting(tok, title, attendee_ids):
    s, e = _future_slot(hours_from_now=2 + (hash(title) % 20), duration_min=30)
    body = {
        "title": title,
        "description": "iter25 test",
        "starts_at": s,
        "ends_at": e,
        "location": "Online",
        "attendee_user_ids": attendee_ids,
    }
    r = requests.post(f"{API}/meetings", headers=_hdr(tok), json=body, timeout=20)
    assert r.status_code == 200, f"create: {r.status_code} {r.text}"
    return r.json()


def _notif_count(db, uid, type_, meeting_id=None):
    q = {"user_id": uid, "type": type_}
    return db.notifications.count_documents(q)


def _outbox_count(db, cid, template):
    return db.whatsapp_outbox.count_documents({"company_id": cid, "template": template})


class TestEditRevertsToPending:
    def test_manager_lengthens_short_meeting_reverts_to_pending(self, tokens, users, db):
        cid = users["alex"]["company_id"]
        attendees = [users["maya"]["id"], users["diego"]["id"]]
        m = _create_short_meeting(tokens["alex"], f"TEST_i25_revert_{uuid.uuid4().hex[:6]}", attendees)
        assert m["approval_status"] == "auto_approved", m

        before_maya_upd = _notif_count(db, users["maya"]["id"], "meeting_updated")
        before_diego_upd = _notif_count(db, users["diego"]["id"], "meeting_updated")
        before_wa_upd = _outbox_count(db, cid, "hrmis_meeting_updated")

        # HR + super_admin baseline for approval_request
        before_hr_jordan = _notif_count(db, users["jordan"]["id"], "meeting_approval_request")
        before_hr_admin = _notif_count(db, users["admin"]["id"], "meeting_approval_request")

        # Extend to 3 hours
        new_s = datetime.now(timezone.utc) + timedelta(hours=5)
        new_e = new_s + timedelta(minutes=180)
        resp = requests.patch(
            f"{API}/meetings/{m['id']}",
            headers=_hdr(tokens["alex"]),
            json={"starts_at": new_s.isoformat(), "ends_at": new_e.isoformat()},
            timeout=20,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["approval_status"] == "pending", data
        assert data.get("approved_by") is None, f"approved_by should be None, got {data.get('approved_by')}"
        assert data.get("approved_at") is None, f"approved_at should be None, got {data.get('approved_at')}"

        time.sleep(1.5)

        # No attendee updates
        after_maya_upd = _notif_count(db, users["maya"]["id"], "meeting_updated")
        after_diego_upd = _notif_count(db, users["diego"]["id"], "meeting_updated")
        after_wa_upd = _outbox_count(db, cid, "hrmis_meeting_updated")
        assert after_maya_upd == before_maya_upd, "attendee should NOT get meeting_updated on revert"
        assert after_diego_upd == before_diego_upd, "attendee should NOT get meeting_updated on revert"
        assert after_wa_upd == before_wa_upd, "no WA fan-out on revert"

        # Exactly one HR approval request per HR/super_admin in tenant
        after_hr_jordan = _notif_count(db, users["jordan"]["id"], "meeting_approval_request")
        after_hr_admin = _notif_count(db, users["admin"]["id"], "meeting_approval_request")
        assert after_hr_jordan == before_hr_jordan + 1, "jordan (HR) should get exactly 1 approval request"
        assert after_hr_admin == before_hr_admin + 1, "admin (super_admin) should get exactly 1 approval request"

        # Validate HR notification body
        hr_notif = db.notifications.find_one(
            {"user_id": users["jordan"]["id"], "type": "meeting_approval_request"},
            sort=[("created_at", -1)],
        )
        assert hr_notif is not None
        assert m["title"] in hr_notif.get("body", ""), f"title missing in body: {hr_notif.get('body')}"
        actor_name = users["alex"]["name"]
        assert actor_name in hr_notif.get("body", ""), f"actor name missing: {hr_notif.get('body')}"

    def test_super_admin_lengthening_keeps_confirmed(self, tokens, users, db):
        cid = users["alex"]["company_id"]
        attendees = [users["maya"]["id"], users["diego"]["id"]]
        m = _create_short_meeting(tokens["alex"], f"TEST_i25_adminkeep_{uuid.uuid4().hex[:6]}", attendees)
        assert m["approval_status"] == "auto_approved"

        before_maya_upd = _notif_count(db, users["maya"]["id"], "meeting_updated")
        before_wa_upd = _outbox_count(db, cid, "hrmis_meeting_updated")
        before_hr_jordan = _notif_count(db, users["jordan"]["id"], "meeting_approval_request")

        new_s = datetime.now(timezone.utc) + timedelta(hours=8)
        new_e = new_s + timedelta(minutes=180)
        resp = requests.patch(
            f"{API}/meetings/{m['id']}",
            headers=_hdr(tokens["admin"]),
            json={"starts_at": new_s.isoformat(), "ends_at": new_e.isoformat()},
            timeout=20,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # Super admin edit MUST NOT revert
        assert data["approval_status"] == "auto_approved", f"super_admin edit must keep auto_approved, got {data['approval_status']}"

        time.sleep(1.5)

        after_maya_upd = _notif_count(db, users["maya"]["id"], "meeting_updated")
        after_wa_upd = _outbox_count(db, cid, "hrmis_meeting_updated")
        after_hr_jordan = _notif_count(db, users["jordan"]["id"], "meeting_approval_request")

        assert after_maya_upd == before_maya_upd + 1, "super_admin edit should fan out meeting_updated"
        assert after_wa_upd >= before_wa_upd + 2, "WA outbox should receive attendee rows"
        assert after_hr_jordan == before_hr_jordan, "no HR approval request on super_admin edit"

    def test_short_confirmed_patch_still_notifies(self, tokens, users, db):
        """Regression: a confirmed meeting kept < 120 min and non-recurring
        still fires meeting_updated WA + in-app."""
        cid = users["alex"]["company_id"]
        attendees = [users["maya"]["id"], users["diego"]["id"]]
        m = _create_short_meeting(tokens["alex"], f"TEST_i25_shortkeep_{uuid.uuid4().hex[:6]}", attendees)
        assert m["approval_status"] == "auto_approved"

        before_maya = _notif_count(db, users["maya"]["id"], "meeting_updated")
        before_wa = _outbox_count(db, cid, "hrmis_meeting_updated")
        before_hr = _notif_count(db, users["jordan"]["id"], "meeting_approval_request")

        # Keep duration short — just change title
        resp = requests.patch(
            f"{API}/meetings/{m['id']}",
            headers=_hdr(tokens["alex"]),
            json={"title": m["title"] + "_shrt"},
            timeout=15,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["approval_status"] == "auto_approved", "short meeting must stay auto_approved"

        time.sleep(1.5)

        assert _notif_count(db, users["maya"]["id"], "meeting_updated") == before_maya + 1
        assert _outbox_count(db, cid, "hrmis_meeting_updated") >= before_wa + 2
        assert _notif_count(db, users["jordan"]["id"], "meeting_approval_request") == before_hr, "no HR ping for short edit"

    def test_hr_lengthening_keeps_confirmed(self, tokens, users, db):
        """HR edits also bypass revert (same authority as super_admin)."""
        cid = users["alex"]["company_id"]
        attendees = [users["maya"]["id"]]
        m = _create_short_meeting(tokens["alex"], f"TEST_i25_hrkeep_{uuid.uuid4().hex[:6]}", attendees)
        assert m["approval_status"] == "auto_approved"

        before_hr = _notif_count(db, users["jordan"]["id"], "meeting_approval_request")

        new_s = datetime.now(timezone.utc) + timedelta(hours=14)
        new_e = new_s + timedelta(minutes=180)
        resp = requests.patch(
            f"{API}/meetings/{m['id']}",
            headers=_hdr(tokens["jordan"]),
            json={"starts_at": new_s.isoformat(), "ends_at": new_e.isoformat()},
            timeout=15,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["approval_status"] == "auto_approved"
        time.sleep(1.0)
        assert _notif_count(db, users["jordan"]["id"], "meeting_approval_request") == before_hr
