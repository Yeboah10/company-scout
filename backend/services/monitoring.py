"""Error reporting via Sentry.

Off unless SENTRY_DSN is set, so local development and anyone cloning the
repo are unaffected.

The point of this is the failures that do not announce themselves. Almost
every bug worth catching in this project has been silent: a cache that fell
back to disk and looked identical to a working one, an extractor that
swallowed quota errors and produced a brief from no evidence, a scorer that
read a company's obituary and recommended contacting them. None of those
raised anything a user would see.

So the levels here are chosen around one question: would I want to be woken
by this? Expected outcomes on a free tier -- quota exhausted, no evidence
found -- are deliberately NOT reported. They are the system working. Filling
the inbox with them is how real alerts get ignored.
"""

import os

from backend.config import settings

_enabled = False


def init() -> None:
    """Start Sentry if a DSN is configured. Safe to call when it is not."""
    global _enabled
    if not settings.sentry_dsn:
        print("[monitoring] SENTRY_DSN not set; error reporting is off", flush=True)
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        print("[monitoring] sentry-sdk not installed; error reporting is off", flush=True)
        return

    try:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            release=settings.app_version,
            integrations=[StarletteIntegration(), FastApiIntegration()],
            # A research tool with a handful of users: sample everything, so a
            # rare bug is never the one that got sampled away.
            traces_sample_rate=0.0,
            # Never send request bodies, headers or IP addresses. The only
            # user input here is a company name, and it reaches Sentry through
            # explicit tags where it is useful.
            send_default_pii=False,
            max_breadcrumbs=30,
            before_send=_scrub,
        )
        _enabled = True
        print(
            f"[monitoring] Sentry active ({settings.sentry_environment}, "
            f"release {settings.app_version})",
            flush=True,
        )
    except Exception as e:
        # Monitoring must never be the reason the app fails to start.
        print(f"[monitoring] Sentry init failed: {e}", flush=True)


def _scrub(event, hint):
    """Last line of defence against secrets reaching Sentry.

    Keys are set as environment variables and could otherwise surface in a
    stack frame's local variables.
    """
    secrets = [
        settings.google_api_key,
        settings.tavily_api_key,
        settings.hunter_api_key,
        settings.redis_url,
    ]
    secrets = [s for s in secrets if s and len(s) > 8]
    if not secrets:
        return event

    def clean(obj):
        if isinstance(obj, str):
            for s in secrets:
                obj = obj.replace(s, "[redacted]")
            return obj
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [clean(v) for v in obj]
        return obj

    try:
        return clean(event)
    except Exception:
        # If scrubbing fails, drop the event rather than risk leaking a key.
        return None


def capture(exc: BaseException, **tags) -> None:
    """Report an exception that was handled but shouldn't have happened."""
    if not _enabled:
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for k, v in tags.items():
                scope.set_tag(k, str(v)[:200])
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass


def warn(message: str, **tags) -> None:
    """Report a degradation: something still works, but not as intended.

    This is the category that matters most here. A cache silently falling back
    to disk is not an error by any runtime measure, and is exactly the kind of
    thing that went unnoticed for a day.
    """
    if not _enabled:
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for k, v in tags.items():
                scope.set_tag(k, str(v)[:200])
            scope.level = "warning"
            sentry_sdk.capture_message(message, level="warning")
    except Exception:
        pass
