import type { EntryMeta, SampleDetail, Task } from '../types';
export const meta: EntryMeta = { instruments: [{ id: 1 }], analytes: [{ id: 1 }, { id: 2 }], sample_statuses: { received: '未制样', queued: '已制样', measuring: '测量中', completed: '待审核', reviewed: '已审核' }, sample_transitions: { measuring: ['queued'], received: ['queued'], queued: ['measuring'] }, allowed_status_targets: ['queued', 'measuring'] };
export function task(id = 1): Task { return { id, analyte_id: id, analyte: id === 1 ? 'Fe' : 'Cu', preparation_id: 1, instrument_id: 1, instrument: 'ICP-OES', itype: 'ppm', method_id: null, method_name: null, formula: null, method_constants: null, prep_name: 'A', prep_mass: 1, prep_vol: 250, status: 'pending', aux: null, readings: [] }; }
export function detail(id = 1): SampleDetail { return { sample: { id, name: `S${id}`, status: 'measuring' }, preps: [{ id: 1, name: 'A', mass_g: 1, volume_ml: 250, dilution_label: '5/100' }], items: [task(), task(2)], special: null }; }
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
