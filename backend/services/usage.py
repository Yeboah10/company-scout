"""Counting what we spend against each provider's free tier.

Two jobs, and the first is what makes the second trustworthy:

  1. Tell the pipeline which models still have budget today, so a run moves to
     another model rather than stopping while three other allowances sit
     untouched.
  2. Answer "how close am I to a limit, and when does it reset?" without
     logging into three dashboards.

Counts are what this process observed, not what the provider has recorded.
They reset with the process unless a shared store is configured, and a
provider's own console is always the authority. Presented that way in the UI:
a number that looks official but is quietly wrong is worse than an honest
estimate.
"""

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from backend.config import settings

# Free-tier ceilings, for showing headroom. Update if a plan changes.
GEMINI_DAILY_PER_MODEL = 20
TAVILY_MONTHLY = 1000
# A fallback only: /usage and the pipeline both prefer Hunter's own count.
# This was 25 on the strength of their pricing page; the account reported
# 50 the first time it was asked.
HUNTER_MONTHLY = 50
APOLLO_MONTHLY = 100
# Groq resets daily, not monthly — a rough display figure only; the
# provider's own console remains the authority, same disclaimer as everywhere
# else on this page.
GROQ_DAILY = 14_400
CEREBRAS_DAILY_TOKENS = 1_000_000

# Where the durable copy of the counters lives.
_STORE_KEY = "usage-counters"

# Gemini's free-tier day is Pacific.
_PACIFIC_OFFSET = timedelta(hours=-8)


def _gemini_day(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return (now + _PACIFIC_OFFSET).strftime("%Y-%m-%d")


def _month(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def seconds_until_gemini_reset(now: datetime | None = None) -> int:
    """Until the next Pacific midnight."""
    now = now or datetime.now(timezone.utc)
    local = now + _PACIFIC_OFFSET
    tomorrow = (local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(0, int((tomorrow - local).total_seconds()))


def seconds_until_month_reset(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if now.month == 12:
        nxt = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0,
                          second=0, microsecond=0)
    else:
        nxt = now.replace(month=now.month + 1, day=1, hour=0, minute=0,
                          second=0, microsecond=0)
    return max(0, int((nxt - now).total_seconds()))


@dataclass
class _Counters:
    gemini_day: str = field(default_factory=_gemini_day)
    gemini: dict[str, int] = field(default_factory=dict)
    # Models that returned a daily-quota error today. Believed over the
    # counter: the provider counts attempts this process never saw.
    gemini_exhausted: set[str] = field(default_factory=set)
    # Rides the same daily boundary as Gemini — Groq's own limit resets
    # daily, unlike Tavily/Hunter/Apollo below, which reset monthly.
    groq: int = 0
    cerebras: int = 0

    month: str = field(default_factory=_month)
    tavily: int = 0
    # Search fallback, monthly like Tavily rather than daily like the LLM
    # fallbacks — it substitutes for Tavily, so it shares Tavily's clock.
    exa: int = 0
    hunter: int = 0
    apollo: int = 0


class UsageTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._c = _Counters()

    def _roll(self) -> None:
        """Caller holds the lock. Reset counters whose period has turned over."""
        today = _gemini_day()
        if self._c.gemini_day != today:
            self._c.gemini_day = today
            self._c.gemini = {}
            self._c.gemini_exhausted = set()
            self._c.groq = 0
            self._c.cerebras = 0

        month = _month()
        if self._c.month != month:
            self._c.month = month
            self._c.tavily = 0
            self._c.exa = 0
            self._c.hunter = 0
            self._c.apollo = 0

    # Set by the app once the cache is available. Counters are useless without
    # it: Render restarts the service on every deploy and after each idle
    # spin-down, and an in-memory count resets to zero each time.
    _store = None

    def attach_store(self, store) -> None:
        """Give the tracker somewhere durable to keep counts.

        `store` needs read(key) and write(key, payload, ttl). Loads whatever is
        already there so a restart continues the day rather than restarting it.
        """
        self._store = store
        try:
            raw = store.read(_STORE_KEY)
            if raw:
                self.load_json(raw)
        except Exception:
            # A missing or unreadable count is not worth failing over.
            pass

    def _persist(self) -> None:
        """Caller holds the lock."""
        if self._store is None:
            return
        try:
            payload = json.dumps(
                {
                    "gemini_day": self._c.gemini_day,
                    "gemini": self._c.gemini,
                    "gemini_exhausted": sorted(self._c.gemini_exhausted),
                    "month": self._c.month,
                    "tavily": self._c.tavily,
                    "exa": self._c.exa,
                    "hunter": self._c.hunter,
                    "apollo": self._c.apollo,
                    "groq": self._c.groq,
                    "cerebras": self._c.cerebras,
                }
            )
            # Two days: long enough to survive a restart and the day boundary,
            # short enough that an abandoned deployment's counts expire.
            self._store.write(_STORE_KEY, payload, 2 * 86400)
        except Exception:
            pass

    def record_gemini(self, model: str) -> None:
        with self._lock:
            self._roll()
            self._c.gemini[model] = self._c.gemini.get(model, 0) + 1
            self._persist()

    def mark_exhausted(self, model: str) -> None:
        with self._lock:
            self._roll()
            self._c.gemini_exhausted.add(model)
            self._persist()

    def is_exhausted(self, model: str) -> bool:
        with self._lock:
            self._roll()
            return model in self._c.gemini_exhausted

    def record_tavily(self, n: int = 1) -> None:
        with self._lock:
            self._roll()
            self._c.tavily += n
            self._persist()

    def record_hunter(self, n: int = 1) -> None:
        with self._lock:
            self._roll()
            self._c.hunter += n
            self._persist()

    def hunter_remaining(self) -> int:
        """Lookups believed left this month.

        A floor, not a measurement: this counts what this process spent, and
        Hunter counts everything on the account. Used to stop spending, never
        to promise headroom.
        """
        with self._lock:
            self._roll()
            return max(0, HUNTER_MONTHLY - self._c.hunter)

    def record_apollo(self, n: int = 1) -> None:
        with self._lock:
            self._roll()
            self._c.apollo += n
            self._persist()

    def record_exa(self, n: int = 1) -> None:
        with self._lock:
            self._roll()
            self._c.exa += n
            self._persist()

    def record_groq(self, n: int = 1) -> None:
        with self._lock:
            self._roll()
            self._c.groq += n
            self._persist()

    def record_cerebras(self, n: int = 1) -> None:
        with self._lock:
            self._roll()
            self._c.cerebras += n
            self._persist()

    def snapshot(self, models: list[str]) -> dict:
        """Everything the usage page needs, in one read."""
        with self._lock:
            self._roll()
            gemini = []
            for m in models:
                used = self._c.gemini.get(m, 0)
                exhausted = m in self._c.gemini_exhausted
                gemini.append(
                    {
                        "model": m,
                        "used": used,
                        "limit": GEMINI_DAILY_PER_MODEL,
                        # An exhausted model has no headroom regardless of what
                        # this process counted; usage before restart is unseen.
                        "remaining": 0 if exhausted else max(0, GEMINI_DAILY_PER_MODEL - used),
                        "exhausted": exhausted,
                    }
                )

            scouts_left = sum(g["remaining"] for g in gemini) // 6

            return {
                "gemini": {
                    "models": gemini,
                    "day": self._c.gemini_day,
                    "resets_in_seconds": seconds_until_gemini_reset(),
                    "total_remaining": sum(g["remaining"] for g in gemini),
                    "approx_scouts_left": scouts_left,
                },
                "tavily": {
                    "used": self._c.tavily,
                    "limit": TAVILY_MONTHLY,
                    "remaining": max(0, TAVILY_MONTHLY - self._c.tavily),
                    "resets_in_seconds": seconds_until_month_reset(),
                },
                "exa": {
                    "configured": bool(settings.exa_api_key),
                    "used": self._c.exa,
                    "resets_in_seconds": seconds_until_month_reset(),
                },
                "hunter": {
                    "used": self._c.hunter,
                    "limit": HUNTER_MONTHLY,
                    "remaining": max(0, HUNTER_MONTHLY - self._c.hunter),
                    "resets_in_seconds": seconds_until_month_reset(),
                },
                "apollo": {
                    "used": self._c.apollo,
                    "limit": APOLLO_MONTHLY,
                    "remaining": max(0, APOLLO_MONTHLY - self._c.apollo),
                    "resets_in_seconds": seconds_until_month_reset(),
                },
                "groq": {
                    "configured": bool(settings.groq_api_key),
                    "used": self._c.groq,
                    "limit": GROQ_DAILY,
                    "remaining": max(0, GROQ_DAILY - self._c.groq),
                    # Resets with Gemini's day, not the calendar month — this
                    # is the fallback path, so it shares Gemini's clock.
                    "resets_in_seconds": seconds_until_gemini_reset(),
                },
                "cerebras": {
                    "configured": bool(settings.cerebras_api_key),
                    # Counted in calls, not tokens: the published limit is
                    # ~1M tokens/day, but the token cost of a call isn't known
                    # until after it returns, so this is a call count shown
                    # next to that figure rather than measured against it.
                    "used": self._c.cerebras,
                    "resets_in_seconds": seconds_until_gemini_reset(),
                },
                "durable": self._store is not None,
            }

    def to_json(self) -> str:
        with self._lock:
            return json.dumps(
                {
                    "gemini_day": self._c.gemini_day,
                    "gemini": self._c.gemini,
                    "gemini_exhausted": sorted(self._c.gemini_exhausted),
                    "month": self._c.month,
                    "tavily": self._c.tavily,
                    "exa": self._c.exa,
                    "hunter": self._c.hunter,
                    "apollo": self._c.apollo,
                    "groq": self._c.groq,
                    "cerebras": self._c.cerebras,
                }
            )

    def load_json(self, raw: str) -> None:
        """Restore counters saved before a restart. Ignores anything malformed
        rather than starting from a corrupted count."""
        try:
            d = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        with self._lock:
            self._c.gemini_day = d.get("gemini_day", _gemini_day())
            self._c.gemini = {k: int(v) for k, v in (d.get("gemini") or {}).items()}
            self._c.gemini_exhausted = set(d.get("gemini_exhausted") or [])
            self._c.month = d.get("month", _month())
            self._c.tavily = int(d.get("tavily", 0))
            self._c.exa = int(d.get("exa", 0))
            self._c.hunter = int(d.get("hunter", 0))
            self._c.apollo = int(d.get("apollo", 0))
            self._c.groq = int(d.get("groq", 0))
            self._c.cerebras = int(d.get("cerebras", 0))
            self._roll()


usage = UsageTracker()
