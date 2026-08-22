import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings
from backend.models.schemas import CompanyBrief

# Share keys arrive from URLs, so anything used to address storage must match
# this before it reaches the filesystem or the key-value store.
_SAFE_KEY = re.compile(r"[a-z0-9-]{1,64}")

# How many recent scouts to remember for the home page.
RECENT_LIMIT = 8


def _entry_key(raw: str) -> str | None:
    try:
        return json.loads(raw).get("key")
    except (json.JSONDecodeError, AttributeError):
        return None


def _log(message: str) -> None:
    # flush because Render pipes stdout, where print() is block-buffered and
    # these lines would otherwise never surface in the logs.
    print(f"[cache] {message}", flush=True)


def _normalise(query: str) -> str:
    """Collapse cosmetic differences so "BasiGo", "basigo " and "Basi  Go"
    all hit the same cache entry."""
    lowered = query.strip().lower()
    return re.sub(r"\s+", " ", lowered)


def _key_for(query: str) -> str:
    """A storage-safe, human-readable key.

    Readable because it doubles as the share URL slug: "basigo" reads better
    in a link than a hash. A short hash is appended so that two queries which
    slugify identically (e.g. "M&A Corp" and "M A Corp") never collide, and
    so an empty slug (a query of only punctuation) still yields a valid name.
    """
    normalised = _normalise(query)
    digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:8]
    slug = re.sub(r"[^a-z0-9]+", "-", normalised).strip("-")[:40]
    return f"{slug}-{digest}" if slug else digest


class _FileBackend:
    """Stores entries as JSON files. Used for local development."""

    def __init__(self, directory: str):
        self.dir = Path(directory)

    def read(self, key: str) -> str | None:
        path = self.dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def write(self, key: str, payload: str, ttl_seconds: int) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            # Write to a temp file first so a crash mid-write cannot leave a
            # truncated entry behind.
            tmp = self.dir / f"{key}.tmp"
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(self.dir / f"{key}.json")
        except OSError:
            pass

    def push_recent(self, entry: str, limit: int) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            existing = self.list_recent(limit)
            # Same company scouted twice should move up, not appear twice.
            key = json.loads(entry).get("key")
            existing = [e for e in existing if json.loads(e).get("key") != key]
            merged = [entry] + existing
            tmp = self.dir / "_recent.tmp"
            tmp.write_text(json.dumps(merged[:limit]), encoding="utf-8")
            tmp.replace(self.dir / "_recent.json")
        except (OSError, json.JSONDecodeError):
            pass

    def list_recent(self, limit: int) -> list[str]:
        path = self.dir / "_recent.json"
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))[:limit]
        except (OSError, json.JSONDecodeError):
            return []


class _RedisBackend:
    """Stores entries in Render Key Value, which outlives the web service's
    ephemeral disk and its idle spin-downs."""

    def __init__(self, url: str):
        import redis  # imported lazily so local runs need no redis install

        self.client = redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        # from_url only parses the URL; it connects lazily. Ping so an
        # unreachable host fails here and falls back to disk, rather than
        # failing on every read and write for the life of the process.
        self.client.ping()

    def read(self, key: str) -> str | None:
        try:
            return self.client.get(f"brief:{key}")
        except Exception as e:
            # A cache outage must degrade to a slow lookup, never an error.
            _log(f"Redis read failed: {e}")
            return None

    def write(self, key: str, payload: str, ttl_seconds: int) -> None:
        try:
            self.client.setex(f"brief:{key}", ttl_seconds, payload)
        except Exception as e:
            _log(f"Redis write failed: {e}")

    def push_recent(self, entry: str, limit: int) -> None:
        try:
            # Entries carry a timestamp, so LREM on the raw string would never
            # match a previous scout of the same company. Filter by key and
            # rewrite the short list instead.
            key = json.loads(entry).get("key")
            existing = [
                e for e in (self.client.lrange("briefs:recent", 0, limit * 2) or [])
                if _entry_key(e) != key
            ]
            merged = [entry] + existing[: limit - 1]

            pipe = self.client.pipeline()
            pipe.delete("briefs:recent")
            pipe.rpush("briefs:recent", *merged)
            pipe.execute()
        except Exception as e:
            _log(f"Redis recent-push failed: {e}")

    def list_recent(self, limit: int) -> list[str]:
        try:
            return self.client.lrange("briefs:recent", 0, limit - 1) or []
        except Exception as e:
            _log(f"Redis recent-read failed: {e}")
            return []


class BriefCache:
    """Cache of completed briefs, backed by Render Key Value when configured
    and by local files otherwise.

    A full scout costs ~6 Gemini calls against a 20/day free-tier quota, so
    this is what makes repeat lookups viable at all. It also backs the share
    links: /r/{key} resolves through here.
    """

    def __init__(
        self,
        cache_dir: str | None = None,
        ttl_days: int | None = None,
        redis_url: str | None = None,
    ):
        # Explicit None checks, not `or` — a caller passing ttl_days=0 means
        # "treat everything as stale", not "use the default".
        days = ttl_days if ttl_days is not None else settings.cache_ttl_days
        self.ttl_seconds = days * 86400

        url = redis_url if redis_url is not None else settings.redis_url
        directory = cache_dir if cache_dir is not None else settings.cache_dir

        self.backend: _FileBackend | _RedisBackend
        if url:
            try:
                self.backend = _RedisBackend(url)
                _log("Using Render Key Value for persistent caching")
            except Exception as e:
                # Missing package or bad URL shouldn't take the app down.
                _log(f"Redis unavailable ({e}); falling back to disk")
                self.backend = _FileBackend(directory)
        else:
            # Silence here would be indistinguishable from a working Redis, and
            # on Render this backend quietly loses every report on restart.
            _log(f"No REDIS_URL set; caching to disk at {directory}")
            self.backend = _FileBackend(directory)

    def key_for(self, query: str) -> str:
        """Public accessor so callers can build share links."""
        return _key_for(query)

    def get(self, query: str) -> CompanyBrief | None:
        if not settings.cache_enabled:
            return None
        return self._load(_key_for(query))

    def get_by_key(self, key: str) -> CompanyBrief | None:
        """Load a brief by its share key rather than the original query."""
        if not settings.cache_enabled:
            return None
        if not _SAFE_KEY.fullmatch(key):
            return None
        return self._load(key)

    def _load(self, key: str) -> CompanyBrief | None:
        raw = self.backend.read(key)
        if raw is None:
            return None

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # A corrupt or half-written entry should behave like a miss.
            return None

        cached_at = payload.get("cached_at", 0)
        # Redis expires entries itself, but the file backend does not, and
        # shortening the configured TTL should take effect either way.
        if time.time() - cached_at > self.ttl_seconds:
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
            cached_at, tz=timezone.utc
        ).isoformat()
        return brief

    def set(self, query: str, brief: CompanyBrief) -> None:
        if not settings.cache_enabled:
            return

        try:
            payload = json.dumps(
                {
                    "cached_at": time.time(),
                    "query": _normalise(query),
                    "brief": brief.model_dump(mode="json"),
                }
            )
        except (TypeError, ValueError):
            return

        # Caching is an optimisation; never fail a request over it.
        key = _key_for(query)
        self.backend.write(key, payload, self.ttl_seconds)

        # A compact index entry, so listing recent scouts doesn't mean loading
        # and parsing a dozen full briefs.
        try:
            scores = brief.analysis.scores
            self.backend.push_recent(
                json.dumps(
                    {
                        "key": key,
                        "name": brief.evidence.company.name,
                        "country": brief.evidence.company.country,
                        "score": scores.overall_score if scores else None,
                        "recommendation": scores.recommendation if scores else None,
                        "at": time.time(),
                    }
                ),
                RECENT_LIMIT,
            )
        except Exception:
            # The list is a convenience; never let it break a completed scout.
            pass

    def set_partial(self, query: str, payload: dict) -> None:
        """Save completed research before the stages that might still fail.

        A scout costs ~6 Gemini calls against a 20/day allowance. Losing the
        last call used to discard all five that came before it, so a run that
        died at scoring cost a full day's budget and produced nothing.
        """
        if not settings.cache_enabled:
            return
        try:
            body = json.dumps({"cached_at": time.time(), "partial": payload})
        except (TypeError, ValueError):
            return
        # Shorter-lived than a finished brief: this is a resume aid, and stale
        # evidence should be re-gathered rather than silently reused.
        self.backend.write(f"{_key_for(query)}-partial", body, 2 * 86400)

    def get_partial(self, query: str) -> dict | None:
        if not settings.cache_enabled:
            return None
        raw = self.backend.read(f"{_key_for(query)}-partial")
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if time.time() - payload.get("cached_at", 0) > 2 * 86400:
            return None
        return payload.get("partial")

    def recent(self, limit: int = RECENT_LIMIT) -> list[dict]:
        """Most recently scouted companies, newest first."""
        if not settings.cache_enabled:
            return []
        out = []
        for raw in self.backend.list_recent(limit):
            try:
                entry = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(entry, dict) and entry.get("key"):
                out.append(entry)
        return out
