/* The usage page. Reads /usage and renders headroom per provider.
 *
 * Bars are coloured by how much is left rather than how much is spent, because
 * the question being asked is "can I run another scout?", not "what have I
 * used?".
 */

function humaniseDuration(seconds) {
    if (seconds == null) return 'unknown';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h >= 24) {
        const d = Math.floor(h / 24);
        return `${d} day${d === 1 ? '' : 's'}`;
    }
    if (h >= 1) return `${h}h ${m}m`;
    return `${m} minutes`;
}

function barClass(remaining, limit) {
    if (!limit) return 'ok';
    const share = remaining / limit;
    if (share <= 0) return 'gone';
    if (share <= 0.25) return 'low';
    if (share <= 0.5) return 'half';
    return 'ok';
}

function meter(label, used, limit, remaining, extra) {
    const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
    return `
        <div class="usage-row">
            <div class="usage-row-head">
                <span class="usage-label">${escapeHtml(label)}</span>
                <span class="usage-count">${used} / ${limit} used</span>
            </div>
            <div class="usage-bar">
                <div class="usage-fill ${barClass(remaining, limit)}" style="width:${pct}%"></div>
            </div>
            <div class="usage-sub">${extra || `${remaining} left`}</div>
        </div>
    `;
}

// The token arrives once in the URL and is kept, so the page stays
// bookmarkable without the key sitting in the address bar afterwards.
function adminToken() {
    try {
        const fromUrl = new URLSearchParams(window.location.search).get('key');
        if (fromUrl) {
            localStorage.setItem('scout-admin-token', fromUrl);
            history.replaceState({}, '', window.location.pathname);
            return fromUrl;
        }
        return localStorage.getItem('scout-admin-token') || '';
    } catch {
        return new URLSearchParams(window.location.search).get('key') || '';
    }
}

async function loadUsage() {
    const body = document.getElementById('usage-body');
    body.innerHTML = '<p class="section-subtitle">Loading…</p>';

    let data;
    try {
        const r = await fetch('/usage', {
            headers: { 'X-Admin-Token': adminToken() }
        });
        if (r.status === 404) {
            body.innerHTML = '<p class="section-subtitle">'
                + 'This page needs an access key. Open it as '
                + '<code>/usage-page?key=YOUR_TOKEN</code> once and it will be remembered.'
                + '</p>';
            return;
        }
        if (!r.ok) throw new Error('Could not read usage.');
        data = await r.json();
    } catch (e) {
        body.innerHTML = `<p class="section-subtitle">Could not load usage: ${escapeHtml(e.message)}</p>`;
        return;
    }

    const g = data.gemini;
    const stages = data.stages || {};
    const stageFor = {};
    Object.entries(stages).forEach(([stage, model]) => {
        (stageFor[model] = stageFor[model] || []).push(stage);
    });

    const scouts = g.approx_scouts_left;
    const headline = scouts > 0
        ? `About <strong>${scouts}</strong> more ${scouts === 1 ? 'scout' : 'scouts'} today`
        : `<strong>No scouts left today</strong>`;

    body.innerHTML = `
        <div class="usage-headline ${scouts > 0 ? '' : 'empty'}">
            ${headline}
            <span class="usage-reset">Gemini resets in ${humaniseDuration(g.resets_in_seconds)}</span>
        </div>

        <div class="section">
            <h3>Gemini — ${g.total_remaining} calls left today</h3>
            <p class="section-subtitle">
                The daily allowance is per model, so the pipeline spreads across several.
                A scout costs about 6 calls.
            </p>
            ${g.models.map(m => meter(
                m.model + (stageFor[m.model] ? ` · ${stageFor[m.model].join(', ')}` : ''),
                m.used, m.limit, m.remaining,
                m.exhausted ? 'Spent for today' : `${m.remaining} left`
            )).join('')}
        </div>

        <div class="section">
            <h3>Tavily — search</h3>
            ${meter('Searches this month', data.tavily.used, data.tavily.limit,
                    data.tavily.remaining,
                    `${data.tavily.remaining} left · resets in ${humaniseDuration(data.tavily.resets_in_seconds)}`)}
        </div>

        <div class="section">
            <h3>Apollo — email lookup by person</h3>
            ${data.apollo && data.apollo.configured
                ? meter('Lookups this month', data.apollo.used, data.apollo.limit,
                        data.apollo.remaining,
                        `${data.apollo.remaining} left · resets in ${humaniseDuration(data.apollo.resets_in_seconds)}`)
                : '<p class="section-subtitle">Not configured. Set APOLLO_API_KEY to enable.</p>'}
        </div>

        <div class="section">
            <h3>Hunter — email lookup by domain</h3>
            ${data.hunter.configured
                ? meter('Lookups this month', data.hunter.used, data.hunter.limit,
                        data.hunter.remaining,
                        `${data.hunter.remaining} left · resets in ${humaniseDuration(data.hunter.resets_in_seconds)}`)
                : '<p class="section-subtitle">Not configured. Set HUNTER_API_KEY to enable email lookups.</p>'}
        </div>
    `;

    // Say which of the two situations the reader is in, rather than always
    // warning: a durable count is worth trusting, a per-process one is not.
    const caveat = document.getElementById('usage-caveat');
    if (caveat) {
        caveat.textContent = data.durable
            ? 'Counts are stored in the shared cache, so they survive restarts and '
              + 'redeploys. They still only include calls this app made — anything '
              + 'run from your laptop is not counted here. Each provider’s console '
              + 'remains the authority.'
            : 'No shared store is attached, so these counts reset every time the '
              + 'service restarts — which on Render is often. Treat them as a rough '
              + 'floor, not a measurement.';
        caveat.classList.toggle('warning', !data.durable);
    }
}

document.getElementById('refresh')?.addEventListener('click', loadUsage);
loadUsage();
