"""Iteration 24: Meeting edit (PATCH) + cancel (DELETE) with WA/in-app notifications."""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

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


def _future_slot(hours_from_now=2, duration_min=30):
    start = datetime.now(timezone.utc) + timedelta(hours=hours_from_now)
    end = start + timedelta(minutes=duration_min)
    return start.isoformat(), end.isoformat()


def _create_meeting(tok, title, attendee_ids, hours=2, duration=30):
    s, e = _future_slot(hours, duration)
    body = {
        "title": title,
        "description": "iter24 test",
        "starts_at": s,
        "ends_at": e,
        "location": "Online",
        "attendee_user_ids": attendee_ids,
    }
    r = requests.post(f"{API}/meetings", headers=_hdr(tok), json=body, timeout=20)
    assert r.status_code == 200, f"create: {r.status_code} {r.text}"
    return r.json()


# ---------------------------------------------------------------- outbox helpers
def _outbox_count(cid: str, template: str) -> int:
    """Count rows via direct Mongo (test runs on same box)."""
    import os as _os
    from pymongo import MongoClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    cli = MongoClient(_os.environ["MONGO_URL"])
    db = cli[_os.environ["DB_NAME"]]
    return db.whatsapp_outbox.count_documents({"company_id": cid, "template": template})


def _notif_count(uid: str, type_: str) -> int:
    import os as _os
    from pymongo import MongoClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    cli = MongoClient(_os.environ["MONGO_URL"])
    db = cli[_os.environ["DB_NAME"]]
    return db.notifications.count_documents({"user_id": uid, "type": type_})


# ================================= PATCH tests ===============================
class TestMeetingPatch:
    def test_organizer_can_patch_title_time_and_attendees(self, tokens, users):
        m = _create_meeting(tokens["alex"], f"TEST_edit_{uuid.uuid4().hex[:6]}", [users["maya"]["id"]])
        assert m["approval_status"] == "auto_approved"

        new_s, new_e = _future_slot(hours_from_now=3, duration_min=45)
        new_title = m["title"] + "_v2"
        resp = requests.patch(
            f"{API}/meetings/{m['id']}",
            headers=_hdr(tokens["alex"]),
            json={
                "title": new_title,
                "starts_at": new_s,
                "ends_at": new_e,
                "attendee_user_ids": [users["maya"]["id"], users["diego"]["id"]],
            },
            timeout=20,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["title"] == new_title
        assert data["starts_at"] == new_s
        assert data["ends_at"] == new_e
        assert set(data["attendee_user_ids"]) == {users["maya"]["id"], users["diego"]["id"]}
        assert "updated_at" in data and data["updated_at"]
        assert data["updated_by"]

    def test_non_organizer_non_admin_cannot_patch(self, tokens, users):
        m = _create_meeting(tokens["alex"], f"TEST_authz_{uuid.uuid4().hex[:6]}", [users["maya"]["id"]])
        resp = requests.patch(
            f"{API}/meetings/{m['id']}",
            headers=_hdr(tokens["maya"]),
            json={"title": "hack"},
            timeout=10,
        )
        assert resp.status_code == 403, resp.text

    def test_super_admin_can_patch_any(self, tokens, users):
        m = _create_meeting(tokens["alex"], f"TEST_adminpatch_{uuid.uuid4().hex[:6]}", [users["maya"]["id"]])
        resp = requests.patch(
            f"{API}/meetings/{m['id']}",
            headers=_hdr(tokens["admin"]),
            json={"title": m["title"] + "_adm"},
            timeout=10,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"].endswith("_adm")

    def test_hr_can_patch_any(self, tokens, users):
        m = _create_meeting(tokens["alex"], f"TEST_hrpatch_{uuid.uuid4().hex[:6]}", [users["maya"]["id"]])
        resp = requests.patch(
            f"{API}/meetings/{m['id']}",
            headers=_hdr(tokens["jordan"]),
            json={"title": m["title"] + "_hr"},
            timeout=10,
        )
        assert resp.status_code == 200, resp.text

    def test_patch_cancelled_meeting_blocked(self, tokens, users):
        m = _create_meeting(tokens["alex"], f"TEST_cxl_{uuid.uuid4().hex[:6]}", [users["maya"]["id"]])
        d = requests.delete(f"{API}/meetings/{m['id']}", headers=_hdr(tokens["alex"]))
        assert d.status_code == 200
        resp = requests.patch(
            f"{API}/meetings/{m['id']}", headers=_hdr(tokens["alex"]),
            json={"title": "x"}, timeout=10,
        )
        assert resp.status_code == 400, resp.text

    def test_patch_bad_time_order_400(self, tokens, users):
        m = _create_meeting(tokens["alex"], f"TEST_bad_{uuid.uuid4().hex[:6]}", [users["maya"]["id"]])
        s, e = _future_slot(5, 30)
        resp = requests.patch(
            f"{API}/meetings/{m['id']}", headers=_hdr(tokens["alex"]),
            json={"starts_at": e, "ends_at": s}, timeout=10,
        )
        assert resp.status_code == 400, resp.text

    def test_patch_room_conflict_409(self, tokens, users):
        # Need an actual room
        r = requests.get(f"{API}/rooms", headers=_hdr(tokens["alex"]))
        if r.status_code != 200 or not r.json():
            pytest.skip("no rooms configured")
        room = r.json()[0]

        s1, e1 = _future_slot(10, 30)
        s2, e2 = _future_slot(11, 30)
        a = requests.post(f"{API}/meetings", headers=_hdr(tokens["alex"]), json={
            "title": f"TEST_room_a_{uuid.uuid4().hex[:5]}",
            "starts_at": s1, "ends_at": e1, "location": "", "attendee_user_ids": [],
            "room_id": room["id"],
        }, timeout=15)
        assert a.status_code == 200, a.text
        b = requests.post(f"{API}/meetings", headers=_hdr(tokens["alex"]), json={
            "title": f"TEST_room_b_{uuid.uuid4().hex[:5]}",
            "starts_at": s2, "ends_at": e2, "location": "", "attendee_user_ids": [],
            "room_id": room["id"],
        }, timeout=15)
        assert b.status_code == 200, b.text
        # patch B into A's slot
        resp = requests.patch(f"{API}/meetings/{b.json()['id']}", headers=_hdr(tokens["alex"]), json={
            "starts_at": s1, "ends_at": e1,
        }, timeout=15)
        assert resp.status_code == 409, resp.text


# ================================= DELETE tests ===============================
class TestMeetingDelete:
    def test_delete_sets_cancelled(self, tokens, users):
        m = _create_meeting(tokens["alex"], f"TEST_del_{uuid.uuid4().hex[:6]}", [users["maya"]["id"]])
        r = requests.delete(f"{API}/meetings/{m['id']}", headers=_hdr(tokens["alex"]))
        assert r.status_code == 200
        assert r.json() == {"success": True}
        # fetch
        lst = requests.get(f"{API}/meetings?scope=all", headers=_hdr(tokens["admin"])).json()
        found = [x for x in lst if x["id"] == m["id"]]
        assert found and found[0]["status"] == "cancelled"
        assert found[0].get("cancelled_by")
        assert found[0].get("cancelled_at")

    def test_delete_idempotent(self, tokens, users):
        m = _create_meeting(tokens["alex"], f"TEST_del2_{uuid.uuid4().hex[:6]}", [users["maya"]["id"]])
        r1 = requests.delete(f"{API}/meetings/{m['id']}", headers=_hdr(tokens["alex"]))
        r2 = requests.delete(f"{API}/meetings/{m['id']}", headers=_hdr(tokens["alex"]))
        assert r1.status_code == 200 and r2.status_code == 200
        assert r2.json() == {"success": True}


# ============================ Notifications side-effects =======================
class TestNotifications:
    def test_patch_inserts_meeting_updated_notifications(self, tokens, users):
        attendees = [users["maya"]["id"], users["diego"]["id"]]
        m = _create_meeting(tokens["alex"], f"TEST_notifupd_{uuid.uuid4().hex[:6]}", attendees)
        before_maya = _notif_count(users["maya"]["id"], "meeting_updated")
        before_diego = _notif_count(users["diego"]["id"], "meeting_updated")
        resp = requests.patch(f"{API}/meetings/{m['id']}", headers=_hdr(tokens["alex"]),
                              json={"title": m["title"] + "_notif"}, timeout=15)
        assert resp.status_code == 200
        after_maya = _notif_count(users["maya"]["id"], "meeting_updated")
        after_diego = _notif_count(users["diego"]["id"], "meeting_updated")
        assert after_maya == before_maya + 1
        assert after_diego == before_diego + 1

    def test_delete_inserts_meeting_cancelled_notifications(self, tokens, users):
        attendees = [users["maya"]["id"], users["diego"]["id"]]
        m = _create_meeting(tokens["alex"], f"TEST_notifcxl_{uuid.uuid4().hex[:6]}", attendees)
        before = _notif_count(users["maya"]["id"], "meeting_cancelled")
        r = requests.delete(f"{API}/meetings/{m['id']}", headers=_hdr(tokens["alex"]))
        assert r.status_code == 200
        after = _notif_count(users["maya"]["id"], "meeting_cancelled")
        assert after == before + 1

    def test_patch_pending_does_not_notify(self, tokens, users):
        # Create a long meeting (> 120 min) as alex (manager, not admin) → pending
        attendees = [users["maya"]["id"]]
        s, e = _future_slot(20, 180)
        r = requests.post(f"{API}/meetings", headers=_hdr(tokens["alex"]), json={
            "title": f"TEST_pending_{uuid.uuid4().hex[:5]}",
            "starts_at": s, "ends_at": e, "location": "Online",
            "attendee_user_ids": attendees,
        }, timeout=15)
        assert r.status_code == 200, r.text
        mdoc = r.json()
        assert mdoc["approval_status"] == "pending", mdoc

        before = _notif_count(users["maya"]["id"], "meeting_updated")
        resp = requests.patch(f"{API}/meetings/{mdoc['id']}", headers=_hdr(tokens["alex"]),
                              json={"title": mdoc["title"] + "_x"}, timeout=15)
        assert resp.status_code == 200
        after = _notif_count(users["maya"]["id"], "meeting_updated")
        assert after == before, "pending meeting should NOT fire meeting_updated notifications"

        # DELETE on pending — should also NOT notify
        before_c = _notif_count(users["maya"]["id"], "meeting_cancelled")
        d = requests.delete(f"{API}/meetings/{mdoc['id']}", headers=_hdr(tokens["alex"]))
        assert d.status_code == 200
        after_c = _notif_count(users["maya"]["id"], "meeting_cancelled")
        assert after_c == before_c, "pending meeting cancel should NOT notify"


# ============================ WhatsApp outbox side-effects =====================
# These check that WA templates are at least ATTEMPTED (outbox rows written) for
# confirmed meetings, suppressed for pending. Delivery itself fails because of
# the placeholder BSP key, but outbox is written before send either way.
class TestWhatsAppOutbox:
    def _ensure_wa_enabled(self, users):
        """Ensure wa config is enabled with meeting_updated/cancelled events ON."""
        from pymongo import MongoClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        cli = MongoClient(os.environ["MONGO_URL"])
        db = cli[os.environ["DB_NAME"]]
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
        # Ensure attendees have phone numbers
        for who in ("maya", "diego"):
            db.employees.update_one(
                {"user_id": users[who]["id"], "company_id": cid},
                {"$set": {"phone": "+919812345678" if who == "maya" else "+919812345679"}},
                upsert=False,
            )
        return cid

    def test_patch_confirmed_writes_wa_outbox(self, tokens, users):
        cid = self._ensure_wa_enabled(users)
        attendees = [users["maya"]["id"], users["diego"]["id"]]
        m = _create_meeting(tokens["alex"], f"TEST_wa_upd_{uuid.uuid4().hex[:6]}", attendees)
        before = _outbox_count(cid, "hrmis_meeting_updated")
        r = requests.patch(f"{API}/meetings/{m['id']}", headers=_hdr(tokens["alex"]),
                           json={"title": m["title"] + "_wa"}, timeout=20)
        assert r.status_code == 200
        # give async a sec
        import time; time.sleep(1.5)
        after = _outbox_count(cid, "hrmis_meeting_updated")
        assert after >= before + 2, f"expected >=2 new outbox rows for 2 attendees, got {after-before}"

    def test_delete_confirmed_writes_wa_outbox(self, tokens, users):
        cid = self._ensure_wa_enabled(users)
        attendees = [users["maya"]["id"], users["diego"]["id"]]
        m = _create_meeting(tokens["alex"], f"TEST_wa_cxl_{uuid.uuid4().hex[:6]}", attendees)
        before = _outbox_count(cid, "hrmis_meeting_cancelled")
        r = requests.delete(f"{API}/meetings/{m['id']}", headers=_hdr(tokens["alex"]))
        assert r.status_code == 200
        import time; time.sleep(1.5)
        after = _outbox_count(cid, "hrmis_meeting_cancelled")
        assert after >= before + 2, f"expected >=2 outbox rows for cancel, got {after-before}"

    def test_patch_pending_does_not_write_outbox(self, tokens, users):
        cid = self._ensure_wa_enabled(users)
        attendees = [users["maya"]["id"]]
        s, e = _future_slot(30, 180)
        rc = requests.post(f"{API}/meetings", headers=_hdr(tokens["alex"]), json={
            "title": f"TEST_wa_pend_{uuid.uuid4().hex[:5]}",
            "starts_at": s, "ends_at": e, "location": "Online",
            "attendee_user_ids": attendees,
        }, timeout=15)
        assert rc.json()["approval_status"] == "pending"
        mid = rc.json()["id"]

        before = _outbox_count(cid, "hrmis_meeting_updated")
        rp = requests.patch(f"{API}/meetings/{mid}", headers=_hdr(tokens["alex"]),
                            json={"title": rc.json()["title"] + "_y"}, timeout=15)
        assert rp.status_code == 200
        import time; time.sleep(1.0)
        after = _outbox_count(cid, "hrmis_meeting_updated")
        assert after == before, "pending patch must NOT write outbox"

        before_c = _outbox_count(cid, "hrmis_meeting_cancelled")
        rd = requests.delete(f"{API}/meetings/{mid}", headers=_hdr(tokens["alex"]))
        assert rd.status_code == 200
        import time; time.sleep(1.0)
        after_c = _outbox_count(cid, "hrmis_meeting_cancelled")
        assert after_c == before_c, "pending cancel must NOT write outbox"
