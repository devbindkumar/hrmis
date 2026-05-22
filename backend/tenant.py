"""Helpers for company-scoped data access."""
from fastapi import HTTPException


def company_id_of(user: dict) -> str:
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(status_code=403, detail="User is not attached to a company")
    return cid
