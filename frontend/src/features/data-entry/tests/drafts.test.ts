import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useEntryDrafts } from '../use-entry-drafts';
import { requestMock, markDirty } from './core-stub';
import { deferred, detail } from './fixtures';
import { variables } from '../types';
vi.mock('../../../api/client', () => import('./core-stub'));
vi.mock('../../../app/state', () => import('./core-stub'));
vi.mock('../../../app/dialogs', () => import('./core-stub'));
beforeEach(() => { requestMock.mockReset(); markDirty.mockClear(); });
afterEach(() => { vi.unstubAllGlobals(); });
describe('reading drafts', () => {
  it('generates a valid client UUID when crypto.randomUUID is unavailable', () => {
    vi.stubGlobal('crypto', { getRandomValues(bytes: Uint8Array) {
      for (let index = 0; index < bytes.length; index++) bytes[index] = index;
      return bytes;
    } });
    const store = useEntryDrafts(vi.fn()), rd = store.install(detail()).tasks[0]!.readings[0]!;
    expect(rd.key).toBe('00010203-0405-4607-8809-0a0b0c0d0e0f');
  });
  it('creates exactly once while edits queue behind creation, then saves immutable values in order', async () => {
    const create = deferred<{ id: number }>(), put = deferred<unknown>();
    requestMock.mockImplementation(async (url, options) => options?.method === 'POST' ? create.promise : url.endsWith('/42') ? put.promise : {});
    const store = useEntryDrafts(vi.fn()), d = store.install(detail()), t = d.tasks[0]!, rd = t.readings[0]!;
    rd.raw = '1'; store.editReading(d, t, rd); const first = store.saveReading(d, t, rd);
    rd.raw = '2'; store.editReading(d, t, rd); void store.saveReading(d, t, rd);
    expect(requestMock).toHaveBeenCalledTimes(1);
    create.resolve({ id: 42 }); await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    put.resolve({}); await first;
    expect(requestMock.mock.calls.map(([url, options]) => [url, options?.body])).toEqual([
      ['/api/readings', { sample_analyte_id: 1, client_reading_id: rd.key }], ['/api/readings/42', { raw: 1, use_avg: true, is_final: false }], ['/api/readings/42', { raw: 2, use_avg: true, is_final: false }],
    ]);
    expect(rd.id).toBe(42); expect(store.dirty(d)).toBe(false);
  });
  it('tracks reading versions and guards later writes with expected_version', async () => {
    requestMock.mockResolvedValueOnce({ id: 42, version: 'a' }).mockResolvedValueOnce({ version: 'b' }).mockResolvedValueOnce({ version: 'c' });
    const store = useEntryDrafts(vi.fn()), d = store.install(detail()), t = d.tasks[0]!, rd = t.readings[0]!;
    rd.raw = '1'; store.editReading(d, t, rd); await store.saveReading(d, t, rd);
    rd.raw = '2'; store.editReading(d, t, rd); await store.saveReading(d, t, rd);
    expect(requestMock.mock.calls.map(([, options]) => options?.body)).toEqual([
      { sample_analyte_id: 1, client_reading_id: rd.key },
      { raw: 1, use_avg: true, is_final: false, expected_version: 'a' },
      { raw: 2, use_avg: true, is_final: false, expected_version: 'b' },
    ]);
    expect(rd.version).toBe('c');
  });
  it('retries failed PUT without creating another reading', async () => {
    requestMock.mockResolvedValueOnce({ id: 42 }).mockRejectedValueOnce(new Error('connection lost')).mockResolvedValue({});
    const store = useEntryDrafts(vi.fn()), d = store.install(detail()), t = d.tasks[0]!, rd = t.readings[0]!;
    rd.raw = '7'; store.editReading(d, t, rd); await store.saveReading(d, t, rd);
    expect(store.dirty(d)).toBe(true); expect(rd.id).toBe(42);
    await store.flush(d); expect(store.dirty(d)).toBe(false);
    expect(requestMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
  });
  it('does not blindly retry an ambiguous creation failure', async () => {
    requestMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const store = useEntryDrafts(vi.fn()), d = store.install(detail()), t = d.tasks[0]!, rd = t.readings[0]!;
    rd.raw = '8'; store.editReading(d, t, rd); await store.saveReading(d, t, rd); await store.flush(d);
    expect(requestMock).toHaveBeenCalledTimes(1); expect(rd.uncertain).toBe(true); expect(rd.raw).toBe('8'); expect(store.dirty(d)).toBe(true);
  });
  it('excludes fixed formula variables and preserves zero-valued entries', async () => {
    requestMock.mockResolvedValue({ id: 1 });
    const data = detail(); Object.assign(data.items[0]!, { itype: 'function', formula: 'c * V * M * v / m', method_constants: '{"M":65.38}' });
    expect(variables(data.items[0]!)).toEqual(['c', 'V']);
    const store = useEntryDrafts(vi.fn()), d = store.install(data), t = d.tasks[0]!, rd = t.readings[0]!;
    rd.extra = { c: '0', V: '2' }; store.editReading(d, t, rd); await store.saveReading(d, t, rd);
    expect(requestMock.mock.calls.at(-1)?.[1]?.body).toEqual({ extra: { c: 0, V: 2 }, use_avg: true, is_final: false });
  });
  it.each([401, 403, 428])('preserves edits and safely retries a definite HTTP %i creation rejection', async status => {
    requestMock.mockRejectedValueOnce(Object.assign(new Error('authorization required'), { status })).mockResolvedValueOnce({ id: 42 }).mockResolvedValue({});
    const store = useEntryDrafts(vi.fn()), d = store.install(detail()), t = d.tasks[0]!, rd = t.readings[0]!;
    rd.raw = '7'; store.editReading(d, t, rd); await store.saveReading(d, t, rd);
    expect(rd.uncertain).toBe(false); expect(rd.raw).toBe('7'); expect(store.dirty(d)).toBe(true);
    rd.raw = '8'; store.editReading(d, t, rd); await store.flush(d);
    expect(requestMock.mock.calls.at(-1)?.[1]?.body).toMatchObject({ raw: 8 });
    expect(store.dirty(d)).toBe(false);
  });
  it('treats a successful creation without an ID as ambiguous rather than creating again', async () => {
    requestMock.mockResolvedValue({ ok: true });
    const store = useEntryDrafts(vi.fn()), d = store.install(detail()), t = d.tasks[0]!, rd = t.readings[0]!;
    rd.raw = '4'; store.editReading(d, t, rd); await store.saveReading(d, t, rd); await store.flush(d);
    expect(requestMock).toHaveBeenCalledTimes(1); expect(rd.uncertain).toBe(true); expect(rd.raw).toBe('4');
  });
  it('does not discard a reading when its creation becomes ambiguous during deletion', async () => {
    const create = deferred<{ id: number }>(); requestMock.mockReturnValue(create.promise);
    const store = useEntryDrafts(vi.fn()), d = store.install(detail()), t = d.tasks[0]!, rd = t.readings[0]!;
    rd.raw = '4'; store.editReading(d, t, rd); const save = store.saveReading(d, t, rd);
    const remove = store.deleteReading(d, t, rd);
    await store.saveReading(d, t, rd);
    create.reject(new TypeError('Failed to fetch')); await save; await remove;
    expect(t.readings).toContain(rd); expect(rd.uncertain).toBe(true); expect(store.dirty(d)).toBe(true);
    expect(requestMock).toHaveBeenCalledTimes(1);
  });
  it('keeps a rejected deletion guarded even when the reading was clean', async () => {
    const data = detail(); data.items[0]!.readings = [{ id: 42, raw: 1, extra: null, use_avg: true, is_final: false, version: 'tok-1' }];
    requestMock.mockRejectedValue(Object.assign(new Error('authorization required'), { status: 428 }));
    const store = useEntryDrafts(vi.fn()), d = store.install(data), t = d.tasks[0]!, rd = t.readings[0]!;
    await store.deleteReading(d, t, rd);
    expect(t.readings).toContain(rd); expect(store.dirty(d)).toBe(true); expect(await store.flush(d)).toBe(false);
    expect(requestMock.mock.calls.at(-1)?.[1]?.body).toEqual({ expected_version: 'tok-1' });
    requestMock.mockResolvedValue({}); await store.deleteReading(d, t, rd);
    expect(requestMock.mock.calls.at(-1)?.[1]?.body).toEqual({ expected_version: 'tok-1' });
    expect(store.dirty(d)).toBe(false);
  });
  it('does not apply stale special calculations or erase zero values and cleared fields', async () => {
    const response = deferred<{ calculated_data: { result: number }; status: string }>(); requestMock.mockReturnValue(response.promise);
    const data = detail(); data.special = { method_name: 'Special', instrument: 'Balance', status: 'pending', raw_data: { m: 1, note: 'old' }, calculated_data: { result: 2 }, schema: { title: 'Special', groups: [{ name: 'Mass', fields: [{ key: 'm', label: 'Mass', type: 'number' }, { key: 'result', label: 'Result', formula: 'm*2' }] }] } };
    const store = useEntryDrafts(vi.fn()), d = store.install(data);
    d.raw.m = '0'; d.raw.note = ''; store.editSpecial(d); const save = store.saveSpecial(d);
    expect(requestMock.mock.calls[0]?.[1]?.body).toEqual({ raw_data: { m: 0 } });
    d.raw.m = '3'; store.editSpecial(d);
    response.resolve({ calculated_data: { result: 0 }, status: 'completed' }); await save;
    expect(d.detail.special?.calculated_data.result).toBe(2); expect(d.raw.m).toBe('3'); expect(store.dirty(d)).toBe(true);
  });
  it('does not send a reading update after a server lock arrives during creation', async () => {
    const create = deferred<{ id: number }>(); requestMock.mockReturnValue(create.promise);
    const store = useEntryDrafts(vi.fn()), d = store.install(detail()), t = d.tasks[0]!, rd = t.readings[0]!;
    rd.raw = '4'; store.editReading(d, t, rd); const save = store.saveReading(d, t, rd);
    d.detail.sample.status = 'reviewed'; create.resolve({ id: 42 }); await save;
    expect(requestMock).toHaveBeenCalledTimes(1); expect(rd.id).toBe(42); expect(store.dirty(d)).toBe(true);
  });
});
