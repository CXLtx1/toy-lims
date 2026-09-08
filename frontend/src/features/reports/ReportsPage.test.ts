import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import ReportsPage from './ReportsPage.vue';
import { featureMeta, reportFixture } from './test-fixtures';
import type { Report } from './model';

const mocks = vi.hoisted(() => ({
  request: vi.fn<(url: string, options?: { method?: string; body?: unknown; signal?: AbortSignal }) => Promise<unknown>>(),
  download: vi.fn(), error: vi.fn(), dirty: vi.fn(),
  state: { page: 'report', currentSampleId: null as number | null, tags: [] as string[], refreshRevision: 0, meta: null },
}));
vi.mock('../../api/client', () => ({ request: mocks.request, download: mocks.download }));
vi.mock('../../app/state', () => ({ useAppState: () => mocks.state, markDirty: mocks.dirty, navigate: vi.fn(), refreshMeta: vi.fn() }));
vi.mock('../../app/dialogs', () => ({ showError: mocks.error }));

let data: Report[];
let wrapper: ReturnType<typeof mount> | undefined;
beforeEach(() => {
  vi.clearAllMocks();
  mocks.state = reactive({ page: 'report', currentSampleId: null, tags: [], refreshRevision: 0, meta: null });
  data = [reportFixture(1), reportFixture(2)];
  mocks.request.mockImplementation(async (url, options) => {
    if (options?.method) return { ok: true };
    if (url === '/api/meta') return structuredClone(featureMeta);
    if (url.startsWith('/api/samples?')) return { rows: data.map(report => structuredClone(report.sample)), total: data.length };
    const report = data.find(item => url === `/api/report/${item.sample.id}`);
    if (report) return structuredClone(report);
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.spyOn(window, 'print').mockImplementation(() => undefined);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks(); });
async function mountAndSelect(ids = [1, 2]) {
  const page = mount(ReportsPage, { attachTo: document.body }); wrapper = page;
  await flushPromises();
  for (const id of ids) { await page.get(`#report-samples [data-sid="${id}"] input`).setValue(true); await flushPromises(); }
  return page;
}
const writes = () => mocks.request.mock.calls.filter(([, options]) => options?.method && options.method !== 'GET');

describe('report composition', () => {
  it('prints draft metadata without saving, then clears print mode afterprint', async () => {
    const page = await mountAndSelect();
    await page.get('#r-customer').setValue('Draft customer');
    expect(page.get('#final-ticket').text()).toContain('Draft customer');
    expect(page.get('#final-ticket').text()).toContain('R-1、R-2');
    await page.get('#r-print-final').trigger('click'); await flushPromises();
    expect(window.print).toHaveBeenCalledOnce();
    expect(writes()).toEqual([]);
    expect(document.body.classList.contains('print-final')).toBe(true);
    expect(document.getElementById('ticket-page-style')?.textContent).toContain('A5 portrait');
    window.dispatchEvent(new Event('afterprint'));
    expect(document.getElementById('ticket-page-style')).toBeNull();
    expect(mocks.dirty).toHaveBeenLastCalledWith('reports', true);
  });
  it('retains a failed batch draft and retries only failed sample ids', async () => {
    const page = await mountAndSelect();
    const defaultRequest = mocks.request.getMockImplementation()!;
    let failed = false;
    mocks.request.mockImplementation(async (url, options) => {
      if (url === '/api/samples/2/report-meta' && options?.method && !failed) { failed = true; throw new Error('connection lost'); }
      return defaultRequest(url, options);
    });
    await page.get('#r-customer').setValue('Batch draft');
    await page.get('#r-save-meta').trigger('click'); await flushPromises();
    expect(page.get('#r-meta-msg').text()).toContain('1/2');
    expect(page.get<HTMLInputElement>('#r-customer').element.value).toBe('Batch draft');
    expect(page.get('#final-ticket').text()).toContain('Batch draft');
    await page.get('#r-save-meta').trigger('click'); await flushPromises();
    expect(writes().map(([url]) => url)).toEqual(['/api/samples/1/report-meta', '/api/samples/2/report-meta', '/api/samples/2/report-meta']);
    expect(mocks.dirty).toHaveBeenLastCalledWith('reports', false);
  });
  it('preserves selected order across pages and metadata across clean-only refresh', async () => {
    const page = await mountAndSelect();
    await page.get('#r-report-no').setValue('DRAFT');
    const requestsBefore = mocks.request.mock.calls.length;
    mocks.state.refreshRevision++; await flushPromises();
    expect(mocks.request).toHaveBeenCalledTimes(requestsBefore);
    await page.get('#report-samples [data-sid="2"] [data-step="-1"]').trigger('click'); await flushPromises();
    expect(page.findAll('#r-table .report-sample-group').map(row => row.attributes('data-sid'))).toEqual(['2', '1']);
    await page.get('#report-search').setValue('different page'); await flushPromises();
    expect(page.get<HTMLInputElement>('#r-report-no').element.value).toBe('DRAFT');
    expect(page.findAll('#report-samples input:checked')).toHaveLength(2);
    expect(writes()).toEqual([]);
  });
  it('blocks mixed water batches and a sample that loses reviewed status before print', async () => {
    data[1]!.sample.is_water_quality = 1;
    const page = await mountAndSelect();
    expect(page.get<HTMLButtonElement>('#r-print-final').element.disabled).toBe(true);
    await page.get('#report-samples [data-sid="2"] input').setValue(false); await flushPromises();
    data[0]!.sample.status = 'completed';
    await page.get('#r-print-raw').trigger('click'); await flushPromises();
    expect(window.print).not.toHaveBeenCalled();
    expect(writes()).toEqual([]);
    expect(page.get<HTMLButtonElement>('#r-print-raw').element.disabled).toBe(true);
    expect(mocks.error).toHaveBeenCalled();
  });
  it('exports saved Excel explicitly without persisting preview metadata', async () => {
    const page = await mountAndSelect([1]);
    await page.get('#r-customer').setValue('Unsaved');
    await page.get('#r-excel-export').trigger('click'); await flushPromises();
    expect(mocks.download).toHaveBeenCalledWith('/api/excel/reports/1');
    expect(writes()).toEqual([]);
  });
  it('sends complete endpoint payloads without replacing untouched per-sample metadata', async () => {
    data[1]!.sample.report_profile_id = 7;
    const page = await mountAndSelect();
    await page.get('#r-customer').setValue(' Shared customer ');
    data[1]!.sample.analyst = 'New server analyst';
    await page.get('#r-save-meta').trigger('click'); await flushPromises();
    expect(writes().map(([, options]) => options?.body)).toEqual([
      { report_profile_id: null, customer: 'Shared customer', report_no: 'R-1', analysis_date: '2026-09-08', analyst: 'Analyst 1' },
      { report_profile_id: 7, customer: 'Shared customer', report_no: 'R-2', analysis_date: '2026-09-08', analyst: 'New server analyst' },
    ]);
    expect(page.get('#final-ticket').text()).toContain('R-1、R-2');
    expect(page.get('#final-ticket').text()).toContain('New server analyst');
  });
  it('does not overwrite a dirty-field conflict even after a read-only print refresh', async () => {
    const page = await mountAndSelect([1]);
    await page.get('#r-customer').setValue('My draft');
    data[0]!.sample.customer = 'Other operator';
    await page.get('#r-print-raw').trigger('click'); await flushPromises();
    expect(window.print).toHaveBeenCalledOnce();
    expect(document.getElementById('ticket-page-style')?.textContent).toContain('A4 landscape');
    await page.get('#r-save-meta').trigger('click'); await flushPromises();
    expect(writes()).toEqual([]);
    expect(page.get('#r-meta-msg').text()).toContain('0/1');
    expect(page.get<HTMLInputElement>('#r-customer').element.value).toBe('My draft');
  });
  it('keeps a failed id pending when a different sample is deselected', async () => {
    data.push(reportFixture(3));
    const page = await mountAndSelect([1, 2, 3]);
    const defaultRequest = mocks.request.getMockImplementation()!;
    mocks.request.mockImplementation(async (url, options) => {
      if (url === '/api/samples/2/report-meta' && options?.method) return { ok: false, error: 'Denied' };
      return defaultRequest(url, options);
    });
    await page.get('#r-customer').setValue('Draft');
    await page.get('#r-save-meta').trigger('click'); await flushPromises();
    await page.get('#report-samples [data-sid="3"] input').setValue(false); await flushPromises();
    mocks.request.mockImplementation(defaultRequest);
    await page.get('#r-save-meta').trigger('click'); await flushPromises();
    expect(writes().map(([url]) => url)).toEqual(['/api/samples/1/report-meta', '/api/samples/2/report-meta', '/api/samples/3/report-meta', '/api/samples/2/report-meta']);
  });
  it('reverts a rejected print exclusion and preserves metadata while arranging', async () => {
    data[0]!.sample.report_excludes = '["m:historic"]';
    const page = await mountAndSelect([1]);
    const defaultRequest = mocks.request.getMockImplementation()!;
    mocks.request.mockImplementation(async (url, options) => options?.method ? { ok: false, error: 'Rejected' } : defaultRequest(url, options));
    await page.get('#r-customer').setValue('Unsaved draft');
    await page.get('#r-table .print-use').setValue(false); await flushPromises();
    expect(page.get<HTMLInputElement>('#r-table .print-use').element.checked).toBe(true);
    expect(page.get<HTMLInputElement>('#r-customer').element.value).toBe('Unsaved draft');
    expect(writes()[0]?.[1]?.body).toEqual({ excludes: ['a:2', 'm:historic', 'a:1'] });
    expect(mocks.error).toHaveBeenCalled();
  });
  it('ignores an obsolete search response that does not honor abort', async () => {
    const page = await mountAndSelect([]);
    const defaultRequest = mocks.request.getMockImplementation()!;
    let finish: ((value: unknown) => void) | undefined;
    mocks.request.mockImplementation((url, options) => {
      if (url.includes('q=old')) return new Promise(resolve => { finish = resolve; });
      if (url.includes('q=new')) return Promise.resolve({ rows: [reportFixture(8).sample], total: 1 });
      return defaultRequest(url, options);
    });
    await page.get('#report-search').setValue('old');
    await page.get('#report-search').setValue('new'); await flushPromises();
    finish?.({ rows: [reportFixture(9).sample], total: 1 }); await flushPromises();
    expect(page.find('#report-samples [data-sid="8"]').exists()).toBe(true);
    expect(page.find('#report-samples [data-sid="9"]').exists()).toBe(false);
  });
  it('does not print or continue a batch save after unmount', async () => {
    const page = await mountAndSelect();
    await page.get('#r-customer').setValue('Draft');
    let finish: ((value: unknown) => void) | undefined;
    const defaultRequest = mocks.request.getMockImplementation()!;
    mocks.request.mockImplementation((url, options) => {
      if (url === '/api/samples/1/report-meta') return new Promise(resolve => { finish = resolve; });
      return defaultRequest(url, options);
    });
    await page.get('#r-save-meta').trigger('click'); await flushPromises();
    page.unmount(); wrapper = undefined;
    finish?.({ ok: true }); await flushPromises();
    expect(writes().map(([url]) => url)).toEqual(['/api/samples/1/report-meta']);
    expect(window.print).not.toHaveBeenCalled();
  });
  it('keeps a last selected sample visibly checked when draft discard is cancelled', async () => {
    const page = await mountAndSelect([1]);
    await page.get('#r-customer').setValue('Keep draft');
    vi.mocked(window.confirm).mockReturnValue(false);
    await page.get('#report-samples [data-sid="1"] input').setValue(false); await flushPromises();
    expect(page.get<HTMLInputElement>('#report-samples [data-sid="1"] input').element.checked).toBe(true);
    expect(page.get<HTMLInputElement>('#r-customer').element.value).toBe('Keep draft');
  });
});
