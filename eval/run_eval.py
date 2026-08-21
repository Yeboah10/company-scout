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
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pipeline.researcher import ResearchPipeline

EVAL_DIR = Path(__file__).resolve().parent
COMPANIES_FILE = EVAL_DIR / "companies.json"
RESULTS_DIR = EVAL_DIR / "results"
EVALUATIONS_FILE = EVAL_DIR / "evaluations.json"


def load_companies(ids=None, category=None):
    with open(COMPANIES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    companies = data["companies"]

    if ids:
        companies = [c for c in companies if c["id"] in ids]
    if category:
        companies = [c for c in companies if c["category"] == category.upper()]

    return companies


def run_company(company, pipeline):
    print(f"\n{'#'*70}")
    print(f"  [{company['id']}/{company['category']}] {company['name']} ({company['country']})")
    print(f"  Expected score range: {company['expected']['expected_score_range']}")
    print(f"{'#'*70}\n")

    try:
        brief = pipeline.research(company["query"])

        result = {
            "id": company["id"],
            "name": company["name"],
            "category": company["category"],
            "query": company["query"],
            "timestamp": datetime.utcnow().isoformat(),
            "duration_seconds": brief.duration_seconds,
            "resolved_name": brief.evidence.company.name,
            "resolved_country": brief.evidence.company.country,
            "claims_count": len(brief.evidence.claims),
            "people_count": len(brief.evidence.people),
            "sources_count": len(brief.evidence.sources),
            "signals_count": len(brief.analysis.signals),
            "story_angles_count": len(brief.analysis.story_angles),
            "scores": {
                "story": brief.analysis.scores.story_score,
                "case_study": brief.analysis.scores.case_study_score,
                "outreach": brief.analysis.scores.outreach_score,
                "research": brief.analysis.scores.research_score,
                "overall": brief.analysis.scores.overall_score,
                "recommendation": brief.analysis.scores.recommendation,
            } if brief.analysis.scores else None,
            "expected_score_range": company["expected"]["expected_score_range"],
            "expected_findings": company["expected"]["should_find"],
            "brief": brief.model_dump(mode="json"),
        }

        # Check which expected findings were found
        all_claims_text = " ".join(
            c.statement.lower() for c in brief.evidence.claims
        )
        all_summary = (brief.analysis.executive_summary or "").lower()
        combined_text = all_claims_text + " " + all_summary

        found = []
        missed = []
        for expected in company["expected"]["should_find"]:
            keywords = expected.lower().split()
            if all(kw in combined_text for kw in keywords):
                found.append(expected)
            else:
                missed.append(expected)

        result["findings_found"] = found
        result["findings_missed"] = missed
        result["findings_hit_rate"] = (
            len(found) / len(company["expected"]["should_find"])
            if company["expected"]["should_find"]
            else 1.0
        )

        # Check if score is in expected range
        if result["scores"]:
            score_range = company["expected"]["expected_score_range"]
            low, high = map(float, score_range.split("-"))
            actual = result["scores"]["overall"]
            result["score_in_range"] = low <= actual <= high
        else:
            result["score_in_range"] = False

        return result

    except Exception as e:
        return {
            "id": company["id"],
            "name": company["name"],
            "category": company["category"],
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
            "scores": None,
        }


def save_result(result):
    RESULTS_DIR.mkdir(exist_ok=True)
    filename = f"{result['id']:02d}_{result['name'].lower().replace(' ', '_')}.json"
    filepath = RESULTS_DIR / filename

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
        print(f"  Expected Range: {result['expected_score_range']}")
        print(f"  In Range:       {'YES' if result.get('score_in_range') else 'NO'}")

    print(f"  Claims: {result.get('claims_count', 0)} | People: {result.get('people_count', 0)} | Sources: {result.get('sources_count', 0)}")
    print(f"  Signals: {result.get('signals_count', 0)} | Story Angles: {result.get('story_angles_count', 0)}")
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
        overall = scores.get("overall", "N/A") if scores else "N/A"
        expected = r.get("expected_score_range", "?")
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
        print(f"\n  Score accuracy:    {scores_in_range}/{scored_count} ({scores_in_range/scored_count:.0%}) in expected range")
        print(f"  Avg findings rate: {total_hit_rate/scored_count:.0%}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Company Scout Evaluation Runner")
    parser.add_argument("--id", type=int, nargs="+", help="Run specific company IDs")
    parser.add_argument("--category", type=str, help="Run a category (A/B/C/D/E)")
    parser.add_argument("--report", action="store_true", help="Print evaluation report")
    args = parser.parse_args()

    if args.report:
        print_report()
        return

    companies = load_companies(ids=args.id, category=args.category)

    if not companies:
        print("No companies matched your filters.")
        return

    print(f"\nRunning evaluation on {len(companies)} companies...\n")

    pipeline = ResearchPipeline()

    for company in companies:
        result = run_company(company, pipeline)
        save_result(result)
        print_result_summary(result)

        # Brief pause between runs to respect rate limits
        if company != companies[-1]:
            time.sleep(2)

    print("\nAll evaluations complete. Run with --report to see summary.")


if __name__ == "__main__":
    main()
