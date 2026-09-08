<script setup lang="ts">
import { rawReading, specialRows, type Group, type Report } from './model';
defineProps<{ reports: Report[]; busy: boolean }>();
defineEmits<{
  move: [id: number, step: number]; order: [id: number, analyteId: number, step: number];
  reset: [id: number]; printUse: [id: number, key: string, use: boolean];
}>();
function checked(event: Event): boolean {
  if (!(event.target instanceof HTMLInputElement)) return false;
  const use = event.target.checked;
  event.target.checked = !use;
  return use;
}
</script>
<template>
  <div id="r-system-details"><div id="r-head">以下内容按样品顺序完整展示。可调整样品顺序、各样品内的元素顺序及是否打印。</div>
    <div class="table-shell"><table id="r-table" class="data-grid"><thead><tr><th>项目</th><th>溶样</th><th>方法/仪器</th><th>原始值</th><th>结果</th><th>打印</th></tr></thead><tbody>
      <template v-for="(report, index) in reports" :key="report.sample.id">
        <tr class="report-sample-group" :data-sid="report.sample.id"><td colspan="6">
          <span class="report-sample-order-actions noprint"><button type="button" class="batch-sample-up" :disabled="busy || index === 0" title="样品前移" @click="$emit('move', report.sample.id, -1)">↑</button><button type="button" class="batch-sample-down" :disabled="busy || index === reports.length - 1" title="样品后移" @click="$emit('move', report.sample.id, 1)">↓</button></span>
          <strong>{{ index + 1 }}. 来样序号：{{ report.sample.name || '—' }}</strong> <span>样品名称：{{ report.sample.category || '—' }}</span> <small>LIMS {{ report.sample.lims_no || '#' + report.sample.id }} · 溶样 {{ report.preps.map((prep: { name: string }) => prep.name).filter(Boolean).join('、') || '—' }}</small>
          <span v-if="report.manual_report" class="manual-result-source" title="系统计算结果被历史手工结果覆盖；请在结果页查看或恢复系统计算">历史手工结果 · {{ report.manual_report.updated_by }} · {{ report.manual_report.updated_at }}</span>
          <button v-if="report.sample.workflow_type === 'regular' && !report.manual_report" type="button" class="sample-order-default noprint" :disabled="busy" @click="$emit('reset', report.sample.id)">恢复该样品默认元素顺序</button>
        </td></tr>
        <template v-if="report.sample.workflow_type === 'special'">
          <tr v-for="(row, rowIndex) in specialRows(report)" :key="rowIndex" class="analyte-group special-report-row" :data-sid="report.sample.id"><td><b>{{ row.item }}</b></td><td>专项检测</td><td>{{ report.special?.method_name || '—' }}{{ report.special?.instrument ? ` / ${report.special.instrument}` : '' }}</td><td>{{ row.result }}</td><td><b>{{ row.result }}</b> {{ row.unit || '' }}</td><td>打印</td></tr>
        </template>
        <template v-else-if="report.manual_report">
          <tr v-for="(row, rowIndex) in report.report_rows" :key="rowIndex" class="analyte-group manual-print-row" :data-sid="report.sample.id" :data-key="`m:${row.item.toLowerCase()}`"><td><b>{{ row.item }}</b><small v-if="row.note">{{ row.note }}</small></td><td>历史手工结果覆盖</td><td>—</td><td>—</td><td><b>{{ row.result }}</b> {{ row.unit || '' }}</td><td><label class="print-use-label"><input class="print-use" type="checkbox" :data-sid="report.sample.id" :data-key="`m:${row.item.toLowerCase()}`" :checked="row.include !== false" :disabled="busy" @change="$emit('printUse', report.sample.id, `m:${row.item.toLowerCase()}`, checked($event))">打印</label></td></tr>
        </template>
        <template v-else>
          <template v-for="group in report.groups" :key="group.key">
            <tr class="analyte-group" :data-sid="report.sample.id" :data-aid="group.analyte_id || ''" :data-key="group.key"><td colspan="5"><span class="report-order-actions noprint"><button class="r-order-up" type="button" title="元素上移" :disabled="busy || !group.analyte_id || group.analyte_id === report.groups.find((item: Group) => item.analyte_id)?.analyte_id" @click="group.analyte_id && $emit('order', report.sample.id, group.analyte_id, -1)">↑</button><button class="r-order-down" type="button" title="元素下移" :disabled="busy || !group.analyte_id || group.analyte_id === report.groups.filter((item: Group) => item.analyte_id).at(-1)?.analyte_id" @click="group.analyte_id && $emit('order', report.sample.id, group.analyte_id, 1)">↓</button></span>
              <b>{{ group.analyte }}</b>&#x3000;最终: <template v-if="group.final"><b>{{ group.final.value }}</b> {{ group.final.unit }} <small>({{ group.final.mode }}{{ group.final.based_on > 1 ? ` × ${group.final.based_on}` : '' }})</small></template><i v-else>—</i>
            </td><td><label class="print-use-label"><input class="print-use" type="checkbox" :data-sid="report.sample.id" :data-key="group.key" :checked="group.print !== false" :disabled="busy" @change="$emit('printUse', report.sample.id, group.key, checked($event))">打印</label></td></tr>
            <tr v-for="(row, rowIndex) in group.rows" :key="rowIndex" class="sub-row" :data-sid="report.sample.id"><td></td><td>{{ row.prep || '—' }}</td><td>{{ row.instrument || '—' }}{{ row.method ? ` / ${row.method}` : '' }}</td><td><template v-if="row.readings?.length"><template v-for="(reading, readingIndex) in row.readings" :key="readingIndex">{{ readingIndex ? ' / ' : '' }}<b v-if="reading.used">{{ rawReading(row, reading) }}</b><span v-else class="rd-unused">{{ rawReading(row, reading) }}</span></template></template><template v-else>—</template></td><td><i v-if="row.value == null">{{ row.unit || '' }}</i><template v-else>{{ row.value }} {{ row.unit || '' }}</template></td><td>—</td></tr>
          </template>
        </template>
      </template>
    </tbody></table></div>
  </div>
</template>
