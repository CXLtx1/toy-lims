<script setup lang="ts">
import { computed } from 'vue';
import { displayNumber, finalRows, mixedWater, reportDate, uniqueSampleValues, waterUnit, type Report, type ReportRow } from './model';
const props = defineProps<{ reports: Report[] }>();
const first = computed(() => props.reports[0]);
const rows = computed(() => props.reports.flatMap(report => {
  const selected = finalRows(report);
  if (!selected.length) selected.push({ item: '—', result: '—', unit: '' });
  return selected.map((row, index) => ({ sample: report.sample, row, first: index === 0, count: selected.length }));
}));
const waterPages = computed(() => props.reports.map(report => {
  const selected = report.report_rows.filter(row => row.include !== false);
  const count = Math.max(15, selected.length || 1);
  const blanks: ReportRow[] = Array.from({ length: count - selected.length }, () => ({ item: '', result: '', unit: '' }));
  return { sample: report.sample, rows: [...selected, ...blanks], count };
}));
</script>
<template>
  <article id="final-ticket" class="print-document final-ticket">
    <div v-if="!first" class="report-empty-preview">选择已审核样品后生成组合报告预览</div>
    <div v-else-if="mixedWater(reports)" class="report-empty-preview">水质样与其他样品使用不同报告票，请分开选择后打印</div>
    <div v-else-if="first.sample.is_water_quality" class="water-final-pages">
      <section v-for="page in waterPages" :key="page.sample.id" class="water-final-page"><div class="water-ticket-code">TL-HYS-20-01</div><h2>废水分析报告票</h2><div class="water-final-date">日期：{{ reportDate(page.sample) }}</div>
        <table class="water-final-table"><tbody><tr><th colspan="2">检测点</th><td>{{ page.sample.category || '' }}</td><th>编号</th><td>{{ page.sample.name || '' }}</td></tr><tr v-for="(row, index) in page.rows" :key="index"><th v-if="index === 0" class="water-project-label" :rowspan="page.count">检测项目</th><th>{{ row.item }}</th><td colspan="2">{{ displayNumber(row.result) === '—' && !row.item ? '' : displayNumber(row.result) }}</td><td>{{ row.item ? waterUnit(row) : '' }}</td></tr><tr><th colspan="2">分析人员</th><td colspan="3">{{ page.sample.analyst || '' }}</td></tr></tbody></table>
      </section>
    </div>
    <template v-else>
      <div class="final-serial">{{ uniqueSampleValues(reports, 'report_no') }}</div><div class="ticket-code">{{ first.report_profile.final_code || '' }}</div>
      <header class="ticket-brand"><h1>{{ first.report_profile.company_name_cn || '' }}</h1></header><h2>分 析 报 告 票</h2>
      <div class="final-meta"><span>来样单位：{{ uniqueSampleValues(reports, 'customer') }}</span><span>分析时间：{{ uniqueSampleValues(reports, 'analysis_date') || reportDate(first.sample) }}</span></div>
      <table class="final-report-table"><thead><tr><th>来样序号</th><th>样品名称</th><th>分析项目</th><th>分析结果</th></tr></thead><tbody><tr v-for="(entry, index) in rows" :key="index"><td v-if="entry.first" :rowspan="entry.count">{{ entry.sample.name || '—' }}</td><td v-if="entry.first" :rowspan="entry.count">{{ entry.sample.category || '—' }}</td><td>{{ entry.row.item }}</td><td>{{ displayNumber(entry.row.result) }} {{ entry.row.unit || '' }}</td></tr><tr v-for="index in Math.max(0, 12 - rows.length)" :key="`blank-${index}`" class="blank-row"><td></td><td></td><td></td><td></td></tr></tbody></table>
      <div class="ticket-signatures"><span>分析：{{ uniqueSampleValues(reports, 'analyst') }}</span><span>审核：{{ uniqueSampleValues(reports, 'reviewer') }}</span></div>
      <div class="report-notes"><b>说明：</b><ol><li>本结果只对来样负责。</li><li>若对本结果有异议，可在15个工作日内提出复查申请。</li><li>本检测报告需部门领导审核签字方能生效。</li></ol></div>
    </template>
  </article>
</template>
<style>
@media print {
  /* A5's printable width excludes the margins set by the print action. */
  body.print-final #final-ticket .water-final-pages { width: 100%; }
}
</style>
