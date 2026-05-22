import os
import asyncio
import logging

import resend

logger = logging.getLogger(__name__)


def _ensure_configured():
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return False
    resend.api_key = api_key
    return True


async def send_email(to: str, subject: str, html: str) -> bool:
    """Send an email via Resend in a background thread. Never raises."""
    if not _ensure_configured():
        logger.warning("RESEND_API_KEY not set, skipping email.")
        return False
    sender = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
    company = os.environ.get("COMPANY_NAME", "HRMIS")
    params = {
        "from": f"{company} <{sender}>",
        "to": [to],
        "subject": subject,
        "html": html,
    }
    try:
        res = await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Email sent to {to}, id={res.get('id') if isinstance(res, dict) else res}")
        return True
    except Exception as e:
        # never break the user flow over a failed email
        logger.error(f"Resend email failed to {to}: {e}")
        return False


def render(title: str, body_html: str, cta_text: str | None = None, cta_url: str | None = None) -> str:
    cta = ""
    if cta_text and cta_url:
        cta = f"""
        <tr><td style="padding: 24px 0 0 0;">
          <a href="{cta_url}" style="display:inline-block;background:#0F172A;color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;font-family:Manrope,Arial,sans-serif;font-size:14px;font-weight:600;">{cta_text}</a>
        </td></tr>
        """
    return f"""
    <html>
      <body style="margin:0;background:#F8F9FA;padding:32px 16px;">
        <table cellpadding="0" cellspacing="0" border="0" width="560" align="center" style="background:#FFFFFF;border:1px solid #E5E7EB;border-radius:16px;padding:32px;font-family:Manrope,Arial,sans-serif;color:#111827;max-width:560px;">
          <tr><td>
            <div style="font-family:Outfit,Arial,sans-serif;font-size:22px;font-weight:600;color:#0F172A;margin-bottom:16px;">{title}</div>
            <div style="font-size:15px;line-height:1.65;color:#374151;">{body_html}</div>
            {cta}
            <div style="margin-top:32px;padding-top:16px;border-top:1px solid #E5E7EB;font-size:12px;color:#6B7280;">Sent automatically by your HRMIS workspace.</div>
          </td></tr>
        </table>
      </body>
    </html>
    """
