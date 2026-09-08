<script setup lang="ts">
import { computed } from 'vue';
import { displayNumber, rawReading, reportDate, uniqueSampleValues, type Report, type Sample, type Value } from './model';
const props = defineProps<{ reports: Report[] }>();
const regular = computed(() => props.reports.filter(report => !report.sample.is_water_quality));
const water = computed(() => props.reports.filter(report => report.sample.is_water_quality));
const profile = computed(() => regular.value[0]?.report_profile);
interface RawRow { sample: Sample; first: boolean; date: string[]; analyte: string; mass?: Value; volume?: Value; dilution?: string; raw: Value; result?: Value; unit?: string; remark: string }
const rows = computed(() => regular.value.flatMap(report => {
  const sampleRows: Omit<RawRow, 'sample' | 'first' | 'date'>[] = [];
  if (report.sample.workflow_type === 'special') {
    for (const group of report.special?.schema.groups || []) for (const field of group.fields) {
      const raw = report.special?.raw_data[field.key];
      const calculated = report.special?.calculated_data[field.key];
      if ([raw, calculated].every(value => value === undefined || value === '')) continue;
      sampleRows.push({ analyte: field.label, dilution: '—', raw: raw ?? calculated, result: calculated ?? raw, unit: field.unit,
        remark: [report.special?.method_name, report.special?.instrument].filter(Boolean).join(' / ') });
    }
  } else for (const group of report.groups) for (const row of group.rows) {
    const readings = row.readings?.length ? row.readings : [{ raw: null, extra: {}, corrected_value: null }];
    readings.forEach((reading, index) => {
      const aux = row.aux?.use ? row.aux.expected && row.aux.measured ? `回标 ${row.aux.expected}→${row.aux.measured}` : '带标校正' : '';
      sampleRows.push({ analyte: group.analyte, mass: row.mass_g, volume: row.volume_ml, dilution: row.dilution,
        raw: rawReading(row, reading), result: reading.corrected_value ?? (index === 0 ? row.value : null), unit: row.unit,
        remark: [row.instrument, row.method, aux].filter(Boolean).join(' / ') });
    });
  }
  if (!sampleRows.length) sampleRows.push({ analyte: '—', raw: '—', result: null, remark: '暂无检测明细' });
  return sampleRows.map((row, index) => ({ ...row, sample: report.sample, first: index === 0, date: reportDate(report.sample).split('-') }));
}));
const waterAnalytes = computed(() => [...new Set(water.value.flatMap(report => report.groups.map(group => group.analyte)))]);
const waterRows = computed(() => water.value.map(report => ({ sample: report.sample, values: new Map(report.groups.map(group =>
  [group.analyte, [...new Set(group.rows.flatMap(row => (row.readings || []).map(reading => rawReading(row, reading))).filter(value => value !== '—'))].join(' / ') || '—'])) })));
</script>
<template>
  <article id="raw-ticket" class="raw-ticket-batch">
    <div v-if="!reports.length" class="report-empty-preview">选择已审核样品后生成原始分析记录预览</div>
    <section v-if="regular.length" class="print-document raw-ticket raw-ticket-page" :style="{ '--raw-row-height': `${Math.max(3.2, Math.min(8, 96 / Math.max(12, rows.length)))}mm`, '--raw-font-size': `${rows.length > 18 ? 9 : 11}px` }">
      <div class="ticket-code">{{ profile?.raw_code || '' }}</div>
      <header class="ticket-brand"><h1>{{ profile?.company_name_cn || '' }}</h1><p v-if="profile?.company_name_en">{{ profile.company_name_en }}</p></header>
      <h2>原 始 分 析 记 录</h2>
      <table class="raw-record-table"><thead><tr><th colspan="3">分析日期</th><th rowspan="2">来样序号</th><th rowspan="2">样品名称</th><th rowspan="2">分析项目</th><th rowspan="2">样品净重<br>(g)</th><th rowspan="2">定容<br>(mL)</th><th rowspan="2">检测体积<br>(mL)</th><th rowspan="2">读数</th><th rowspan="2">分析结果</th><th rowspan="2">分析者</th><th rowspan="2">备注</th></tr><tr><th>年</th><th>月</th><th>日</th></tr></thead>
        <tbody><tr v-for="(row, index) in rows" :key="index"><td>{{ row.first ? row.date[0]?.slice(-2) : '' }}</td><td>{{ row.first ? row.date[1] : '' }}</td><td>{{ row.first ? row.date[2] : '' }}</td><td>{{ row.first ? row.sample.name || '—' : '' }}</td><td>{{ row.first ? row.sample.category || '—' : '' }}</td><td>{{ row.analyte }}</td><td>{{ displayNumber(row.mass) }}</td><td>{{ displayNumber(row.volume) }}</td><td>{{ row.dilution || '—' }}</td><td>{{ row.raw }}</td><td>{{ row.result == null ? '—' : `${displayNumber(row.result)} ${row.unit || ''}` }}</td><td>{{ row.first ? row.sample.analyst || '' : '' }}</td><td>{{ row.remark }}</td></tr>
          <tr v-for="index in Math.max(0, 12 - rows.length)" :key="`blank-${index}`" class="blank-row"><td v-for="column in 13" :key="column"></td></tr><tr class="remark-row"><td colspan="3">备注</td><td colspan="10"></td></tr></tbody></table>
      <div class="ticket-signatures"><span>分析：{{ uniqueSampleValues(regular, 'analyst') }}</span><span>审核：{{ uniqueSampleValues(regular, 'reviewer') }}</span></div>
    </section>
    <section v-if="water.length" class="print-document raw-ticket raw-ticket-page water-raw-ticket">
      <div class="water-ticket-code">TL-HYS-06-01</div><h2>污水处理分析原始记录</h2><div class="water-unit-note">除 pH 外，单位均为 mg/L</div>
      <table class="water-raw-table"><thead><tr><th>日期</th><th>取样点</th><th>编号</th><th v-for="name in waterAnalytes" :key="name">{{ name }}</th><th>分析人</th><th>备注</th></tr></thead><tbody><tr v-for="row in waterRows" :key="row.sample.id"><td>{{ reportDate(row.sample) }}</td><td>{{ row.sample.category || '—' }}</td><td>{{ row.sample.name || '—' }}</td><td v-for="name in waterAnalytes" :key="name">{{ row.values.get(name) || '—' }}</td><td>{{ row.sample.analyst || '' }}</td><td></td></tr><tr v-for="index in Math.max(0, 18 - water.length)" :key="`blank-${index}`" class="blank-row"><td v-for="column in waterAnalytes.length + 5" :key="column"></td></tr></tbody></table>
    </section>
  </article>
</template>
