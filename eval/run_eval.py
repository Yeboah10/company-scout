"""
Company Scout Evaluation Runner

Runs companies from the evaluation set through the pipeline,
saves results, and prompts for human evaluation.

Usage:
    python eval/run_eval.py                  # Run all companies
    python eval/run_eval.py --id 1 3 5       # Run specific companies by ID
    python eval/run_eval.py --category A     # Run a category
    python eval/run_eval.py --report         # Print summary of past evaluations
"""

import argparse
import json
import re
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pipeline.researcher import ResearchPipeline
from backend.config import settings
from backend.services.llm import LLMService, QuotaExhaustedError

EVAL_DIR = Path(__file__).resolve().parent
COMPANIES_FILE = EVAL_DIR / "companies.json"
RESULTS_DIR = EVAL_DIR / "results"
EVALUATIONS_FILE = EVAL_DIR / "evaluations.json"

# 1 resolver + ~3 extractor batches + 1 analyst + 1 scorer.
CALLS_PER_SCOUT = 6
DAILY_CALL_BUDGET = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_companies(ids=None, category=None):
    with open(COMPANIES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    companies = data["companies"]

    if ids:
        companies = [c for c in companies if c["id"] in ids]
    if category:
        companies = [c for c in companies if c["category"] == category.upper()]

    return companies


_STOPWORDS = {
    "or", "and", "the", "of", "a", "an", "in", "to", "for", "with", "on",
    "attempts", "major", "issues", "problems",
}


JUDGE_PROMPT = """You are checking whether a research system found specific facts.

You will be given evidence a system gathered about a company, and a list of
facts it was expected to find.

For each expected fact, decide whether the evidence contains it — judging by
meaning, not wording. "Cut over 300 jobs in a restructuring" DOES establish
"layoffs". "Area Yield Index Insurance" does NOT establish "satellite data",
because they are different things.

Return ONLY valid JSON:
{"results": [{"expected": "<the fact verbatim>", "found": true, "why": "<the evidence, or what is absent>"}]}

Be strict. A fact is found only if the evidence actually supports it, not if
the topic is merely nearby."""


def judge_findings(expected_items, text, llm):
    """Ask a model whether each expected fact is genuinely present.

    Keyword matching cannot do this. Requiring every word was far too strict —
    Twiga's "cut over 300 jobs" scored "layoffs" as MISSED. Accepting any word
    was far too loose — "parametric insurance" counted as found because the
    word "insurance" appeared somewhere. Both produced a precise-looking
    percentage that measured the matcher rather than the pipeline.

    Costs one call per company, on the lite model so it does not compete with
    the pipeline's own budget. Falls back to keyword matching when quota is
    gone, and says which method was used.
    """
    if not expected_items:
        return [], [], "none expected"

    evidence = text[:12000]  # a long brief would otherwise dominate the prompt
    prompt = (
        f"EVIDENCE GATHERED:\n{evidence}\n\n"
        f"EXPECTED FACTS:\n"
        + "\n".join(f"- {e}" for e in expected_items)
    )

    try:
        data = llm.extract_structured(JUDGE_PROMPT, prompt)
        found, missed = [], []
        for row in data.get("results", []):
            item = row.get("expected", "")
            # Match back to the original wording; the model may reformat.
            original = next(
                (e for e in expected_items if e.lower() in item.lower()
                 or item.lower() in e.lower()),
                item,
            )
            (found if row.get("found") else missed).append(original)

        # Anything the model failed to rule on counts as missed rather than
        # silently vanishing from the denominator.
        judged = set(found) | set(missed)
        missed += [e for e in expected_items if e not in judged]
        return found, missed, "llm"
    except Exception as e:
        print(f"  ! Finding judge unavailable ({type(e).__name__}); "
              f"falling back to keyword match", flush=True)
        found, missed = _match_findings(expected_items, text)
        return found, missed, "keyword (approximate)"


def _match_findings(expected_items, text):
    """Approximate check that an expected fact turned up in the evidence.

    The original required every word of the expected phrase to appear
    literally, which measured almost nothing: Twiga's evidence said "cut over
    300 jobs as part of a major restructuring", and "layoffs" was scored as
    MISSED. That produced a hit rate that looked like an extraction weakness
    and was mostly a matching artefact.

    Now a phrase counts as found when any of its distinctive words appears.
    Still crude -- it cannot see that "job cuts" means "layoffs" -- so the
    report labels the number approximate and prints both lists for a human to
    judge. A precise-looking percentage from a crude matcher is worse than an
    admittedly rough one.
    """
    found, missed = [], []
    for expected in expected_items:
        words = [
            w for w in re.findall(r"[a-z0-9]+", expected.lower())
            if len(w) > 3 and w not in _STOPWORDS
        ]
        if not words:
            words = [expected.lower()]
        if any(w in text for w in words):
            found.append(expected)
        else:
            missed.append(expected)
    return found, missed


def run_company(company, pipeline, judge_llm):
    print(f"\n{'#'*70}")
    print(f"  [{company['id']}/{company['category']}] {company['name']} ({company['country']})")
    print(f"  Expected: attention {company['expected']['expected_interest_range']}"
          f" | reach {company['expected']['expected_reachability_range']}")
    print(f"{'#'*70}\n")

    try:
        brief = pipeline.research(company["query"])

        result = {
            "id": company["id"],
            "name": company["name"],
            "category": company["category"],
            "query": company["query"],
            "timestamp": _now(),
            "duration_seconds": brief.duration_seconds,
            "resolved_name": brief.evidence.company.name,
            "resolved_country": brief.evidence.company.country,
            "claims_count": len(brief.evidence.claims),
            "people_count": len(brief.evidence.people),
            "sources_count": len(brief.evidence.sources),
            "signals_count": len(brief.analysis.signals),
            "story_angles_count": len(brief.analysis.story_angles),
            # Which of the nine research questions came back empty. A run that
            # scored well on six areas and learned nothing about the other
            # three is a different result from one that covered all nine, and
            # the score alone cannot tell them apart.
            "coverage": {
                "covered": brief.evidence.coverage.covered_count,
                "total": brief.evidence.coverage.total_areas,
                "gaps": brief.evidence.coverage.gaps,
            } if brief.evidence.coverage else None,
            "scores": {
                "story": brief.analysis.scores.story_score,
                "case_study": brief.analysis.scores.case_study_score,
                "outreach": brief.analysis.scores.outreach_score,
                "research": brief.analysis.scores.research_score,
                "overall": brief.analysis.scores.overall_score,
                "recommendation": brief.analysis.scores.recommendation,
            } if brief.analysis.scores else None,
            "expected_interest_range": company["expected"]["expected_interest_range"],
            "expected_reachability_range": company["expected"]["expected_reachability_range"],
            "expectation_basis": company["expected"].get("basis"),
            "interest_score": brief.interest_score,
            "reachability_score": brief.reachability_score,
            "verdict": brief.verdict,
            "expected_findings": company["expected"]["should_find"],
            "brief": brief.model_dump(mode="json"),
        }

        # Check which expected findings were found
        all_claims_text = " ".join(
            c.statement.lower() for c in brief.evidence.claims
        )
        all_summary = (brief.analysis.executive_summary or "").lower()
        combined_text = all_claims_text + " " + all_summary

        found, missed, method = judge_findings(
            company["expected"]["should_find"], combined_text, judge_llm
        )

        result["findings_found"] = found
        result["findings_missed"] = missed
        result["findings_method"] = method
        result["findings_hit_rate"] = (
            len(found) / len(company["expected"]["should_find"])
            if company["expected"]["should_find"]
            else 1.0
        )

        # Both scores are checked, because they answer different questions and
        # a company can legitimately be far apart on them. Judging a collapsed
        # company against one blended number is what made category C look like
        # a failure when the tool was right.
        def _in(range_str, value):
            low, high = map(float, range_str.split("-"))
            return low <= value <= high

        result["interest_in_range"] = _in(
            company["expected"]["expected_interest_range"], brief.interest_score
        )
        result["reach_in_range"] = _in(
            company["expected"]["expected_reachability_range"],
            brief.reachability_score,
        )
        result["score_in_range"] = (
            result["interest_in_range"] and result["reach_in_range"]
        )

        return result

    except QuotaExhaustedError:
        # Every remaining company would fail identically. Let the caller stop
        # the run rather than recording a row of meaningless failures.
        raise
    except Exception as e:
        return {
            "id": company["id"],
            "name": company["name"],
            "category": company["category"],
            "timestamp": _now(),
            "error": str(e),
            "scores": None,
        }


def _result_path(company_id: int, name: str) -> Path:
    return RESULTS_DIR / f"{company_id:02d}_{name.lower().replace(' ', '_')}.json"


def _existing_result(company_id: int, name: str) -> dict | None:
    path = _result_path(company_id, name)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def is_complete(company) -> bool:
    """A company counts as done only if it produced actual scores.

    The evaluation spans several days of free-tier quota, so runs get
    interrupted; anything that errored should be retried, not skipped.
    """
    existing = _existing_result(company["id"], company["name"])
    return bool(existing and existing.get("scores"))


def save_result(result):
    RESULTS_DIR.mkdir(exist_ok=True)
    filepath = _result_path(result["id"], result["name"])

    # A failed rerun must never destroy a good result. Losing a successful
    # evaluation costs a day of quota to recreate.
    if "error" in result:
        previous = _existing_result(result["id"], result["name"])
        if previous and previous.get("scores"):
            print(
                f"  ! Keeping the previous successful result for {result['name']} "
                f"rather than overwriting it with this failure."
            )
            return filepath

    # Save full result (without the massive brief for the summary file)
    brief_data = result.pop("brief", None)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    # Save full brief separately
    if brief_data:
        brief_path = RESULTS_DIR / f"{result['id']:02d}_{result['name'].lower().replace(' ', '_')}_brief.json"
        with open(brief_path, "w", encoding="utf-8") as f:
            json.dump(brief_data, f, indent=2, default=str)

    return filepath


def print_result_summary(result):
    print(f"\n{'='*70}")
    print(f"  EVAL RESULT: {result['name']}")
    print(f"{'='*70}")

    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return

    scores = result.get("scores", {})
    if scores:
        print(f"  Overall Score:  {scores['overall']}/10 ({scores['recommendation']})")
    if result.get("interest_score") is not None:
        print(f"  Attention:      {result['interest_score']}/10 "
              f"(expected {result['expected_interest_range']}) "
              f"{'OK' if result.get('interest_in_range') else 'OUT'}")
        print(f"  Reach:          {result['reachability_score']}/10 "
              f"(expected {result['expected_reachability_range']}) "
              f"{'OK' if result.get('reach_in_range') else 'OUT'}")
        print(f"  Verdict:        {result.get('verdict')}")

    print(f"  Claims: {result.get('claims_count', 0)} | People: {result.get('people_count', 0)} | Sources: {result.get('sources_count', 0)}")
    print(f"  Signals: {result.get('signals_count', 0)} | Story Angles: {result.get('story_angles_count', 0)}")

    cov = result.get("coverage")
    if cov:
        print(f"  Coverage: {cov['covered']}/{cov['total']}"
              + (f" | nothing on: {', '.join(cov['gaps'])}" if cov["gaps"] else ""))
    print(f"  Duration: {result.get('duration_seconds', 0):.1f}s")

    found = result.get("findings_found", [])
    missed = result.get("findings_missed", [])
    hit_rate = result.get("findings_hit_rate", 0)
    print(f"\n  Expected findings hit rate: {hit_rate:.0%}")
    if found:
        print(f"  Found:  {', '.join(found)}")
    if missed:
        print(f"  MISSED: {', '.join(missed)}")
    print(f"{'='*70}\n")


def print_report():
    if not RESULTS_DIR.exists():
        print("No results yet. Run some evaluations first.")
        return

    results = []
    for f in sorted(RESULTS_DIR.glob("*.json")):
        if f.name.endswith("_brief.json"):
            continue
        with open(f, "r", encoding="utf-8") as fh:
            results.append(json.load(fh))

    if not results:
        print("No results found.")
        return

    print(f"\n{'='*70}")
    print(f"  COMPANY SCOUT EVALUATION REPORT")
    print(f"  {len(results)} companies evaluated")
    print(f"{'='*70}\n")

    print(f"  {'ID':<4} {'Name':<20} {'Cat':<4} {'Score':<8} {'Expected':<10} {'Match':<6} {'Findings':<10} {'Time':<8}")
    print(f"  {'-'*4} {'-'*20} {'-'*4} {'-'*8} {'-'*10} {'-'*6} {'-'*10} {'-'*8}")

    scores_in_range = 0
    total_hit_rate = 0
    scored_count = 0

    for r in results:
        if "error" in r:
            print(f"  {r['id']:<4} {r['name']:<20} {r['category']:<4} {'ERROR':<8}")
            continue

        scores = r.get("scores", {})
        overall = (f"{r.get('interest_score')}/{r.get('reachability_score')}"
                   if r.get("interest_score") is not None else "N/A")
        expected = (f"{r.get('expected_interest_range','?')} "
                    f"{r.get('expected_reachability_range','?')}")
        in_range = "YES" if r.get("score_in_range") else "NO"
        hit_rate = r.get("findings_hit_rate", 0)
        duration = r.get("duration_seconds", 0)

        print(f"  {r['id']:<4} {r['name']:<20} {r['category']:<4} {overall:<8} {expected:<10} {in_range:<6} {hit_rate:<10.0%} {duration:<8.0f}s")

        if scores:
            scored_count += 1
            if r.get("score_in_range"):
                scores_in_range += 1
            total_hit_rate += hit_rate

    if scored_count:
        # Blind and revised expectations are not equal evidence, and a single
        # headline percentage quietly launders the weaker ones into the
        # stronger number. Reported apart so the scoreboard cannot flatter
        # itself.
        blind = [r for r in results
                 if r.get("expectation_basis") == "written before the run"]
        blind_ok = sum(1 for r in blind if r.get("score_in_range"))
        posthoc = [r for r in results
                   if r.get("expectation_basis") == "revised after seeing the result"]
        posthoc_ok = sum(1 for r in posthoc if r.get("score_in_range"))

        print(f"\n  Score accuracy:    {scores_in_range}/{scored_count} "
              f"({scores_in_range/scored_count:.0%}) in expected range")
        if blind:
            print(f"    blind:           {blind_ok}/{len(blind)} "
                  f"({blind_ok/len(blind):.0%}) - the number that counts")
        if posthoc:
            print(f"    revised after:   {posthoc_ok}/{len(posthoc)} "
                  f"- weaker, these expectations were rewritten having seen the runs")
        print(f"  Avg findings rate: {total_hit_rate/scored_count:.0%} (recall)")

        judged = [r for r in results
                  if (r.get("precision") or {}).get("precision") is not None]
        if judged:
            avg_p = sum(r["precision"]["precision"] for r in judged) / len(judged)
            bad = sum(len(r["precision"].get("overstated", []))
                      + len(r["precision"].get("unsupported", [])) for r in judged)
            print(f"  Avg precision:     {avg_p:.0%} over {len(judged)} judged "
                  f"({bad} claim(s) not supported by their own source)")
        else:
            print("  Avg precision:     not measured - run eval/judge_quality.py")

        novel = sum(len((r.get("discovery") or {}).get("novel", [])) for r in results)
        if novel:
            print(f"  Novel findings:    {novel} across all companies")
    print()


def main():
    parser = argparse.ArgumentParser(description="Company Scout Evaluation Runner")
    parser.add_argument("--id", type=int, nargs="+", help="Run specific company IDs")
    parser.add_argument("--category", type=str, help="Run a category (A/B/C/D/E)")
    parser.add_argument("--report", action="store_true", help="Print evaluation report")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run companies that already have a successful result",
    )
    args = parser.parse_args()

    if args.report:
        print_report()
        return

    companies = load_companies(ids=args.id, category=args.category)

    if not companies:
        print("No companies matched your filters.")
        return

    if not args.force:
        already_done = [c for c in companies if is_complete(c)]
        companies = [c for c in companies if not is_complete(c)]
        if already_done:
            names = ", ".join(c["name"] for c in already_done)
            print(f"\nSkipping {len(already_done)} already evaluated: {names}")
            print("Use --force to run them again.")

    if not companies:
        print("\nEverything requested has already been evaluated.")
        print("Run with --report to see the summary.")
        return

    # A scout costs ~6 Gemini calls against a 20/day free-tier allowance, so
    # say up front how much of the day's budget this run wants.
    estimated_calls = len(companies) * CALLS_PER_SCOUT
    print(f"\nRunning evaluation on {len(companies)} companies.")
    print(
        f"Estimated cost: ~{estimated_calls} Gemini calls "
        f"(~{estimated_calls / DAILY_CALL_BUDGET:.1f} days of free-tier quota).\n"
    )

    pipeline = ResearchPipeline()
    # A separate lite model so judging does not eat the pipeline's budget.
    judge_llm = LLMService(settings.llm_model_extractor)
    completed = 0

    for index, company in enumerate(companies):
        try:
            result = run_company(company, pipeline, judge_llm)
        except QuotaExhaustedError as e:
            print(f"\n{'='*70}")
            # Plain ASCII: the Windows console encoding mangles an em-dash.
            print("  STOPPED - daily Gemini quota exhausted")
            print(f"{'='*70}")
            print(f"  {e}")
            print(f"  Completed this run: {completed} of {len(companies)}")
            remaining = [c["name"] for c in companies[index:]]
            print(f"  Still to do: {', '.join(remaining)}")
            print("  Rerun the same command tomorrow; finished companies are skipped.")
            print(f"{'='*70}\n")
            break

        save_result(result)
        print_result_summary(result)
        completed += 1

        # Brief pause between runs to respect rate limits
        if company is not companies[-1]:
            time.sleep(2)
    else:
        print("\nAll evaluations complete. Run with --report to see summary.")


if __name__ == "__main__":
    main()
