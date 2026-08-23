"""Render saved eval runs into one readable markdown file.

Reading four briefs as raw JSON is not reading them. This exists so a category
can be reviewed the way a person actually reviews things — in order, in prose,
with the expectation printed next to the result.

The findings check here re-checks the brief in front of you rather than
replaying the verdict stored at run time. Those stored verdicts were produced
by a matcher that was wrong twice, and a stale ❌ next to evidence that is
plainly present in the brief is worse than no check at all.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.schemas import CompanyBrief
from backend.services.report import brief_to_markdown

RESULTS = Path(__file__).resolve().parent / "results"
OUT_DIR = Path(__file__).resolve().parent / "reports"

# Words that carry no signal when checking whether a finding was found.
STOP = {"or", "and", "the", "a", "of", "to", "in", "for", "with",
        "major", "history", "multiple"}


def _check(expectation: str, brief_text: str) -> tuple[str, str]:
    words = [w for w in re.split(r"[^a-z0-9]+", expectation.lower())
             if len(w) > 2 and w not in STOP]
    present = [w for w in words if w in brief_text]
    if not words:
        return "🟡", "nothing checkable"
    share = len(present) / len(words)
    mark = "✅" if share >= 0.5 else ("🟡" if present else "❌")
    return mark, ", ".join(present) if present else "nothing matching"


def build(ids: list[int], title: str, preamble: str, out_name: str) -> Path:
    out = [f"# {title}\n", preamble]

    loaded = []
    for i in ids:
        brief_path = next(RESULTS.glob(f"{i}_*_brief.json"))
        result_path = next(p for p in RESULTS.glob(f"{i}_*.json")
                           if not p.name.endswith("_brief.json"))
        brief = CompanyBrief.model_validate(json.loads(brief_path.read_text("utf-8")))
        result = json.loads(result_path.read_text("utf-8"))
        loaded.append((brief, result, brief_path.read_text("utf-8").lower()))

    out.append("## At a glance\n")
    out.append("| Company | Worth attention | Can you reach them | Verdict | I expected | Sources | Claims |")
    out.append("|---|---|---|---|---|---|---|")
    for brief, r, _ in loaded:
        out.append(
            f"| {r['name']} | {brief.interest_score} | {brief.reachability_score} "
            f"| {brief.verdict} | {r['expected_score_range']} "
            f"| {r['sources_count']} | {r['claims_count']} |"
        )
    out.append("\n---\n")

    for brief, r, raw in loaded:
        out.append(f"\n# {r['name']}\n")
        out.append(
            f"*Query used: `{r['query']}` · resolved to **{r['resolved_name']}** "
            f"({r['resolved_country']}) · took {r['duration_seconds']:.0f}s*\n"
        )
        out.append(
            f"**I expected {r['expected_score_range']}. It gave "
            f"{brief.interest_score} / {brief.reachability_score} — {brief.verdict}.**\n"
        )
        out.append("\n### Did it find what I said it should?\n")
        out.append("Checked by looking for each term in the brief's own text. Crude, but it "
                   "is checking the run in front of you rather than replaying an old verdict.\n")
        for expectation in r.get("expected_findings") or []:
            mark, detail = _check(expectation, raw)
            out.append(f"- {mark} **{expectation}** — found in brief: {detail}")
        out.append("\n### The brief\n")
        out.append(brief_to_markdown(brief))
        out.append("\n---\n")

    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / out_name
    path.write_text("\n".join(out), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(build(
        [11, 12, 13, 14],
        "Category C — the four briefs, in full",
        "See eval/reports/category_c_briefs.md for the reviewed copy.\n",
        "category_c_briefs.md",
    ))
