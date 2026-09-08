export interface Analyte { id: number; name: string; default_unit: string | null }
export interface Instrument { id: number; name: string; itype: string; analytes: number[] }
export interface Dilution { id: number; label: string; factor: number; active: number }
export interface VolumePreset { id: number; volume_ml: number; active: number }
export interface Method { id: number; name: string; itype: string; formula: string; constants: string; note: string; output_unit: string; target: string; active: number }
export interface Routing { instrument_id: number; method_id: number | null }
export type InstrumentMap = Record<string, Routing>;
export interface Prep { name?: string; mass_g: number | null | ''; volume_ml: number | null; dilution_ids: number[]; dilution_id?: number | null; count: number | ''; analyte_ids?: number[]; instrument_map: InstrumentMap }
export interface SampleTemplate { id: number; name: string; category: string; tags_json: string; is_liquid: number; is_water_quality: number; xrf: number; order_template_id: number | null; dilution_id: number | null; analyte_ids: string; prep_config: string; instrument_config: string }
export interface Combination { id: number; name: string; rows: Prep[] }
export interface OrderTemplate { id: number; name: string; items: string[]; is_default: number }
export interface ReportProfile { id: number; name: string; company_name_cn: string; company_name_en: string; raw_code: string; final_code: string }
export interface SettingsMeta {
  analytes: Analyte[]; instruments: Instrument[]; dilutions: Dilution[]; volume_presets: VolumePreset[];
  default_volume_ml: number; methods: Method[]; templates: SampleTemplate[];
  preparation_combinations: Combination[]; report_profiles: ReportProfile[];
  result_order_templates: OrderTemplate[]; default_order_template_id: number | null;
  sample_tags: { name: string; count: number }[];
}
export const emptyMeta = (): SettingsMeta => ({ analytes: [], instruments: [], dilutions: [], volume_presets: [], default_volume_ml: 250, methods: [], templates: [], preparation_combinations: [], report_profiles: [], result_order_templates: [], default_order_template_id: null, sample_tags: [] });
export function tokens(text: string): string[] { return [...new Set(text.split(/[,，、;；\s]+/).filter(Boolean))]; }
export function parseAnalytes(text: string, analytes: Analyte[]) {
  const matched: Analyte[] = [], unmatched: string[] = [];
  for (const token of tokens(text)) {
    const found = analytes.find(a => a.name.toLowerCase() === token.toLowerCase());
    if (found) { if (!matched.some(a => a.id === found.id)) matched.push(found); }
    else unmatched.push(token);
  }
  return { matched, unmatched };
}
// These fields are JSON strings in the existing database and /api/meta contract.
export function stored<T>(value: string | null | undefined, fallback: T): T {
  try { return (JSON.parse(value || 'null') as T | null) ?? fallback; } catch { return fallback; }
}
export function constantsText(method: Method): string {
  return Object.entries(stored<Record<string, number>>(method.constants, {})).map(([key, value]) => `${key}=${value}`).join(', ');
}
export function newPrep(meta: SettingsMeta, prep: Partial<Prep> = {}): Prep {
  const first = meta.dilutions.find(d => d.active)?.id;
  return { name: '', mass_g: null, volume_ml: meta.default_volume_ml, count: 1, instrument_map: {}, ...prep,
    dilution_ids: prep.dilution_ids?.length ? [...prep.dilution_ids] : prep.dilution_id ? [prep.dilution_id] : first ? [first] : [] };
}
