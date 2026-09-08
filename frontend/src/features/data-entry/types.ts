export type Scalar = string | number | boolean | null;
export type Fields = Record<string, Scalar>;
export interface StatusEvent { action: string; operator?: string; at?: string; reason?: string; rollback?: boolean }
export interface Sample {
  id: number; name: string; category?: string; lims_no?: string; status: string;
  workflow_type?: string; is_liquid?: number | boolean; is_water_quality?: number | boolean;
  xrf?: number | boolean; method_name?: string; created_at?: string;
  status_history?: StatusEvent[]; status_operator?: string; status_action?: string; status_changed_at?: string;
}
export interface Preparation { id: number; name: string; mass_g: number | null; volume_ml: number | null; dilution_label?: string }
export interface Reading { id: number; raw: number | null; extra: string | Fields | null; use_avg: boolean | number; is_final: boolean | number; version?: string }
export interface Task {
  id: number; analyte_id: number; analyte: string; preparation_id: number | null;
  instrument_id: number | null; instrument: string | null; itype: string | null;
  method_id: number | null; method_name: string | null; formula: string | null;
  method_constants: string | Fields | null; method_note?: string; method_output_unit?: string;
  prep_name: string | null; prep_mass: number | null; prep_vol: number | null;
  status: string; aux: string | Fields | null; readings: Reading[];
}
export interface SpecialField { key: string; label: string; formula?: string; required?: boolean; type?: string; unit?: string }
export interface Special {
  method_name: string; instrument: string; status: string; raw_data: Fields; calculated_data: Fields;
  schema: { title: string; groups: { name: string; fields: SpecialField[] }[] };
}
export interface SampleDetail { sample: Sample; preps: Preparation[]; items: Task[]; special: Special | null }
export interface EntryMeta {
  instruments: { id: number }[]; analytes: { id: number }[];
  sample_statuses: Record<string, string>; sample_transitions: Record<string, string[]>;
  allowed_status_targets: string[];
}
export const lockedStatuses = ['registered', 'received', 'queued', 'reviewed', 'reported', 'cancelled'];
export const finalStatuses = ['reviewed', 'reported', 'cancelled'];
export function fields(value: string | Fields | null | undefined): Fields {
  let parsed: unknown = value;
  if (typeof value === 'string') { try { parsed = JSON.parse(value); } catch { return {}; } }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
  return Object.fromEntries(Object.entries(parsed).filter((pair): pair is [string, Scalar] =>
    pair[1] === null || ['string', 'number', 'boolean'].includes(typeof pair[1])));
}
export function variables(task: Task): string[] {
  const constants = fields(task.method_constants);
  return [...new Set(task.formula?.match(/\b[A-Za-z_][A-Za-z0-9_]*\b/g) || [])].filter(key =>
    !Object.hasOwn(constants, key) && !(key === 'm' && task.prep_mass != null) && !(key === 'v' && task.prep_vol != null));
}
export function fixedValues(task: Task): string {
  const constants = fields(task.method_constants);
  if (/\bm\b/.test(task.formula || '') && task.prep_mass != null) constants.m = task.prep_mass;
  if (/\bv\b/.test(task.formula || '') && task.prep_vol != null) constants.v = task.prep_vol;
  return Object.entries(constants).map(([key, value]) => `${key}=${value}`).join(' ');
}
export function numberValue(value: string): number | null {
  if (!value.trim()) return null;
  const result = Number(value);
  if (!Number.isFinite(result)) throw new Error('请输入有效数值');
  return result;
}
export function sampleKind(sample: Sample): string {
  return sample.workflow_type === 'special' ? '其他样' : sample.is_water_quality ? '水质样' : sample.is_liquid ? '液体样' : '固体';
}
