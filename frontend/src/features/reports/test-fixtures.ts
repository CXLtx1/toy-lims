import type { FeatureMeta, Report } from './model';

export const featureMeta: FeatureMeta = {
  sample_statuses: { completed: '已完成', reviewed: '已审核', queued: '已制样' },
  sample_tags: [{ name: '批次 A', count: 2 }],
  result_order_templates: [{ id: 1, name: '默认顺序', is_default: true }],
  default_order_template_id: 1,
  report_profiles: [{ id: 1, name: '默认', company_name_cn: '测试实验室', company_name_en: 'Test laboratory', raw_code: 'RAW-01', final_code: 'FINAL-01' }],
};

export function reportFixture(id = 1): Report {
  return {
    sample: { id, name: `S-${id}`, lims_no: `LIMS-${id}`, category: '矿样', status: 'reviewed', workflow_type: 'regular',
      customer: `Customer ${id}`, report_no: `R-${id}`, analysis_date: '2026-09-08', analyst: `Analyst ${id}`, reviewer: 'Reviewer', tags: ['批次 A'], analyte_names: 'Cu, Fe' },
    preps: [{ name: '酸溶' }], special: null,
    groups: [{ key: 'a:1', analyte: 'Cu', analyte_id: 1, print: true, available_units: ['%', 'ppm'], final: { value: 0.125, unit: '%', mode: '自动平均', based_on: 2 }, rows: [
      { sample_analyte_id: id * 10, prep: '酸溶', instrument: 'ICP', value: 0.1, unit: '%', mass_g: 0.5, volume_ml: 250, dilution: '原样', readings: [{ raw: 10, used: true, corrected_value: 0.1 }, { raw: 11, used: false }] },
      { sample_analyte_id: id * 10 + 1, prep: '碱溶', instrument: '滴定', method: '滴定法', value: 0.15, unit: '%', readings: [{ extra: { V: 0, B: 1 }, used: true, corrected_value: 0.15 }], aux: { use: true, expected: 10, measured: 9 } },
    ] }, { key: 'a:2', analyte: 'Fe', analyte_id: 2, print: false, available_units: ['%'], final: null, rows: [{ value: null, unit: '%', prep: '原样', instrument: 'ICP' }] }],
    report_rows: [{ item: 'Cu', result: '0.125', unit: '%', note: '自动平均', include: true }],
    default_report_rows: [{ item: 'Cu', result: '0.125', unit: '%', note: '自动平均', include: true }],
    manual_report: null,
    report_profile: { id: 1, name: '默认', company_name_cn: '测试实验室', company_name_en: 'Test laboratory', raw_code: 'RAW-01', final_code: 'FINAL-01' },
    data_editors: [{ name: 'Data editor', count: 2 }], xrf_targets: [], xrf_warnings: [],
  };
}
