"""Render a CompanyBrief as readable Markdown.

The JSON download is fine for machines but useless for the actual job of
sending a brief to a colleague or pasting it into notes, which is what this
is for.
"""

from backend.models.schemas import CompanyBrief


def _line(label: str, value: str | None) -> str:
    return f"**{label}:** {value}\n\n" if value else ""


def brief_to_markdown(brief: CompanyBrief) -> str:
    evidence = brief.evidence
    analysis = brief.analysis
    company = evidence.company
    scores = analysis.scores

    out: list[str] = []

    out.append(f"# {company.name}\n\n")

    if scores:
        out.append(
            f"## {scores.overall_score}/10 — {scores.recommendation}\n\n"
        )

    meta = [
        v
        for v in (
            company.country,
            company.industry,
            company.website,
            f"Founded {company.founded_year}" if company.founded_year else None,
        )
        if v
    ]
    if meta:
        out.append(" · ".join(meta) + "\n\n")

    if brief.from_cache and brief.cached_at:
        out.append(f"*Saved report, researched {brief.cached_at[:10]}.*\n\n")

    out.append("---\n\n")

    if analysis.executive_summary:
        out.append("## Executive Summary\n\n")
        out.append(f"{analysis.executive_summary}\n\n")

    if scores:
        out.append("## Opportunity Scores\n\n")
        out.append("| Dimension | Score | Reasoning |\n")
        out.append("| --- | --- | --- |\n")
        for label, score, reason in (
            ("Story", scores.story_score, scores.story_reasoning),
            ("Case Study", scores.case_study_score, scores.case_study_reasoning),
            ("Outreach", scores.outreach_score, scores.outreach_reasoning),
            ("Research", scores.research_score, scores.research_reasoning),
        ):
            # Pipes inside a cell would break the table.
            clean = (reason or "").replace("|", "\\|").replace("\n", " ")
            out.append(f"| {label} | {score}/10 | {clean} |\n")
        out.append("\n")

        # Show the adjustment rather than just its result: a score that moved
        # for unexplained reasons is worth less than one you can argue with.
        if scores.recency_factor != 1.0:
            direction = "raised" if scores.recency_factor > 1 else "reduced"
            note = (scores.recency_note or "").replace("\n", " ")
            out.append(
                f"Average of the four: **{scores.base_score}/10**. "
                f"Recency {direction} this to **{scores.overall_score}/10** "
                f"(x{scores.recency_factor:g}). {note}\n\n"
            )

    if analysis.top_priorities:
        out.append("## Top Priorities\n\n")
        for i, p in enumerate(analysis.top_priorities, 1):
            out.append(f"{i}. **{p.topic}** — {p.why}\n")
        out.append("\n")

    if analysis.signals:
        out.append("## Strategic Signals\n\n")
        for i, s in enumerate(analysis.signals, 1):
            out.append(f"### {i}. {s.title} `{s.confidence.value}`\n\n")
            out.append(_line("Evidence", s.evidence))
            out.append(_line("Interpretation", s.interpretation))
            out.append(_line("Open question", s.question))

    if analysis.story_angles:
        out.append("## Story Angles\n\n")
        for i, a in enumerate(analysis.story_angles, 1):
            out.append(f"### {i}. {a.angle}\n\n")
            out.append(_line("Why interesting", a.why_interesting))
            out.append(_line("Supporting evidence", a.supporting_evidence))
            out.append(_line("Information gap", a.information_gap))

    if analysis.case_study:
        cs = analysis.case_study
        out.append(f"## Case Study Potential — {cs.score}/10\n\n")
        out.append(f"### {cs.potential_title}\n\n")
        out.append(_line("Central decision", cs.central_decision))
        out.append(_line("Decision maker", cs.decision_maker))
        out.append(_line("Strategic tension", cs.strategic_tension))
        out.append(_line("Evidence available", cs.evidence_available))
        out.append(_line("Missing information", cs.missing_information))

    if analysis.outreach:
        o = analysis.outreach
        out.append("## Outreach Opportunity\n\n")
        out.append(_line("Recommended contact", f"{o.recommended_contact} — {o.role}"))
        out.append(_line("Why", o.why))
        out.append(_line("Trigger", o.trigger))
        out.append(_line("Thesis", o.outreach_thesis))
        out.append(_line("What you could offer", o.what_you_could_offer))

    if evidence.people:
        out.append("## Key People\n\n")
        for p in evidence.people:
            out.append(
                f"- **{p.name}** — {p.role} ({p.relationship}) `{p.confidence.value}`\n"
            )
        out.append("\n")

    if evidence.claims:
        out.append("## Evidence\n\n")
        for c in evidence.claims:
            dated = f" ({c.date_of_event})" if c.date_of_event else ""
            out.append(f"- `{c.confidence.value}` {c.statement}{dated}\n")
            if c.source and c.source.url:
                out.append(f"  - Source: [{c.source.title}]({c.source.url})\n")
        out.append("\n")

    if evidence.sources:
        tiers = {"tier_1": 0, "tier_2": 0, "tier_3": 0}
        for s in evidence.sources:
            key = s.source_quality.value
            if key in tiers:
                tiers[key] += 1

        out.append("## Source Ledger\n\n")
        out.append(
            f"{len(evidence.sources)} sources — "
            f"Tier 1: {tiers['tier_1']} · "
            f"Tier 2: {tiers['tier_2']} · "
            f"Tier 3: {tiers['tier_3']}\n\n"
        )
        for s in evidence.sources:
            label = s.source_quality.value.replace("_", " ").upper()
            out.append(f"- [{label}] [{s.title}]({s.url})\n")
        out.append("\n")

    out.append("---\n\n")
    out.append("*Generated by Company Scout.*\n")

    return "".join(out)
