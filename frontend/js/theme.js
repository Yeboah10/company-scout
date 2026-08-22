/* Light/dark theme. The <head> script applies the saved choice before
 * first paint; this only handles the icon and switching.
 */

/* ---------- Theme ---------- */

// The <head> script has already applied any saved choice; this only decides
// which icon to show and handles switching.
function currentTheme() {
    const explicit = document.documentElement.getAttribute('data-theme');
    if (explicit) return explicit;
    return window.matchMedia('(prefers-color-scheme: light)').matches
        ? 'light'
        : 'dark';
}

function paintThemeToggle() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    // Show where the click leads, not where you already are.
    btn.textContent = currentTheme() === 'dark' ? '☀' : '☾';
}

function toggleTheme() {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try {
        localStorage.setItem('scout-theme', next);
    } catch {
        // Private mode: the choice still applies for this page view.
    }
    paintThemeToggle();
}

document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);

// Follow the OS while the visitor has expressed no preference of their own.
window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
    if (!document.documentElement.getAttribute('data-theme')) paintThemeToggle();
});

paintThemeToggle();
