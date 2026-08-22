/* The "what's changed" panel. Its content lives in changelog-data.js. */

/* ---------- Changelog ---------- */

function renderChangelog() {
    const body = document.getElementById('changelog-body');
    if (!body || typeof CHANGELOG === 'undefined') return;

    body.innerHTML = CHANGELOG.map(entry => `
        <div class="changelog-entry">
            <div class="changelog-version">
                <strong>v${escapeHtml(entry.version)}</strong>
                <span class="changelog-date">${escapeHtml(entry.date)}</span>
            </div>
            <ul>
                ${entry.changes.map(c => `<li>${escapeHtml(c)}</li>`).join('')}
            </ul>
        </div>
    `).join('');
}

function openChangelog() {
    renderChangelog();
    document.getElementById('changelog-panel')?.classList.remove('hidden');
    document.getElementById('changelog-backdrop')?.classList.remove('hidden');
    document.getElementById('changelog-toggle')?.setAttribute('aria-expanded', 'true');
}

function closeChangelog() {
    document.getElementById('changelog-panel')?.classList.add('hidden');
    document.getElementById('changelog-backdrop')?.classList.add('hidden');
    document.getElementById('changelog-toggle')?.setAttribute('aria-expanded', 'false');
}

document.getElementById('changelog-toggle')?.addEventListener('click', () => {
    const panel = document.getElementById('changelog-panel');
    if (panel?.classList.contains('hidden')) openChangelog();
    else closeChangelog();
});
document.getElementById('changelog-close')?.addEventListener('click', closeChangelog);
document.getElementById('changelog-backdrop')?.addEventListener('click', closeChangelog);
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeChangelog();
});

if (typeof APP_VERSION !== 'undefined') {
    const label = document.getElementById('version-label');
    if (label) label.textContent = 'v' + APP_VERSION;
}
