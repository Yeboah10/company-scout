"""Precision and discovery — the two things recall cannot tell you.

The evaluation has only ever asked one question: did Scout find the facts we
listed? That is recall, and it is necessary. It is also the least dangerous
failure mode. A brief that misses a funding round wastes your time. A brief
that *invents* one, with a citation next to it, sends you into a meeting with a
false premise, and nothing in this evaluation would have caught it.

So this adds two more:

  PRECISION   For each claim, does the source it cites actually support it?
              An unsupported claim is a false finding, and false findings are
              the thing that destroys trust in a research tool.

  DISCOVERY   What did Scout find that we never thought to ask for? A benchmark
              made of things we already knew can only ever confirm that the
              tool matches our own knowledge. The point of an agent is to
              return something we did not put in.

Deliberately runs over *saved* briefs rather than inside the scout. Two reasons:
it costs LLM calls, and the daily budget is the binding constraint on running
the evaluation at all; and a judgment that can be re-run without re-scouting is
a judgment you can improve without spending quota to test the improvement.

Usage:
    python eval/judge_quality.py                # every saved result
    python eval/judge_quality.py 11 12          # specific companies
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings
from backend.models.schemas import CompanyBrief
from backend.services.llm import LLMService, QuotaExhaustedError

RESULTS = Path(__file__).resolve().parent / "results"

PRECISION_PROMPT = """You are auditing a research tool for false claims.

You will be given claims, each with the snippet from the source it cites.

For each claim, decide whether THAT SNIPPET supports THAT CLAIM.

Return ONLY valid JSON:
{
  "results": [
    {
      "index": 0,
      "verdict": "supported|unsupported|overstated|unverifiable",
      "why": "one short sentence"
    }
  ]
}

Definitions — be strict, this exists to catch flattery:
- "supported": the snippet states the claim, or states something that plainly
  entails it.
- "overstated": the snippet is related but weaker than the claim. "plans to
  raise $50M" reported as "raised $50M". "one of the largest" reported as
  "the largest". This is the most common and most damaging failure.
- "unsupported": the snippet does not contain this information at all.
- "unverifiable": the snippet is too short or truncated to judge. Use this
  sparingly and never as a way to avoid deciding.

Judge only against the snippet given. Do not use your own knowledge of the
company — a claim that happens to be true but is not in the cited source is
still a sourcing failure, and that is exactly what this audit is for.
"""

DISCOVERY_PROMPT = """You are assessing whether a research tool found anything
its benchmark did not already anticipate.

You will be given a list of facts that were EXPECTED, and the claims the tool
actually produced.

Identify claims that are genuinely informative and are NOT covered by any
expected fact. Ignore trivia, boilerplate, and restatements of the expected
facts in different words.

Return ONLY valid JSON:
{
  "novel": [
    {"claim": "the claim, quoted", "why_useful": "one short sentence"}
  ]
}

A novel finding must be something a researcher would actually want to know:
a development, a risk, a relationship, a number, a contradiction. "The company
is based in Nairobi" is not novel even if nobody listed it.
"""


def audit_precision(brief: CompanyBrief, llm: LLMService) -> dict:
    """Check every claim against the snippet of the source it cites."""
    claims = [c for c in brief.evidence.claims if c.source and c.source.snippet]
    skipped = len(brief.evidence.claims) - len(claims)

    if not claims:
        return {"judged": 0, "skipped": skipped, "note": "no claims carried a source snippet"}

    payload = "\n\n".join(
        f"[{i}] CLAIM: {c.statement}\n    SOURCE SNIPPET: {(c.source.snippet or '')[:700]}"
        for i, c in enumerate(claims)
    )

    data = llm.extract_structured(PRECISION_PROMPT, payload[:14000])

    buckets: dict[str, list] = {}
    for row in data.get("results", []):
        i = row.get("index")
        verdict = row.get("verdict", "unverifiable")
        if not isinstance(i, int) or not 0 <= i < len(claims):
            continue
        buckets.setdefault(verdict, []).append(
            {"claim": claims[i].statement, "why": row.get("why", "")}
        )

    judged = sum(len(v) for v in buckets.values())
    supported = len(buckets.get("supported", []))
    # Anything unjudged counts against precision rather than disappearing from
    # the denominator — the same trap the findings matcher fell into twice.
    denominator = len(claims)

    return {
        "judged": judged,
        "skipped": skipped,
        "claims_total": len(claims),
        "supported": supported,
        "overstated": buckets.get("overstated", []),
        "unsupported": buckets.get("unsupported", []),
        "unverifiable": len(buckets.get("unverifiable", [])),
        "precision": round(supported / denominator, 3) if denominator else None,
    }


def audit_discovery(brief: CompanyBrief, expected: list[str], llm: LLMService) -> dict:
    """What the tool returned that the benchmark never asked for."""
    claims = brief.evidence.claims
    if not claims:
        return {"novel": [], "note": "no claims"}

    payload = (
        "EXPECTED FACTS:\n"
        + "\n".join(f"- {e}" for e in expected or ["(none listed)"])
        + "\n\nCLAIMS PRODUCED:\n"
        + "\n".join(f"- {c.statement}" for c in claims)
    )
    data = llm.extract_structured(DISCOVERY_PROMPT, payload[:14000])
    return {"novel": data.get("novel", [])}


def run(ids: list[int] | None = None) -> None:
    # The lite model on purpose: this is judgment about text already gathered,
    # and it must not compete with the pipeline for the stronger models' quota.
    llm = LLMService(settings.llm_model_extractor, fallbacks=settings.fallback_models)

    targets = sorted(
        p for p in RESULTS.glob("*_brief.json")
        if not ids or int(p.name.split("_")[0]) in ids
    )
    if not targets:
        print("No saved briefs to judge.")
        return

    for brief_path in targets:
        num = brief_path.name.split("_")[0]
        result_path = next(
            (p for p in RESULTS.glob(f"{num}_*.json")
             if not p.name.endswith("_brief.json")), None
        )
        if result_path is None:
            continue

        result = json.loads(result_path.read_text("utf-8"))
        brief = CompanyBrief.model_validate(json.loads(brief_path.read_text("utf-8")))

        print(f"\n{'='*70}\n  {result['name']}\n{'='*70}")

        try:
            precision = audit_precision(brief, llm)
            discovery = audit_discovery(brief, result.get("expected_findings") or [], llm)
        except QuotaExhaustedError:
            print("  Quota exhausted — stopping. Re-run tomorrow; saved briefs "
                  "do not expire and nothing already judged is lost.")
            return
        except Exception as e:
            print(f"  ! Judge failed: {type(e).__name__}: {e}")
            continue

        result["precision"] = precision
        result["discovery"] = discovery
        result_path.write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )

        p = precision.get("precision")
        print(f"  Precision: {p if p is not None else 'n/a'} "
              f"({precision.get('supported', 0)}/{precision.get('claims_total', 0)} "
              f"claims supported by their own source)")
        for row in precision.get("overstated", []):
            print(f"    OVERSTATED: {row['claim'][:90]}")
            print(f"                {row['why'][:90]}")
        for row in precision.get("unsupported", []):
            print(f"    UNSUPPORTED: {row['claim'][:90]}")
            print(f"                 {row['why'][:90]}")

        novel = discovery.get("novel", [])
        print(f"  Novel findings: {len(novel)}")
        for row in novel[:5]:
            print(f"    + {str(row.get('claim',''))[:95]}")


if __name__ == "__main__":
    run([int(a) for a in sys.argv[1:]] or None)
