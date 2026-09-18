/* Comparison view — two briefs side by side.
 * Loaded after report.js. Activated when the URL is /compare?a=KEY1&b=KEY2.
 */

async function loadComparison() {
    const params = new URLSearchParams(window.location.search);
    const a = params.get('a');
    const b = params.get('b');
    if (!a || !b) return;

    hideIntro();
    hideResults();
    showLoading();
    document.getElementById('loading-status').textContent = 'Loading comparison...';

    try {
        const r = await fetch(`/compare-data?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            throw new Error(err.detail || 'Could not load comparison.');
        }
        const data = await r.json();
        hideLoading();
        renderComparison(data.a, data.b);
    } catch (err) {
        hideLoading();
        showError(err.message);
    }
}

function renderComparison(dataA, dataB) {
    const briefA = dataA.brief;
    const briefB = dataB.brief;

    const container = document.getElementById('compare-view');
    if (!container) return;

    container.innerHTML = `
        <div class="compare-header">
            <h2>Comparison</h2>
            <p class="section-subtitle">Two companies, side by side. Same scores, same evidence standard.</p>
        </div>
        <div class="compare-grid">
            ${renderCompanyColumn(briefA, dataA.share_key)}
            ${renderCompanyColumn(briefB, dataB.share_key)}
        </div>
        <div class="compare-footer">
            <a href="/" class="cta-link">&larr; Scout another company</a>
        </div>
    `;
    container.classList.remove('hidden');
}

function renderCompanyColumn(brief, shareKey) {
    const company = brief.evidence?.company || {};
    const scores = brief.scores || {};
    const rec = getRecommendation(scores);
    const badgeClass = getBadgeClass(rec);

    const signals = (brief.analysis?.signals || []).slice(0, 3);
    const gaps = (brief.evidence?.coverage?.gaps || []).slice(0, 3);

    return `
        <div class="compare-column">
            <div class="compare-company">
                <h3>${escapeHtml(company.name || 'Unknown')}</h3>
                <span class="compare-country">${escapeHtml(company.country || '')}</span>
                <span class="score-badge ${badgeClass}">${escapeHtml(rec)}</span>
            </div>

            <div class="compare-scores">
                <div class="compare-score-row">
                    <span class="compare-score-label">Story</span>
                    <span class="compare-score-value" style="color:${scoreColor(scores.story_score || 0)}">${scores.story_score ?? '—'}</span>
                </div>
                <div class="compare-score-row">
                    <span class="compare-score-label">Case study</span>
                    <span class="compare-score-value" style="color:${scoreColor(scores.case_study_score || 0)}">${scores.case_study_score ?? '—'}</span>
                </div>
                <div class="compare-score-row">
                    <span class="compare-score-label">Outreach</span>
                    <span class="compare-score-value" style="color:${scoreColor(scores.outreach_score || 0)}">${scores.outreach_score ?? '—'}</span>
                </div>
                <div class="compare-score-row">
                    <span class="compare-score-label">Research</span>
                    <span class="compare-score-value" style="color:${scoreColor(scores.research_score || 0)}">${scores.research_score ?? '—'}</span>
                </div>
                <div class="compare-score-row compare-score-overall">
                    <span class="compare-score-label">Overall</span>
                    <span class="compare-score-value" style="color:${scoreColor(scores.overall_score || 0)}">${scores.overall_score ?? '—'}</span>
                </div>
            </div>

            <div class="compare-summary">
                <p>${escapeHtml(brief.executive_summary || '')}</p>
            </div>

            ${signals.length ? `
                <div class="compare-signals">
                    <h4>Top signals</h4>
                    ${signals.map(s => `<p class="compare-signal">${escapeHtml(s.signal || s.headline || '')}</p>`).join('')}
                </div>
            ` : ''}

            ${gaps.length ? `
                <div class="compare-gaps">
                    <h4>Gaps</h4>
                    ${gaps.map(g => `<p class="compare-gap">${escapeHtml(g)}</p>`).join('')}
                </div>
            ` : ''}

            <a href="/r/${encodeURIComponent(shareKey)}" class="compare-open">Open full brief &rarr;</a>
        </div>
    `;
}
