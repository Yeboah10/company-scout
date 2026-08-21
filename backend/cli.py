import json
import sys

from backend.pipeline.researcher import ResearchPipeline


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m backend.cli <company name or URL>")
        print('Example: python -m backend.cli "Spiro"')
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    print(f"\n{'='*60}")
    print(f"  COMPANY SCOUT — Researching: {query}")
    print(f"{'='*60}\n")

    pipeline = ResearchPipeline()
    evidence, duration = pipeline.research(query)

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}\n")

    c = evidence.company
    print(f"  Company:   {c.name}")
    print(f"  Website:   {c.website or 'Not found'}")
    print(f"  Country:   {c.country or 'Not found'}")
    print(f"  Industry:  {c.industry or 'Not found'}")
    print(f"  Founded:   {c.founded_year or 'Not found'}")
    print(f"  About:     {c.description or 'Not found'}")

    print(f"\n  --- People ({len(evidence.people)}) ---")
    for p in evidence.people:
        print(f"  • {p.name} — {p.role} ({p.relationship}) [{p.confidence.value}]")

    print(f"\n  --- Claims ({len(evidence.claims)}) ---")
    for claim in evidence.claims:
        conf = claim.confidence.value.upper()
        print(f"\n  [{conf}] {claim.statement}")
        print(f"    Type:   {claim.claim_type}")
        print(f"    Source: {claim.source.title}")
        print(f"    URL:    {claim.source.url}")
        if claim.date_of_event:
            print(f"    Date:   {claim.date_of_event}")

    print(f"\n  --- Sources ({len(evidence.sources)}) ---")
    for s in evidence.sources:
        print(f"  • [{s.source_quality.value}] {s.title}")
        print(f"    {s.url}")

    print(f"\n  Completed in {duration:.1f}s")
    print(f"{'='*60}\n")

    output_path = f"scout_report_{c.name.lower().replace(' ', '_')}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(evidence.model_dump(mode="json"), f, indent=2, default=str)
    print(f"  Full report saved to: {output_path}\n")


if __name__ == "__main__":
    main()
