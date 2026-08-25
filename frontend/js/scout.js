/* ---------- Pipeline stages ----------
 * Fetched once so the loading screen always shows exactly as many rows as
 * the backend actually reports against — never hardcoded here.
 */
let pipelineStageCount = 0;

async function loadPipelineStages() {
    const container = document.getElementById('loading-steps');
    if (!container) return;
    try {
        const r = await fetch('/pipeline-stages');
        if (!r.ok) throw new Error('bad response');
        const data = await r.json();
        const stages = data.stages || [];
        pipelineStageCount = stages.length;
        container.innerHTML = stages.map((label, i) => `
            <div id="step-${i + 1}" class="step">${escapeHtml(label)}</div>
        `).join('');
    } catch {
        // No stage list is not worth blocking the page over — the loading
        // screen just shows the status line without the step-by-step rows.
        pipelineStageCount = 0;
    }
}

/* Running a scout: the search form, job polling, progress, share links,
 * and loading a saved report. Loaded last; owns start-up.
 */

/* ---------- Example chips ---------- */

document.querySelectorAll('.example-chip').forEach(chip => {
    chip.addEventListener('click', () => {
        const query = chip.dataset.q;
        document.getElementById('company-input').value = query;
        scoutCompany(query);
    });
});

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

    const steps = Array.from({ length: pipelineStageCount }, (_, i) => i + 1);
    document.getElementById('step-1')?.classList.add('active');

    // Research can take a few minutes on the free hosting tier — reassure
    // the user past a minute so it doesn't look stuck.
    const patienceEl = document.getElementById('loading-patience');
    patienceEl.classList.add('hidden');
    const patienceTimeout = setTimeout(() => {
        patienceEl.classList.remove('hidden');
    }, 60000);

    try {
        const started = await fetch('/scout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query })
        });

        if (!started.ok) {
            const err = await started.json().catch(() => ({}));
            throw new Error(err.detail || 'Research failed. Please try again.');
        }

        const job = await started.json();

        // A cached report comes back complete, with no job to poll.
        const data = job.result
            ? job.result
            : await pollUntilDone(job.id);

        clearTimeout(patienceTimeout);
        currentBrief = data.brief;
        currentShareKey = data.share_key || null;
        if (currentShareKey) {
            history.replaceState({}, '', '/r/' + currentShareKey);
        }
        renderBrief(data.brief);
        hideLoading();
        showResults();

    } catch (err) {
        clearTimeout(patienceTimeout);
        hideLoading();
        if (err.quota) showQuotaExhausted();
        else if (err.searchQuota) showSearchQuotaExhausted();
        else if (err.modelOverloaded) showModelOverloaded();
        else showError(err.message);
        loadCapacity();
    } finally {
        btn.disabled = false;
        steps.forEach(s => {
            document.getElementById('step-' + s)?.classList.remove('active', 'done');
        });
    }
}

// The scout itself runs on the server, well past the ~100s the proxy will
// hold a request open. Poll for its progress instead of waiting on one call.
async function pollUntilDone(jobId) {
    const POLL_INTERVAL_MS = 3000;

    while (true) {
        await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));

        let response;
        try {
            response = await fetch(`/scout/status/${jobId}`);
        } catch {
            // A dropped poll is normal on flaky connections; the job keeps
            // running on the server, so try again rather than giving up.
            continue;
        }

        if (response.status === 404) {
            throw new Error('That research job has expired. Please try again.');
        }
        if (!response.ok) continue;

        const job = await response.json();
        updateProgress(job);

        if (job.status === 'done' && job.result) return job.result;
        if (job.status === 'error') {
            // The quota case is not a fault and should not read like one: the
            // day's shared budget is spent, and the saved reports below still
            // cost nothing. Anything else keeps the server's message.
            if (job.error_kind === 'quota_exhausted') {
                const e = new Error('QUOTA');
                e.quota = true;
                throw e;
            }
            if (job.error_kind === 'search_quota_exhausted') {
                const e = new Error('SEARCH_QUOTA');
                e.searchQuota = true;
                throw e;
            }
            if (job.error_kind === 'model_overloaded') {
                const e = new Error('MODEL_OVERLOADED');
                e.modelOverloaded = true;
                throw e;
            }
            throw new Error(job.error || 'Research failed. Please try again.');
        }
    }
}

// Drive the step indicator from the server's actual stage rather than a timer,
// so the display cannot drift away from what is really happening.
function updateProgress(job) {
    if (job.message) {
        document.getElementById('loading-status').textContent = job.message;
    }
    const total = pipelineStageCount || job.total_stages || 0;
    for (let s = 1; s <= total; s++) {
        const el = document.getElementById('step-' + s);
        if (!el) continue;
        el.classList.remove('active', 'done');
        if (s < job.stage) el.classList.add('done');
        else if (s === job.stage) el.classList.add('active');
    }
}
async function copyShareLink() {
    if (!currentShareKey) return;
    const url = `${window.location.origin}/r/${currentShareKey}`;
    const btn = document.getElementById('share-btn');
    const original = btn.textContent;

    try {
        await navigator.clipboard.writeText(url);
        btn.textContent = 'Link copied';
    } catch {
        // Clipboard API needs a secure context and permission; fall back to
        // showing the URL so the link is never simply unavailable.
        window.prompt('Copy this link:', url);
        return;
    }
    setTimeout(() => { btn.textContent = original; }, 2000);
}

function downloadMarkdown() {
    if (!currentShareKey) return;
    window.location.href = `/report/${currentShareKey}.md`;
}
/* ---------- Daily capacity ---------- */

// Said before anyone types rather than after they have waited three minutes.
// The number is deliberately the only thing this endpoint returns.
function humaniseReset(seconds) {
    if (seconds == null) return 'tomorrow';
    const h = Math.floor(seconds / 3600);
    if (h >= 2) return `in about ${h} hours`;
    const m = Math.max(1, Math.floor(seconds / 60));
    return `in about ${m} minutes`;
}

async function loadCapacity() {
    const el = document.getElementById('capacity');
    if (!el) return;
    let data;
    try {
        const r = await fetch('/capacity');
        if (!r.ok) return;
        data = await r.json();
    } catch {
        return;  // Not knowing the number is no reason to say anything wrong.
    }

    const n = data.scouts_left;
    el.classList.remove('hidden', 'empty');
    if (n > 0) {
        el.innerHTML = `<strong>${n}</strong> fresh ${n === 1 ? 'report' : 'reports'} left today`
            + ' &middot; saved reports below are always free';
    } else {
        el.classList.add('empty');
        el.innerHTML = 'Today&rsquo;s fresh reports are used up &mdash; resets '
            + `${humaniseReset(data.resets_in_seconds)}. Saved reports below still work.`;
    }
}

// A spent search plan is a different problem from a spent AI quota: it
// resets monthly rather than daily, and no amount of waiting until tomorrow
// fixes it. Saying so is the difference between a useful message and a
// pointless retry.
function showSearchQuotaExhausted() {
    const el = document.getElementById('error');
    const msg = document.getElementById('error-message');
    if (!el || !msg) return;
    msg.innerHTML =
        '<strong>The monthly search allowance is used up.</strong><br>'
        + 'Research needs web search, and this month&rsquo;s allowance is spent. '
        + 'It resets at the start of next month. Reports already saved below '
        + 'still open instantly and cost nothing.';
    el.classList.remove('hidden');
}

// Google's own capacity, not this project's allowance. Worth saying plainly:
// unlike a spent quota, this is genuinely worth retrying soon, and the
// research completed before the failure is checkpointed, so a retry is
// usually one call rather than the whole run again.
function showModelOverloaded() {
    const el = document.getElementById('error');
    const msg = document.getElementById('error-message');
    if (!el || !msg) return;
    msg.innerHTML =
        '<strong>Google&rsquo;s AI service is briefly overloaded.</strong><br>'
        + 'This is on their end, not a quota running out, and it usually '
        + 'clears within minutes. Most of this research already completed and '
        + 'is saved, so trying the same search again should be quick.';
    el.classList.remove('hidden');
}

function showQuotaExhausted() {
    const el = document.getElementById('error');
    const msg = document.getElementById('error-message');
    if (!el || !msg) return;
    msg.innerHTML =
        '<strong>Today&rsquo;s research budget is spent.</strong><br>'
        + 'This runs on a free tier that allows about three fresh companies a day, '
        + 'shared by everyone using the site. It resets overnight. '
        + 'Any report already saved below still opens instantly and costs nothing.';
    el.classList.remove('hidden');
}

/* ---------- Recent scouts ---------- */

async function loadRecent() {
    let data;
    try {
        const r = await fetch('/recent');
        if (!r.ok) return;
        data = await r.json();
    } catch {
        return;  // A missing recent list is not worth an error on screen.
    }

    const items = (data && data.recent) || [];
    if (!items.length) return;

    const list = document.getElementById('recent-list');
    const wrap = document.getElementById('recent');
    if (!list || !wrap) return;

    // A row per company: name, the two scores, the verdict, and a way in.
    // Scores are right-aligned and tabular so the column reads as a column.
    list.innerHTML = items.map(item => `
        <a class="recent-card" href="/r/${encodeURIComponent(item.key)}">
            <span>
                <span class="recent-name">${escapeHtml(item.name || item.key)}</span>
                ${item.country ? `<br><span class="recent-country">${escapeHtml(item.country)}</span>` : ''}
            </span>
            <span class="recent-score">${item.interest != null ? escapeHtml(item.interest) : '&mdash;'}</span>
            <span class="recent-score">${item.reach != null ? escapeHtml(item.reach) : '&mdash;'}</span>
            <span class="recent-verdict">${escapeHtml(item.verdict || '')}</span>
            <span class="recent-open">Open &rarr;</span>
        </a>
    `).join('');

    wrap.classList.remove('hidden');
}
// A /r/{key} URL should load that saved report directly.
async function loadSharedReport() {
    const match = window.location.pathname.match(/^\/r\/([a-z0-9-]+)$/);
    if (!match) return;

    showLoading();
    document.getElementById('loading-status').textContent = 'Loading saved report...';
    try {
        const response = await fetch(`/report/${match[1]}`);
        if (!response.ok) {
            throw new Error(
                response.status === 404
                    ? 'That report has expired or was not found. Try scouting the company again.'
                    : 'Could not load that report.'
            );
        }
        const data = await response.json();
        currentBrief = data.brief;
        currentShareKey = data.share_key || match[1];
        renderBrief(data.brief);
        hideLoading();
        showResults();
    } catch (err) {
        hideLoading();
        showError(err.message);
    }
}

loadSharedReport();

// Only worth showing on the home page; a shared report replaces this view.
if (!/^\/r\//.test(window.location.pathname)) {
    loadPipelineStages();
    loadRecent();
    loadCapacity();
    // Two cards now point at the search box rather than one, so bind all of
    // them rather than only the first match.
    document.querySelectorAll('[data-focus-search]').forEach(el => {
        el.addEventListener('click', () => {
            document.getElementById('company-input')?.focus();
        });
    });
}
