/* The usage page. Reads /usage and renders headroom per provider.
 *
 * Bars are coloured by how much is left rather than how much is spent, because
 * the question being asked is "can I run another scout?", not "what have I
 * used?".
 */

// Signed-up users, and whether the welcome email is wired up. Not a growth
// dashboard — just enough to confirm "did that signup actually happen"
// without opening a database console.
function accountsSection(accounts, mail) {
    if (!accounts || !accounts.enabled) {
        return '<p class="section-subtitle">No database configured.</p>';
    }
    if (accounts.error) {
        return `<p class="section-subtitle">Could not read accounts: ${escapeHtml(accounts.error)}</p>`;
    }
    const mailLine = mail && mail.configured
        ? 'Welcome email: configured'
        : 'Welcome email: not configured (set RESEND_API_KEY)';
    const rows = (accounts.recent || []).map(u => `
        <div class="usage-row-flat">
            <span>${escapeHtml(u.email)}</span>
            <span class="usage-sub">${escapeHtml(new Date(u.created_at).toLocaleString())}</span>
        </div>
    `).join('');
    return `
        <p class="section-subtitle"><strong>${accounts.total}</strong> account(s) &middot; ${mailLine}</p>
        ${rows || '<p class="section-subtitle">No signups yet.</p>'}
    `;
}


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

// A key that is set and a key that works are different facts, and only the
// second one predicts whether the next scout finds an address. Asked of
// Hunter directly rather than inferred from our own configuration.
function hunterStatus(h) {
    if (!h.configured) return '';
    if (h.valid === true) {
        return '<p class="section-subtitle">Key checked against Hunter and working.</p>';
    }
    if (h.valid === false) {
        return '<p class="section-subtitle warning">'
            + 'Key is set but <strong>Hunter rejected it</strong>'
            + (h.reason ? ` (${escapeHtml(h.reason)})` : '')
            + '. Contact discovery is running without it.</p>';
    }
    return '<p class="section-subtitle">'
        + 'Key is set, but it could not be checked just now'
        + (h.reason ? ` (${escapeHtml(h.reason)})` : '')
        + '. Unknown, not confirmed.</p>';
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
            ${data.tavily.exhausted
                ? '<p class="section-subtitle warning"><strong>Allowance spent.</strong> '
                  + 'No new research can run until this resets — search is the first '
                  + 'step of every scout. Saved reports still open.</p>'
                : ''}
            ${meter('Searches this month', data.tavily.used, data.tavily.limit,
                    data.tavily.remaining,
                    `${data.tavily.remaining} left · ${data.tavily.authoritative
                        ? 'counted by Tavily'
                        : 'counted here'}${data.tavily.plan ? ' · ' + escapeHtml(data.tavily.plan) + ' plan' : ''}`)}
        </div>

        <div class="section">
            <h3>Exa — fallback when Tavily is spent</h3>
            <p class="section-subtitle">
                Only used once Tavily's monthly plan is gone. A count above zero
                means that happened this month.
            </p>
            ${data.exa && data.exa.configured
                ? `<p class="section-subtitle"><strong>${data.exa.used}</strong> search(es) this month · resets in ${humaniseDuration(data.exa.resets_in_seconds)}</p>`
                : '<p class="section-subtitle">Not configured. Set EXA_API_KEY to enable the search fallback.</p>'}
        </div>

        <div class="section">
            <h3>Groq — fallback when Gemini is fully spent</h3>
            <p class="section-subtitle">
                Only reached once every Gemini model's daily allowance for
                today is gone. A count above zero means that happened today.
            </p>
            ${data.groq && data.groq.configured
                ? meter('Calls today', data.groq.used, data.groq.limit,
                        data.groq.remaining,
                        `${data.groq.remaining} left · resets in ${humaniseDuration(data.groq.resets_in_seconds)}`)
                : '<p class="section-subtitle">Not configured. Set GROQ_API_KEY to enable it — tried first.</p>'}
            ${data.cerebras && data.cerebras.configured
                ? `<p class="section-subtitle">Cerebras (second in line): <strong>${data.cerebras.used}</strong> call(s) today · resets in ${humaniseDuration(data.cerebras.resets_in_seconds)}</p>`
                : '<p class="section-subtitle">Cerebras not configured. Set CEREBRAS_API_KEY to add it as a second fallback.</p>'}
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
            ${hunterStatus(data.hunter)}
            ${data.hunter.configured
                ? meter('Lookups this month', data.hunter.used, data.hunter.limit,
                        data.hunter.remaining,
                        `${data.hunter.remaining} left · ${data.hunter.authoritative
                            ? 'counted by Hunter'
                            : 'counted here'} · resets in ${humaniseDuration(data.hunter.resets_in_seconds)}`)
                : '<p class="section-subtitle">Not configured. Set HUNTER_API_KEY to enable email lookups.</p>'}
        </div>

        <div class="section">
            <h3>Accounts</h3>
            ${accountsSection(data.accounts, data.mail)}
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
