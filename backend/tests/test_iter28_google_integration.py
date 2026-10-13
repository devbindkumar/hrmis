"""Iteration 28 — Google Meet / Calendar integration tests.

Covers:
 * /api/google/status, /oauth/start, /oauth/callback, /disconnect
 * /api/meetings create+patch+delete with add_google_meet while Google is
   NOT configured (feature must stay gracefully inactive)
 * Unit-level checks on google_calendar_service via monkeypatch of httpx and
   _access_token (no real Google calls)
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def _frontend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("REACT_APP_BACKEND_URL not set")

BASE_URL = _frontend_url().rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@acme.com", "Admin@123")
MANAGER = ("alex@acme.com", "Demo@123")
EMPLOYEE = ("maya@acme.com", "Demo@123")
HR = ("jordan@acme.com", "Demo@123")


# -------------------- fixtures --------------------
def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def manager_token():
    return _login(*MANAGER)


@pytest.fixture(scope="module")
def employee_token():
    return _login(*EMPLOYEE)


@pytest.fixture(scope="module")
def hr_token():
    return _login(*HR)


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# -------------------- /api/google/status --------------------
class TestGoogleStatus:
    def test_status_super_admin_includes_redirect_uri(self, admin_token):
        r = requests.get(f"{API}/google/status", headers=_h(admin_token), timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["configured"] is False
        assert d["connected"] is False
        assert d.get("email") in (None, "")
        assert "redirect_uri" in d and d["redirect_uri"]  # super_admin sees it

    def test_status_employee_hides_redirect_uri(self, employee_token):
        r = requests.get(f"{API}/google/status", headers=_h(employee_token), timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["configured"] is False
        assert d["connected"] is False
        assert "redirect_uri" not in d

    def test_status_manager_hides_redirect_uri(self, manager_token):
        r = requests.get(f"{API}/google/status", headers=_h(manager_token), timeout=10)
        assert r.status_code == 200
        assert "redirect_uri" not in r.json()

    def test_status_requires_auth(self):
        r = requests.get(f"{API}/google/status", timeout=10)
        assert r.status_code in (401, 403)


# -------------------- /api/google/oauth/start --------------------
class TestOAuthStart:
    def test_start_super_admin_without_creds_returns_400(self, admin_token):
        r = requests.get(f"{API}/google/oauth/start", headers=_h(admin_token), timeout=10)
        assert r.status_code == 400
        assert "not configured" in (r.json().get("detail") or "").lower()

    def test_start_hr_forbidden(self, hr_token):
        r = requests.get(f"{API}/google/oauth/start", headers=_h(hr_token), timeout=10)
        assert r.status_code == 403

    def test_start_manager_forbidden(self, manager_token):
        r = requests.get(f"{API}/google/oauth/start", headers=_h(manager_token), timeout=10)
        assert r.status_code == 403

    def test_start_employee_forbidden(self, employee_token):
        r = requests.get(f"{API}/google/oauth/start", headers=_h(employee_token), timeout=10)
        assert r.status_code == 403


# -------------------- /api/google/oauth/callback --------------------
class TestOAuthCallback:
    def test_callback_access_denied_redirects(self):
        r = requests.get(f"{API}/google/oauth/callback",
                         params={"error": "access_denied"},
                         allow_redirects=False, timeout=10)
        assert r.status_code in (302, 307)
        loc = r.headers.get("location", "")
        assert "/admin/settings" in loc
        assert "google=error" in loc
        assert "access_denied" in loc

    def test_callback_missing_code_redirects(self):
        r = requests.get(f"{API}/google/oauth/callback",
                         allow_redirects=False, timeout=10)
        assert r.status_code in (302, 307)
        loc = r.headers.get("location", "")
        assert "google=error" in loc
        assert "missing_code" in loc

    def test_callback_bogus_state_exchange_failed(self):
        r = requests.get(f"{API}/google/oauth/callback",
                         params={"code": "fake", "state": "not-a-jwt"},
                         allow_redirects=False, timeout=10)
        assert r.status_code in (302, 307)
        loc = r.headers.get("location", "")
        assert "google=error" in loc
        assert "exchange_failed" in loc


# -------------------- /api/google/disconnect --------------------
class TestDisconnect:
    def test_disconnect_requires_super_admin(self, employee_token, manager_token, hr_token):
        for tok in (employee_token, manager_token, hr_token):
            r = requests.delete(f"{API}/google/disconnect", headers=_h(tok), timeout=10)
            assert r.status_code == 403, f"expected 403, got {r.status_code}"

    def test_disconnect_super_admin_ok(self, admin_token):
        # Idempotent even when nothing to disconnect.
        r = requests.delete(f"{API}/google/disconnect", headers=_h(admin_token), timeout=10)
        assert r.status_code == 200
        assert r.json().get("success") is True


# -------------------- /api/meetings with add_google_meet --------------------
def _future_iso(minutes_from_now: int, duration: int = 30):
    start = datetime.now(timezone.utc) + timedelta(days=2, minutes=minutes_from_now)
    end = start + timedelta(minutes=duration)
    return start.isoformat(), end.isoformat()


class TestMeetingsWithGoogleMeet:
    _created_ids: list = []

    def test_create_meeting_add_meet_true_no_500(self, admin_token):
        starts, ends = _future_iso(10)
        payload = {
            "title": f"TEST_iter28_meet_{uuid.uuid4().hex[:6]}",
            "description": "google meet toggle on, no creds configured",
            "starts_at": starts, "ends_at": ends,
            "location": "Online",
            "attendee_user_ids": [],
            "add_google_meet": True,
        }
        r = requests.post(f"{API}/meetings", json=payload, headers=_h(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["add_google_meet"] is True
        assert d.get("meet_link") in (None, "")
        assert d.get("google_event_id") in (None, "")
        self.__class__._created_ids.append(d["id"])

    def test_patch_toggles_add_google_meet(self, admin_token):
        assert self._created_ids, "need a prior created meeting"
        mid = self._created_ids[-1]
        r = requests.patch(f"{API}/meetings/{mid}",
                           json={"add_google_meet": False},
                           headers=_h(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["add_google_meet"] is False

        r2 = requests.patch(f"{API}/meetings/{mid}",
                            json={"add_google_meet": True},
                            headers=_h(admin_token), timeout=15)
        assert r2.status_code == 200
        assert r2.json()["add_google_meet"] is True
        # Still no meet_link since Google not configured
        assert r2.json().get("meet_link") in (None, "")

    def test_cancel_meeting(self, admin_token):
        starts, ends = _future_iso(90)
        payload = {
            "title": f"TEST_iter28_cancel_{uuid.uuid4().hex[:6]}",
            "starts_at": starts, "ends_at": ends,
            "location": "Online",
            "attendee_user_ids": [],
            "add_google_meet": True,
        }
        r = requests.post(f"{API}/meetings", json=payload, headers=_h(admin_token), timeout=15)
        assert r.status_code == 200
        mid = r.json()["id"]
        self.__class__._created_ids.append(mid)
        r2 = requests.delete(f"{API}/meetings/{mid}", headers=_h(admin_token), timeout=15)
        assert r2.status_code == 200
        assert r2.json().get("success") is True

    def test_cleanup(self, admin_token):
        # Try to cancel any lingering TEST_ meetings we created.
        for mid in self._created_ids:
            try:
                requests.delete(f"{API}/meetings/{mid}", headers=_h(admin_token), timeout=10)
            except Exception:
                pass


# -------------------- WhatsApp smart routing regression (iter27) --------------------
class TestWhatsAppRegression:
    """Light regression — attendee add/remove should still return 200 without
    stacktraces, i.e. meeting update continues to work alongside the new
    Google block."""

    def test_update_meeting_attendees_still_works(self, admin_token):
        # Grab two employees
        emp = requests.get(f"{API}/employees", headers=_h(admin_token), timeout=10).json()
        ids = [e["user_id"] for e in emp if e.get("user_id")][:2]
        starts, ends = _future_iso(200)
        r = requests.post(f"{API}/meetings", json={
            "title": f"TEST_iter28_wa_{uuid.uuid4().hex[:6]}",
            "starts_at": starts, "ends_at": ends,
            "location": "Online",
            "attendee_user_ids": ids[:1],
            "add_google_meet": False,
        }, headers=_h(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        # Swap attendee
        r2 = requests.patch(f"{API}/meetings/{mid}",
                            json={"attendee_user_ids": ids[1:2]},
                            headers=_h(admin_token), timeout=15)
        assert r2.status_code == 200, r2.text
        # cleanup
        requests.delete(f"{API}/meetings/{mid}", headers=_h(admin_token), timeout=10)


# -------------------- Unit level: google_calendar_service with mocks --------------------
# These tests exercise the service functions directly, mocking httpx and
# _access_token so no real Google API is contacted.

@pytest.fixture
def gcal_module(monkeypatch):
    """Return a configured google_calendar_service with env + db patched."""
    # Ensure env has credentials so is_configured() -> True
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "cse")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://example/api/google/oauth/callback")
    import importlib
    import google_calendar_service as gcs
    importlib.reload(gcs)
    return gcs


class _AsyncResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, calls, responses):
        self.calls = calls
        self.responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self.responses.pop(0)

    async def patch(self, url, **kw):
        self.calls.append(("PATCH", url, kw))
        return self.responses.pop(0)

    async def delete(self, url, **kw):
        self.calls.append(("DELETE", url, kw))
        return self.responses.pop(0)

    async def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self.responses.pop(0)


@pytest.fixture
def meeting_doc():
    return {
        "id": "m-1",
        "company_id": "co-1",
        "title": "Design sync",
        "description": "weekly design review",
        "starts_at": "2026-02-01T10:00:00+00:00",
        "ends_at": "2026-02-01T11:00:00+00:00",
        "location": "Online",
        "room_name": None,
        "attendee_user_ids": ["u1", "u2"],
        "created_by_name": "Admin User",
        "google_event_id": "ev-123",
    }


@pytest.mark.asyncio
async def test_create_event_sends_conference_data(monkeypatch, gcal_module, meeting_doc):
    async def _fake_token(cid):
        return "tok"

    async def _fake_body(m):
        return {"summary": m["title"], "start": {}, "end": {}, "attendees": [{"email": "u1@acme.com"}]}

    monkeypatch.setattr(gcal_module, "_access_token", _fake_token)
    monkeypatch.setattr(gcal_module, "_event_body", _fake_body)

    calls = []
    responses = [_AsyncResp(200, {"id": "ev-xyz", "hangoutLink": "https://meet.google.com/abc-defg-hij",
                                   "htmlLink": "https://cal/x"})]
    monkeypatch.setattr(gcal_module.httpx, "AsyncClient", lambda **kw: _FakeClient(calls, responses))

    res = await gcal_module.create_event(meeting_doc)
    assert res["google_event_id"] == "ev-xyz"
    assert res["meet_link"] == "https://meet.google.com/abc-defg-hij"
    method, url, kw = calls[0]
    assert method == "POST"
    assert url.endswith("/calendars/primary/events")
    assert kw["params"]["conferenceDataVersion"] == 1
    assert kw["params"]["sendUpdates"] == "all"
    body = kw["json"]
    assert body["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"] == "hangoutsMeet"
    assert "requestId" in body["conferenceData"]["createRequest"]


@pytest.mark.asyncio
async def test_update_event_patches_with_send_updates_all(monkeypatch, gcal_module, meeting_doc):
    async def _fake_token(cid):
        return "tok"

    async def _fake_body(m):
        return {"summary": m["title"]}

    monkeypatch.setattr(gcal_module, "_access_token", _fake_token)
    monkeypatch.setattr(gcal_module, "_event_body", _fake_body)
    calls = []
    responses = [_AsyncResp(200, {"id": "ev-123"})]
    monkeypatch.setattr(gcal_module.httpx, "AsyncClient", lambda **kw: _FakeClient(calls, responses))

    ok = await gcal_module.update_event(meeting_doc)
    assert ok is True
    method, url, kw = calls[0]
    assert method == "PATCH"
    assert url.endswith("/events/ev-123")
    assert kw["params"]["sendUpdates"] == "all"


@pytest.mark.asyncio
async def test_cancel_event_deletes_with_send_updates_all(monkeypatch, gcal_module, meeting_doc):
    async def _fake_token(cid):
        return "tok"

    monkeypatch.setattr(gcal_module, "_access_token", _fake_token)
    calls = []
    responses = [_AsyncResp(204, {})]
    monkeypatch.setattr(gcal_module.httpx, "AsyncClient", lambda **kw: _FakeClient(calls, responses))

    ok = await gcal_module.cancel_event(meeting_doc)
    assert ok is True
    method, url, kw = calls[0]
    assert method == "DELETE"
    assert url.endswith("/events/ev-123")
    assert kw["params"]["sendUpdates"] == "all"


@pytest.mark.asyncio
async def test_event_body_converts_tz_and_maps_attendees(monkeypatch, gcal_module, meeting_doc):
    # Patch tenant tz lookup
    async def _tz(cid):
        return "Asia/Kolkata"

    async def _fake_find_users(*a, **kw):
        class _Cur:
            async def to_list(self, n):
                return [
                    {"email": "u1@acme.com", "name": "User One"},
                    {"email": "u2@acme.com", "name": "User Two"},
                ]
        return _Cur()

    # notification_service._tenant_tz was imported into gcal module
    monkeypatch.setattr(gcal_module, "_tenant_tz", _tz)

    # Patch get_db().users.find to return our fake cursor
    class _Users:
        def find(self, *a, **kw):
            class _Cur:
                async def to_list(self, n):
                    return [
                        {"email": "u1@acme.com", "name": "User One"},
                        {"email": "u2@acme.com", "name": "User Two"},
                    ]
            return _Cur()

    class _DB:
        users = _Users()

    monkeypatch.setattr(gcal_module, "get_db", lambda: _DB())

    body = await gcal_module._event_body(meeting_doc)
    assert body["start"]["timeZone"] == "Asia/Kolkata"
    assert body["end"]["timeZone"] == "Asia/Kolkata"
    # ISO strings should have +05:30 offset after tz conversion
    assert "+05:30" in body["start"]["dateTime"]
    assert "+05:30" in body["end"]["dateTime"]
    assert body["attendees"] == [
        {"email": "u1@acme.com", "displayName": "User One"},
        {"email": "u2@acme.com", "displayName": "User Two"},
    ]
    assert "Organised by Admin User" in body["description"]
