import { request } from '../../api/client';

export type Value = string | number | boolean | null | undefined;
export interface StatusHistory { action: string; operator?: string; at?: string; reason?: string; rollback?: boolean }
export interface Sample {
  id: number; name: string; status: string; lims_no?: string | null; category?: string | null;
  workflow_type?: string; is_water_quality?: boolean | number; is_liquid?: boolean | number; xrf?: boolean | number;
  tags?: string[]; analyte_names?: string | null; created_at?: string; customer?: string | null;
  report_no?: string | null; analysis_date?: string | null; analyst?: string | null; reviewer?: string | null;
  report_profile_id?: number | null; status_history?: StatusHistory[]; status_operator?: string;
  status_action?: string; status_changed_at?: string; report_excludes?: string; updated_at?: string | null;
}
export interface Reading { raw?: Value; extra?: Record<string, Value>; used?: boolean; value?: Value; corrected_value?: Value }
export interface Measurement {
  sample_analyte_id?: number | null; xrf_value_id?: number; prep?: string; instrument?: string | null;
  method?: string; value?: Value; unit?: string; selection?: string | null; readings?: Reading[];
  mass_g?: Value; volume_ml?: Value; dilution?: string;
  aux?: { use?: boolean; expected?: number; measured?: number };
  xrf_resolution?: { via: string; note: string };
}
export interface Group {
  key: string; analyte: string; analyte_id?: number | null; print?: boolean; available_units?: string[];
  final: { value: Value; unit: string; mode: string; based_on: number } | null; rows: Measurement[];
}
export interface ReportRow { item: string; result: Value; unit?: string; note?: string; include?: boolean }
export interface SpecialField { key: string; label: string; unit?: string }
export interface Special {
  method_name?: string; instrument?: string; raw_data: Record<string, Value>; calculated_data: Record<string, Value>;
  schema: { title?: string; groups: { name: string; fields: SpecialField[] }[] };
}
export interface Profile { id: number | null; name: string; company_name_cn: string; company_name_en?: string; raw_code?: string; final_code?: string }
export interface Target { family: string; target: string; include: boolean | number; allow_conversion?: boolean | number }
export interface Report {
  sample: Sample; groups: Group[]; preps: { name: string }[]; special: Special | null;
  report_rows: ReportRow[]; default_report_rows: ReportRow[];
  manual_report: { rows: ReportRow[]; updated_by: string; updated_at: string } | null;
  report_profile: Profile; data_editors?: { name: string; count: number }[];
  xrf_targets?: Target[]; xrf_warnings?: { message: string }[];
}
export interface FeatureMeta {
  sample_statuses: Record<string, string>; sample_tags: { name: string; count: number }[];
  result_order_templates: { id: number; name: string; is_default?: boolean | number }[];
  report_profiles: Profile[]; default_order_template_id?: number | null;
}
export interface SamplePage { rows: Sample[]; total: number }
export interface Metadata { report_profile_id: number | null; customer: string; report_no: string; analysis_date: string; analyst: string }

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function scalar(value: unknown): boolean {
  return value == null || ['string', 'boolean'].includes(typeof value) || (typeof value === 'number' && Number.isFinite(value));
}
function sampleValid(value: unknown): value is Sample {
  return record(value) && Number.isSafeInteger(value.id) && Number(value.id) > 0 && typeof value.name === 'string' && typeof value.status === 'string';
}
function rowsValid(value: unknown): boolean {
  return Array.isArray(value) && value.every(row => record(row) && typeof row.item === 'string' && scalar(row.result) &&
    (row.unit == null || typeof row.unit === 'string') && (row.note == null || typeof row.note === 'string') &&
    (row.include === undefined || typeof row.include === 'boolean'));
}
export function validateReport(value: unknown, id: number): Report {
  if (!record(value) || !sampleValid(value.sample) || value.sample.id !== id ||
      !Array.isArray(value.groups) || !Array.isArray(value.preps) || !rowsValid(value.report_rows) ||
       !rowsValid(value.default_report_rows) || !record(value.report_profile) ||
       (value.report_profile.id !== null && !Number.isSafeInteger(value.report_profile.id)) ||
       typeof value.report_profile.name !== 'string' || typeof value.report_profile.company_name_cn !== 'string' ||
       !value.preps.every(prep => record(prep) && typeof prep.name === 'string') ||
       (value.data_editors !== undefined && (!Array.isArray(value.data_editors) || !value.data_editors.every(editor =>
         record(editor) && typeof editor.name === 'string' && typeof editor.count === 'number' && Number.isFinite(editor.count))))) throw new Error('报告响应格式无效');
  for (const group of value.groups) {
    if (!record(group) || typeof group.key !== 'string' || typeof group.analyte !== 'string' || !Array.isArray(group.rows) ||
        (group.final !== null && (!record(group.final) || !scalar(group.final.value))) ||
        (group.available_units !== undefined && (!Array.isArray(group.available_units) || !group.available_units.every(unit => typeof unit === 'string')))) throw new Error('报告项目格式无效');
    for (const row of group.rows) {
      if (!record(row) || !scalar(row.value) || !scalar(row.mass_g) || !scalar(row.volume_ml) || (row.readings !== undefined && (!Array.isArray(row.readings) ||
          !row.readings.every(reading => record(reading) && scalar(reading.raw) && scalar(reading.value) && scalar(reading.corrected_value) &&
            (reading.extra == null || (record(reading.extra) && Object.values(reading.extra).every(scalar))))))) throw new Error('报告读数格式无效');
    }
  }
  if (value.sample.workflow_type === 'special' && value.special !== null) {
    const special = value.special;
    if (!record(special) || !record(special.schema) || !Array.isArray(special.schema.groups) ||
        !record(special.raw_data) || !record(special.calculated_data) ||
        !Object.values(special.raw_data).every(scalar) || !Object.values(special.calculated_data).every(scalar) || !special.schema.groups.every(group =>
          record(group) && Array.isArray(group.fields) && group.fields.every(field => record(field) && typeof field.key === 'string' && typeof field.label === 'string'))) throw new Error('专项报告格式无效');
  }
  if (value.manual_report !== null && (!record(value.manual_report) || !rowsValid(value.manual_report.rows))) throw new Error('手工报告格式无效');
  return value as unknown as Report;
}
export async function fetchReport(id: number, signal?: AbortSignal): Promise<Report> {
  return validateReport(await request<unknown>(`/api/report/${id}`, { signal }), id);
}
export async function fetchSamples(params: URLSearchParams, signal?: AbortSignal): Promise<SamplePage> {
  const value = await request<unknown>(`/api/samples?${params}`, { signal });
  if (!record(value) || !Array.isArray(value.rows) || !value.rows.every(sampleValid) ||
      typeof value.total !== 'number' || !Number.isSafeInteger(value.total) || value.total < 0) throw new Error('样品列表响应格式无效');
  return { rows: value.rows, total: value.total };
}
export async function fetchMeta(): Promise<FeatureMeta> {
  const value = await request<unknown>('/api/meta');
  if (!record(value) || !record(value.sample_statuses) || !Array.isArray(value.sample_tags) ||
      !Array.isArray(value.result_order_templates) || !Array.isArray(value.report_profiles)) throw new Error('元数据响应格式无效');
  return value as unknown as FeatureMeta;
}
export async function write(url: string, body: unknown, method = 'PUT'): Promise<Record<string, unknown>> {
  const result = await request<unknown>(url, { method, body });
  if (!record(result) || result.ok !== true) throw new Error(record(result) && typeof result.error === 'string' ? result.error : '服务器未确认保存成功');
  return result;
}
export function reportDate(sample: Sample): string {
  const today = new Date();
  return sample.analysis_date || sample.created_at?.slice(0, 10) || `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
}
export function displayNumber(value: Value): string {
  if (value == null || value === '') return '—';
  return Number.isFinite(Number(value)) ? String(Number(value)) : String(value);
}
export function xrfValue(value: Value): string {
  if (value == null || value === '') return '—';
  return Number.isFinite(Number(value)) ? String(Number(Number(value).toPrecision(5))) : String(value);
}
export function rawReading(row: Measurement, reading: Reading): string {
  return row.method && !row.xrf_value_id ? Object.entries(reading.extra || {}).map(([key, value]) => `${key}=${value}`).join(' ') || '—' : displayNumber(reading.raw);
}
export function specialRows(report: Report): ReportRow[] {
  const values = { ...report.special?.raw_data, ...report.special?.calculated_data };
  return (report.special?.schema.groups || []).flatMap(group => group.fields).filter(field => values[field.key] !== undefined && values[field.key] !== '')
    .map(field => ({ item: field.label, result: values[field.key], unit: field.unit || '' }));
}
export function finalRows(report: Report): ReportRow[] {
  return report.sample.workflow_type === 'special' ? specialRows(report) : report.report_rows.filter(row => row.include !== false);
}
export function mixedWater(reports: Report[]): boolean {
  return reports.some(report => report.sample.is_water_quality) && reports.some(report => !report.sample.is_water_quality);
}
export function uniqueSampleValues(reports: Report[], key: 'report_no' | 'customer' | 'analysis_date' | 'analyst' | 'reviewer'): string {
  return [...new Set(reports.map(report => report.sample[key]).filter(Boolean))].join('、');
}
export function waterUnit(row: ReportRow): string {
  if (/^p\s*h$/i.test(row.item)) return '';
  return (row.unit || 'mg/L').toLowerCase() === 'ppm' ? 'mg/L' : row.unit || 'mg/L';
}
export function errorText(error: unknown): string { return error instanceof Error ? error.message : String(error); }
