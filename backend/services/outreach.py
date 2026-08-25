"""Outreach: drafting an email from evidence already gathered, never a new
research pass, and never sent without the person clicking Send themselves.

Three rules run through this module and are enforced here, not just in the
frontend, because a UI restriction that isn't also a server-side check is not
a restriction at all:

  FOUND      a published address, confirmed to belong to this person. Can be
             sent after one click.
  INFERRED   a guessed address, built from a pattern. Can be sent, but only
             after the sender explicitly confirms they understand it is a
             guess.
  CANDIDATE  a generic-format guess with no company-specific evidence behind
             it. Can never be sent through this feature. Not a UI choice —
             `send()` refuses it unconditionally.

The draft itself is generated from the brief's own claims and signals. No new
search runs, no new Gemini extraction of facts — only synthesis of what the
scout has already gathered and paid for.
"""

import json

from backend.config import settings
from backend.models.schemas import CompanyBrief, Person
from backend.services import mailer
from backend.services.db import connect
from backend.services.llm import LLMService

SCHEMA = """
CREATE TABLE IF NOT EXISTS outreach_drafts (
    id              BIGSERIAL PRIMARY KEY,
    share_key       TEXT NOT NULL,
    person_name     TEXT NOT NULL,
    person_email    TEXT NOT NULL,
    contact_tier    TEXT NOT NULL,
    subject         TEXT NOT NULL,
    body            TEXT NOT NULL,
    evidence        JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft',
    owner           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS outreach_drafts_share_key_idx
    ON outreach_drafts (share_key);
"""

_ready = False

DRAFT_PROMPT = """You write outreach emails for a business-school researcher
who has already completed a full research brief on a company and wants to
request an interview or conversation with a named person there.

You are given: the person's name and role, why they were identified as a good
contact, and a set of evidence claims about the company. Write ONLY from that
evidence. Do not invent facts, numbers, or events not present in what you are
given.

The email should:
- Be addressed to the person by name
- Reference one or two SPECIFIC facts from the evidence (not generic praise)
- State plainly why the sender is reaching out — a case study, an interview,
  a research conversation — inferred from the "why this person" context given
- Be short: 120-180 words
- Close with a specific, low-friction ask (a 20-minute call, answering a few
  questions by email) rather than an open-ended "let's connect"
- Never mention scores, confidence levels, or that this was AI-generated

Return ONLY valid JSON:
{"subject": "...", "body": "..."}

The body should NOT include a greeting salutation line like "Hi Name," or a
sign-off — those are added separately so the sender's own name is used.
"""


def ensure_schema() -> bool:
    global _ready
    if _ready:
        return True
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA)
            conn.commit()
        _ready = True
        return True
    except Exception as e:
        print(f"[outreach] Could not prepare schema: {e}", flush=True)
        return False


def _find_person(brief: CompanyBrief, person_name: str) -> Person | None:
    return next(
        (p for p in brief.evidence.people if p.name == person_name), None
    )


def _find_contact(brief: CompanyBrief, person_name: str) -> tuple[str, str] | None:
    """(email, tier) for this person, or None if there is no route to them.

    Checked here rather than trusted from the frontend: a request naming a
    person with no found or inferred address, or a former employee, must be
    refused before anything is drafted or sent — not just hidden in the UI.
    """
    person = _find_person(brief, person_name)
    if person is None or person.status == "former":
        return None

    contacts = brief.contacts
    if contacts is None:
        return None

    found = next((f for f in contacts.found if f.person == person_name), None)
    if found and found.kind == "personal":
        return found.email, "found"

    inferred = next((i for i in contacts.inferred if i.person == person_name), None)
    if inferred:
        # An inferred address built from a generic format rather than a
        # pattern observed at this company is a candidate, not a genuine
        # inference, whatever list it happens to sit in.
        tier = "candidate" if "common format" in (inferred.basis or "") else "inferred"
        return inferred.email, tier

    return None


def _evidence_for(brief: CompanyBrief, person_name: str) -> list[dict]:
    """The claims and signals worth citing, most relevant first.

    Kept small and specific rather than dumping the whole brief in: a
    generator that sees fifty claims writes a vaguer email than one that sees
    the five that actually matter, and a reader can tell.
    """
    person = _find_person(brief, person_name)
    items: list[dict] = []

    # Claims that name this person, or that are recent leadership/funding
    # claims likely to be why they were identified as relevant at all.
    for c in brief.evidence.claims:
        mentions_person = person and person.name.split()[-1] in c.statement
        if mentions_person or c.claim_type in ("leadership", "funding", "expansion"):
            items.append({"statement": c.statement, "source": c.source.url,
                          "type": c.claim_type})
        if len(items) >= 8:
            break

    for sig in brief.analysis.signals[:3]:
        items.append({"statement": sig.evidence, "source": None,
                      "type": "strategic_signal"})

    return items


def draft(brief: CompanyBrief, person_name: str, sender_name: str,
          share_key: str, owner: str | None = None) -> dict:
    """Generate a draft, or return why one cannot be made.

    Never raises for a refusal case (no contact, former employee) — those are
    expected outcomes the caller needs to show the user, not failures.
    """
    contact = _find_contact(brief, person_name)
    if contact is None:
        person = _find_person(brief, person_name)
        if person and person.status == "former":
            return {"ok": False, "reason":
                    "The evidence says this person has left. No outreach can "
                    "be drafted for someone who is no longer there."}
        return {"ok": False, "reason":
                "No email address — found or inferred — exists for this "
                "person, so there is no route to draft outreach through."}

    email, tier = contact
    if tier == "candidate":
        return {"ok": False, "reason":
                "Only a generic-format guess exists for this person, with no "
                "company-specific evidence behind it. Too weak to draft or "
                "send outreach from — verify their address another way first."}

    person = _find_person(brief, person_name)
    evidence = _evidence_for(brief, person_name)

    llm = LLMService(settings.llm_model_analyst)
    user_prompt = json.dumps({
        "person_name": person_name,
        "person_role": person.role if person else "",
        "company_name": brief.evidence.company.name,
        "evidence": evidence,
    })
    result = llm.extract_structured(DRAFT_PROMPT, user_prompt)

    body = f"Hi {person_name.split()[0]},\n\n{result['body']}\n\nBest,\n{sender_name}"

    draft_id = None
    if ensure_schema():
        try:
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO outreach_drafts
                            (share_key, person_name, person_email, contact_tier,
                             subject, body, evidence, owner)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id
                        """,
                        (share_key, person_name, email, tier,
                         result["subject"], body, json.dumps(evidence), owner),
                    )
                    draft_id = cur.fetchone()[0]
                conn.commit()
        except Exception as e:
            print(f"[outreach] Could not save draft: {e}", flush=True)

    return {
        "ok": True,
        "draft_id": draft_id,
        "person_name": person_name,
        "email": email,
        "tier": tier,
        "subject": result["subject"],
        "body": body,
        "evidence": evidence,
    }


def get_draft(draft_id: int) -> dict | None:
    if not ensure_schema():
        return None
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT person_name, person_email, contact_tier, subject, "
                    "body, status FROM outreach_drafts WHERE id = %s",
                    (draft_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            "person_name": row[0], "email": row[1], "tier": row[2],
            "subject": row[3], "body": row[4], "status": row[5],
        }
    except Exception as e:
        print(f"[outreach] Could not read draft: {e}", flush=True)
        return None


def send(draft_id: int, subject: str, body_text: str,
         confirmed_inferred: bool = False) -> dict:
    """Send a draft. The three-tier rule is enforced here, not trusted from
    the caller — a request that skips the confirmation step is refused
    regardless of what the frontend sent.
    """
    d = get_draft(draft_id)
    if d is None:
        return {"ok": False, "reason": "Draft not found."}
    if d["status"] == "sent":
        return {"ok": False, "reason": "This draft has already been sent."}

    if d["tier"] == "candidate":
        return {"ok": False, "reason":
                "Candidate addresses can never be sent through this feature."}
    if d["tier"] == "inferred" and not confirmed_inferred:
        return {"ok": False, "reason":
                "This is an inferred address, not a confirmed one. "
                "Confirmation is required before sending."}

    ok = mailer.send_raw(d["email"], subject, body_text)
    if not ok:
        return {"ok": False, "reason":
                "The email could not be sent. Nothing was marked as sent."}

    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE outreach_drafts SET status = 'sent', sent_at = now(), "
                    "subject = %s, body = %s WHERE id = %s",
                    (subject, body_text, draft_id),
                )
            conn.commit()
    except Exception as e:
        print(f"[outreach] Sent but could not record it: {e}", flush=True)

    return {"ok": True}
