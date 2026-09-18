"""Structured PDF export of a brief.

Generates a clean, one-page-ish HTML summary designed for browser print-to-PDF.
No external PDF library needed — the browser's own print engine does the rendering,
which means the output matches what the user already sees.

The structured export strips the interactive elements (tabs, buttons, forms) and
produces a linear, printable document with: company header, scores, executive
summary, top signals, key people, and source count. Everything a meeting handout
needs, nothing it doesn't.
"""

from backend.models.schemas import CompanyBrief


def brief_to_print_html(brief: CompanyBrief, share_key: str = "") -> str:
    company = brief.evidence.company
    scores = brief.scores
    analysis = brief.analysis

    def esc(val):
        if not val:
            return ""
        return str(val).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def score_color(val):
        if val is None:
            return "#888"
        if val >= 8:
            return "#3f6b4d"
        if val >= 6:
            return "#2563eb"
        if val >= 4:
            return "#f0a000"
        return "#d84a28"

    def recommendation(score):
        if score is None:
            return "N/A"
        if score >= 8:
            return "HIGH PRIORITY"
        if score >= 6:
            return "WORTH A LOOK"
        if score >= 4:
            return "LOW PRIORITY"
        return "SKIP"

    signals_html = ""
    if analysis and analysis.signals:
        top = analysis.signals[:5]
        rows = "".join(
            f'<tr><td style="padding:6px 8px;border-bottom:1px solid #e5e2de;font-size:13px">'
            f'{esc(s.signal or s.headline or "")}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #e5e2de;font-size:13px;'
            f'color:{score_color(s.confidence * 10 if hasattr(s, "confidence") and s.confidence else 5)}">'
            f'{"%.0f" % (s.confidence * 100) if hasattr(s, "confidence") and s.confidence else "—"}%</td></tr>'
            for s in top
        )
        signals_html = f"""
        <h3 style="font-size:11px;font-weight:700;letter-spacing:0.12em;
                   text-transform:uppercase;color:#605d5d;margin:24px 0 8px">
            Top signals</h3>
        <table style="width:100%;border-collapse:collapse">{rows}</table>
        """

    people_html = ""
    people = brief.evidence.people[:6] if brief.evidence.people else []
    if people:
        rows = "".join(
            f'<tr><td style="padding:4px 8px;border-bottom:1px solid #e5e2de;font-size:13px">'
            f'{esc(p.name)}</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #e5e2de;font-size:13px;color:#605d5d">'
            f'{esc(p.role or "")}</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #e5e2de;font-size:13px;color:#605d5d">'
            f'{esc(p.status or "")}</td></tr>'
            for p in people
        )
        people_html = f"""
        <h3 style="font-size:11px;font-weight:700;letter-spacing:0.12em;
                   text-transform:uppercase;color:#605d5d;margin:24px 0 8px">
            Key people</h3>
        <table style="width:100%;border-collapse:collapse">{rows}</table>
        """

    overall = scores.overall_score if scores else None
    rec = recommendation(overall)
    rec_color = score_color(overall)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{esc(company.name)} — Company Scout</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;700;800&display=swap');
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: Archivo, system-ui, sans-serif; color: #201e1d; max-width: 700px;
        margin: 0 auto; padding: 40px 24px; line-height: 1.5; }}
@media print {{ body {{ padding: 20px; }} }}
</style>
</head>
<body>
<div style="display:flex;align-items:center;gap:6px;margin-bottom:20px">
    <span style="width:11px;height:11px;display:inline-block;background:#d84a28"></span>
    <span style="width:11px;height:11px;display:inline-block;background:#f0a000"></span>
    <span style="font-size:8.5px;font-weight:600;letter-spacing:0.16em;color:#605d5d;margin-left:4px">
        COMPANY SCOUT</span>
</div>

<h1 style="font-size:28px;font-weight:800;letter-spacing:-0.03em;margin-bottom:4px">
    {esc(company.name)}</h1>
<p style="font-size:13px;color:#605d5d;margin-bottom:20px">
    {esc(company.country or '')}
    {(' · ' + esc(company.industry)) if company.industry else ''}
    {(' · ' + esc(company.website)) if company.website else ''}
</p>

<div style="display:flex;gap:16px;padding:16px 0;border-top:2px solid #e5e2de;border-bottom:2px solid #e5e2de;margin-bottom:20px">
    <div style="flex:1;text-align:center">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#605d5d">
            Overall</div>
        <div style="font-size:28px;font-weight:800;color:{rec_color}">{overall if overall is not None else '—'}</div>
        <div style="font-size:11px;font-weight:700;color:{rec_color}">{esc(rec)}</div>
    </div>
    <div style="flex:1;text-align:center">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#605d5d">
            Story</div>
        <div style="font-size:20px;font-weight:700;color:{score_color(scores.story_score if scores else None)}">
            {scores.story_score if scores and scores.story_score is not None else '—'}</div>
    </div>
    <div style="flex:1;text-align:center">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#605d5d">
            Case study</div>
        <div style="font-size:20px;font-weight:700;color:{score_color(scores.case_study_score if scores else None)}">
            {scores.case_study_score if scores and scores.case_study_score is not None else '—'}</div>
    </div>
    <div style="flex:1;text-align:center">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#605d5d">
            Outreach</div>
        <div style="font-size:20px;font-weight:700;color:{score_color(scores.outreach_score if scores else None)}">
            {scores.outreach_score if scores and scores.outreach_score is not None else '—'}</div>
    </div>
    <div style="flex:1;text-align:center">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#605d5d">
            Research</div>
        <div style="font-size:20px;font-weight:700;color:{score_color(scores.research_score if scores else None)}">
            {scores.research_score if scores and scores.research_score is not None else '—'}</div>
    </div>
</div>

<p style="font-size:14px;line-height:1.6;margin-bottom:20px">{esc(brief.executive_summary or '')}</p>

{signals_html}
{people_html}

<p style="margin-top:24px;font-size:12px;color:#605d5d;border-top:1px solid #e5e2de;padding-top:12px">
    {len(brief.evidence.claims)} claims from {len(brief.evidence.sources)} sources ·
    Generated by Company Scout · scout.yeboah.works{'/r/' + share_key if share_key else ''}
</p>
</body>
</html>"""
