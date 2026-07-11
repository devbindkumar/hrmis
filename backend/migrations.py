"""Idempotent, additive DB migrations that run on every backend startup.

Each migration is a small async function returning ``None``. Migrations MUST
be safe to re-run — they check current state before writing. This is the
right home for "flip an existing default", "unset a deprecated field",
"backfill a new field from an existing one", etc.
"""
from __future__ import annotations

import logging

from db import get_db

logger = logging.getLogger("hrmis.migrations")


async def _flip_checkin_checkout_default() -> None:
    """Iteration 12 changed the default for ``events_enabled.checkin_checkout``
    to True, but tenants who saved a config while the old default (False) was
    active kept the persisted False. Flip only those rows — leave any tenant
    that has explicitly turned it off since then alone (rare and audited).
    """
    db = get_db()
    res = await db.whatsapp_configs.update_many(
        {"events_enabled.checkin_checkout": False},
        {"$set": {"events_enabled.checkin_checkout": True}},
    )
    if res.modified_count:
        logger.info(
            f"[migration] flipped events_enabled.checkin_checkout on "
            f"{res.modified_count} tenant(s)"
        )


async def run_all() -> None:
    for fn in (_flip_checkin_checkout_default,):
        try:
            await fn()
        except Exception as e:
            # Never crash startup — migrations are best-effort
            logger.error(f"[migration] {fn.__name__} failed: {e}")
