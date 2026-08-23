/* The options menu in the top-right corner.
 *
 * The header used to carry a bare theme toggle and nothing else, and the
 * "How it works" page was reachable only from the footer — which is to say,
 * only by people who had already scrolled past everything it explains.
 *
 * One button, one menu. The theme control moves inside it as a labelled item
 * rather than an unexplained glyph, and the changelog joins it, so the header
 * gains a place for things to live instead of a row of competing icons.
 */

function closeMenu() {
    document.getElementById('options-menu')?.classList.add('hidden');
    document.getElementById('options-toggle')?.setAttribute('aria-expanded', 'false');
}

function openMenu() {
    document.getElementById('options-menu')?.classList.remove('hidden');
    document.getElementById('options-toggle')?.setAttribute('aria-expanded', 'true');
    paintMenuTheme();
}

// The menu says what the click will do, not what the current state is — the
// same rule the icon-only toggle followed, now in words.
function paintMenuTheme() {
    const label = document.getElementById('menu-theme-label');
    if (!label || typeof currentTheme !== 'function') return;
    label.textContent = currentTheme() === 'dark' ? 'Switch to light' : 'Switch to dark';
}

document.getElementById('options-toggle')?.addEventListener('click', (e) => {
    e.stopPropagation();
    const menu = document.getElementById('options-menu');
    if (!menu) return;
    menu.classList.contains('hidden') ? openMenu() : closeMenu();
});

document.getElementById('menu-theme')?.addEventListener('click', () => {
    if (typeof toggleTheme === 'function') toggleTheme();
    paintMenuTheme();
});

// A menu that only closes via its own button strands anyone who opened it by
// accident, so a click anywhere else and Escape both close it.
document.addEventListener('click', (e) => {
    const menu = document.getElementById('options-menu');
    if (!menu || menu.classList.contains('hidden')) return;
    if (!menu.contains(e.target)) closeMenu();
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeMenu();
});

paintMenuTheme();
