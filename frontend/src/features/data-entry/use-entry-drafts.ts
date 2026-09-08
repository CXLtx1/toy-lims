import { reactive } from 'vue';
import { request } from '../../api/client';
import { markDirty } from '../../app/state';
import { showError } from '../../app/dialogs';
import { createSaveQueue, type SaveState } from './save-queue';
import { fields, lockedStatuses, numberValue, variables, type Fields, type SampleDetail, type Task } from './types';

export interface ReadingDraft extends SaveState {
  key: string; id: number | null; version: string | null; raw: string; extra: Record<string, string>; included: boolean;
  deleting: boolean; uncertain: boolean;
}
export interface TaskDraft extends SaveState { task: Task; readings: ReadingDraft[]; expected: string; measured: string; use: boolean }
export interface EntryDraft extends SaveState { detail: SampleDetail; tasks: TaskDraft[]; raw: Record<string, string>; generation: number; focused: boolean; busy: boolean }
interface ReadingPayload { raw?: number | null; extra?: Fields; use_avg: boolean; is_final: boolean }
const initialState = (): SaveState => ({ dirty: false, saving: false, error: '', savedAt: '' });

export function useEntryDrafts(onSaved: (id: number) => void) {
  const drafts = reactive(new Map<number, EntryDraft>());
  const queues = new WeakMap<object, ReturnType<typeof createSaveQueue<ReadingPayload>>>();
  const auxQueues = new WeakMap<object, ReturnType<typeof createSaveQueue<Fields>>>();
  const specialQueues = new WeakMap<object, ReturnType<typeof createSaveQueue<Fields>>>();
  function dirty(draft: EntryDraft, includeBusy = true): boolean {
    return draft.dirty || draft.saving || !!draft.error || (includeBusy && draft.busy) || draft.tasks.some(task => task.dirty || task.saving || !!task.error || task.readings.some(rd => rd.dirty || rd.saving || rd.deleting || !!rd.error));
  }
  function changed(draft: EntryDraft) {
    draft.generation++;
    markDirty(`data:${draft.detail.sample.id}`, dirty(draft));
  }
  function setBusy(draft: EntryDraft, busy: boolean) { draft.busy = busy; changed(draft); }
  function assertWritable(draft: EntryDraft) {
    if (lockedStatuses.includes(draft.detail.sample.status)) throw new Error('当前样品已锁定，草稿已保留。');
  }
  function makeReading(reading?: Task['readings'][number], hasFinal = false): ReadingDraft {
    return reactive({ ...initialState(), key: crypto.randomUUID(), id: reading?.id ?? null,
      version: typeof reading?.version === 'string' && reading.version ? reading.version : null,
      raw: reading?.raw == null ? '' : String(reading.raw), extra: Object.fromEntries(Object.entries(fields(reading?.extra)).map(([key, value]) => [key, value == null ? '' : String(value)])),
      included: hasFinal ? Boolean(reading?.is_final) : reading ? Boolean(reading.use_avg) : true,
      deleting: false, uncertain: false });
  }
  function install(detail: SampleDetail): EntryDraft {
    const draft: EntryDraft = reactive({ ...initialState(), detail, generation: 0, focused: false, busy: false,
      raw: Object.fromEntries(Object.entries(detail.special?.raw_data || {}).map(([key, value]) => [key, value == null ? '' : String(value)])),
      tasks: detail.items.filter(task => task.itype !== 'xrf').map(task => {
        const aux = fields(task.aux);
        return { ...initialState(), task, expected: String(aux.expected ?? ''), measured: String(aux.measured ?? ''), use: Boolean(aux.use),
          readings: task.readings.length ? task.readings.map(rd => makeReading(rd, task.readings.some(item => Boolean(item.is_final)))) : [makeReading()] };
      }),
    });
    drafts.set(detail.sample.id, draft);
    return drafts.get(detail.sample.id)!;
  }
  function queue(draft: EntryDraft, task: TaskDraft, rd: ReadingDraft) {
    let existing = queues.get(rd);
    if (!existing) {
      existing = createSaveQueue<ReadingPayload>(rd, async snapshot => {
        assertWritable(draft);
        if (rd.uncertain) throw new Error('创建读数的响应丢失，草稿已保留。请核对服务器读数后重新载入，勿重复创建。');
        if (!rd.id) {
          try {
            // The stable client key makes a retry of the same draft row return
            // the original reading (replayed) instead of creating a duplicate.
            const created = await request<{ id: number; version?: string }>('/api/readings', { method: 'POST', body: { sample_analyte_id: task.task.id, client_reading_id: rd.key } });
            if (!Number.isInteger(created.id) || created.id <= 0) throw new Error('创建读数未返回有效编号，草稿已保留。');
            rd.id = created.id;
            if (typeof created.version === 'string' && created.version) rd.version = created.version;
          } catch (error) {
            // A definite HTTP rejection is safe to retry; a lost response is not.
            const status = error && typeof error === 'object' && 'status' in error ? Number(error.status) : 0;
            if (!status || status >= 500) rd.uncertain = true;
            throw error;
          }
        }
        assertWritable(draft);
        const body: ReadingPayload & { expected_version?: string } = { ...snapshot };
        if (rd.version) body.expected_version = rd.version;
        const updated = await request<{ version?: string }>(`/api/readings/${rd.id}`, { method: 'PUT', body });
        if (typeof updated.version === 'string' && updated.version) rd.version = updated.version;
        onSaved(draft.detail.sample.id);
      }, () => changed(draft), error => { void showError(error, '自动保存失败，草稿已保留'); });
      queues.set(rd, existing);
    }
    return existing;
  }
  function editReading(draft: EntryDraft, task: TaskDraft, rd: ReadingDraft) { queue(draft, task, rd).edit(); }
  function saveReading(draft: EntryDraft, task: TaskDraft, rd: ReadingDraft): Promise<void> {
    if (rd.deleting) return Promise.resolve();
    try {
      const payload: ReadingPayload = { use_avg: task.readings.length === 1 ? true : rd.included, is_final: false };
      if (task.task.itype === 'function') payload.extra = Object.fromEntries(variables(task.task).filter(key => (rd.extra[key] || '').trim() !== '').map(key => [key, numberValue(rd.extra[key] || '')]));
      else payload.raw = numberValue(rd.raw);
      return queue(draft, task, rd).save(payload);
    } catch (error) { rd.error = error instanceof Error ? error.message : String(error); changed(draft); return Promise.resolve(); }
  }
  function participation(draft: EntryDraft, task: TaskDraft) {
    for (const rd of task.readings) { editReading(draft, task, rd); void saveReading(draft, task, rd); }
  }
  function addReading(draft: EntryDraft, task: TaskDraft) {
    const rd = makeReading();
    task.readings.push(rd);
    editReading(draft, task, rd);
    void saveReading(draft, task, rd);
  }
  async function deleteReading(draft: EntryDraft, task: TaskDraft, rd: ReadingDraft) {
    if (rd.deleting || rd.uncertain || draft.busy || lockedStatuses.includes(draft.detail.sample.status)) return;
    rd.deleting = true; changed(draft);
    try {
      await queue(draft, task, rd).idle();
      if (rd.uncertain) return;
      assertWritable(draft);
      if (rd.id) await request(`/api/readings/${rd.id}`, { method: 'DELETE', body: rd.version ? { expected_version: rd.version } : {} });
      const index = task.readings.indexOf(rd);
      if (index !== -1) task.readings.splice(index, 1);
      if (!task.readings.length) task.readings.push(makeReading());
      onSaved(draft.detail.sample.id);
    } catch (error) { rd.error = error instanceof Error ? error.message : String(error); void showError(error); }
    finally { rd.deleting = false; changed(draft); }
  }
  function auxQueue(draft: EntryDraft, task: TaskDraft) {
    let existing = auxQueues.get(task);
    if (!existing) {
      existing = createSaveQueue<Fields>(task, async aux => {
        assertWritable(draft);
        await request('/api/results', { method: 'POST', body: { sample_analyte_id: task.task.id, aux } });
        onSaved(draft.detail.sample.id);
      }, () => changed(draft), error => { void showError(error, '辅助数据保存失败'); });
      auxQueues.set(task, existing);
    }
    return existing;
  }
  function editAux(draft: EntryDraft, task: TaskDraft) { auxQueue(draft, task).edit(); }
  function saveAux(draft: EntryDraft, task: TaskDraft) {
    try { return auxQueue(draft, task).save({ use: task.use, expected: numberValue(task.expected), measured: numberValue(task.measured) }); }
    catch (error) { task.error = error instanceof Error ? error.message : String(error); changed(draft); return Promise.resolve(); }
  }
  function specialQueue(draft: EntryDraft) {
    let existing = specialQueues.get(draft);
    if (!existing) {
      existing = createSaveQueue<Fields>(draft, async (raw, isCurrent) => {
        assertWritable(draft);
        const result = await request<{ calculated_data: Fields; status: string }>(`/api/special-results/${draft.detail.sample.id}`, { method: 'PUT', body: { raw_data: raw } });
        if (draft.detail.special && isCurrent()) {
          draft.detail.special.calculated_data = result.calculated_data;
          draft.detail.special.status = result.status;
        }
        onSaved(draft.detail.sample.id);
      }, () => changed(draft), error => { void showError(error, '专项数据保存失败'); });
      specialQueues.set(draft, existing);
    }
    return existing;
  }
  function editSpecial(draft: EntryDraft) { specialQueue(draft).edit(); }
  function saveSpecial(draft: EntryDraft) {
    try {
      const raw: Fields = {};
      for (const field of draft.detail.special?.schema.groups.flatMap(group => group.fields) || []) {
        const value = draft.raw[field.key] || '';
        if (field.formula || !value.trim()) continue;
        raw[field.key] = (field.type || (field.unit ? 'number' : 'text')) === 'number' ? numberValue(value) : value;
      }
      if (draft.raw.note) raw.note = draft.raw.note;
      return specialQueue(draft).save(raw);
    } catch (error) { draft.error = error instanceof Error ? error.message : String(error); changed(draft); return Promise.resolve(); }
  }
  async function flush(draft: EntryDraft): Promise<boolean> {
    const jobs: Promise<void>[] = [];
    for (const task of draft.tasks) {
      for (const rd of task.readings) if (rd.dirty && !rd.deleting) jobs.push(saveReading(draft, task, rd));
      if (task.dirty) jobs.push(saveAux(draft, task));
    }
    if (draft.dirty) jobs.push(saveSpecial(draft));
    await Promise.all(jobs);
    return !dirty(draft, false);
  }
  return { drafts, dirty, setBusy, install, editReading, saveReading, participation, addReading, deleteReading, editAux, saveAux, editSpecial, saveSpecial, flush };
}
