let currentBrief = null;

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
    });
});

// Form submission
document.getElementById('search-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = document.getElementById('company-input').value.trim();
    if (!query) return;
    await scoutCompany(query);
});

async function scoutCompany(query) {
    showLoading();
    hideError();
    hideResults();

    const btn = document.getElementById('scout-btn');
    btn.disabled = true;

    // Animate loading steps
    const steps = [1, 2, 3, 4, 5];
    let stepIndex = 0;
    const stepMessages = [
        'Resolving company identity...',
        'Searching for evidence...',
        'Extracting structured evidence...',
        'Analysing strategic signals...',
        'Scoring opportunity...'
    ];

    const stepInterval = setInterval(() => {
        if (stepIndex < steps.length) {
            if (stepIndex > 0) {
                document.getElementById('step-' + steps[stepIndex - 1]).classList.remove('active');
                document.getElementById('step-' + steps[stepIndex - 1]).classList.add('done');
            }
            document.getElementById('step-' + steps[stepIndex]).classList.add('active');
            document.getElementById('loading-status').textContent = stepMessages[stepIndex];
            stepIndex++;
        }
    }, 15000);

    // Mark first step active immediately
    document.getElementById('step-1').classList.add('active');

    // Research can take a few minutes on the free hosting tier — reassure
    // the user past a minute so it doesn't look stuck.
    const patienceEl = document.getElementById('loading-patience');
    patienceEl.classList.add('hidden');
    const patienceTimeout = setTimeout(() => {
        patienceEl.classList.remove('hidden');
    }, 60000);

    try {
        const response = await fetch('/scout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query })
        });

        clearInterval(stepInterval);
        clearTimeout(patienceTimeout);

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Research failed. Please try again.');
        }

        const data = await response.json();
        currentBrief = data.brief;
        renderBrief(data.brief);
        hideLoading();
        showResults();

    } catch (err) {
        clearInterval(stepInterval);
        clearTimeout(patienceTimeout);
        hideLoading();
        showError(err.message);
    } finally {
        btn.disabled = false;
        // Reset step states
        steps.forEach(s => {
            const el = document.getElementById('step-' + s);
            el.classList.remove('active', 'done');
        });
    }
}

function renderBrief(brief) {
    const evidence = brief.evidence;
    const analysis = brief.analysis;
    const scores = analysis.scores;
    const company = evidence.company;

    // Score Banner
    document.getElementById('company-name').textContent = company.name;

    const scoreValue = scores ? scores.overall_score : 'N/A';
    const recommendation = scores ? getRecommendation(scores) : 'N/A';
    document.getElementById('score-value').textContent = scoreValue + '/10';

    const badge = document.getElementById('score-badge');
    badge.textContent = recommendation;
    badge.className = 'score-badge ' + getBadgeClass(recommendation);

    const meta = [];
    if (company.country) meta.push(company.country);
    if (company.industry) meta.push(company.industry);
    if (company.website) meta.push(company.website);
    if (company.founded_year) meta.push('Founded ' + company.founded_year);
    document.getElementById('company-meta').textContent = meta.join(' | ');

    // Executive Summary
    document.getElementById('executive-summary').textContent = analysis.executive_summary;

    // Scores Grid
    if (scores) {
        document.getElementById('scores-grid').innerHTML = [
            scoreCard('Story', scores.story_score, scores.story_reasoning),
            scoreCard('Case Study', scores.case_study_score, scores.case_study_reasoning),
            scoreCard('Outreach', scores.outreach_score, scores.outreach_reasoning),
            scoreCard('Research', scores.research_score, scores.research_reasoning),
        ].join('');
    }

    // Top Priorities
    const prioritiesEl = document.getElementById('priorities-list');
    prioritiesEl.innerHTML = (analysis.top_priorities || []).map((p, i) => `
        <div class="card">
            <div class="priority-card">
                <span class="priority-number">${i + 1}</span>
                <div>
                    <div class="card-title">${esc(p.topic)}</div>
                    <div class="card-body">${esc(p.why)}</div>
                </div>
            </div>
        </div>
    `).join('');

    // People
    const peopleEl = document.getElementById('people-list');
    peopleEl.innerHTML = (evidence.people || []).map(p => `
        <div class="card">
            <div class="person-card">
                <div class="person-info">
                    <span class="person-name">${esc(p.name)}</span>
                    <span class="person-role"> &mdash; ${esc(p.role)} (${esc(p.relationship)})</span>
                </div>
                <span class="confidence ${p.confidence}">${p.confidence}</span>
            </div>
        </div>
    `).join('');

    // Signals
    const signalsEl = document.getElementById('signals-list');
    signalsEl.innerHTML = (analysis.signals || []).map((s, i) => `
        <div class="card">
            <div class="card-title">Signal ${i + 1}: ${esc(s.title)} <span class="confidence ${s.confidence}">${s.confidence}</span></div>
            <div class="card-body">
                <p><span class="card-label">Evidence</span><br>${esc(s.evidence)}</p>
                <p><span class="card-label">Interpretation</span><br>${esc(s.interpretation)}</p>
                <p><span class="card-label">Question</span><br>${esc(s.question)}</p>
            </div>
        </div>
    `).join('');

    // Story Angles
    const anglesEl = document.getElementById('angles-list');
    anglesEl.innerHTML = (analysis.story_angles || []).map((a, i) => `
        <div class="card">
            <div class="card-title">${i + 1}. ${esc(a.angle)}</div>
            <div class="card-body">
                <p><span class="card-label">Why interesting</span><br>${esc(a.why_interesting)}</p>
                <p><span class="card-label">Supporting evidence</span><br>${esc(a.supporting_evidence)}</p>
                <p><span class="card-label">Information gap</span><br>${esc(a.information_gap)}</p>
            </div>
        </div>
    `).join('');

    // Case Study
    const csSection = document.getElementById('case-study-section');
    const csContent = document.getElementById('case-study-content');
    if (analysis.case_study) {
        const cs = analysis.case_study;
        csSection.classList.remove('hidden');
        csContent.innerHTML = `
            <div class="card">
                <div class="card-title">${esc(cs.potential_title)} <span class="score-value" style="font-size:1rem">${cs.score}/10</span></div>
                <div class="card-body">
                    <p><span class="card-label">Central Decision</span><br>${esc(cs.central_decision)}</p>
                    <p><span class="card-label">Decision Maker</span><br>${esc(cs.decision_maker)}</p>
                    <p><span class="card-label">Strategic Tension</span><br>${esc(cs.strategic_tension)}</p>
                    <p><span class="card-label">Evidence Available</span><br>${esc(cs.evidence_available)}</p>
                    <p><span class="card-label">Missing Information</span><br>${esc(cs.missing_information)}</p>
                    <p><span class="card-label">Reasoning</span><br>${esc(cs.reasoning)}</p>
                </div>
            </div>
        `;
    } else {
        csSection.classList.add('hidden');
    }

    // Outreach
    const orSection = document.getElementById('outreach-section');
    const orContent = document.getElementById('outreach-content');
    if (analysis.outreach) {
        const o = analysis.outreach;
        orSection.classList.remove('hidden');
        orContent.innerHTML = `
            <div class="card">
                <div class="card-title">${esc(o.recommended_contact)} &mdash; ${esc(o.role)}</div>
                <div class="card-body">
                    <p><span class="card-label">Why</span><br>${esc(o.why)}</p>
                    <p><span class="card-label">Trigger</span><br>${esc(o.trigger)}</p>
                    <p><span class="card-label">Outreach Thesis</span><br>${esc(o.outreach_thesis)}</p>
                    <p><span class="card-label">What You Could Offer</span><br>${esc(o.what_you_could_offer)}</p>
                </div>
            </div>
        `;
    } else {
        orSection.classList.add('hidden');
    }

    // Claims
    const claimsEl = document.getElementById('claims-list');
    claimsEl.innerHTML = (evidence.claims || []).map(c => `
        <div class="card">
            <div class="card-body">
                <span class="confidence ${c.confidence}">${c.confidence}</span>
                <span style="margin-left:8px">${esc(c.statement)}</span>
                ${c.date_of_event ? `<br><span class="card-label" style="margin-top:6px;display:inline-block">Date: ${esc(c.date_of_event)}</span>` : ''}
                <br><span class="card-label">Source:</span> ${esc(c.source.title)}
                ${c.source.url ? `<br><a href="${esc(c.source.url)}" target="_blank" rel="noopener" class="source-link">${esc(c.source.url)}</a>` : ''}
            </div>
        </div>
    `).join('');

    // Sources
    const sources = evidence.sources || [];
    const tier1 = sources.filter(s => s.source_quality === 'tier_1').length;
    const tier2 = sources.filter(s => s.source_quality === 'tier_2').length;
    const tier3 = sources.filter(s => s.source_quality === 'tier_3').length;

    document.getElementById('source-stats').innerHTML = `
        <span class="stat"><strong>${sources.length}</strong> total</span>
        <span class="stat"><span class="tier-badge tier_1">Tier 1</span> ${tier1}</span>
        <span class="stat"><span class="tier-badge tier_2">Tier 2</span> ${tier2}</span>
        <span class="stat"><span class="tier-badge tier_3">Tier 3</span> ${tier3}</span>
    `;

    document.getElementById('sources-list').innerHTML = sources.map(s => `
        <div class="card">
            <div class="card-body">
                <span class="tier-badge ${s.source_quality}">${formatTier(s.source_quality)}</span>
                <span style="margin-left:8px;font-weight:500">${esc(s.title)}</span>
                <br><a href="${esc(s.url)}" target="_blank" rel="noopener" class="source-link">${esc(s.url)}</a>
            </div>
        </div>
    `).join('');

    // Duration / cache provenance
    if (brief.from_cache) {
        document.getElementById('duration').textContent =
            `Saved report from ${formatCachedAt(brief.cached_at)} — shown instantly`;
    } else {
        document.getElementById('duration').textContent =
            `Completed in ${brief.duration_seconds.toFixed(1)}s`;
    }

    // Reset to overview tab
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelector('.tab[data-tab="overview"]').classList.add('active');
    document.getElementById('tab-overview').classList.add('active');
}

function scoreCard(label, score, reasoning) {
    return `
        <div class="score-card">
            <div class="score-card-header">
                <span class="score-card-label">${label}</span>
                <span class="score-card-value" style="color:${scoreColor(score)}">${score}</span>
            </div>
            <div class="score-card-reasoning">${esc(reasoning)}</div>
        </div>
    `;
}

function scoreColor(score) {
    if (score >= 8) return 'var(--green)';
    if (score >= 6) return 'var(--blue)';
    if (score >= 4) return 'var(--yellow)';
    return 'var(--red)';
}

function getRecommendation(scores) {
    const s = scores.overall_score;
    if (s >= 8) return 'HIGH PRIORITY';
    if (s >= 6) return 'WORTH A LOOK';
    if (s >= 4) return 'LOW PRIORITY';
    return 'SKIP';
}

function getBadgeClass(rec) {
    if (rec === 'HIGH PRIORITY') return 'high';
    if (rec === 'WORTH A LOOK') return 'worth';
    if (rec === 'LOW PRIORITY') return 'low';
    return 'skip';
}

function formatTier(tier) {
    return tier.replace('_', ' ').toUpperCase();
}

function formatCachedAt(iso) {
    if (!iso) return 'earlier';
    const then = new Date(iso);
    if (isNaN(then)) return 'earlier';
    const hours = Math.floor((Date.now() - then) / 3600000);
    if (hours < 1) return 'just now';
    if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
    const days = Math.floor(hours / 24);
    return `${days} day${days === 1 ? '' : 's'} ago`;
}

function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

function downloadReport() {
    if (!currentBrief) return;
    const blob = new Blob([JSON.stringify(currentBrief, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `scout_report_${currentBrief.evidence.company.name.toLowerCase().replace(/\s+/g, '_')}.json`;
    a.click();
    URL.revokeObjectURL(url);
}

function showLoading() { document.getElementById('loading').classList.remove('hidden'); }
function hideLoading() { document.getElementById('loading').classList.add('hidden'); }
function showResults() { document.getElementById('results').classList.remove('hidden'); }
function hideResults() { document.getElementById('results').classList.add('hidden'); }
function showError(msg) {
    document.getElementById('error-message').textContent = msg;
    document.getElementById('error').classList.remove('hidden');
}
function hideError() { document.getElementById('error').classList.add('hidden'); }
