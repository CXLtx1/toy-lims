import { nextTick } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Meta } from '../api/types';

vi.mock('../api/client', () => ({
  network: { writes: 0, lastWrite: 0, sessionLost: false },
  request: vi.fn(),
}));

const metadata: Meta = {
  sample_statuses: { pending: 'Pending' }, sample_tags: [{ name: 'priority', count: 2 }],
  terminal: null, current_user: null, authorized_user: null, authorization_required: true, capabilities: {},
};
let app: typeof import('./state');
let api: typeof import('../api/client');
let stopNavigation: (() => void) | undefined;

beforeEach(async () => {
  vi.resetModules();
  api = await import('../api/client');
  api.network.writes = 0;
  api.network.sessionLost = false;
  vi.mocked(api.request).mockReset();
  app = await import('./state');
  history.replaceState(null, '', '/frontend/');
  vi.spyOn(window, 'confirm').mockReturnValue(false);
});
afterEach(() => { stopNavigation?.(); stopNavigation = undefined; });

describe('dirty state and navigation', () => {
  it('shares state and tracks independent draft owners without duplicate dirty keys', () => {
    expect(app.useAppState()).toBe(app.useAppState());
    expect(app.hasUnsavedChanges()).toBe(false);
    app.markDirty('intake', true);
    app.markDirty('intake', true);
    app.markDirty('results', true);
    expect(app.useAppState().dirty.size).toBe(2);
    app.markDirty('intake', false);
    expect(app.hasUnsavedChanges()).toBe(true);
    app.markDirty('results', false);
    expect(app.hasUnsavedChanges()).toBe(false);
    api.network.writes = 1;
    expect(app.hasUnsavedChanges()).toBe(true);
    api.network.writes = 0;
    expect(app.hasUnsavedChanges()).toBe(false);
  });

  it('cancels dirty navigation without altering page, sample, drafts, or URL', () => {
    const state = app.useAppState();
    state.currentSampleId = 12;
    app.markDirty('intake', true);
    const url = location.href;
    app.navigate('results', 34);
    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(state.page).toBe('intake');
    expect(state.currentSampleId).toBe(12);
    expect([...state.dirty]).toEqual(['intake']);
    expect(location.href).toBe(url);
  });

  it('allows confirmed dirty navigation but retains the draft markers', () => {
    vi.mocked(window.confirm).mockReturnValue(true);
    app.markDirty('intake', true);
    app.navigate('data', 42);
    expect(app.useAppState()).toMatchObject({ page: 'data', currentSampleId: 42 });
    expect(app.hasUnsavedChanges()).toBe(true);
    expect([...app.useAppState().dirty]).toEqual(['intake']);
    expect(new URL(location.href).searchParams.get('sample')).toBe('42');
  });

  it('blocks context changes during writes even if a user would confirm', () => {
    vi.mocked(window.confirm).mockReturnValue(true);
    api.network.writes = 1;
    app.markDirty('intake', true);
    const url = location.href;
    app.navigate('data', 42);
    expect(app.useAppState()).toMatchObject({ page: 'intake', currentSampleId: null });
    expect(window.confirm).not.toHaveBeenCalled();
    expect(location.href).toBe(url);
  });

  it('does nothing for the current page/sample, including while dirty', () => {
    app.useAppState().currentSampleId = 12;
    app.markDirty('intake', true);
    const replace = vi.spyOn(history, 'replaceState');
    app.navigate('intake');
    app.navigate('intake', 12);
    expect(window.confirm).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  it('confirms sample-only changes on the same page', () => {
    app.useAppState().currentSampleId = 12;
    app.markDirty('intake', true);
    app.navigate('intake', 13);
    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(app.useAppState().currentSampleId).toBe(12);
    vi.mocked(window.confirm).mockReturnValue(true);
    app.navigate('intake', 13);
    expect(app.useAppState().currentSampleId).toBe(13);
  });

  it('preserves the selected sample when omitted and clears it for explicit null', () => {
    app.useAppState().currentSampleId = 12;
    app.navigate('data');
    expect(app.useAppState().currentSampleId).toBe(12);
    expect(new URL(location.href).searchParams.get('sample')).toBe('12');
    app.navigate('results', null);
    expect(app.useAppState().currentSampleId).toBeNull();
    expect(new URL(location.href).searchParams.has('sample')).toBe(false);
  });
});

describe('URL navigation', () => {
  it('reads page/sample and trims, deduplicates, and drops empty tags', () => {
    history.replaceState(null, '', '/frontend/?page=results&sample=42&tag=+urgent+&tag=urgent&tag=&tag=chemistry');
    stopNavigation = app.initializeNavigation();
    expect(app.useAppState()).toMatchObject({ page: 'results', currentSampleId: 42, tags: ['urgent', 'chemistry'] });
  });

  it.each(['', '0', '-1', '1.5', 'NaN', 'Infinity', '9007199254740992', 'abc'])('ignores invalid sample %j and unknown pages', sample => {
    history.replaceState(null, '', `/frontend/?page=unknown&sample=${sample}`);
    stopNavigation = app.initializeNavigation();
    expect(app.useAppState()).toMatchObject({ page: 'intake', currentSampleId: null });
  });

  it('defaults absent navigation parameters', () => {
    stopNavigation = app.initializeNavigation();
    expect(app.useAppState()).toMatchObject({ page: 'intake', currentSampleId: null, tags: [] });
  });

  it('replaces URL state while preserving unrelated parameters and the hash', () => {
    history.replaceState(null, '', '/frontend/?campaign=summer&tag=old#details');
    stopNavigation = app.initializeNavigation();
    app.useAppState().tags = ['A & B', 'x/y'];
    const replace = vi.spyOn(history, 'replaceState');
    const push = vi.spyOn(history, 'pushState');
    app.navigate('report', 99);
    const url = new URL(location.href);
    expect(url.pathname).toBe('/frontend/');
    expect(url.hash).toBe('#details');
    expect(url.searchParams.get('campaign')).toBe('summer');
    expect(url.searchParams.get('page')).toBe('report');
    expect(url.searchParams.get('sample')).toBe('99');
    expect(url.searchParams.getAll('tag')).toEqual(['A & B', 'x/y']);
    expect(replace).toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it('watches both tag replacement and in-place edits and removes obsolete tags', async () => {
    stopNavigation = app.initializeNavigation();
    app.useAppState().tags = ['first'];
    await nextTick();
    expect(new URL(location.href).searchParams.getAll('tag')).toEqual(['first']);
    app.useAppState().tags.push('second');
    await nextTick();
    expect(new URL(location.href).searchParams.getAll('tag')).toEqual(['first', 'second']);
    app.useAppState().tags.splice(0);
    await nextTick();
    expect(new URL(location.href).searchParams.has('tag')).toBe(false);
  });

  it('returns cleanup that stops tag URL synchronization', async () => {
    stopNavigation = app.initializeNavigation();
    stopNavigation();
    const url = location.href;
    app.useAppState().tags.push('not-synchronized');
    await nextTick();
    expect(location.href).toBe(url);
  });
});

describe('metadata and retained data', () => {
  it('loads metadata without changing selected sample or drafts', async () => {
    app.useAppState().currentSampleId = 12;
    app.markDirty('intake', true);
    vi.mocked(api.request).mockResolvedValueOnce(metadata);
    await app.refreshMeta();
    expect(api.request).toHaveBeenCalledWith('/api/meta');
    expect(app.useAppState().meta).toEqual(metadata);
    expect(app.useAppState().currentSampleId).toBe(12);
    expect(app.hasUnsavedChanges()).toBe(true);
  });

  it('does not let an older response overwrite newer metadata', async () => {
    let resolveOld!: (value: Meta) => void;
    vi.mocked(api.request).mockImplementationOnce(() => new Promise<Meta>(resolve => { resolveOld = resolve; }));
    const older = app.refreshMeta();
    const newer = { ...metadata, sample_tags: [{ name: 'new', count: 3 }] };
    vi.mocked(api.request).mockResolvedValueOnce(newer);
    await app.refreshMeta();
    resolveOld(metadata);
    await older;
    expect(app.useAppState().meta).toEqual(newer);
  });

  it('propagates a 401 without clearing loaded data or unsaved state', async () => {
    const state = app.useAppState();
    state.meta = metadata;
    state.currentSampleId = 12;
    state.currentSample = { id: 12, name: 'Draft sample', category: 'ore', lims_no: 'L12', status: 'pending' };
    state.tags = ['urgent'];
    app.markDirty('intake', true);
    const error = Object.assign(new Error('session expired'), { status: 401 });
    vi.mocked(api.request).mockRejectedValueOnce(error);
    await expect(app.refreshMeta()).rejects.toBe(error);
    expect(state.meta).toEqual(metadata);
    expect(state.currentSampleId).toBe(12);
    expect(state.currentSample?.name).toBe('Draft sample');
    expect(state.tags).toEqual(['urgent']);
    expect([...state.dirty]).toEqual(['intake']);
  });

  it.each([null, {}, { sample_statuses: 'invalid', sample_tags: [] }, { sample_statuses: {}, sample_tags: {} }])(
    'rejects malformed metadata without replacing valid data: %j', async data => {
      app.useAppState().meta = metadata;
      vi.mocked(api.request).mockResolvedValueOnce(data);
      await expect(app.refreshMeta()).rejects.toThrow();
      expect(app.useAppState().meta).toEqual(metadata);
    },
  );

  // Known state.ts validation bug: typeof null and arrays is 'object'.
  it.each([{ sample_statuses: null }, { sample_statuses: [] }])('rejects non-record sample_statuses: $sample_statuses', async ({ sample_statuses }) => {
    vi.mocked(api.request).mockResolvedValueOnce({ ...metadata, sample_statuses });
    await expect(app.refreshMeta()).rejects.toThrow();
  });
});
