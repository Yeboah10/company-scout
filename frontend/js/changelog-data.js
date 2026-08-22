// Version history, newest first. Keep this honest: it is the one place a
// visitor can see what actually changed and when, so entries should describe
// what they'd notice, not the commit that caused it.
const CHANGELOG = [
    {
        version: '0.7.0',
        date: '2026-08-23',
        changes: [
            'New Contacts tab: published email addresses, likely addresses clearly marked as guesses, and LinkedIn profiles.',
            'Where a LinkedIn profile could not be found, the report says so and links you straight to a manual search.',
            'Better sources: press-release wires and scraper directories are now excluded, and African tech press is searched directly.'
        ]
    },
    {
        version: '0.6.0',
        date: '2026-08-21',
        changes: [
            'Recently scouted companies now appear on the home page — one click to reopen a report.',
            'Evidence is sorted newest first, with readable dates on every claim.',
            'Copy any single claim, with its date and source, straight to your clipboard.',
            'The page now sketches the report while it loads instead of showing a bare spinner.',
            'Proper layout on phones, and shared links now show a preview card.'
        ]
    },
    {
        version: '0.5.0',
        date: '2026-08-21',
        changes: [
            'Light and dark mode, following your system setting by default.',
            'Reports now explain how evidence age changed the score.',
            'Example companies on the home page to get started faster.'
        ]
    },
    {
        version: '0.4.0',
        date: '2026-08-21',
        changes: [
            'Recency now affects the score: a company that has gone quiet for years scores lower, and the report says by how much.',
            'A report is no longer produced when no usable evidence was found — it says so instead.'
        ]
    },
    {
        version: '0.3.0',
        date: '2026-08-21',
        changes: [
            'Research now runs in the background, so long scouts no longer time out and fail.',
            'Progress shows the stage actually running instead of a guess.',
            'When the daily research quota runs out, the page explains that plainly.'
        ]
    },
    {
        version: '0.2.0',
        date: '2026-08-21',
        changes: [
            'Shareable report links, and reports now survive server restarts.',
            'Download a report as Markdown, or print it to PDF.',
            'Repeat lookups return instantly from cache.'
        ]
    },
    {
        version: '0.1.0',
        date: '2026-08-20',
        changes: [
            'First release: company research, strategic analysis and opportunity scoring.'
        ]
    }
];

const APP_VERSION = CHANGELOG[0].version;
