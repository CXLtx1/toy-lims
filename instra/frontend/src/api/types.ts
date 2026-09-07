/** 与后端 API 对应的类型定义。 */

export interface SampleListItem {
  id: number;
  lims_no: string | null;
  name: string;
  category: string;
  type: string;
  status: string;
  xrf: boolean;
  created_at: string | null;
  customer: string;
  analysis_date: string;
  analyst: string;
  reviewer: string;
  tags: string[];
  analytes: string[];
  prep_count: number;
  xrf_scan_count: number;
}

export interface Paged<T> {
  ok: boolean;
  total: number;
  page: number;
  per_page: number;
  items: T[];
}

export interface ReadingDetail {
  raw: number | null;
  extra: Record<string, unknown>;
  value: number | null;
  unit: string;
  used: boolean;
  is_final: boolean;
  corrected_value: number | null;
}

export interface AggregateRow {
  sample_analyte_id: number;
  analyte: string;
  prep: string;
  mass_g: number | null;
  volume_ml: number | null;
  dilution: string;
  instrument: string;
  method: string;
  task_status: string;
  selection: string | null;
  value: number | null;
  unit: string;
  readings: ReadingDetail[];
}

export interface AggregateGroup {
  analyte: string;
  final: { value: number; unit: string; based_on: number; mode: string } | null;
  available_units: string[];
  rows: AggregateRow[];
}

export interface XrfValue {
  name: string;
  value: number;
  use_report?: number;
  alt_name?: string;
}

export interface XrfAnalysisBrief {
  id: number;
  external_id: string;
  kind: string;
  sample_name: string;
  method: string;
  batch: string;
  analyzed_at: string | null;
  remark: string;
  values: XrfValue[];
}

export interface PrepPlan {
  id: number;
  name: string;
  mass_g: number | null;
  volume_ml: number | null;
  dilution_label: string;
  dilution_factor: number;
  dilution_steps: string[];
  tasks: { analyte: string; instrument: string; method: string; status: string }[];
}

export interface Aggregate {
  ok: boolean;
  sample: SampleListItem & { density_g_ml: number | null; cancel_reason: string };
  tags: string[];
  groups: AggregateGroup[];
  xrf_analyses: XrfAnalysisBrief[];
  preps: PrepPlan[];
}

export interface QuantListItem {
  id: number;
  external_id: string;
  sample_id: number | null;
  sample_name: string;
  method: string;
  batch: string;
  analyzed_at: string | null;
  remark: string;
  lims_name: string | null;
  lims_no: string | null;
  kind: "quant";
  value_count: number;
  top_values: XrfValue[];
}

export interface UqListItem {
  id: number;
  external_id: string;
  general_id: string;
  job_id: string;
  sample_id: number | null;
  sample_name: string;
  method: string;
  film: string | null;
  processed: boolean | null;
  analyzed_at: string | null;
  lims_name: string | null;
  lims_no: string | null;
  kind: "uq";
  value_count: number;
  top_values: XrfValue[];
}

export interface UqChannel {
  name: string;
  alt_name: string;
  int_cps: number | null;
  conc: number | null;
  sigma_conc: number | null;
  std_err: number | null;
  counting_time: number | null;
  overlapping_elements: string;
  is_reported: boolean;
}

export interface UqPair {
  oxide_name: string | null;
  oxide_value: number | null;
  element_name: string | null;
  element_value: number | null;
}

export interface UqDetail extends UqListItem {
  options: Record<string, unknown>;
  job: Record<string, unknown>;
  channels: UqChannel[];
  composition: XrfValue[];
  pairs: UqPair[];
}

export interface OrderTemplate {
  id: number;
  name: string;
  is_default: boolean;
  items: string[];
}

export type XrfUnit = "%" | "ppm" | "ppb";

export interface XrfUnitField {
  key: string;
  label: string;
  oxide_name: string | null;
  element_name: string | null;
  default_unit: XrfUnit;
}
