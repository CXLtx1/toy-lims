export type SampleType = 'solid' | 'liquid' | 'water_quality' | 'special'
export interface Analyte { id: number; name: string }
export interface Instrument { id: number; name: string; itype: string; analytes: number[] }
export interface Method { id: number; name: string; itype: string; active: number; target?: string; formula?: string; note?: string; output_unit?: string; constants?: string }
export interface Dilution { id: number; label: string; factor: number; active: number }
export interface Assignment { instrument_id: number | null; method_id: number | null }
export type InstrumentMap = Record<string, Assignment>
export interface Preparation {
  id?: number; name?: string; mass_g?: number | null; volume_ml?: number | null;
  dilution_id?: number | null; dilution_ids?: number[]; dilution_steps?: string | number[];
  analyte_ids?: number[]; instrument_map?: InstrumentMap; count?: number;
}
export interface PrepDraft {
  key: number; id?: number; name: string; autoName: boolean; parallelIndex: number | null;
  mass: string | number; volume: number; dilutionIds: number[]; count: string | number; instrumentMap: InstrumentMap;
}
export interface SampleTemplate {
  id: number; name: string; category: string; tags_json: string; is_liquid: number; is_water_quality: number;
  xrf: number; analyte_ids: string; prep_config: string; instrument_config: string;
  dilution_id: number | null; order_template_id: number | null;
}
export interface IntakeMeta {
  analytes: Analyte[]; instruments: Instrument[]; dilutions: Dilution[]; methods: Method[];
  volume_presets: { id: number | null; volume_ml: number; active: number }[]; default_volume_ml: number;
  templates: SampleTemplate[]; special_methods: { id: number; name: string; instrument: string }[];
  preparation_combinations: { id: number; name: string; rows: Preparation[] }[];
  result_order_templates: { id: number; name: string; is_default: number; items: string[] }[];
  default_order_template_id: number | null; categories: string[]; sample_tags: { name: string; count: number }[];
  sample_statuses: Record<string, string>; sample_transitions: Record<string, string[]>; allowed_status_targets: string[];
}
export interface StatusHistory { action: string; operator?: string; at?: string; rollback?: boolean; reason?: string }
export interface Sample {
  id: number; name: string; category: string; lims_no: string; status: string; workflow_type: string;
  is_liquid: number; is_water_quality: number; density_g_ml: number | null; xrf: number;
  xrf_method_id: number | null; xrf_report_items: string; special_method_id: number | null;
  special_method_name?: string; special_instrument?: string; tags: string[]; report_order: string;
  order_template_id: number | null; prep_count: number; analyte_names: string | null; created_at: string; updated_at?: string;
  status_history?: StatusHistory[]; status_operator?: string; status_action?: string; status_changed_at?: string;
}
export interface SampleDetail {
  sample: Sample; preps: Preparation[];
  items: { preparation_id: number | null; analyte_id: number; instrument_id: number | null; method_id: number | null }[];
  special?: { raw_data: Record<string, unknown> } | null;
}
export interface SampleDraft {
  name: string; category: string; type: SampleType; density: string | number; tags: string[];
  analyteText: string; xrf: boolean; xrfText: string; xrfMethodId: number | null;
  specialMethodId: number | null; orderTemplateId: number | null; reportOrder: number[];
  instrumentMap: InstrumentMap; preps: PrepDraft[];
}
export interface MutationResult { ok: boolean; id: number; lims_no?: string; message?: string; status?: string }

export function parseJson<T>(value: string | null | undefined, fallback: T): T {
  try { return (JSON.parse(value || '') as T | null) ?? fallback } catch { return fallback }
}
export function parseAnalytes(text: string, analytes: Analyte[]): { matched: Analyte[]; unmatched: string[] } {
  const names = new Map(analytes.map(a => [a.name.toLowerCase(), a]))
  const matched: Analyte[] = [], unmatched: string[] = [], seen = new Set<number>()
  for (const token of text.split(/[,，、;；\s]+/).filter(Boolean)) {
    const analyte = names.get(token.toLowerCase())
    if (!analyte) unmatched.push(token)
    else if (!seen.has(analyte.id)) { seen.add(analyte.id); matched.push(analyte) }
  }
  return { matched, unmatched }
}
export function sampleType(sample: Pick<Sample, 'workflow_type' | 'is_water_quality' | 'is_liquid'>): SampleType {
  return sample.workflow_type === 'special' ? 'special' : sample.is_water_quality ? 'water_quality' : sample.is_liquid ? 'liquid' : 'solid'
}
export function nullableNumber(value: string | number): number | null {
  if (String(value).trim() === '') return null
  const number = Number(value)
  if (!Number.isFinite(number)) throw new Error('请输入有效数字。')
  return number
}
export function cloneMap(map: InstrumentMap): InstrumentMap {
  return Object.fromEntries(Object.entries(map).map(([key, value]) => [key, { ...value }]))
}
let prepKey = 0
export function createPrep(meta: IntakeMeta, prep: Preparation = {}, defaults: InstrumentMap = {}): PrepDraft {
  const ids = prep.dilution_ids ?? (Array.isArray(prep.dilution_steps) ? prep.dilution_steps : parseJson<number[]>(prep.dilution_steps, []))
  const fallback = prep.dilution_id ?? meta.dilutions.find(d => d.active)?.id
  return {
    key: ++prepKey, id: prep.id, name: prep.name ?? '', autoName: !prep.name, parallelIndex: null,
    mass: prep.mass_g ?? '', volume: prep.volume_ml ?? meta.default_volume_ml ?? 250,
    dilutionIds: ids.length ? [...ids] : fallback === undefined || fallback === null ? [] : [fallback],
    count: prep.count ?? 1, instrumentMap: cloneMap(prep.instrument_map ?? defaults),
  }
}
export function assignedIds(prep: PrepDraft, analyteIds: number[], meta: IntakeMeta): number[] {
  return analyteIds.filter(id => {
    const instrument = meta.instruments.find(i => i.id === prep.instrumentMap[String(id)]?.instrument_id)
    return instrument?.itype !== 'xrf' && instrument?.analytes.includes(id)
  })
}
export function parallelCount(prep: PrepDraft): number {
  return Math.min(10, Math.max(1, Number.parseInt(String(prep.count), 10) || 1))
}
export function automaticName(prep: PrepDraft, name: string, ids: number[], meta: IntakeMeta, index: number | null = null): string {
  const factor = prep.dilutionIds.reduce((product, id) => product * (meta.dilutions.find(d => d.id === id)?.factor ?? 1), 1)
  const first = meta.analytes.find(a => a.id === assignedIds(prep, ids, meta)[0])?.name
  const base = `${first ? `${first}.` : ''}${name.trim() || '?'}`
  const parallel = index ?? prep.parallelIndex
  return `${base}${parallel ? `-${parallel}` : ''}*${Number(factor.toFixed(6))}`
}
export function preparationNames(prep: PrepDraft, name: string, ids: number[], meta: IntakeMeta): string[] {
  const count = parallelCount(prep), custom = prep.autoName ? '' : prep.name.trim()
  return Array.from({ length: count }, (_, index) => custom
    ? count === 1 ? custom : custom.includes('{n}') ? custom.replaceAll('{n}', String(index + 1)) : `${custom}-${index + 1}`
    : automaticName(prep, name, ids, meta, count > 1 ? index + 1 : null))
}
export function collectPreps(draft: SampleDraft, meta: IntakeMeta): Preparation[] {
  const ids = parseAnalytes(draft.analyteText, meta.analytes).matched.map(a => a.id)
  const liquid = draft.type === 'liquid' || draft.type === 'water_quality'
  return draft.preps.flatMap(prep => {
    const included = assignedIds(prep, ids, meta)
    const map = Object.fromEntries(included.map(id => [String(id), { ...prep.instrumentMap[String(id)]! }]))
    return preparationNames(prep, draft.name, ids, meta).map(name => ({
      ...(parallelCount(prep) === 1 && prep.id !== undefined ? { id: prep.id } : {}), name,
      mass_g: liquid ? null : nullableNumber(prep.mass), volume_ml: liquid ? null : prep.volume,
      dilution_id: prep.dilutionIds[0] ?? null, dilution_ids: [...prep.dilutionIds], analyte_ids: included, instrument_map: map,
    }))
  })
}
export function newDraft(meta: IntakeMeta, type: SampleType = 'solid', tags: string[] = []): SampleDraft {
  return { name: '', category: '', type, density: '', tags: [...tags], analyteText: '', xrf: false, xrfText: '',
    xrfMethodId: null, specialMethodId: null, orderTemplateId: meta.default_order_template_id ?? meta.result_order_templates[0]?.id ?? null,
    reportOrder: [], instrumentMap: {}, preps: [createPrep(meta)] }
}
export function detailDraft(detail: SampleDetail, meta: IntakeMeta, copy = false): SampleDraft {
  const { sample, items } = detail
  const draft = newDraft(meta, sampleType(sample), sample.tags ?? [])
  Object.assign(draft, { name: copy ? `${sample.name}-副本` : sample.name, category: sample.category ?? '',
    density: sample.density_g_ml ?? '', xrf: !!sample.xrf, xrfText: sample.xrf_report_items ?? '',
    xrfMethodId: sample.xrf_method_id, specialMethodId: sample.special_method_id,
    orderTemplateId: sample.order_template_id ?? draft.orderTemplateId, reportOrder: parseJson<number[]>(sample.report_order, []) })
  const solution = items.filter(i => i.preparation_id !== null)
  const ids = [...new Set(solution.map(i => i.analyte_id))]
  draft.analyteText = ids.map(id => meta.analytes.find(a => a.id === id)?.name).filter(Boolean).join(', ')
  for (const item of solution) if (item.instrument_id !== null && !draft.instrumentMap[String(item.analyte_id)])
    draft.instrumentMap[String(item.analyte_id)] = { instrument_id: item.instrument_id, method_id: item.method_id }
  draft.preps = detail.preps.map(prep => {
    const map: InstrumentMap = Object.fromEntries(solution.filter(i => i.preparation_id === prep.id && i.instrument_id !== null)
      .map(i => [String(i.analyte_id), { instrument_id: i.instrument_id, method_id: i.method_id }]))
    const row = createPrep(meta, { ...prep, id: copy ? undefined : prep.id, name: copy ? '' : prep.name, instrument_map: map })
    row.autoName = !row.name || row.name === automaticName(row, draft.name, ids, meta)
    return row
  })
  if (!draft.preps.length && draft.type !== 'special') draft.preps.push(createPrep(meta))
  return draft
}
export function applyTemplate(draft: SampleDraft, template: SampleTemplate, meta: IntakeMeta): void {
  const ids = parseJson<number[]>(template.analyte_ids, [])
  const config = parseJson<Record<string, unknown>>(template.instrument_config, {})
  const map: InstrumentMap = {}
  for (const [key, value] of Object.entries(config)) if (/^\d+$/.test(key) && typeof value === 'object' && value !== null) {
    const setting = value as Record<string, unknown>
    map[key] = { instrument_id: typeof setting.instrument_id === 'number' ? setting.instrument_id : null,
      method_id: typeof setting.method_id === 'number' ? setting.method_id : null }
  }
  draft.category = template.category ?? ''
  for (const tag of parseJson<string[]>(template.tags_json, [])) if (!draft.tags.some(t => t.toLowerCase() === tag.toLowerCase())) draft.tags.push(tag)
  draft.type = template.is_water_quality ? 'water_quality' : template.is_liquid ? 'liquid' : 'solid'
  draft.analyteText = meta.analytes.filter(a => ids.includes(a.id)).map(a => a.name).join(', ')
  draft.xrf = !!template.xrf
  const xrfIds = Array.isArray(config.__xrf_analyte_ids) ? config.__xrf_analyte_ids : ids
  draft.xrfText = template.xrf ? typeof config.__xrf_report_items === 'string' ? config.__xrf_report_items : meta.analytes.filter(a => xrfIds.includes(a.id)).map(a => a.name).join(', ') : ''
  draft.xrfMethodId = typeof config.__xrf_method_id === 'number' ? config.__xrf_method_id : null
  draft.reportOrder = template.order_template_id ? [] : Array.isArray(config.__report_order) ? config.__report_order.filter((id): id is number => typeof id === 'number') : [...ids]
  draft.orderTemplateId = template.order_template_id ?? draft.orderTemplateId
  draft.instrumentMap = map
  const preps = parseJson<Preparation[]>(template.prep_config, [])
  draft.preps = (preps.length ? preps : [{ dilution_id: template.dilution_id }]).flatMap(prep => {
    const count = Math.min(10, Math.max(1, prep.count ?? 1))
    return Array.from({ length: count }, (_, index) => {
      const row = createPrep(meta, { ...prep, count: 1 }, map)
      if (count > 1) row.parallelIndex = index + 1
      return row
    })
  })
}
export function templatePayload(draft: SampleDraft, meta: IntakeMeta, name: string): Record<string, unknown> {
  const ids = parseAnalytes(draft.analyteText, meta.analytes).matched.map(a => a.id)
  const preps = collectPreps(draft, meta).map(({ id: _id, name: _name, ...prep }) => prep)
  return { name, category: draft.category.trim(), tags: draft.tags, is_liquid: Number(['liquid', 'water_quality'].includes(draft.type)),
    is_water_quality: Number(draft.type === 'water_quality'), xrf: Number(draft.xrf), dilution_id: preps[0]?.dilution_id ?? null,
    analyte_ids: ids, preps, instrument_map: { ...cloneMap(draft.instrumentMap), __xrf_report_items: draft.xrfText.trim(),
      __xrf_method_id: draft.xrfMethodId, __report_order: draft.reportOrder.length ? draft.reportOrder : ids }, order_template_id: draft.orderTemplateId }
}
export function removesTasks(detail: SampleDetail, preps: Preparation[]): boolean {
  return detail.preps.some(prep => !preps.some(row => row.id === prep.id)) || detail.items.some(item => {
    if (item.preparation_id === null) return false
    const prep = preps.find(row => row.id === item.preparation_id)
    const route = prep?.instrument_map?.[String(item.analyte_id)]
    return !prep?.analyte_ids?.includes(item.analyte_id) || route?.instrument_id !== item.instrument_id || route?.method_id !== item.method_id
  })
}
export function samplePayload(draft: SampleDraft, meta: IntakeMeta): Record<string, unknown> {
  const name = draft.name.trim()
  if (!name) throw new Error('请填写来样序号。')
  if (draft.tags.length > 20 || draft.tags.some(tag => tag.length > 30)) throw new Error('每个样品最多添加 20 个标签，每个标签不能超过 30 个字符。')
  if (draft.type === 'special') {
    if (!draft.specialMethodId) throw new Error('请选择专项检测方法。')
    return { name, category: draft.category.trim(), workflow_type: 'special', special_method_id: draft.specialMethodId, tags: draft.tags }
  }
  const parsed = parseAnalytes(draft.analyteText, meta.analytes)
  if (parsed.unmatched.length) throw new Error(`请先添加或移除未登记的分析项目：${parsed.unmatched.join('、')}`)
  for (const prep of draft.preps) for (const analyte of parsed.matched) {
    const route = prep.instrumentMap[String(analyte.id)]
    if (route && !meta.instruments.some(i => i.id === route.instrument_id && i.itype !== 'xrf' && i.analytes.includes(analyte.id)))
      throw new Error(`请重新分配仪器或明确选择不测：${analyte.name}`)
  }
  const preps = collectPreps(draft, meta)
  if (!preps.some(p => p.analyte_ids?.length) && !draft.xrf) throw new Error('溶样方案和分析项目至少需要有一项。')
  if (draft.xrf && !draft.xrfMethodId) throw new Error('请选择 XRF 方法。')
  const missing: string[] = []
  for (const prep of preps) for (const id of prep.analyte_ids ?? []) {
    const setting = prep.instrument_map?.[String(id)]
    if (meta.instruments.find(i => i.id === setting?.instrument_id)?.itype === 'function' && !setting?.method_id)
      missing.push(`${prep.name}：${meta.analytes.find(a => a.id === id)?.name ?? id}`)
  }
  if (missing.length) throw new Error(`请选择公式方法：${missing.slice(0, 5).join('；')}`)
  const density = draft.type === 'liquid' ? nullableNumber(draft.density) : null
  if (density !== null && density <= 0) throw new Error('液体密度必须大于 0。')
  return { name, category: draft.category.trim(), is_liquid: Number(['liquid', 'water_quality'].includes(draft.type)),
    is_water_quality: Number(draft.type === 'water_quality'), xrf: Number(draft.xrf), preps,
    xrf_report_items: draft.xrfText.trim(), xrf_method_id: draft.xrf ? draft.xrfMethodId : null,
    instrument_map: cloneMap(draft.instrumentMap), report_order: draft.reportOrder,
    order_template_id: draft.orderTemplateId, density_g_ml: density, tags: [...draft.tags] }
}
