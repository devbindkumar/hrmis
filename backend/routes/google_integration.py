import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from auth import get_current_user, require_roles
from google_calendar_service import (
    build_auth_url, decode_state, disconnect, exchange_code, get_status, is_configured, redirect_uri,
)
from tenant import company_id_of

router = APIRouter(prefix="/api/google", tags=["google"])


def _frontend_origin() -> str:
    u = urlparse(redirect_uri())
    return f"{u.scheme}://{u.netloc}"


@router.get("/status")
async def status(user: dict = Depends(get_current_user)):
    s = await get_status(company_id_of(user))
    if user.get("role") != "super_admin":
        s.pop("redirect_uri", None)
    return s


@router.get("/oauth/start")
async def oauth_start(admin: dict = Depends(require_roles("super_admin"))):
    if not is_configured():
        raise HTTPException(status_code=400, detail="Google credentials are not configured on the server yet.")
    return {"authorization_url": build_auth_url(company_id_of(admin), admin["id"])}


@router.get("/oauth/callback")
async def oauth_callback(code: str = "", state: str = "", error: str = ""):
    target = f"{_frontend_origin()}/admin/settings"
    if error or not code or not state:
        return RedirectResponse(f"{target}?google=error&reason={error or 'missing_code'}")
    try:
        st = decode_state(state)
        await exchange_code(st["cid"], st["uid"], code)
    except Exception as e:
        logging.getLogger("hrmis.google").error(f"google oauth callback failed: {e}")
        return RedirectResponse(f"{target}?google=error&reason=exchange_failed")
    return RedirectResponse(f"{target}?google=connected")


@router.delete("/disconnect")
async def oauth_disconnect(admin: dict = Depends(require_roles("super_admin"))):
    await disconnect(company_id_of(admin))
    return {"success": True}
