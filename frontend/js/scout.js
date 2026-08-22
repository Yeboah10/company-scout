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

    const steps = [1, 2, 3, 4, 5, 6];
    document.getElementById('step-1').classList.add('active');

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
        showError(err.message);
    } finally {
        btn.disabled = false;
        steps.forEach(s => {
            const el = document.getElementById('step-' + s);
            el.classList.remove('active', 'done');
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
    for (let s = 1; s <= 6; s++) {
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

    list.innerHTML = items.map(item => `
        <a class="recent-card" href="/r/${encodeURIComponent(item.key)}">
            <span class="recent-name">${escapeHtml(item.name || item.key)}</span>
            <span class="recent-sub">
                ${item.country ? escapeHtml(item.country) : ''}
                ${item.score != null ? `<span class="recent-score">${escapeHtml(item.score)}/10</span>` : ''}
            </span>
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
    loadRecent();
}
