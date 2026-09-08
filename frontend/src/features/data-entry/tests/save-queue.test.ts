import { describe, expect, it, vi } from 'vitest';
import { createSaveQueue, type SaveState } from '../save-queue';
import { deferred } from './fixtures';
const state = (): SaveState => ({ dirty: false, saving: false, error: '', savedAt: '' });
describe('immutable serialized autosave', () => {
  it('does not mutate an in-flight snapshot or clear a newer unsaved edit', async () => {
    const gate = deferred<void>(), status = state(), snapshots: { raw: number }[] = [];
    const queue = createSaveQueue(status, async (snapshot: { raw: number }) => { snapshots.push(snapshot); await gate.promise; }, vi.fn(), vi.fn());
    const payload = { raw: 1 };
    queue.edit(); const first = queue.save(payload); payload.raw = 9; queue.edit();
    gate.resolve(); await first;
    expect(snapshots).toEqual([{ raw: 1 }]); expect(status.dirty).toBe(true);
  });
  it('serializes subsequent saves and retains the last snapshot after failure', async () => {
    const gate = deferred<void>(), status = state(), calls: number[] = [];
    let fail = true;
    const queue = createSaveQueue(status, async (snapshot: number) => { calls.push(snapshot); if (snapshot === 1) await gate.promise; if (fail) throw new Error('offline'); }, vi.fn(), vi.fn());
    queue.edit(); const first = queue.save(1); queue.edit(); void queue.save(2);
    expect(calls).toEqual([1]); gate.resolve(); await first;
    expect(status.dirty).toBe(true); expect(status.error).toBe('offline');
    fail = false; await queue.retry();
    expect(calls).toEqual([1, 2]); expect(status.dirty).toBe(false); expect(status.error).toBe('');
  });
  it('invalidates an older queued snapshot as soon as a newer unvalidated edit exists', async () => {
    const gate = deferred<void>(), status = state(), calls: number[] = [];
    const queue = createSaveQueue(status, async (value: number) => { calls.push(value); await gate.promise; }, vi.fn(), vi.fn());
    queue.edit(); const first = queue.save(1); queue.edit(); void queue.save(2); queue.edit();
    gate.resolve(); await first; await queue.retry();
    expect(calls).toEqual([1]); expect(status.dirty).toBe(true);
    await queue.save(3); expect(calls).toEqual([1, 3]); expect(status.dirty).toBe(false);
  });
  it('does not retry an obsolete failed write after a newer unsaved edit', async () => {
    const gate = deferred<void>(), status = state(), write = vi.fn<(value: number) => Promise<void>>().mockReturnValue(gate.promise);
    const queue = createSaveQueue(status, write, vi.fn(), vi.fn());
    queue.edit(); const first = queue.save(1); queue.edit();
    gate.reject(new Error('offline')); await first; await queue.retry();
    expect(write).toHaveBeenCalledTimes(1); expect(status.dirty).toBe(true);
  });
});
