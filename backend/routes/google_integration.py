import logging
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from auth import get_current_user, require_roles
from google_calendar_service import (
    build_auth_url, clear_app_creds, decode_state, disconnect, exchange_code, get_status,
    is_configured, redirect_uri_from_headers, save_app_creds,
)
from tenant import company_id_of

router = APIRouter(prefix="/api/google", tags=["google"])


def _redirect_uri(request: Request) -> str:
    return redirect_uri_from_headers(request.headers, request.url.netloc)


def _origin(uri: str) -> str:
    u = urlparse(uri)
    return f"{u.scheme}://{u.netloc}"


@router.get("/status")
async def status(request: Request, user: dict = Depends(get_current_user)):
    s = await get_status(company_id_of(user), _redirect_uri(request))
    if user.get("role") != "super_admin":
        for k in ("redirect_uri", "client_id", "client_secret_masked", "creds_source"):
            s.pop(k, None)
    return s


class AppCreds(BaseModel):
    client_id: str
    client_secret: Optional[str] = None


@router.put("/credentials")
async def put_credentials(body: AppCreds, request: Request, admin: dict = Depends(require_roles("super_admin"))):
    cid = company_id_of(admin)
    client_id = body.client_id.strip()
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise HTTPException(status_code=400, detail="Client ID should end with .apps.googleusercontent.com")
    current = await get_status(cid)
    if not (body.client_secret or "").strip() and current.get("creds_source") != "settings":
        raise HTTPException(status_code=400, detail="Client Secret is required")
    await save_app_creds(cid, client_id, (body.client_secret or "").strip() or None)
    return await get_status(cid, _redirect_uri(request))


@router.delete("/credentials")
async def delete_credentials(request: Request, admin: dict = Depends(require_roles("super_admin"))):
    cid = company_id_of(admin)
    await disconnect(cid)
    await clear_app_creds(cid)
    return await get_status(cid, _redirect_uri(request))


@router.get("/oauth/start")
async def oauth_start(request: Request, admin: dict = Depends(require_roles("super_admin"))):
    if not await is_configured(company_id_of(admin)):
        raise HTTPException(status_code=400, detail="Google credentials are not configured yet.")
    return {"authorization_url": await build_auth_url(company_id_of(admin), admin["id"], _redirect_uri(request))}


@router.get("/oauth/callback")
async def oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    ru = _redirect_uri(request)
    target = f"{_origin(ru)}/admin/settings"
    if error or not code or not state:
        return RedirectResponse(f"{target}?google=error&reason={error or 'missing_code'}")
    try:
        st = decode_state(state)
        ru = st.get("ru") or ru
        target = f"{_origin(ru)}/admin/settings"
        await exchange_code(st["cid"], st["uid"], code, ru)
    except Exception as e:
        logging.getLogger("hrmis.google").error(f"google oauth callback failed: {e}")
        return RedirectResponse(f"{target}?google=error&reason=exchange_failed")
    return RedirectResponse(f"{target}?google=connected")


@router.delete("/disconnect")
async def oauth_disconnect(admin: dict = Depends(require_roles("super_admin"))):
    await disconnect(company_id_of(admin))
    return {"success": True}
