import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const pageFiles = [
  'intake/IntakePage.vue', 'data-entry/DataEntryPage.vue', 'instruments/InstrumentsPage.vue',
  'results/ResultsPage.vue', 'reports/ReportsPage.vue', 'audit/AuditPage.vue',
  'users/UsersPage.vue', 'settings/SettingsPage.vue', 'about/AboutPage.vue',
];

describe('page sections', () => {
  it.each(pageFiles)('%s keeps the active class bound to the router state', file => {
    const source = readFileSync(resolve(process.cwd(), 'src/features', file), 'utf8');
    // A hardcoded `page active` would pin that page on top of every other tab.
    expect(source).not.toMatch(/class="page[^"]*active/);
    expect(source).toMatch(/class="page"/);
  });
});
