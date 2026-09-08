import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import EntryGrid from '../EntryGrid.vue';
import DataEntryPage from '../DataEntryPage.vue';
import InstrumentsPage from '../../instruments/InstrumentsPage.vue';
import { useEntryDrafts } from '../use-entry-drafts';
import { app, markDirty, requestMock, uploadMock } from './core-stub';
import { deferred, detail, meta } from './fixtures';
vi.mock('../../../api/client', () => import('./core-stub'));
vi.mock('../../../app/state', () => import('./core-stub'));
vi.mock('../../../app/dialogs', () => import('./core-stub'));
beforeEach(() => { requestMock.mockReset(); app.currentSampleId = null; app.page = 'data'; app.refreshRevision = 0; app.meta = meta; });
afterEach(() => { vi.useRealTimers(); });
describe('Vue-bound entry and instrument pages', () => {
  it('pastes into bound readings, with readonly preventing paste/downfill writes', async () => {
    requestMock.mockResolvedValue({ id: 10 });
    const store = useEntryDrafts(vi.fn()), draft = store.install(detail());
    const wrapper = mount(EntryGrid, { props: { store, draft, meta, readonly: false } });
    await wrapper.get('[data-row="0"][data-col="3"]').trigger('mousedown', { button: 0 });
    await wrapper.get('table').trigger('paste', { clipboardData: { getData: () => '1\n2\n' } });
    await flushPromises(); expect(draft.tasks.map(task => task.readings[0]?.raw)).toEqual(['1', '2']);
    await wrapper.setProps({ readonly: true }); requestMock.mockClear();
    await wrapper.get('table').trigger('paste', { clipboardData: { getData: () => '7\n8' } });
    await wrapper.get('[data-row="1"][data-col="3"]').trigger('mousedown', { button: 0, shiftKey: true });
    await wrapper.get('table').trigger('keydown', { key: 'd', ctrlKey: true });
    expect(draft.tasks.map(task => task.readings[0]?.raw)).toEqual(['1', '2']); expect(requestMock).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('leaves single-value paste and copy in a focused auxiliary input to the browser', async () => {
    const store = useEntryDrafts(vi.fn()), draft = store.install(detail());
    const wrapper = mount(EntryGrid, { props: { store, draft, meta, readonly: false } });
    await wrapper.get('[data-row="0"][data-col="3"]').trigger('mousedown', { button: 0 });
    const input = wrapper.get('.aux-std').element;
    const paste = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(paste, 'clipboardData', { value: { getData: () => '12' } });
    input.dispatchEvent(paste);
    const copy = new Event('copy', { bubbles: true, cancelable: true });
    Object.defineProperty(copy, 'clipboardData', { value: { setData: vi.fn() } });
    input.dispatchEvent(copy);
    expect(paste.defaultPrevented).toBe(false); expect(copy.defaultPrevented).toBe(false);
    expect(draft.tasks[0]?.readings[0]?.raw).toBe(''); expect(requestMock).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it('uses keyboard-focused cells rather than a stale mouse selection for arrow navigation', async () => {
    const store = useEntryDrafts(vi.fn()), draft = store.install(detail());
    const wrapper = mount(EntryGrid, { props: { store, draft, meta, readonly: false } });
    await wrapper.get('[data-row="0"][data-col="0"]').trigger('mousedown', { button: 0 });
    await wrapper.get('[data-row="1"] .rd-raw').trigger('keydown', { key: 'ArrowLeft' });
    expect(wrapper.get('[data-row="1"][data-col="2"]').classes()).toContain('active'); wrapper.unmount();
  });
  it('keeps a dirty input across revision refresh, but immediately honors server locks', async () => {
    let data = detail();
    requestMock.mockImplementation(async url => url === '/api/meta' ? meta : url.includes('/api/xrf/') ? { analyses: [], targets: [] } : structuredClone(data));
    app.currentSampleId = 1;
    const wrapper = mount(DataEntryPage); await flushPromises();
    const input = wrapper.get<HTMLInputElement>('.rd-raw'); input.element.value = '12'; await input.trigger('input');
    data = detail(); data.sample.status = 'reviewed'; app.refreshRevision++;
    await flushPromises();
    expect(wrapper.get<HTMLInputElement>('.rd-raw').element.value).toBe('12');
    expect(wrapper.get<HTMLInputElement>('.rd-raw').element.disabled).toBe(true);
    wrapper.unmount();
  });
  it('renders special fields and never allows formula inputs to be edited', async () => {
    const data = detail(); data.sample.workflow_type = 'special'; data.special = { method_name: '水分', instrument: '天平', status: 'pending', raw_data: { m: 1 }, calculated_data: { result: 2 }, schema: { title: '水分分析', groups: [{ name: '称量', fields: [{ key: 'm', label: '质量', type: 'number', required: true }, { key: 'result', label: '结果', formula: 'm*2', unit: '%' }] }] } };
    requestMock.mockImplementation(async url => url === '/api/meta' ? meta : url.includes('/api/xrf/') ? { analyses: [], targets: [] } : structuredClone(data));
    app.currentSampleId = 1; const wrapper = mount(DataEntryPage); await flushPromises();
    expect(wrapper.get<HTMLInputElement>('[data-key="result"]').element.disabled).toBe(true);
    expect(wrapper.get<HTMLInputElement>('[data-key="m"]').element.disabled).toBe(false);
    wrapper.unmount();
  });
  it('blocks feature navigation on 428 and saves the newest edit before retrying navigation', async () => {
    let denied = true;
    requestMock.mockImplementation(async (url, options) => {
      if (options?.method) { if (denied) throw Object.assign(new Error('authorization required'), { status: 428 }); return { id: 42 }; }
      return url === '/api/meta' ? meta : url.includes('/api/xrf/') ? { analyses: [], targets: [] } : detail();
    });
    app.currentSampleId = 1; const wrapper = mount(DataEntryPage); await flushPromises();
    const input = wrapper.get<HTMLInputElement>('.rd-raw'); input.element.value = '12'; await input.trigger('input');
    await wrapper.get('#d-view-report').trigger('click'); await flushPromises();
    expect(app.page).toBe('data'); expect(input.element.value).toBe('12'); expect(markDirty).toHaveBeenCalledWith('data:1', true);
    denied = false; input.element.value = '13'; await input.trigger('input');
    await wrapper.get('#d-view-report').trigger('click'); await flushPromises();
    expect(app.page).toBe('results'); expect(requestMock.mock.calls.find(([, options]) => options?.method === 'PUT')?.[1]?.body).toMatchObject({ raw: 13 });
    expect(markDirty).toHaveBeenLastCalledWith('data:1', false); wrapper.unmount();
  });
  it('locks inputs and rejects duplicate status clicks while flushing', async () => {
    const create = deferred<{ id: number }>(); vi.spyOn(window, 'confirm').mockReturnValue(true);
    requestMock.mockImplementation(async (url, options) => {
      if (url === '/api/readings') return create.promise;
      if (options?.method) return {};
      return url === '/api/meta' ? meta : url.includes('/api/xrf/') ? { analyses: [], targets: [] } : detail();
    });
    app.currentSampleId = 1; const wrapper = mount(DataEntryPage); await flushPromises();
    const input = wrapper.get<HTMLInputElement>('.rd-raw'); input.element.value = '12'; await input.trigger('input');
    const button = wrapper.get('[data-status="queued"]'); await button.trigger('click'); await button.trigger('click');
    expect(input.element.disabled).toBe(true); expect(markDirty).toHaveBeenCalledWith('data:1', true);
    create.resolve({ id: 42 }); await flushPromises();
    expect(requestMock.mock.calls.filter(([url]) => url.endsWith('/status'))).toHaveLength(1); wrapper.unmount();
  });
  it('preserves the clean snapshot and releases the busy guard on Excel authorization rejection', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true); uploadMock.mockRejectedValueOnce(Object.assign(new Error('authorization required'), { status: 428 }));
    requestMock.mockImplementation(async url => url === '/api/meta' ? meta : url.includes('/api/xrf/') ? { analyses: [], targets: [] } : detail());
    app.currentSampleId = 1; const wrapper = mount(DataEntryPage); await flushPromises();
    const file = wrapper.get<HTMLInputElement>('#d-excel-file'); Object.defineProperty(file.element, 'files', { value: [new File(['sheet'], 'data.xlsx')] });
    await file.trigger('change'); await flushPromises();
    expect(wrapper.findAll('.rd-raw')).toHaveLength(2); expect(wrapper.get<HTMLButtonElement>('#d-excel-import').element.disabled).toBe(false);
    expect(markDirty).toHaveBeenCalledWith('data:1', true); expect(markDirty).toHaveBeenLastCalledWith('data:1', false); wrapper.unmount();
  });
  it('preserves expanded instrument history and filter bindings during polling', async () => {
    vi.useFakeTimers(); app.page = 'instrument';
    requestMock.mockResolvedValue({ client: { online: false, state: 'reading' }, standard_clients: [], page: 1, pages: 1, total: 1, scans: [{ id: 1, kind: 'uq', sample_name: 'S1', external_id: 'E1', values: [{ id: 1, name: 'Fe', value: 12.34567, use_report: 1 }], value_count: 1, top_values: ['Fe 12.346%'] }] });
    const wrapper = mount(InstrumentsPage); await flushPromises();
    expect(wrapper.get('.instrument-state').text()).toBe('离线'); await wrapper.get('.xrf-scan-row').trigger('click');
    await wrapper.get('#xrf-scan-search').setValue('Fe'); await vi.advanceTimersByTimeAsync(250); await flushPromises();
    await vi.advanceTimersByTimeAsync(2000); await flushPromises();
    expect(wrapper.get('.xrf-scan-row').attributes('aria-expanded')).toBe('true');
    expect(wrapper.get<HTMLInputElement>('#xrf-scan-search').element.value).toBe('Fe');
    expect(wrapper.get('.xrf-result-list').text()).toContain('12.346%'); wrapper.unmount();
  });
});
