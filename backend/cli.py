import json
import sys

from backend.pipeline.researcher import ResearchPipeline


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m backend.cli <company name or URL>")
        print('Example: python -m backend.cli "Spiro"')
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    print(f"\n{'='*70}")
    print(f"  COMPANY SCOUT -- Researching: {query}")
    print(f"{'='*70}\n")

    pipeline = ResearchPipeline()
    brief = pipeline.research(query)

    evidence = brief.evidence
    analysis = brief.analysis
    scores = analysis.scores
    c = evidence.company

    print(f"\n{'='*70}")
    print(f"  COMPANY INTELLIGENCE BRIEF")
    print(f"{'='*70}")

    # Header
    rec = scores.recommendation if scores else "N/A"
    overall = scores.overall_score if scores else 0
    print(f"\n  {c.name.upper()}")
    print(f"  {rec} -- {overall}/10")
    print(f"  {c.country or 'Unknown'} | {c.industry or 'Unknown'} | {c.website or 'No website'}")
    if c.founded_year:
        print(f"  Founded: {c.founded_year}")

    # Executive Summary
    print(f"\n  {'- '*35}")
    print(f"  EXECUTIVE SUMMARY")
    print(f"  {'- '*35}")
    _print_wrapped(analysis.executive_summary, indent=4)

    # Company Snapshot
    print(f"\n  {'- '*35}")
    print(f"  PEOPLE ({len(evidence.people)})")
    print(f"  {'- '*35}")
    for p in evidence.people:
        print(f"    {p.name} -- {p.role} ({p.relationship}) [{p.confidence.value}]")

    # Recent Developments (top claims)
    print(f"\n  {'- '*35}")
    print(f"  KEY CLAIMS ({len(evidence.claims)})")
    print(f"  {'- '*35}")
    for claim in evidence.claims[:8]:
        conf = claim.confidence.value.upper()
        print(f"\n    [{conf}] {claim.statement}")
        print(f"    Source: {claim.source.title}")
        if claim.date_of_event:
            print(f"    Date: {claim.date_of_event}")

    # Strategic Signals
    print(f"\n  {'- '*35}")
    print(f"  STRATEGIC SIGNALS ({len(analysis.signals)})")
    print(f"  {'- '*35}")
    for i, s in enumerate(analysis.signals, 1):
        print(f"\n    Signal {i}: {s.title} [{s.confidence.value}]")
        print(f"    Evidence: {s.evidence}")
        print(f"    Interpretation: {s.interpretation}")
        print(f"    Question: {s.question}")

    # Story Angles
    print(f"\n  {'- '*35}")
    print(f"  STORY ANGLES ({len(analysis.story_angles)})")
    print(f"  {'- '*35}")
    for i, a in enumerate(analysis.story_angles, 1):
        print(f"\n    {i}. {a.angle}")
        print(f"       Why: {a.why_interesting}")
        print(f"       Gap: {a.information_gap}")

    # Case Study
    if analysis.case_study:
        cs = analysis.case_study
        print(f"\n  {'- '*35}")
        print(f"  CASE STUDY OPPORTUNITY ({cs.score}/10)")
        print(f"  {'- '*35}")
        print(f"    Title: {cs.potential_title}")
        print(f"    Central decision: {cs.central_decision}")
        print(f"    Decision maker: {cs.decision_maker}")
        print(f"    Tension: {cs.strategic_tension}")
        print(f"    Missing: {cs.missing_information}")

    # Outreach
    if analysis.outreach:
        o = analysis.outreach
        print(f"\n  {'- '*35}")
        print(f"  OUTREACH OPPORTUNITY")
        print(f"  {'- '*35}")
        print(f"    Contact: {o.recommended_contact} ({o.role})")
        print(f"    Why: {o.why}")
        print(f"    Trigger: {o.trigger}")
        print(f"    Thesis: {o.outreach_thesis}")
        print(f"    Offer: {o.what_you_could_offer}")

    # Scores
    if scores:
        print(f"\n  {'- '*35}")
        print(f"  OPPORTUNITY SCORES")
        print(f"  {'- '*35}")
        print(f"    Story:      {scores.story_score}/10 -- {scores.story_reasoning}")
        print(f"    Case Study: {scores.case_study_score}/10 -- {scores.case_study_reasoning}")
        print(f"    Outreach:   {scores.outreach_score}/10 -- {scores.outreach_reasoning}")
        print(f"    Research:   {scores.research_score}/10 -- {scores.research_reasoning}")
        print(f"\n    OVERALL:    {scores.overall_score}/10 -- {scores.recommendation}")

    # Top Priorities
    if analysis.top_priorities:
        print(f"\n  {'- '*35}")
        print(f"  TOP PRIORITIES")
        print(f"  {'- '*35}")
        print(f"  If you only investigate three things, investigate these:")
        for i, p in enumerate(analysis.top_priorities, 1):
            print(f"    {i}. {p.topic}")
            print(f"       Why: {p.why}")

    # Source Ledger
    tier_1 = [s for s in evidence.sources if s.source_quality.value == "tier_1"]
    tier_2 = [s for s in evidence.sources if s.source_quality.value == "tier_2"]
    tier_3 = [s for s in evidence.sources if s.source_quality.value == "tier_3"]
    print(f"\n  {'- '*35}")
    print(f"  SOURCES ({len(evidence.sources)}: {len(tier_1)} tier-1, {len(tier_2)} tier-2, {len(tier_3)} tier-3)")
    print(f"  {'- '*35}")
    for s in evidence.sources:
        print(f"    [{s.source_quality.value}] {s.title}")
        print(f"           {s.url}")

    print(f"\n  Completed in {brief.duration_seconds:.1f}s")
    print(f"{'='*70}\n")

    # Save JSON report
    output_path = f"scout_report_{c.name.lower().replace(' ', '_')}.json"
    report_data = brief.model_dump(mode="json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, default=str)
    print(f"  Full report saved to: {output_path}\n")


def _print_wrapped(text: str, indent: int = 4, width: int = 66):
    prefix = " " * indent
    words = text.split()
    line = prefix
    for word in words:
        if len(line) + len(word) + 1 > width + indent:
            print(line)
            line = prefix + word
        else:
            line = line + " " + word if line.strip() else prefix + word
    if line.strip():
        print(line)


if __name__ == "__main__":
    main()
