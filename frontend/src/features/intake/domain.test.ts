import assert from 'node:assert/strict'
import { test } from 'vitest'
import { applyTemplate, automaticName, collectPreps, createPrep, detailDraft, newDraft, nullableNumber, parseAnalytes,
  preparationNames, removesTasks, samplePayload, templatePayload, type IntakeMeta, type SampleDetail, type SampleTemplate } from './domain'

const meta: IntakeMeta = {
  analytes: [{ id: 1, name: 'Cu' }, { id: 2, name: 'Fe' }, { id: 3, name: 'pH' }],
  instruments: [{ id: 10, name: 'ICP', itype: 'ppm', analytes: [1, 2] }, { id: 11, name: '公式计算', itype: 'function', analytes: [1, 2] }, { id: 12, name: 'XRF', itype: 'xrf', analytes: [1, 2] }],
  dilutions: [{ id: 1, label: '不稀释', factor: 1, active: 1 }, { id: 2, label: '5/100', factor: 20, active: 1 }, { id: 3, label: '10/100', factor: 10, active: 0 }],
  methods: [{ id: 20, name: 'Cu滴定', itype: 'function', active: 1 }, { id: 21, name: 'WUNI', itype: 'xrf', active: 1 }],
  volume_presets: [{ id: 1, volume_ml: 250, active: 1 }], default_volume_ml: 250,
  templates: [], special_methods: [{ id: 30, name: '水分', instrument: '天平' }], preparation_combinations: [],
  result_order_templates: [{ id: 40, name: '默认', is_default: 1, items: ['Cu', 'Fe'] }], default_order_template_id: 40,
  categories: [], sample_tags: [], sample_statuses: {}, sample_transitions: {}, allowed_status_targets: [],
}
function configuredDraft() {
  const draft = newDraft(meta)
  draft.name = 'RY2888'; draft.analyteText = 'Cu Fe'
  draft.preps[0]!.instrumentMap = { '1': { instrument_id: 10, method_id: null } }
  return draft
}
test('analyte recognition is case insensitive, deduplicated, and preserves unknown tokens', () => {
  assert.deepEqual(parseAnalytes('cu、FE; CU，ph bad <script>', meta.analytes), {
    matched: meta.analytes, unmatched: ['bad', '<script>'],
  })
})
test('zero is not an empty mass or a missing numeric value', () => {
  assert.equal(nullableNumber('0'), 0); assert.equal(nullableNumber(0), 0); assert.equal(nullableNumber(''), null)
  assert.throws(() => nullableNumber('not a number'))
  const draft = configuredDraft(); draft.preps[0]!.mass = 0
  assert.equal(collectPreps(draft, meta)[0]!.mass_g, 0)
  assert.equal(createPrep(meta, { mass_g: 0, volume_ml: 0 }).volume, 0)
})
test('dilution chains multiply factors and retain inactive historical IDs', () => {
  const draft = configuredDraft(), prep = draft.preps[0]!
  prep.dilutionIds = [2, 3]
  assert.equal(automaticName(prep, draft.name, [1, 2], meta), 'Cu.RY2888*200')
  assert.deepEqual(collectPreps(draft, meta)[0]!.dilution_ids, [2, 3])
  assert.deepEqual(createPrep(meta, { dilution_steps: '[2,3]' }).dilutionIds, [2, 3])
})
test('parallel names support automatic analyte prefixes and custom placeholders', () => {
  const draft = configuredDraft(), prep = draft.preps[0]!
  prep.count = 2; prep.dilutionIds = [2]
  assert.deepEqual(preparationNames(prep, draft.name, [1, 2], meta), ['Cu.RY2888-1*20', 'Cu.RY2888-2*20'])
  prep.autoName = false; prep.name = '消解-{n}'
  assert.deepEqual(preparationNames(prep, draft.name, [1, 2], meta), ['消解-1', '消解-2'])
  prep.name = '消解'
  assert.deepEqual(preparationNames(prep, draft.name, [1, 2], meta), ['消解-1', '消解-2'])
})
test('unchanged preparation IDs survive edits; parallel expansion never duplicates IDs', () => {
  const draft = configuredDraft(), prep = draft.preps[0]!
  prep.id = 55
  assert.equal(collectPreps(draft, meta)[0]!.id, 55)
  prep.count = 2
  assert.ok(collectPreps(draft, meta).every(row => row.id === undefined))
})
test('not measured, incompatible instruments and XRF never enter solution tasks', () => {
  const draft = configuredDraft(), prep = draft.preps[0]!
  assert.deepEqual(collectPreps(draft, meta)[0]!.analyte_ids, [1])
  prep.instrumentMap['2'] = { instrument_id: 12, method_id: null }
  assert.deepEqual(collectPreps(draft, meta)[0]!.analyte_ids, [1])
  assert.throws(() => samplePayload(draft, meta), /重新分配/)
  delete prep.instrumentMap['2']
  delete prep.instrumentMap['1']
  assert.throws(() => samplePayload(draft, meta), /至少需要/)
})
test('liquid and water-quality payloads omit mass and volume but only liquid takes density', () => {
  const draft = configuredDraft(); draft.type = 'liquid'; draft.density = '1.05'; draft.preps[0]!.mass = 2
  assert.equal(samplePayload(draft, meta).density_g_ml, 1.05)
  assert.equal(collectPreps(draft, meta)[0]!.mass_g, null)
  assert.equal(collectPreps(draft, meta)[0]!.volume_ml, null)
  draft.density = 0; assert.throws(() => samplePayload(draft, meta), /大于 0/)
  draft.type = 'water_quality'
  assert.equal(samplePayload(draft, meta).density_g_ml, null)
  assert.equal(samplePayload(draft, meta).is_liquid, 1)
  assert.equal(samplePayload(draft, meta).is_water_quality, 1)
})
test('formula routes and XRF require their methods, pure XRF needs no solution task', () => {
  const draft = configuredDraft()
  draft.preps[0]!.instrumentMap['1'] = { instrument_id: 11, method_id: null }
  assert.throws(() => samplePayload(draft, meta), /公式方法/)
  draft.preps[0]!.instrumentMap['1']!.method_id = 20
  assert.doesNotThrow(() => samplePayload(draft, meta))
  draft.preps = []; draft.xrf = true
  assert.throws(() => samplePayload(draft, meta), /XRF 方法/)
  draft.xrfMethodId = 21; draft.xrfText = 'Fe2O3, Cu'
  assert.equal(samplePayload(draft, meta).xrf_report_items, 'Fe2O3, Cu')
})
test('special samples do not leak regular tasks or XRF configuration', () => {
  const draft = configuredDraft(); draft.type = 'special'; draft.xrf = true
  assert.throws(() => samplePayload(draft, meta), /专项/)
  draft.specialMethodId = 30
  assert.deepEqual(samplePayload(draft, meta), { name: 'RY2888', category: '', workflow_type: 'special', special_method_id: 30, tags: [] })
})
test('templates merge tags, preserve explicit empty XRF items, expand persisted parallels and carry per-route methods', () => {
  const draft = configuredDraft(); draft.tags = ['实验样']
  const template: SampleTemplate = { id: 1, name: '模板', category: '氧化物', tags_json: '["实验样","二组"]', is_liquid: 0, is_water_quality: 1,
    xrf: 1, analyte_ids: '[1,2]', prep_config: '[{"count":2,"mass_g":0,"dilution_ids":[2,3]}]',
    instrument_config: '{"1":{"instrument_id":11,"method_id":20},"__xrf_report_items":"","__xrf_method_id":21}', dilution_id: 2, order_template_id: 40 }
  applyTemplate(draft, template, meta)
  assert.deepEqual(draft.tags, ['实验样', '二组']); assert.equal(draft.name, 'RY2888')
  assert.equal(draft.xrfText, ''); assert.equal(draft.xrfMethodId, 21); assert.equal(draft.type, 'water_quality')
  assert.equal(draft.preps.length, 2); assert.equal(draft.preps[0]!.mass, 0)
  assert.equal(draft.preps[1]!.parallelIndex, 2); assert.equal(draft.preps[0]!.instrumentMap['1']!.method_id, 20)
  const saved = templatePayload(draft, meta, '新模板')
  assert.equal(saved.name, '新模板'); assert.equal(saved.order_template_id, 40)
  assert.ok(!('id' in (saved.preps as Record<string, unknown>[])[0]!))
})
test('detail loading preserves independent routes and copying strips persisted IDs', () => {
  const detail: SampleDetail = { sample: { id: 50, name: 'RY2888', category: '样品', lims_no: '20260908-001', status: 'received', workflow_type: 'regular',
    is_liquid: 0, is_water_quality: 0, density_g_ml: null, xrf: 0, xrf_method_id: null, xrf_report_items: '', special_method_id: null,
    tags: ['二组'], report_order: '[2,1]', order_template_id: 40, prep_count: 2, analyte_names: 'Fe, Cu', created_at: '', },
    preps: [{ id: 60, name: '自定义', mass_g: 0, volume_ml: 100, dilution_ids: [3] }, { id: 61, name: '另一路', dilution_ids: [2] }],
    items: [{ preparation_id: 60, analyte_id: 1, instrument_id: 10, method_id: null }, { preparation_id: 61, analyte_id: 1, instrument_id: 11, method_id: 20 }] }
  const draft = detailDraft(detail, meta)
  assert.equal(draft.preps[0]!.id, 60); assert.equal(draft.preps[0]!.name, '自定义'); assert.equal(draft.preps[0]!.mass, 0)
  assert.equal(draft.preps[0]!.instrumentMap['1']!.instrument_id, 10); assert.equal(draft.preps[1]!.instrumentMap['1']!.method_id, 20)
  const copied = detailDraft(detail, meta, true)
  assert.equal(copied.name, 'RY2888-副本'); assert.ok(copied.preps.every(row => row.id === undefined && row.autoName))
  assert.deepEqual(copied.tags, ['二组']); assert.deepEqual(copied.reportOrder, [2, 1])
  copied.preps[0]!.instrumentMap['1']!.instrument_id = 11
  assert.equal(detail.items[0]!.instrument_id, 10)
})

test('invalid routes and unknown analytes cannot silently remove requested tasks on save', () => {
  const draft = configuredDraft()
  draft.analyteText += ' unknown'
  assert.throws(() => samplePayload(draft, meta), /未登记/)
  draft.analyteText = 'Cu Fe'
  draft.preps[0]!.instrumentMap['2'] = { instrument_id: 999, method_id: null }
  assert.throws(() => samplePayload(draft, meta), /重新分配/)
  delete draft.preps[0]!.instrumentMap['2']
  assert.doesNotThrow(() => samplePayload(draft, meta))
})

test('destructive plan checks distinguish retained tasks from removals and rerouting', () => {
  const draft = configuredDraft()
  draft.preps[0]!.id = 60
  const detail = { preps: [{ id: 60 }], items: [{ preparation_id: 60, analyte_id: 1, instrument_id: 10, method_id: null }] } as SampleDetail
  draft.name = 'renamed'; draft.preps[0]!.mass = 2
  assert.equal(removesTasks(detail, collectPreps(draft, meta)), false)
  draft.preps[0]!.instrumentMap['1'] = { instrument_id: 11, method_id: 20 }
  assert.equal(removesTasks(detail, collectPreps(draft, meta)), true)
  assert.equal(removesTasks(detail, []), true)
  draft.preps[0]!.instrumentMap = {}
  assert.equal(removesTasks(detail, collectPreps(draft, meta)), true)
})
