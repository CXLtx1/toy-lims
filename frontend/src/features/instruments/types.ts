import type { Sample } from '../data-entry/types';
export interface XrfValue { id: number; name: string; alt_name?: string; value: number | null; use_report: number | boolean }
export interface Scan {
  id: number; kind: string; sample_id?: number | null; sample_name: string; external_id: string;
  analyzed_at?: string; created_at?: string; method?: string; batch?: string; remark?: string;
  matched?: boolean; sample_status?: string; lims_sample_name?: string; lims_no?: string;
  oxide?: boolean; top_values?: string[]; value_count?: number; values: XrfValue[];
  option_details?: { label: string; value: string | number | boolean | string[] }[];
}
export interface XrfTarget { family: string; target: string; include: boolean | number; allow_conversion?: boolean | number }
export interface XrfSample { sample: Sample; analyses: Scan[]; targets: XrfTarget[] }
export interface XrfReference {
  elements: { symbol: string; name_zh: string; atomic_number: number }[];
  oxides: { formula: string; element_symbol: string; is_conventional: boolean | number }[];
}
export interface StandardClient {
  client_id: string; instrument_name?: string; machine_name?: string; network_position?: string;
  display_name?: string; username?: string; seen_at?: string;
  recent_entry?: { at: string; count: number; items: string[] } | null;
}
export interface XrfClient {
  online: boolean; state: string; machine_name?: string; client_id?: string;
  current_sample?: string; current_method?: string; current_batch?: string; current_run_id?: string;
  current_position?: string; current_started_at?: string; seen_at?: string; message?: string;
}
export interface Monitor { standard_clients: StandardClient[]; client: XrfClient | null; scans: Scan[]; total: number; page: number; pages: number }
export function xrfValueText(value: number | null): string { return value == null ? '—' : Number(value.toPrecision(5)).toString(); }
