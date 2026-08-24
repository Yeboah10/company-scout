"""Outbound email, via Resend.

Nothing else in the product depends on this working. Signup succeeds, the
session cookie is issued and the user is signed in whether or not a welcome
email goes out — the same defensive shape as every other optional integration
here (Hunter, Apollo, Sentry): off unless configured, and a failure is logged,
never raised, so a mail provider having a bad day cannot break account
creation.

Resend rather than raw SMTP: one HTTPS call via the httpx dependency already
in requirements.txt, no new library, no mail server to run or misconfigure.
Free tier is 3,000 emails a month, which this product will not get near for a
long time.
"""

import httpx

from backend.config import settings
from backend.services import monitoring

_API = "https://api.resend.com/emails"
_TIMEOUT = 10.0


def is_configured() -> bool:
    return bool(settings.resend_api_key)


WELCOME_SUBJECT = "Welcome to Company Scout"

WELCOME_HTML = """\
<div style="font-family:Georgia,'Times New Roman',serif;max-width:520px;
            margin:0 auto;color:#201e1d;line-height:1.6">
  <p style="font:800 20px/1 Archivo,Arial,sans-serif;letter-spacing:-0.02em;
            margin:0 0 24px">Company Scout</p>
  <p>Thanks for signing up.</p>
  <p>Company Scout turns a company name into an evidence-backed brief — what
     the company does, whether it's worth your attention, whether you can
     actually reach anyone there, and what the public record does and does
     not say. Every claim traces back to a dated source you can check
     yourself.</p>
  <p>A good first step: search a company you already know something about,
     so you can see how the evidence lines up against what you expected.</p>
  <p style="margin-top:28px">
    <a href="https://scout.yeboah.works" style="background:#d84a28;color:#fff;
       padding:12px 20px;text-decoration:none;font-weight:700;
       font-family:Archivo,Arial,sans-serif;display:inline-block">
      Scout your first company
    </a>
  </p>
  <p style="margin-top:28px;font-size:13px;color:#605d5d">
    Thanks for using the service.<br>&mdash; Company Scout
  </p>
</div>
"""


def send_welcome(to_email: str) -> bool:
    """Best-effort. Returns whether it went out; never raises."""
    if not is_configured():
        print(f"[mailer] RESEND_API_KEY not set — skipping welcome email to {to_email}",
              flush=True)
        return False

    try:
        r = httpx.post(
            _API,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.mail_from,
                "to": [to_email],
                "subject": WELCOME_SUBJECT,
                "html": WELCOME_HTML,
            },
            timeout=_TIMEOUT,
        )
        if r.status_code >= 400:
            print(f"[mailer] Resend rejected the welcome email ({r.status_code}): "
                  f"{r.text[:200]}", flush=True)
            monitoring.warn("Welcome email rejected", status=r.status_code)
            return False
        print(f"[mailer] Welcome email sent to {to_email}", flush=True)
        return True
    except Exception as e:
        print(f"[mailer] Welcome email failed: {e}", flush=True)
        monitoring.warn("Welcome email failed", error=str(e)[:200])
        return False
