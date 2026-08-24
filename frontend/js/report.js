/* Rendering a finished brief into the results view: score banner, tabs,
 * signals, evidence, sources.
 */

/* ---------- People ----------
 * Joins three things the backend already produces but never showed together:
 * the person (role, tenure), the best address found for them, and their
 * LinkedIn result. Ranked so whoever is most reachable sits at the top,
 * because a list ordered by extraction accident is a list you have to read
 * end to end.
 */

// Sort key: a found personal address beats an inferred one, which beats a
// LinkedIn profile, which beats nothing. Former staff sink regardless — they
// are shown, because knowing someone has left is useful, but never first.
function contactRank(entry) {
    if (entry.person.status === 'former') return 0;
    if (entry.found && entry.found.kind === 'personal') return 4;
    if (entry.found) return 3;
    if (entry.linkedin && entry.linkedin.found) return 2;
    if (entry.inferred) return 1;
    return 0;
}

function routeBadge(entry) {
    if (entry.found && entry.found.kind === 'personal') {
        return '<span class="route-badge found">Found</span>';
    }
    if (entry.found) {
        return '<span class="route-badge role">Team inbox</span>';
    }
    if (entry.inferred) {
        return '<span class="route-badge inferred">Inferred</span>';
    }
    if (entry.linkedin && entry.linkedin.found) {
        return '<span class="route-badge linkedin">LinkedIn only</span>';
    }
    return '<span class="route-badge none">No route found</span>';
}

function renderPeople(people, contacts) {
    const el = document.getElementById('people-list');
    if (!el) return;

    const found = contacts.found || [];
    const inferred = contacts.inferred || [];
    const linkedin = contacts.linkedin || [];

    const entries = people.map(person => ({
        person,
        found: found.find(f => f.person && f.person === person.name),
        inferred: inferred.find(i => i.person === person.name),
        linkedin: linkedin.find(l => !l.is_company_page && l.person === person.name),
    }));

    entries.sort((a, b) => contactRank(b) - contactRank(a));

    if (!entries.length) {
        el.innerHTML = '<p class="section-subtitle">No named people were found for this company.</p>';
        return;
    }

    el.innerHTML = entries.map(entry => {
        const p = entry.person;
        const isFormer = p.status === 'former';

        // An address for someone who has left is the single most damaging
        // thing this page could present as usable, so it is never shown as a
        // route — only the fact that they have gone.
        const route = isFormer
            ? '<p class="person-departed">No contact route offered &mdash; the evidence says they have left.</p>'
            : `
                ${entry.found ? `
                    <div class="person-route">
                        <a class="contact-email" href="mailto:${encodeURIComponent(entry.found.email)}">${esc(entry.found.email)}</a>
                        ${entry.found.observed_on ? `<span class="person-route-note">seen ${esc(entry.found.observed_on)}</span>` : ''}
                    </div>` : ''}
                ${!entry.found && entry.inferred ? `
                    <div class="person-route">
                        <span class="contact-email guess">${esc(entry.inferred.email)}</span>
                        <span class="person-route-note">${esc(entry.inferred.basis || 'inferred')} &mdash; unverified</span>
                    </div>` : ''}
                ${entry.linkedin ? `
                    <div class="person-route">
                        ${entry.linkedin.found
                            ? `<a href="${esc(entry.linkedin.url)}" target="_blank" rel="noopener" class="source-link">LinkedIn profile &rarr;</a>`
                            : `<a href="${esc(entry.linkedin.search_url || '')}" target="_blank" rel="noopener" class="source-link">Not found &mdash; search LinkedIn &rarr;</a>`}
                    </div>` : ''}
                ${!entry.found && !entry.inferred && !entry.linkedin
                    ? '<p class="person-route-note">No address or profile found for this person.</p>' : ''}
            `;

        return `
            <div class="card person-card-full ${isFormer ? 'is-former' : ''}">
                <div class="person-head">
                    <div>
                        <span class="person-name">${esc(p.name)}</span>
                        <span class="person-role">${esc(p.role)}</span>
                    </div>
                    ${routeBadge(entry)}
                </div>
                <p class="person-tenure ${p.status || 'unclear'}">${esc(p.tenure_note || '')}</p>
                ${route}
            </div>
        `;
    }).join('');
}

function renderBrief(brief) {
    const evidence = brief.evidence;
    const analysis = brief.analysis;
    const scores = analysis.scores;
    const company = evidence.company;

    // Score Banner
    document.getElementById('company-name').textContent = company.name;

    // Two scores, not one. A company can be fascinating and unreachable, and
    // a single averaged number hides exactly that — which is how a company
    // that shut down in 2023 was once reported as HIGH PRIORITY.
    const badge = document.getElementById('score-badge');
    badge.textContent = brief.verdict || 'N/A';
    badge.className = 'score-badge ' + verdictClass(brief.verdict);

    const pair = document.getElementById('score-pair');
    if (pair) {
        pair.innerHTML = `
            <div class="score-half">
                <span class="score-half-label">Worth your attention</span>
                <span class="score-half-value" style="color:${scoreColor(brief.interest_score)}">
                    ${brief.interest_score}<span class="score-half-max">/10</span>
                </span>
                <span class="score-half-note">story, case study, research</span>
            </div>
            <div class="score-half">
                <span class="score-half-label">Can you reach them</span>
                <span class="score-half-value" style="color:${scoreColor(brief.reachability_score)}">
                    ${brief.reachability_score}<span class="score-half-max">/10</span>
                </span>
                <span class="score-half-note">contact route and whether they're still trading</span>
            </div>
        `;
    }

    // Explain any recency adjustment, so a score that differs from the plain
    // average of the four dimensions doesn't look like an error.
    const recencyEl = document.getElementById('score-recency');
    if (recencyEl) {
        if (scores && scores.recency_factor && scores.recency_factor !== 1) {
            const dir = scores.recency_factor > 1 ? 'raised' : 'lowered';
            recencyEl.textContent =
                `Evidence age ${dir} the attention score by `
                + `${Math.round(Math.abs(1 - scores.recency_factor) * 100)}%. `
                + (scores.recency_note || '');
            recencyEl.classList.remove('hidden');
        } else {
            recencyEl.classList.add('hidden');
        }
    }

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

    // People — each person shown with their own route in, rather than a bare
    // list of names on one tab and a bare list of addresses on another. The
    // question a reader actually has is "can I reach this person, and should
    // I trust that address", and that can only be answered in one place.
    renderPeople(evidence.people || [], brief.contacts || {});

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

    renderContacts(brief.contacts);

    // Claims, newest first. Recency drives the score, so the evidence list
    // should lead with what's current rather than whatever order it came back in.
    const claimsEl = document.getElementById('claims-list');
    const claims = sortByDateDesc(evidence.claims || [], c => c.date_of_event || c.source?.published_date);

    claimsEl.innerHTML = claims.map((c, i) => {
        const when = c.date_of_event || c.source?.published_date;
        return `
        <div class="card">
            <div class="card-body">
                <div class="claim-head">
                    <span class="confidence ${c.confidence}">${c.confidence}</span>
                    ${when ? `<span class="claim-date">${esc(formatEvidenceDate(when))}</span>` : '<span class="claim-date undated">undated</span>'}
                    <button class="copy-claim" type="button" data-claim="${i}" title="Copy this claim">Copy</button>
                </div>
                <p class="claim-text">${esc(c.statement)}</p>
                <span class="card-label">Source:</span> ${esc(c.source.title)}
                ${c.source.url ? `<br><a href="${esc(c.source.url)}" target="_blank" rel="noopener" class="source-link">${esc(c.source.url)}</a>` : ''}
            </div>
        </div>
        `;
    }).join('');

    // One listener on the container rather than per card, so re-rendering a
    // report doesn't leave orphaned handlers behind.
    claimsEl.onclick = (e) => {
        const btn = e.target.closest('.copy-claim');
        if (!btn) return;
        const claim = claims[Number(btn.dataset.claim)];
        if (!claim) return;
        const when = claim.date_of_event || claim.source?.published_date;
        const text = `"${claim.statement}"`
            + (when ? `\n(${when})` : '')
            + `\nSource: ${claim.source.title}`
            + (claim.source.url ? `\n${claim.source.url}` : '');
        copyText(text, btn);
    };

    // Coverage — what the research went looking for and did not find.
    // Rendered above the source list because a gap changes how the rest of
    // the tab should be read.
    const coverage = evidence.coverage;
    const coverageEl = document.getElementById('coverage-section');
    if (coverage && (coverage.areas || []).length) {
        coverageEl.classList.remove('hidden');
        const gaps = coverage.gaps || [];
        document.getElementById('coverage-headline').innerHTML =
            `<strong>${coverage.covered_count}/${coverage.total_areas}</strong> areas produced evidence`
            + (gaps.length
                ? ` &mdash; nothing found on <strong>${esc(gaps.join(', '))}</strong>.`
                : ' &mdash; every area the search asked about came back with something.');
        document.getElementById('coverage-list').innerHTML = coverage.areas.map(a => `
            <div class="coverage-row ${a.covered ? 'covered' : 'gap'}">
                <span class="coverage-mark">${a.covered ? '&check;' : '&mdash;'}</span>
                <span class="coverage-label">${esc(a.label)}</span>
                <span class="coverage-detail">${a.covered
                    ? `${a.claims} claim${a.claims === 1 ? '' : 's'}`
                    : 'nothing usable'}</span>
            </div>
        `).join('');
    } else {
        coverageEl.classList.add('hidden');
    }

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
