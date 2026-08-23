/* The Contacts tab. Found addresses, inferred guesses and LinkedIn results
 * are rendered as visually distinct blocks and never merged.
 */

/* ---------- Contacts ---------- */

// Found and inferred addresses render in visually distinct blocks and are
// never merged into one list: a guess that looks like a confirmed address is
// how someone ends up emailing a stranger with a personalised pitch.
function renderContacts(contacts) {
    const foundEl = document.getElementById('contacts-found');
    const inferredEl = document.getElementById('contacts-inferred');
    const inferredSection = document.getElementById('contacts-inferred-section');
    const noteEl = document.getElementById('contacts-note');
    if (!foundEl) return;

    const found = (contacts && contacts.found) || [];
    const inferred = (contacts && contacts.inferred) || [];

    foundEl.innerHTML = found.length ? found.map(f => `
        <div class="card contact-card">
            <div class="card-body">
                <div class="contact-row">
                    <span class="contact-kind ${f.kind === 'role' ? 'role' : 'personal'}">${f.kind === 'role' ? 'team inbox' : 'person'}</span>
                    <a class="contact-email" href="mailto:${encodeURIComponent(f.email)}">${escapeHtml(f.email)}</a>
                    <button class="copy-claim" type="button" data-email="${escapeHtml(f.email)}">Copy</button>
                </div>
                ${f.person ? `<div class="contact-person">${escapeHtml(f.person)}</div>` : ''}
                ${f.source_url ? `<a href="${escapeHtml(f.source_url)}" target="_blank" rel="noopener" class="source-link">${escapeHtml(f.source_url)}</a>` : ''}
                ${f.observed_on ? `<div class="contact-observed">Seen on that page ${escapeHtml(f.observed_on)}</div>` : ''}
            </div>
        </div>
    `).join('') : '<p class="section-subtitle">No addresses were published on the company&rsquo;s own pages.</p>';

    if (inferred.length) {
        inferredEl.innerHTML = inferred.map(i => `
            <div class="card contact-card inferred">
                <div class="card-body">
                    <div class="contact-row">
                        <span class="contact-kind guess">guess</span>
                        <span class="contact-email">${escapeHtml(i.email)}</span>
                        <button class="copy-claim" type="button" data-email="${escapeHtml(i.email)}">Copy</button>
                    </div>
                    <div class="contact-person">${escapeHtml(i.person)} &middot; <code>${escapeHtml(i.pattern)}</code> &middot; ${escapeHtml(i.basis || '')}</div>
                    ${i.person_status && i.person_status !== 'current' ? `
                        <div class="contact-warning">${escapeHtml(i.person_tenure_note || 'Their current role is not confirmed.')}</div>
                    ` : ''}
                </div>
            </div>
        `).join('');
        inferredSection.classList.remove('hidden');
    } else {
        inferredEl.innerHTML = '';
        inferredSection.classList.add('hidden');
    }

    // "Not found" is rendered as loudly as a hit: it tells the user to go and
    // look manually rather than assume the person has no profile.
    const liEl = document.getElementById('contacts-linkedin');
    const li = (contacts && contacts.linkedin) || [];
    if (liEl) {
        liEl.innerHTML = li.length ? li.map(l => {
            const who = l.is_company_page
                ? 'Company page'
                : escapeHtml(l.person || 'Unknown') + (l.role ? ` · ${escapeHtml(l.role)}` : '');
            return l.found
                ? `<div class="card contact-card">
                       <div class="card-body">
                           <div class="contact-row">
                               <span class="contact-kind personal">found</span>
                               <span class="contact-person" style="margin:0">${who}</span>
                           </div>
                           <a href="${escapeHtml(l.url)}" target="_blank" rel="noopener" class="source-link">${escapeHtml(l.url)}</a>
                       </div>
                   </div>`
                : `<div class="card contact-card not-found">
                       <div class="card-body">
                           <div class="contact-row">
                               <span class="contact-kind missing">not found</span>
                               <span class="contact-person" style="margin:0">${who}</span>
                           </div>
                           <a href="${escapeHtml(l.search_url)}" target="_blank" rel="noopener" class="source-link">Search LinkedIn manually →</a>
                       </div>
                   </div>`;
        }).join('') : '<p class="section-subtitle">No people were identified to look up.</p>';
    }

    noteEl.textContent = (contacts && contacts.note) || '';

    document.getElementById('tab-contacts').onclick = (e) => {
        const btn = e.target.closest('.copy-claim');
        if (btn && btn.dataset.email) copyText(btn.dataset.email, btn);
    };
}
