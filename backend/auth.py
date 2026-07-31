import os
import jwt
import bcrypt
import uuid
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, status
from pydantic import BaseModel, EmailStr, Field

from db import get_db

log = logging.getLogger("hrmis.auth")

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# OTP tuning
OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 3
OTP_SEND_COOLDOWN_SECONDS = 45
OTP_MAX_SENDS_PER_HOUR = 5
RESET_TOKEN_EXPIRY_MINUTES = 15

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------- helpers ----------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
        "type": "access",
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def _strip_user(u: dict) -> dict:
    u.pop("password_hash", None)
    u.pop("_id", None)
    return u


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    db = get_db()
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return _strip_user(user)


def require_roles(*roles: str):
    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker


# ---------- request bodies ----------

class LoginBody(BaseModel):
    email: EmailStr
    password: str


class ForgotBody(BaseModel):
    email: EmailStr


class VerifyOtpBody(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=OTP_LENGTH, max_length=OTP_LENGTH)


class ResetBody(BaseModel):
    reset_token: str = Field(min_length=20)
    new_password: str = Field(min_length=6, max_length=200)


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str
    role: str = "employee"


# ---------- endpoints ----------

@router.post("/login")
async def login(body: LoginBody):
    db = get_db()
    email = body.email.lower()

    # brute-force protection
    attempt_key = f"login:{email}"
    record = await db.login_attempts.find_one({"key": attempt_key})
    if record and record.get("locked_until"):
        if datetime.now(timezone.utc) < datetime.fromisoformat(record["locked_until"]):
            raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")

    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user or not verify_password(body.password, user["password_hash"]):
        # increment attempts
        count = (record["count"] if record else 0) + 1
        update = {"key": attempt_key, "count": count, "updated_at": datetime.now(timezone.utc).isoformat()}
        if count >= 5:
            update["locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            update["count"] = 0
        await db.login_attempts.update_one({"key": attempt_key}, {"$set": update}, upsert=True)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if user.get("status") == "inactive":
        raise HTTPException(status_code=403, detail="Account is inactive. Contact your administrator.")

    # success
    await db.login_attempts.delete_one({"key": attempt_key})
    token = create_access_token(user["id"], user["email"], user["role"])
    user_payload = _strip_user(user)
    # attach company info for convenience
    if user_payload.get("company_id"):
        company = await db.companies.find_one({"id": user_payload["company_id"]}, {"_id": 0, "id": 1, "name": 1, "slug": 1, "accent_color": 1, "logo_path": 1})
        if company:
            company["has_logo"] = bool(company.pop("logo_path", None))
            user_payload["company"] = company
    return {
        "token": token,
        "user": user_payload,
    }


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    db = get_db()
    if user.get("company_id"):
        company = await db.companies.find_one({"id": user["company_id"]}, {"_id": 0, "id": 1, "name": 1, "slug": 1, "accent_color": 1, "logo_path": 1})
        if company:
            company["has_logo"] = bool(company.pop("logo_path", None))
            user["company"] = company
    return user


@router.post("/logout")
async def logout():
    return {"success": True}


@router.post("/register")
async def register(body: RegisterBody, _admin: dict = Depends(require_roles("super_admin", "hr"))):
    """Admin/HR-only registration of new users."""
    db = get_db()
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "name": body.name,
        "role": body.role,
        "status": "active",
        "password_hash": hash_password(body.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user)
    return _strip_user(dict(user))


@router.post("/forgot-password")
async def forgot_password(body: ForgotBody):
    """Step 1 — send a WhatsApp OTP to the user's registered phone.

    Always returns 200 with a generic hint so bad actors cannot enumerate
    which emails belong to the company (`phone_hint` is None when the account
    doesn't exist or has no phone).
    """
    db = get_db()
    email = body.email.lower().strip()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    generic = {"success": True, "phone_hint": None}
    if not user:
        return generic

    # Look up the phone from the employee record (users don't carry phones)
    emp = await db.employees.find_one(
        {"user_id": user["id"], "company_id": user.get("company_id")},
        {"_id": 0, "phone": 1},
    )
    phone = (emp or {}).get("phone") or user.get("phone")
    if not phone:
        # Best effort — record the attempt but don't leak the reason
        log.warning("[forgot-password] no phone on file for %s", email)
        return generic

    now = datetime.now(timezone.utc)

    # Rate limit — max 5 sends per rolling hour, 45s cooldown between sends
    hourly = await db.password_reset_otps.count_documents({
        "user_id": user["id"],
        "created_at": {"$gte": (now - timedelta(hours=1)).isoformat()},
    })
    if hourly >= OTP_MAX_SENDS_PER_HOUR:
        # Silent 200 — the throttled user has usually already got the earlier code
        return {**generic, "phone_hint": _mask_phone(phone), "throttled": True}

    last = await db.password_reset_otps.find_one(
        {"user_id": user["id"]}, {"_id": 0}, sort=[("created_at", -1)],
    )
    if last:
        try:
            last_ts = datetime.fromisoformat(last["created_at"])
            if (now - last_ts).total_seconds() < OTP_SEND_COOLDOWN_SECONDS:
                return {**generic, "phone_hint": _mask_phone(phone), "cooldown": True}
        except Exception:
            pass

    # Generate + store hashed OTP
    otp_code = f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"
    otp_hash = hashlib.sha256(otp_code.encode()).hexdigest()
    await db.password_reset_otps.update_many(
        {"user_id": user["id"], "used": False},
        {"$set": {"used": True, "invalidated_reason": "superseded"}},
    )
    await db.password_reset_otps.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "email": email,
        "otp_hash": otp_hash,
        "attempts_left": OTP_MAX_ATTEMPTS,
        "used": False,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=OTP_EXPIRY_MINUTES)).isoformat(),
    })
    log.info("[forgot-password] OTP generated for %s (expires in %dm)", email, OTP_EXPIRY_MINUTES)

    # Fire the WhatsApp send — never raises, always logs
    try:
        from whatsapp_service import send_template, get_config, DEFAULT_TEMPLATES
        cfg = await get_config(user["company_id"]) if user.get("company_id") else None
        if cfg and cfg.get("enabled") and (cfg.get("events_enabled") or {}).get("password_reset_otp", True):
            tmpl = ((cfg.get("templates") or {}).get("password_reset_otp")
                    or DEFAULT_TEMPLATES["password_reset_otp"])
            params = [user["name"], otp_code, str(OTP_EXPIRY_MINUTES)]
            await send_template(user["company_id"], phone, tmpl, params)
        else:
            log.warning("[forgot-password] WhatsApp not configured for company %s — OTP for %s: %s",
                        user.get("company_id"), email, otp_code)
    except Exception as e:
        log.exception("[forgot-password] send failed: %s", e)

    return {**generic, "phone_hint": _mask_phone(phone)}


@router.post("/verify-otp")
async def verify_otp(body: VerifyOtpBody):
    """Step 2 — verify the 6-digit code and hand back a short-lived reset JWT."""
    db = get_db()
    email = body.email.lower().strip()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=400, detail="Invalid code or code has expired")

    record = await db.password_reset_otps.find_one(
        {"user_id": user["id"], "used": False},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if not record:
        raise HTTPException(status_code=400, detail="Invalid code or code has expired")

    # Expiry
    try:
        expires_at = datetime.fromisoformat(record["expires_at"])
    except Exception:
        expires_at = datetime.now(timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        await db.password_reset_otps.update_one({"id": record["id"]},
            {"$set": {"used": True, "invalidated_reason": "expired"}})
        raise HTTPException(status_code=400, detail="Code has expired. Please request a new one.")

    # Constant-time compare
    supplied_hash = hashlib.sha256(body.otp.strip().encode()).hexdigest()
    if not hmac.compare_digest(supplied_hash, record["otp_hash"]):
        new_attempts = max(0, record.get("attempts_left", OTP_MAX_ATTEMPTS) - 1)
        if new_attempts <= 0:
            await db.password_reset_otps.update_one({"id": record["id"]},
                {"$set": {"used": True, "invalidated_reason": "too_many_attempts", "attempts_left": 0}})
            raise HTTPException(status_code=400,
                detail="Too many wrong codes. Please request a new OTP.")
        await db.password_reset_otps.update_one({"id": record["id"]},
            {"$set": {"attempts_left": new_attempts}})
        raise HTTPException(status_code=400,
            detail=f"Wrong code — {new_attempts} attempt{'s' if new_attempts != 1 else ''} left.")

    # Success → mint the reset JWT and mark OTP as verified
    reset_jti = str(uuid.uuid4())
    reset_token = jwt.encode({
        "sub": user["id"], "email": email, "otp_id": record["id"],
        "type": "password_reset", "jti": reset_jti,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES),
    }, _jwt_secret(), algorithm=JWT_ALGORITHM)
    await db.password_reset_otps.update_one({"id": record["id"]},
        {"$set": {"used": True, "invalidated_reason": "verified",
                  "reset_jti": reset_jti, "verified_at": datetime.now(timezone.utc).isoformat()}})
    return {"reset_token": reset_token, "expires_in": RESET_TOKEN_EXPIRY_MINUTES * 60}


@router.post("/reset-password")
async def reset_password(body: ResetBody):
    """Step 3 — apply the new password using the reset JWT from /verify-otp."""
    db = get_db()
    try:
        payload = jwt.decode(body.reset_token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Reset link has expired — start over")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid reset token")
    if payload.get("type") != "password_reset":
        raise HTTPException(status_code=400, detail="Invalid reset token")

    # Single-use: reject if the JTI on the OTP has already been consumed
    otp_id = payload.get("otp_id")
    otp = await db.password_reset_otps.find_one({"id": otp_id}, {"_id": 0}) if otp_id else None
    if not otp or otp.get("reset_jti") != payload.get("jti"):
        raise HTTPException(status_code=400, detail="Reset token already used or superseded")
    if otp.get("consumed_at"):
        raise HTTPException(status_code=400, detail="This reset link has already been used")

    await db.users.update_one(
        {"id": payload["sub"]},
        {"$set": {"password_hash": hash_password(body.new_password),
                  "password_changed_at": datetime.now(timezone.utc).isoformat()}},
    )
    await db.password_reset_otps.update_one({"id": otp_id},
        {"$set": {"consumed_at": datetime.now(timezone.utc).isoformat()}})
    # Invalidate any lingering login lockout
    await db.login_attempts.delete_one({"key": f"login:{payload['email']}"})
    log.info("[reset-password] password updated for user_id=%s", payload["sub"])
    return {"success": True}


def _mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) < 4:
        return "•" * len(digits)
    return "•" * (len(digits) - 4) + digits[-4:]
