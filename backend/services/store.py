"""Durable storage for finished briefs.

The cache and this module answer different questions, and conflating them is
what has been limiting the product:

  CACHE   "serve this report again quickly" — Redis, seven-day expiry, keyed
          by query. Fast, and structurally unable to remember anything for
          longer than a week.
  STORE   "what did this company look like last month, and what changed" —
          Postgres, no expiry, one row per scout run.

Everything the product is growing into — a watchlist, change detection, a
durable evaluation record, saved reports still there next term — is the same
missing thing: rows that outlive a cache.

The whole brief is kept as JSONB rather than shredded across a dozen tables.
The query patterns are not known yet, and normalising ahead of them produces a
schema that is wrong in a way that is expensive to correct. The columns that
*are* extracted are the ones already known to be queried: which company, when,
and what it scored. Claims and sources can be normalised later, out of data
that will still be here.
"""

import json
import threading

from backend.config import settings
from backend.models.schemas import CompanyBrief
from backend.services import monitoring
from backend.services.db import connect as _connect

_lock = threading.Lock()
_ready = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id              BIGSERIAL PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    country         TEXT,
    website         TEXT,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scouted    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scout_runs (
    id              BIGSERIAL PRIMARY KEY,
    company_id      BIGINT REFERENCES companies(id) ON DELETE CASCADE,
    owner           TEXT,
    query           TEXT NOT NULL,
    share_key       TEXT NOT NULL,
    company_name    TEXT,
    company_country TEXT,
    interest_score      NUMERIC(4,2),
    reachability_score  NUMERIC(4,2),
    verdict             TEXT,
    coverage_covered    INTEGER,
    coverage_total      INTEGER,
    claims_count        INTEGER,
    sources_count       INTEGER,
    duration_seconds    NUMERIC(8,2),
    brief           JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS scout_runs_share_key_idx ON scout_runs (share_key);
CREATE INDEX IF NOT EXISTS scout_runs_company_time_idx
    ON scout_runs (company_id, created_at DESC);
CREATE INDEX IF NOT EXISTS scout_runs_time_idx ON scout_runs (created_at DESC);
"""

# Notes on the schema above, kept here rather than as SQL comments so they
# survive a dump/restore:
#
#   companies.slug   Lowercased and punctuation-stripped, so "Twiga Foods" and
#                    "twiga foods" are one company. A watchlist that disagrees
#                    with itself about which company you are watching is worse
#                    than no watchlist.
#   scout_runs.owner Nullable, filled from the signed-in session. There is one
#                    operator today; the column costs nothing now and
#                    retrofitting ownership onto existing rows later is
#                    genuinely painful.
#   the indexes      Reading a shared link always arrives by key; the recent
#                    list and any future "compare with last time" both want
#                    the latest run per company.


def is_enabled() -> bool:
    return bool(settings.database_url)


def ensure_schema() -> bool:
    """Create the tables if they are not there. Safe to call repeatedly."""
    global _ready
    if not is_enabled():
        return False
    with _lock:
        if _ready:
            return True
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA)
            conn.commit()
        with _lock:
            _ready = True
        print("[store] Postgres schema ready", flush=True)
        return True
    except Exception as e:
        # A missing store must not take the site down — the cache still serves
        # reports — but it is announced rather than discovered weeks later.
        print(f"[store] Could not prepare schema: {e}", flush=True)
        monitoring.warn("Postgres schema preparation failed", error=str(e)[:200])
        return False


def _slug(name: str) -> str:
    keep = [c.lower() for c in (name or "") if c.isalnum() or c.isspace()]
    return " ".join("".join(keep).split()) or "unknown"


def save(brief: CompanyBrief, query: str, share_key: str,
         owner: str | None = None) -> None:
    """Record one scout run.

    Never raises: a failed write must not lose a brief the user is already
    looking at.
    """
    if not is_enabled() or not ensure_schema():
        return

    company = brief.evidence.company
    cov = brief.evidence.coverage
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO companies (slug, name, country, website)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (slug) DO UPDATE
                        SET last_scouted = now(),
                            country = COALESCE(EXCLUDED.country, companies.country),
                            website = COALESCE(EXCLUDED.website, companies.website)
                    RETURNING id
                    """,
                    (_slug(company.name), company.name, company.country,
                     company.website),
                )
                company_id = cur.fetchone()[0]

                cur.execute(
                    """
                    INSERT INTO scout_runs (
                        company_id, owner, query, share_key,
                        company_name, company_country,
                        interest_score, reachability_score, verdict,
                        coverage_covered, coverage_total,
                        claims_count, sources_count, duration_seconds, brief
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        company_id, owner, query, share_key,
                        company.name, company.country,
                        brief.interest_score, brief.reachability_score,
                        brief.verdict,
                        cov.covered_count if cov else None,
                        cov.total_areas if cov else None,
                        len(brief.evidence.claims), len(brief.evidence.sources),
                        brief.duration_seconds,
                        json.dumps(brief.model_dump(mode="json")),
                    ),
                )
            conn.commit()
        print(f"[store] Saved run for {company.name}", flush=True)
    except Exception as e:
        print(f"[store] Save failed: {e}", flush=True)
        monitoring.warn("Postgres save failed", error=str(e)[:200])


def load_by_key(share_key: str) -> CompanyBrief | None:
    """The most recent run behind a share link.

    This is what lets a shared report outlive the cache's seven days: a link
    someone was given last month still opens.
    """
    if not is_enabled():
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT brief FROM scout_runs WHERE share_key = %s"
                    " ORDER BY created_at DESC LIMIT 1",
                    (share_key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return CompanyBrief.model_validate(row[0])
    except Exception as e:
        print(f"[store] Load failed: {e}", flush=True)
        return None


def recent(limit: int = 8) -> list[dict]:
    """Most recently scouted companies, one row each, newest run winning.

    DISTINCT ON is what stops "Spiro" and "Spiro battery swapping" showing as
    two separate companies — the duplicate-entry problem the cache-backed
    version has.
    """
    if not is_enabled():
        return []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (company_id)
                           company_name, company_country, share_key,
                           interest_score, reachability_score, verdict, created_at
                    FROM scout_runs
                    WHERE company_id IS NOT NULL
                    ORDER BY company_id, created_at DESC
                    """
                )
                rows = cur.fetchall()
        rows.sort(key=lambda r: r[6], reverse=True)
        return [
            {
                "name": r[0],
                "country": r[1],
                "key": r[2],
                "interest": float(r[3]) if r[3] is not None else None,
                "reach": float(r[4]) if r[4] is not None else None,
                "verdict": r[5],
                "scouted_at": r[6].isoformat(),
            }
            for r in rows[:limit]
        ]
    except Exception as e:
        print(f"[store] Recent failed: {e}", flush=True)
        return []


def history(company_name: str, limit: int = 10) -> list[dict]:
    """Every run for one company, newest first.

    The raw material for "what changed since last time" — which is a query
    against this table rather than a feature anyone has to invent.
    """
    if not is_enabled():
        return []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT r.share_key, r.interest_score, r.reachability_score,
                           r.verdict, r.claims_count, r.created_at
                    FROM scout_runs r
                    JOIN companies c ON c.id = r.company_id
                    WHERE c.slug = %s
                    ORDER BY r.created_at DESC
                    LIMIT %s
                    """,
                    (_slug(company_name), limit),
                )
                rows = cur.fetchall()
        return [
            {
                "key": r[0],
                "interest": float(r[1]) if r[1] is not None else None,
                "reach": float(r[2]) if r[2] is not None else None,
                "verdict": r[3],
                "claims": r[4],
                "scouted_at": r[5].isoformat(),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[store] History failed: {e}", flush=True)
        return []
