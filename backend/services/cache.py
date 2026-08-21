import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings
from backend.models.schemas import CompanyBrief


def _normalise(query: str) -> str:
    """Collapse cosmetic differences so "BasiGo", "basigo " and "Basi  Go"
    all hit the same cache entry."""
    lowered = query.strip().lower()
    return re.sub(r"\s+", " ", lowered)


def _key_for(query: str) -> str:
    normalised = _normalise(query)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:32]


class BriefCache:
    """File-backed cache of completed briefs.

    Note: on Render's free tier the filesystem is ephemeral and the service
    spins down when idle, so this cache survives within a warm session but
    not across restarts. It still prevents the common case of re-running a
    company that was just scouted.
    """

    def __init__(self, cache_dir: str | None = None, ttl_days: int | None = None):
        # Explicit None checks, not `or` — a caller passing ttl_days=0 means
        # "treat everything as stale", not "use the default".
        self.dir = Path(cache_dir if cache_dir is not None else settings.cache_dir)
        days = ttl_days if ttl_days is not None else settings.cache_ttl_days
        self.ttl_seconds = days * 86400

    def _path_for(self, query: str) -> Path:
        return self.dir / f"{_key_for(query)}.json"

    def get(self, query: str) -> CompanyBrief | None:
        if not settings.cache_enabled:
            return None

        path = self._path_for(query)
        if not path.exists():
            return None

        try:
            with path.open(encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            # A corrupt or half-written entry should behave like a miss.
            return None

        if time.time() - payload.get("cached_at", 0) > self.ttl_seconds:
            return None

        try:
            brief = CompanyBrief.model_validate(payload["brief"])
        except (KeyError, ValueError):
            # Schema changed since this entry was written.
            return None

        # Let the UI tell the user this is a stored result and how old it is,
        # rather than implying it was just researched.
        brief.from_cache = True
        brief.cached_at = datetime.fromtimestamp(
            payload.get("cached_at", 0), tz=timezone.utc
        ).isoformat()
        return brief

    def set(self, query: str, brief: CompanyBrief) -> None:
        if not settings.cache_enabled:
            return

        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "cached_at": time.time(),
                "query": _normalise(query),
                "brief": brief.model_dump(mode="json"),
            }
            # Write to a temp file first so a crash mid-write cannot leave a
            # truncated entry behind.
            tmp = self._path_for(query).with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f)
            tmp.replace(self._path_for(query))
        except OSError:
            # Caching is an optimisation; never fail a request over it.
            pass
