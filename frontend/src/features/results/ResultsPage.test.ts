import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import ResultsPage from './ResultsPage.vue';
import { featureMeta, reportFixture } from '../reports/test-fixtures';
import type { Report } from '../reports/model';

const mocks = vi.hoisted(() => ({
  request: vi.fn<(url: string, options?: { method?: string; body?: unknown; signal?: AbortSignal }) => Promise<unknown>>(),
  download: vi.fn(), error: vi.fn(), dirty: vi.fn(),
  state: { page: 'results', currentSampleId: null as number | null, tags: [] as string[], refreshRevision: 0, meta: null },
}));
vi.mock('../../api/client', () => ({ request: mocks.request, download: mocks.download }));
vi.mock('../../app/state', () => ({ useAppState: () => mocks.state, markDirty: mocks.dirty, refreshMeta: vi.fn() }));
vi.mock('../../app/dialogs', () => ({ showError: mocks.error }));

let data: Report;
let wrapper: ReturnType<typeof mount> | undefined;
const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView');
beforeEach(() => {
  vi.clearAllMocks();
  mocks.state = reactive({ page: 'results', currentSampleId: null, tags: [], refreshRevision: 0, meta: null });
  data = reportFixture(); data.sample.status = 'completed';
  mocks.request.mockImplementation(async (url, options) => {
    if (options?.method) return { ok: true };
    if (url === '/api/meta') return structuredClone(featureMeta);
    if (url.startsWith('/api/samples?')) return { rows: [structuredClone(data.sample)], total: 1 };
    if (url === '/api/report/1') return structuredClone(data);
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  vi.spyOn(window, 'prompt').mockReturnValue('Reason');
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
});
afterEach(() => {
  wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks();
  if (originalScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScroll);
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView');
});
async function open() {
  const page = mount(ResultsPage, { attachTo: document.body }); wrapper = page;
  await flushPromises();
  await page.get('.result-row').trigger('click'); await flushPromises();
  return page;
}
async function authorize() {
  const input = document.querySelector<HTMLInputElement>('#results-authorization-password');
  if (!input) throw new Error('Authorization not shown');
  input.value = 'secret'; input.dispatchEvent(new Event('input', { bubbles: true }));
  document.querySelector('#results-authorization-form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  await flushPromises();
}
const writes = () => mocks.request.mock.calls.filter(([, options]) => options?.method);

describe('results safety', () => {
  it('restores the confirmed participation checkbox after an API rejection', async () => {
    const page = await open();
    const defaultRequest = mocks.request.getMockImplementation()!;
    mocks.request.mockImplementation(async (url, options) => options?.method ? { ok: false, error: 'Locked' } : defaultRequest(url, options));
    await page.get('.report-use').setValue(false); await flushPromises();
    expect(page.get<HTMLInputElement>('.report-use').element.checked).toBe(true);
    expect(writes()[0]).toEqual(['/api/sample-analytes/10/report-use', { method: 'PUT', body: { use: false } }]);
    expect(mocks.error).toHaveBeenCalled();
  });
  it('preserves a manual draft across list refresh and cancelled collapse', async () => {
    const page = await open();
    await page.get('.r-manual-edit').trigger('click');
    await page.get('.mr-result').setValue('0');
    const before = mocks.request.mock.calls.length;
    mocks.state.refreshRevision++; await flushPromises();
    expect(mocks.request).toHaveBeenCalledTimes(before);
    await page.get('#results-search').setValue('S-1'); await flushPromises();
    vi.mocked(window.confirm).mockReturnValue(false);
    await page.get('#results-collapse-all').trigger('click');
    expect(page.get<HTMLInputElement>('.mr-result').element.value).toBe('0');
    expect(mocks.dirty).toHaveBeenLastCalledWith('results', true);
  });
  it('requires one-shot authorization and preserves a draft after failed manual save', async () => {
    const page = await open();
    const defaultRequest = mocks.request.getMockImplementation()!;
    mocks.request.mockImplementation(async (url, options) => url === '/api/reports/1/manual' ? { ok: false, error: 'Save failed' } : defaultRequest(url, options));
    await page.get('.r-manual-edit').trigger('click');
    await page.get('.mr-result').setValue('0');
    await page.get('.r-manual-save').trigger('click'); await flushPromises();
    expect(writes()).toEqual([]);
    await authorize();
    expect(writes()[0]).toEqual(['/api/authorize', { method: 'POST', body: { password: 'secret', purpose: 'result_override' } }]);
    expect(writes()[1]?.[1]?.body).toEqual({ reason: 'Reason', rows: [{ item: 'Cu', result: '0', unit: '%', note: '自动平均', include: true }] });
    expect(page.get<HTMLInputElement>('.mr-result').element.value).toBe('0');
    expect(mocks.dirty).toHaveBeenLastCalledWith('results', true);
    await page.get('.r-manual-save').trigger('click'); await flushPromises();
    expect(document.querySelector('#results-authorization-password')).not.toBeNull();
  });
  it('does not overwrite server results changed during manual editing', async () => {
    const page = await open();
    await page.get('.r-manual-edit').trigger('click');
    await page.get('.mr-result').setValue('Draft');
    data.default_report_rows[0]!.result = 'Updated';
    await page.get('.r-manual-save').trigger('click'); await flushPromises();
    await authorize();
    expect(writes().map(([url]) => url)).toEqual(['/api/authorize']);
    expect(page.get<HTMLInputElement>('.mr-result').element.value).toBe('Draft');
    expect(mocks.error).toHaveBeenCalled();
  });
  it('does not submit a privileged mutation after its authorization component unmounts', async () => {
    const page = await open();
    await page.get('.r-manual-edit').trigger('click');
    await page.get('.r-manual-save').trigger('click'); await flushPromises();
    let finish: ((value: unknown) => void) | undefined;
    mocks.request.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    await authorize();
    page.unmount(); wrapper = undefined;
    finish?.({ ok: true }); await flushPromises();
    expect(writes().map(([url]) => url)).toEqual(['/api/authorize']);
    expect(document.body.classList.contains('authorization-open')).toBe(false);
  });
  it('keeps target editing available when all XRF targets are excluded', async () => {
    data.groups = []; data.xrf_targets = [{ family: 'fe', target: 'Fe2O3', include: false }];
    const page = await open();
    expect(page.get<HTMLButtonElement>('.xrf-target-edit').element.disabled).toBe(false);
  });
});
