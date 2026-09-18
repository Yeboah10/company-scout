/* Team notes — private annotations on a brief.
 * Loaded after report.js, before scout.js.
 */

async function loadNotes(shareKey) {
    const container = document.getElementById('notes-list');
    if (!container || !shareKey) return;
    try {
        const r = await fetch(`/notes/${shareKey}`);
        if (!r.ok) return;
        const data = await r.json();
        renderNotes(data.notes || [], container);
    } catch {
        // Notes are not critical — a failed load is not worth an error.
    }
}

function renderNotes(notesList, container) {
    if (!notesList.length) {
        container.innerHTML = '<p class="notes-empty">No notes yet. Add one below.</p>';
        return;
    }
    container.innerHTML = notesList.map(n => `
        <div class="note-card" data-note-id="${n.id}">
            <div class="note-meta">
                <span class="note-author">${escapeHtml(n.user_email)}</span>
                <span class="note-date">${formatCachedAt(n.created_at)}</span>
            </div>
            <p class="note-body">${escapeHtml(n.body)}</p>
            <button class="note-delete" onclick="deleteNote(${n.id})" title="Delete note">&times;</button>
        </div>
    `).join('');
}

async function submitNote() {
    if (!currentShareKey) return;
    const input = document.getElementById('note-input');
    if (!input) return;
    const body = input.value.trim();
    if (!body) return;

    try {
        const r = await fetch(`/notes/${currentShareKey}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ body })
        });
        if (r.status === 401) return;
        if (!r.ok) return;
        input.value = '';
        await loadNotes(currentShareKey);
    } catch {
        // Swallow — the note input stays filled so the user can retry.
    }
}

async function deleteNote(noteId) {
    try {
        const r = await fetch(`/notes/${noteId}`, { method: 'DELETE' });
        if (r.ok) await loadNotes(currentShareKey);
    } catch {
        // Swallow.
    }
}
