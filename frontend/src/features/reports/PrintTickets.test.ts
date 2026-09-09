import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createSSRApp, h } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { describe, expect, it, vi } from 'vitest';
import RawTicket from './RawTicket.vue';
import FinalTicket from './FinalTicket.vue';
import { finalRows, validateReport, waterUnit, type Report } from './model';
import { reportFixture } from './test-fixtures';

vi.mock('../../api/client', () => ({ request: vi.fn(), download: vi.fn() }));

describe('print markup', () => {
  const special = reportFixture(3);
  special.sample.workflow_type = 'special';
  special.groups = [];
  special.special = { schema: { title: '专项记录', groups: [{ name: '测量', fields: [{ key: 'zero', label: '零值', unit: 'g' }, { key: 'text', label: '文本' }, { key: 'empty', label: '空值' }] }] }, raw_data: { zero: 0, text: '<img src=x onerror=alert(1)>', empty: '' }, calculated_data: { zero: 1.25 }, method_name: '专项法', instrument: '天平' };
  const manual = reportFixture(4);
  manual.report_rows = [{ item: 'Cu', result: '<0.01', unit: '%', include: true }, { item: 'hidden', result: '9', include: false }];
  manual.manual_report = { rows: manual.report_rows, updated_by: 'Auditor', updated_at: '2026-09-08' };
  const water = reportFixture(5);
  water.sample.is_water_quality = 1;
  water.report_rows = [{ item: 'pH', result: 7.1, unit: 'ppm' }, { item: 'Cu', result: 0, unit: 'ppm' }];
  const dense = reportFixture(6);
  dense.groups[0]!.rows[0]!.readings = Array.from({ length: 25 }, (_, index) => ({ raw: index, corrected_value: index / 10, used: index % 2 === 0 }));
  dense.report_rows = Array.from({ length: 20 }, (_, index) => ({ item: `Element ${index}`, result: index / 10, unit: '%' }));
  const cases: [string, Report[]][] = [['empty', []], ['regular batch', [reportFixture(), reportFixture(2)]], ['manual', [manual]], ['water', [water]], ['water batch', [water, { ...water, sample: { ...water.sample, id: 7, name: 'S-7' } }]], ['dense', [dense]], ['mixed', [reportFixture(), water]]];
  for (const [name, reports] of cases) for (const kind of ['raw', 'final'] as const) it(`${name}: ${kind}`, async () => {
    const component = kind === 'raw' ? RawTicket : FinalTicket;
    const markup = await renderToString(createSSRApp({ render: () => h(component, { reports }) }));
    const document = new DOMParser().parseFromString(markup, 'text/html');
    const article = document.querySelector(`#${kind}-ticket`);
    expect(article).not.toBeNull();
    expect(article?.classList.contains(kind === 'raw' ? 'raw-ticket-batch' : 'final-ticket')).toBe(true);
    expect(document.querySelector('script,img,iframe,object,embed')).toBeNull();
    if (name === 'mixed' && kind === 'final') {
      expect(article?.textContent).toContain('水质样与其他样品使用不同报告票，请分开选择后打印');
    } else {
      for (const report of reports) expect(article?.textContent).toContain(report.sample.name);
    }
  });
  it('renders hostile special-record text without executable markup', async () => {
    for (const component of [RawTicket, FinalTicket]) {
      const markup = await renderToString(createSSRApp({ render: () => h(component, { reports: [special] }) }));
      const document = new DOMParser().parseFromString(markup, 'text/html');
      expect(document.querySelector('img')).toBeNull();
      expect(document.body.textContent).toContain('<img src=x onerror=alert(1)>');
    }
  });
});

describe('critical report validation', () => {
  it('rejects mismatched identities, non-finite values and malformed groups', () => {
    expect(() => validateReport(reportFixture(2), 1)).toThrow();
    const report = reportFixture();
    report.groups[0]!.rows[0]!.value = Infinity;
    expect(() => validateReport(report, 1)).toThrow();
    expect(() => validateReport({ ...reportFixture(), groups: [{ key: 'a:1' }] }, 1)).toThrow();
  });
  it('keeps zero values and honors print exclusions and water units', () => {
    const report = reportFixture();
    report.report_rows.push({ item: 'excluded', result: 0, include: false });
    expect(finalRows(validateReport(report, 1))).toHaveLength(1);
    expect(waterUnit({ item: 'pH', result: 0, unit: 'ppm' })).toBe('');
    expect(waterUnit({ item: 'Cu', result: 0, unit: 'ppm' })).toBe('mg/L');
  });
  it('rejects invalid printed readings, special values, editor counts and profiles', () => {
    const report = reportFixture();
    report.groups[0]!.rows[0]!.readings![0]!.corrected_value = NaN;
    expect(() => validateReport(report, 1)).toThrow();
    expect(() => validateReport({ ...reportFixture(), data_editors: [{ name: 'A', count: '2' }] }, 1)).toThrow();
    expect(() => validateReport({ ...reportFixture(), report_profile: {} }, 1)).toThrow();
    expect(() => validateReport({ ...reportFixture(), sample: { ...reportFixture().sample, workflow_type: 'special' }, special: {
      schema: { groups: [] }, raw_data: { value: Infinity }, calculated_data: {},
    } }, 1)).toThrow();
  });
  it('prints XRF raw values even when the scan has a method name', async () => {
    const report = reportFixture();
    report.groups[0]!.rows = [{ xrf_value_id: 12, method: 'XRF scan method', instrument: 'XRF', value: 5.5, unit: '%', readings: [{ raw: 5.5, extra: {}, used: true, corrected_value: 5.5 }] }];
    const markup = await renderToString(createSSRApp({ render: () => h(RawTicket, { reports: [report] }) }));
    const document = new DOMParser().parseFromString(markup, 'text/html');
    const cells = document.querySelectorAll('.raw-record-table tbody tr:first-child td');
    expect(cells[9]?.textContent).toBe('5.5');
    expect(cells[10]?.textContent).toBe('5.5 %');
  });
  it('fits water final wrappers inside the A5 printable width', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/features/reports/FinalTicket.vue'), 'utf8');
    expect(source).toMatch(/@media print\s*\{[\s\S]*body\.print-final #final-ticket \.water-final-pages\s*\{\s*width: 100%;/);
  });
});
