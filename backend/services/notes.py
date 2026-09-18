"""Team notes on a brief — private annotations a signed-in user attaches to
a scouted company.

A brief is read-only output. This turns it into a working document: "Called
the CEO, he's open to a case study" or "Skip — same story as Moniepoint."
Each note is tied to a user email and a share key, so different people can
annotate the same report.
"""

from backend.services.db import connect as _connect
from backend.services import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id          BIGSERIAL PRIMARY KEY,
    share_key   TEXT NOT NULL,
    user_email  TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS notes_key_idx ON notes (share_key, created_at DESC);
"""

_ready = False


def ensure_schema() -> bool:
    global _ready
    if _ready:
        return True
    if not db.is_configured():
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA)
            conn.commit()
        _ready = True
        return True
    except Exception as e:
        print(f"[notes] Could not prepare schema: {e}", flush=True)
        return False


def add(share_key: str, user_email: str, body: str) -> dict | None:
    if not body.strip() or not ensure_schema():
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO notes (share_key, user_email, body)"
                    " VALUES (%s, %s, %s) RETURNING id, created_at",
                    (share_key, user_email, body.strip()),
                )
                row = cur.fetchone()
            conn.commit()
        return {
            "id": row[0],
            "share_key": share_key,
            "user_email": user_email,
            "body": body.strip(),
            "created_at": row[1].isoformat(),
        }
    except Exception as e:
        print(f"[notes] Add failed: {e}", flush=True)
        return None


def list_for(share_key: str) -> list[dict]:
    if not ensure_schema():
        return []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, user_email, body, created_at FROM notes"
                    " WHERE share_key = %s ORDER BY created_at DESC",
                    (share_key,),
                )
                rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "user_email": r[1],
                "body": r[2],
                "created_at": r[3].isoformat(),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[notes] List failed: {e}", flush=True)
        return []


def delete(note_id: int, user_email: str) -> bool:
    """Delete a note. Only the author can delete their own notes."""
    if not ensure_schema():
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM notes WHERE id = %s AND user_email = %s",
                    (note_id, user_email),
                )
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted
    except Exception as e:
        print(f"[notes] Delete failed: {e}", flush=True)
        return False
