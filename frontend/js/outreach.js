/* The outreach composer.
 *
 * Generated from the report's own evidence — no new research runs when this
 * opens. The three contact tiers each behave differently on Send, and the
 * server checks the same rule again regardless of what this UI shows: a
 * restriction enforced only here would not be a restriction.
 */

let outreachDraft = null;

function openOutreachPanel() {
    document.getElementById('outreach-panel')?.classList.remove('hidden');
    document.getElementById('outreach-backdrop')?.classList.remove('hidden');
}

function closeOutreachPanel() {
    document.getElementById('outreach-panel')?.classList.add('hidden');
    document.getElementById('outreach-backdrop')?.classList.add('hidden');
    outreachDraft = null;
}

document.getElementById('outreach-close')?.addEventListener('click', closeOutreachPanel);
document.getElementById('outreach-backdrop')?.addEventListener('click', closeOutreachPanel);

function outreachBody(html) {
    const el = document.getElementById('outreach-body');
    if (el) el.innerHTML = html;
}

async function openOutreachComposer(personName) {
    if (!currentShareKey) return;
    openOutreachPanel();
    outreachBody('<p class="section-subtitle">Drafting from this report&rsquo;s evidence&hellip;</p>');

    // Asked once per session rather than stored: this becomes the sign-off
    // name on every email sent, and a wrong name silently reused across many
    // drafts is worse than asking each time a composer opens for the first
    // time this session.
    let senderName = sessionStorage.getItem('scout-sender-name');
    if (!senderName) {
        senderName = window.prompt('Your name, for the sign-off on outreach emails:', '') || '';
        if (senderName.trim()) sessionStorage.setItem('scout-sender-name', senderName.trim());
    }

    let data;
    try {
        const r = await fetch('/outreach/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                share_key: currentShareKey,
                person_name: personName,
                sender_name: senderName,
            }),
        });
        data = await r.json();
    } catch {
        outreachBody('<p class="section-subtitle">Could not reach the server. Try again.</p>');
        return;
    }

    if (!data.ok) {
        outreachBody(`<p class="section-subtitle">${esc(data.reason || 'Could not draft outreach for this person.')}</p>`);
        return;
    }

    outreachDraft = data;
    renderOutreachDraft();
}

function tierNote(tier) {
    if (tier === 'found') {
        return '<p class="outreach-tier-note found">Published address, confirmed for this person. Sends on one click.</p>';
    }
    return '<p class="outreach-tier-note inferred">This address is inferred, not confirmed — built from a pattern seen '
         + 'at this company, not published for this person specifically. You will be asked to confirm before it sends.</p>';
}

function renderOutreachDraft() {
    const d = outreachDraft;
    if (!d) return;

    document.getElementById('outreach-title').textContent = `Outreach — ${d.person_name}`;

    outreachBody(`
        ${tierNote(d.tier)}
        <div class="field">
            <label class="login-label" for="outreach-to">To</label>
            <input class="login-input" id="outreach-to" value="${esc(d.email)}" readonly>
        </div>
        <div class="field">
            <label class="login-label" for="outreach-subject">Subject</label>
            <input class="login-input" id="outreach-subject" value="${esc(d.subject)}">
        </div>
        <div class="field">
            <label class="login-label" for="outreach-message">Message</label>
            <textarea class="login-input outreach-textarea" id="outreach-message" rows="10">${esc(d.body)}</textarea>
        </div>

        <details class="outreach-evidence">
            <summary>Why this email &mdash; ${d.evidence.length} claim(s) used</summary>
            <ul>
                ${d.evidence.map(e => `<li>${esc(e.statement)}${e.source ? ` &mdash; <a href="${esc(e.source)}" target="_blank" rel="noopener">source</a>` : ''}</li>`).join('')}
            </ul>
        </details>

        <p id="outreach-status" class="outreach-status hidden"></p>

        <div class="outreach-actions">
            <button class="download-btn" type="button" id="outreach-regenerate">Regenerate</button>
            <button class="scout-btn" type="button" id="outreach-send">
                ${d.tier === 'found' ? 'Send' : 'Review &amp; send'}
            </button>
        </div>
    `);

    document.getElementById('outreach-regenerate')?.addEventListener('click', () => {
        openOutreachComposer(d.person_name);
    });
    document.getElementById('outreach-send')?.addEventListener('click', handleOutreachSend);
}

async function handleOutreachSend() {
    const d = outreachDraft;
    if (!d || !d.draft_id) {
        setOutreachStatus('This draft was not saved, so it cannot be sent. Regenerate and try again.', true);
        return;
    }

    const subject = document.getElementById('outreach-subject').value;
    const body = document.getElementById('outreach-message').value;

    // The inferred tier gets one more explicit, human-readable checkpoint —
    // a confirm() dialog, not a silent flag — because sending a guessed
    // address to a real person is the single most damaging thing this
    // feature could do if it went out on autopilot.
    let confirmedInferred = false;
    if (d.tier === 'inferred') {
        confirmedInferred = window.confirm(
            `${d.email} is an inferred address, not a confirmed one — it may reach the wrong person. Send anyway?`
        );
        if (!confirmedInferred) return;
    }

    setOutreachStatus('Sending…', false);
    try {
        const r = await fetch(`/outreach/${d.draft_id}/send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subject, body_text: body, confirmed_inferred: confirmedInferred }),
        });
        const result = await r.json();
        if (result.ok) {
            setOutreachStatus('Sent.', false);
            document.getElementById('outreach-send')?.setAttribute('disabled', 'true');
        } else {
            setOutreachStatus(result.reason || 'Could not send.', true);
        }
    } catch {
        setOutreachStatus('Could not reach the server. Nothing was sent.', true);
    }
}

function setOutreachStatus(text, isError) {
    const el = document.getElementById('outreach-status');
    if (!el) return;
    el.textContent = text;
    el.classList.remove('hidden');
    el.classList.toggle('outreach-status-error', !!isError);
}
