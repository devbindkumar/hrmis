import os
import jwt
import bcrypt
import uuid
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, status
from pydantic import BaseModel, EmailStr, Field

from db import get_db

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

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


class ResetBody(BaseModel):
    token: str
    new_password: str = Field(min_length=6)


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
    db = get_db()
    email = body.email.lower()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    # Always return success to avoid enumeration
    if not user:
        return {"success": True}
    token = secrets.token_urlsafe(32)
    await db.password_reset_tokens.insert_one({
        "token": token,
        "user_id": user["id"],
        "used": False,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Email is sent by caller pipeline; we expose the token for dev
    print(f"[forgot-password] reset token for {email}: {token}")
    return {"success": True, "reset_token_dev": token}


@router.post("/reset-password")
async def reset_password(body: ResetBody):
    db = get_db()
    record = await db.password_reset_tokens.find_one({"token": body.token}, {"_id": 0})
    if not record or record.get("used"):
        raise HTTPException(status_code=400, detail="Invalid or used token")
    expires_at = record["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="Token expired")
    await db.users.update_one(
        {"id": record["user_id"]},
        {"$set": {"password_hash": hash_password(body.new_password)}},
    )
    await db.password_reset_tokens.update_one({"token": body.token}, {"$set": {"used": True}})
    return {"success": True}
