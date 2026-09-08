import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DataXrfPanel from '../../instruments/DataXrfPanel.vue';
import XrfTargetDialog from '../../instruments/XrfTargetDialog.vue';
import InstrumentsPage from '../../instruments/InstrumentsPage.vue';
import type { Monitor, Scan, XrfSample } from '../../instruments/types';
import { app, markDirty, requestMock } from './core-stub';
import { deferred, detail } from './fixtures';

vi.mock('../../../api/client', () => import('./core-stub'));
vi.mock('../../../app/state', () => import('./core-stub'));
vi.mock('../../../app/dialogs', () => import('./core-stub'));
beforeEach(() => { requestMock.mockReset(); markDirty.mockClear(); app.page = 'instrument'; });
const scan: Scan = { id: 10, kind: 'quant', sample_name: 'Scan', external_id: 'E10', values: [] };
const monitor: Monitor = { client: null, standard_clients: [], scans: [scan], page: 1, pages: 1, total: 1 };
const sample = (id: number): XrfSample => ({ sample: { ...detail(id).sample, xrf: true }, analyses: [], targets: [{ family: 'fe', target: 'Fe', include: true, allow_conversion: true }] });
const reference = { elements: [{ symbol: 'Fe', name_zh: 'Iron', atomic_number: 26 }], oxides: [{ formula: 'Fe2O3', element_symbol: 'Fe', is_conventional: true }] };

describe('XRF request and draft isolation', () => {
  it('does not render a late sample response into the newly selected sample', async () => {
    const old = deferred<XrfSample>();
    requestMock.mockImplementation(async url => url.endsWith('/1') ? old.promise : sample(2));
    const wrapper = mount(DataXrfPanel, { props: { sample: sample(1).sample, revision: 0, active: true } });
    await wrapper.setProps({ sample: sample(2).sample }); await flushPromises();
    old.resolve({ ...sample(1), analyses: [{ ...scan, values: [{ id: 1, name: 'Fe', value: 9, use_report: true }] }] }); await flushPromises();
    expect(wrapper.findAll('.xrf-value')).toHaveLength(0); wrapper.unmount();
  });
  it('does not clear the new sample search when an old assignment completes', async () => {
    const save = deferred<unknown>();
    requestMock.mockImplementation(async (url, options) => options?.method ? save.promise : url.includes('/monitor') ? monitor : sample(Number(url.split('/').at(-1))));
    const wrapper = mount(DataXrfPanel, { props: { sample: sample(1).sample, revision: 0, active: true } }); await flushPromises();
    await wrapper.get('#d-xrf-scan-search').trigger('focus'); await flushPromises();
    await wrapper.get('[data-analysis-id="10"]').trigger('click');
    expect(markDirty).toHaveBeenCalledWith('xrf-link:1', true);
    await wrapper.setProps({ sample: sample(2).sample }); await flushPromises();
    await wrapper.get('#d-xrf-scan-search').setValue('new query');
    save.resolve({}); await flushPromises();
    expect(wrapper.get<HTMLInputElement>('#d-xrf-scan-search').element.value).toBe('new query');
    expect(wrapper.emitted('changed')).toBeUndefined(); expect(markDirty).toHaveBeenLastCalledWith('xrf-link:1', false); wrapper.unmount();
  });
  it('retains target edits after 428 and saves the edited target on retry', async () => {
    let denied = true;
    requestMock.mockImplementation(async (url, options) => {
      if (options?.method) { if (denied) throw Object.assign(new Error('authorization required'), { status: 428 }); return {}; }
      return url.endsWith('/reference') ? reference : sample(1);
    });
    const wrapper = mount(XrfTargetDialog, { props: { sampleId: 1, open: true }, global: { stubs: { teleport: true } } }); await flushPromises();
    await wrapper.get('select').setValue('Fe2O3'); await wrapper.get('#xrf-target-save').trigger('click'); await flushPromises();
    expect(wrapper.get<HTMLSelectElement>('select').element.value).toBe('Fe2O3'); expect(wrapper.emitted('close')).toBeUndefined();
    expect(markDirty).toHaveBeenLastCalledWith('xrf-targets:1', true);
    denied = false; await wrapper.get('#xrf-target-save').trigger('click'); await flushPromises();
    expect(requestMock.mock.calls.at(-1)?.[1]?.body).toMatchObject({ targets: [{ target: 'Fe2O3' }] });
    expect(wrapper.emitted('saved')).toEqual([[1]]); expect(markDirty).toHaveBeenLastCalledWith('xrf-targets:1', false); wrapper.unmount();
  });
  it('keeps target drafts per sample instead of showing or saving the previous sample rows', async () => {
    requestMock.mockImplementation(async (url, options) => options?.method ? {} : url.endsWith('/reference') ? reference : sample(Number(url.split('/').at(-1))));
    const wrapper = mount(XrfTargetDialog, { props: { sampleId: 1, open: true }, global: { stubs: { teleport: true } } }); await flushPromises();
    await wrapper.get('select').setValue('Fe2O3');
    await wrapper.setProps({ sampleId: 2 }); await flushPromises();
    expect(wrapper.get<HTMLSelectElement>('select').element.value).toBe('Fe');
    await wrapper.setProps({ sampleId: 1 }); await flushPromises();
    expect(wrapper.get<HTMLSelectElement>('select').element.value).toBe('Fe2O3');
    await wrapper.get('#xrf-target-save').trigger('click'); await flushPromises();
    expect(requestMock.mock.calls.at(-1)?.[0]).toBe('/api/xrf/samples/1/targets'); wrapper.unmount();
  });
  it('invalidates a closed target dialog load before reopening for a new sample', async () => {
    const old = deferred<XrfSample>();
    requestMock.mockImplementation(async url => url.endsWith('/reference') ? reference : url.endsWith('/1') ? old.promise : sample(2));
    const wrapper = mount(XrfTargetDialog, { props: { sampleId: 1, open: true }, global: { stubs: { teleport: true } } });
    await wrapper.setProps({ open: false }); await wrapper.setProps({ sampleId: 2, open: true }); await flushPromises();
    old.resolve({ ...sample(1), targets: [{ family: 'fe', target: 'Fe2O3', include: true }] }); await flushPromises();
    expect(wrapper.get<HTMLSelectElement>('select').element.value).toBe('Fe'); wrapper.unmount();
  });
  it('hides old assignment candidates immediately when the search changes', async () => {
    requestMock.mockImplementation(async url => url.includes('/monitor') ? monitor : [sample(1).sample]);
    const wrapper = mount(InstrumentsPage, { global: { stubs: { teleport: true } } }); await flushPromises();
    await wrapper.get('.xrf-assign-open').trigger('click'); await flushPromises();
    expect(wrapper.findAll('[data-sample-id]')).toHaveLength(1);
    await wrapper.get('#xrf-assign-sample-search').setValue('other');
    expect(wrapper.findAll('[data-sample-id]')).toHaveLength(0); wrapper.unmount();
  });
});
