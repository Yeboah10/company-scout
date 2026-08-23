/* Shared state and small helpers used across every other module.
 * Loaded first: everything below depends on these.
 */

let currentBrief = null;
let currentShareKey = null;
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

function verdictClass(verdict) {
    // Coloured by what the reader should do, not by the number.
    if (verdict === 'PURSUE') return 'high';
    if (verdict && verdict.startsWith('WORTH IT')) return 'worth';
    if (verdict && verdict.startsWith('WORTH WRITING')) return 'writing';
    if (verdict === 'REACHABLE BUT THIN') return 'low';
    return 'skip';
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
/* ---------- Evidence helpers ---------- */

// Dates arrive in mixed formats ("2026-03-14", "March 2026", "2026"). Anything
// unparseable sorts last rather than being guessed at.
function parseEvidenceDate(value) {
    if (!value) return null;
    const t = Date.parse(value);
    if (!Number.isNaN(t)) return t;
    const year = /^(\d{4})$/.exec(String(value).trim());
    if (year) return Date.parse(`${year[1]}-01-01`);
    return null;
}

function sortByDateDesc(items, getDate) {
    return [...items].sort((a, b) => {
        const da = parseEvidenceDate(getDate(a));
        const db = parseEvidenceDate(getDate(b));
        if (da === null && db === null) return 0;
        if (da === null) return 1;
        if (db === null) return -1;
        return db - da;
    });
}

function formatEvidenceDate(value) {
    const t = parseEvidenceDate(value);
    if (t === null) return String(value);
    const d = new Date(t);
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

async function copyText(text, btn) {
    const original = btn.textContent;
    try {
        await navigator.clipboard.writeText(text);
        btn.textContent = 'Copied';
    } catch {
        // Clipboard needs a secure context and permission; never leave the
        // user with no way to get the text.
        window.prompt('Copy this:', text);
        btn.textContent = original;
        return;
    }
    setTimeout(() => { btn.textContent = original; }, 1500);
}
function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
}

// The intro cards are a first-run explanation. Once there is something real
// on screen they are just noise above it.
function hideIntro() {
    document.getElementById('intro')?.classList.add('hidden');
    document.getElementById('examples')?.classList.add('hidden');
    document.getElementById('recent')?.classList.add('hidden');
}

function showLoading() { hideIntro(); document.getElementById('loading').classList.remove('hidden'); }
function hideLoading() { document.getElementById('loading').classList.add('hidden'); }
function showResults() { hideIntro(); document.getElementById('results').classList.remove('hidden'); }
function hideResults() { document.getElementById('results').classList.add('hidden'); }
function showError(msg) {
    document.getElementById('error-message').textContent = msg;
    document.getElementById('error').classList.remove('hidden');
}
function hideError() { document.getElementById('error').classList.add('hidden'); }
