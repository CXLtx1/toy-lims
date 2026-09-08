<script setup lang="ts">
import { computed } from 'vue';
import { displayNumber, xrfValue, type Group, type Measurement, type Report, type ReportRow } from '../reports/model';
export interface ManualDraft { editing: boolean; rows: { item: string; result: string; unit: string; note: string; include: boolean }[] }
const props = defineProps<{ report: Report; draft: ManualDraft; statuses: Record<string, string>; busy: boolean }>();
const emit = defineEmits<{
  review: []; unit: [group: Group, current: string]; use: [row: Measurement, use: boolean]; targets: [];
  edit: []; cancel: []; save: []; restore: []; changed: [];
}>();
const locked = computed(() => ['reviewed', 'reported', 'cancelled'].includes(props.report.sample.status));
const unitLocked = computed(() => ['reported', 'cancelled'].includes(props.report.sample.status));
const reviewable = computed(() => ['completed', 'reviewed'].includes(props.report.sample.status));
const regular = computed(() => props.report.groups.map(group => ({ ...group, rows: group.rows.filter(row => !row.xrf_value_id) })).filter(group => group.rows.length));
const xrf = computed(() => props.report.groups.flatMap(group => group.rows.filter(row => row.xrf_value_id).map(row => ({ group, row }))).sort((a, b) => (Number(b.row.value) || 0) - (Number(a.row.value) || 0)));
const values = computed(() => ({ ...props.report.special?.raw_data, ...props.report.special?.calculated_data }));
const history = computed(() => props.report.sample.status_history?.length ? props.report.sample.status_history : props.report.sample.status_operator ? [{ action: props.report.sample.status_action || '', operator: props.report.sample.status_operator, at: props.report.sample.status_changed_at }] : []);
const actionLabels: Record<string, string> = { received: '登记', queued: '制样', measuring: '开始测量', completed: '测量完成', reviewed: '审核', cancelled: '作废' };
function source(row: ReportRow) {
  const original = props.report.default_report_rows.find(item => item.item.toLowerCase() === row.item.toLowerCase());
  return original ? `原值 ${original.result}${original.unit ? ' ' + original.unit : ''}` : '手工新增';
}
function changed() {
  const last = props.draft.rows[props.draft.rows.length - 1];
  // draft is a shared reactive object owned by the parent; row edits are intentional.
  // eslint-disable-next-line vue/no-mutating-props
  if (!last || [last.item, last.result, last.unit, last.note].some(value => value.trim())) props.draft.rows.push({ item: '', result: '', unit: '', note: '', include: true });
  emit('changed');
}
// eslint-disable-next-line vue/no-mutating-props -- shared parent-owned draft
function remove(index: number) { props.draft.rows.splice(index, 1); changed(); }
function checked(event: Event) {
  if (!(event.target instanceof HTMLInputElement)) return false;
  const use = event.target.checked;
  // Keep the control at the confirmed server value until the write succeeds.
  event.target.checked = !use;
  return use;
}
</script>
<template>
  <div class="result-detail">
    <div class="result-detail-head"><b>{{ report.sample.lims_no || '#' + report.sample.id }}</b><span>{{ report.sample.name }}</span><span class="sample-status" :class="report.sample.status">{{ statuses[report.sample.status] || report.sample.status }}</span>
      <span v-if="history.length" class="status-history"><span v-for="(item, index) in history" :key="index" class="status-history-item" :class="{ rollback: item.rollback, 'review-rollback': item.rollback && item.action === 'completed' }" :title="[item.at || '时间未知', item.reason].filter(Boolean).join(' · ')"><b>{{ item.rollback ? item.action === 'completed' ? '撤回审核' : `退回${statuses[item.action] || item.action}` : actionLabels[item.action] || item.action || '状态' }}</b><em>{{ item.operator || '系统' }}</em></span></span><span class="footer-spacer"></span>
      <button type="button" class="r-manual-edit primary" :disabled="busy || !reviewable || report.sample.workflow_type === 'special' || draft.editing" :title="report.sample.workflow_type === 'special' ? '专项检测不支持手工补录' : reviewable ? '需要特权权限、操作原因和再次密码确认' : '样品测量完成后才能手工补录结果'" @click="$emit('edit')">{{ report.manual_report ? '修改手工补录' : '手工补录结果' }}</button>
      <button v-if="reviewable" type="button" class="results-review" :class="report.sample.status === 'reviewed' ? 'danger-soft' : 'primary'" :disabled="busy || draft.editing" @click="$emit('review')">{{ report.sample.status === 'reviewed' ? '特权退回审核' : '审核确认' }}</button>
    </div>
    <div class="results-simple-details" :hidden="draft.editing">
      <template v-if="report.sample.workflow_type === 'special'"><p class="hint">{{ report.special?.schema.title || '专项检测' }}{{ report.special?.method_name ? ` · ${report.special.method_name}` : '' }}{{ report.special?.instrument ? ` · ${report.special.instrument}` : '' }}</p><table class="data-grid results-simple-table"><thead><tr><th>项目</th><th>结果值</th><th>单位</th></tr></thead><tbody><template v-for="(group, index) in report.special?.schema.groups || []" :key="index"><tr class="analyte-group"><td colspan="3"><b>{{ group.name }}</b></td></tr><tr v-for="field in group.fields" :key="field.key" class="sub-row"><td>{{ field.label }}</td><td>{{ values[field.key] ?? '—' }}</td><td>{{ field.unit || '' }}</td></tr></template><tr v-if="!report.special?.schema.groups.length"><td colspan="3" class="xrf-empty">暂无专项数据</td></tr></tbody></table></template>
      <div v-else-if="report.manual_report" class="result-element-grid" style="--result-grid-columns:5"><article v-for="(row, index) in report.report_rows" :key="index" class="result-element-card result-manual-card"><header><span class="result-element-name">{{ row.item }}</span><span class="result-element-final"><strong>{{ row.result }} <small>{{ row.unit || '' }}</small></strong><em>{{ source(row) }}</em></span></header><div class="result-measurements"><div class="result-measurement-row"><div class="result-measurement-main"><b>{{ row.note ? '说明' : '手工补录' }}</b><span>{{ row.note || '—' }}</span></div></div></div></article><p v-if="!report.report_rows.length" class="xrf-empty">暂无手工补录结果</p></div>
      <template v-else>
        <section v-if="xrf.length || report.sample.xrf || report.xrf_targets?.length" class="result-xrf-composition"><h4>XRF 最终组成 <small>{{ xrf.length }} 项 · 点击单位可切换</small><button v-if="!locked" type="button" class="xrf-target-edit" :data-sid="report.sample.id" title="设置每个元素族的报告口径" :disabled="busy" @click="$emit('targets')">口径</button></h4><p v-for="(warning, index) in report.xrf_warnings || []" :key="index" class="hint xrf-warning">注意：{{ warning.message }}</p><div class="xrf-result-list result-xrf-list"><div v-for="(entry, index) in xrf" :key="index"><span v-if="report.xrf_targets?.length && entry.row.xrf_resolution" class="xrf-resolution" :title="entry.row.xrf_resolution.note">{{ entry.row.xrf_resolution.via === 'converted' ? entry.row.xrf_resolution.note : '直出' }}</span><input v-else class="xrf-report-use" type="checkbox" :data-xrf-value="entry.row.xrf_value_id" :aria-label="`${entry.group.analyte}参与最终结果`" title="参与最终结果" :checked="entry.row.selection !== 'exclude'" :disabled="busy || locked" @change="$emit('use', entry.row, checked($event))"><b>{{ entry.group.analyte }}</b><span>{{ xrfValue(entry.row.value) }}<button type="button" class="result-unit-button xrf-unit-button" :data-key="entry.group.key" :data-current="entry.row.unit || ''" :data-units="entry.group.available_units?.join(',') || ''" :disabled="busy || unitLocked || (entry.group.available_units?.length || 0) < 2" title="点击切换显示单位" @click="$emit('unit', entry.group, entry.row.unit || '')">{{ entry.row.unit || '' }}</button></span></div></div></section>
        <div v-if="regular.length" class="result-element-grid" style="--result-grid-columns:5"><article v-for="group in regular" :key="group.key" class="result-element-card"><header><span class="result-element-name">{{ group.analyte }}</span><span class="result-element-final"><template v-if="group.final"><strong>{{ group.final.value }} <button type="button" class="result-unit-button" :data-key="group.key" :data-current="group.final.unit" :data-units="group.available_units?.join(',') || ''" :disabled="busy || unitLocked || (group.available_units?.length || 0) < 2" title="点击切换显示单位" @click="$emit('unit', group, group.final.unit)">{{ group.final.unit }}</button></strong><em>{{ group.final.mode }}{{ group.final.based_on > 1 ? ` × ${group.final.based_on}` : '' }}</em></template><template v-else><strong>—</strong><em>暂无最终值</em></template></span></header><div class="result-measurements"><div v-for="(row, index) in group.rows" :key="index" class="result-measurement-row"><div class="result-measurement-main"><b :title="row.prep || '—'">{{ row.prep || '—' }}</b><span><i v-if="row.value == null">{{ row.unit || '' }}</i><template v-else>{{ displayNumber(row.value) }} {{ row.unit || '' }}</template></span></div><div class="result-measurement-meta"><span :title="[row.instrument, row.method].filter(Boolean).join(' / ') || '—'">{{ [row.instrument, row.method].filter(Boolean).join(' / ') || '—' }}</span><span><label v-if="group.rows.length > 1" class="report-use-label"><input class="report-use" type="checkbox" :data-said="row.sample_analyte_id || ''" :checked="row.selection !== 'exclude'" :disabled="busy || locked || !row.sample_analyte_id" :title="locked ? '已审核样品需先特权退回才能改参与' : ''" @change="$emit('use', row, checked($event))">参与</label><template v-else>—</template></span></div></div></div></article></div><p v-if="!xrf.length && !regular.length" class="xrf-empty">暂无结果</p>
      </template>
    </div>
    <div class="r-manual-details" :hidden="!draft.editing && !report.manual_report"><div class="r-manual-audit manual-report-audit"><template v-if="report.manual_report"><b>当前结果包含特权手工补录</b>&#x3000;{{ report.manual_report.updated_by }} · {{ report.manual_report.updated_at }}<br><small>卡片中同时显示系统原值与补录值；系统计算和仪器原始记录未被改写。</small></template><template v-else><b>正在建立手工补录结果</b>&#x3000;保存后作为最终结果内容，系统计算和仪器原始记录保持不变。</template></div>
      <div class="table-shell" :hidden="!draft.editing"><table class="r-manual-table data-grid spreadsheet"><thead><tr><th>结果项目</th><th>结果</th><th>单位</th><th>说明</th><th></th></tr></thead><tbody><tr v-for="(row, index) in draft.rows" :key="index" :class="{ 'manual-empty-row': !row.item && !row.result && !row.unit && !row.note }"><td><input v-model="row.item" class="mr-item" placeholder="如 Cu" maxlength="120" :disabled="busy" @input="changed"></td><td><input v-model="row.result" class="mr-result" placeholder="数值或报告文本" maxlength="120" :disabled="busy" @input="changed"></td><td><input v-model="row.unit" class="mr-unit" placeholder="如 %" maxlength="40" :disabled="busy" @input="changed"></td><td><input v-model="row.note" class="mr-note" placeholder="可留空" maxlength="300" :disabled="busy" @input="changed"></td><td><button class="del mr-delete" type="button" title="删除该行" :disabled="busy" @click="remove(index)">×</button></td></tr></tbody></table></div>
      <div class="r-manual-actions editor-footer" :hidden="!draft.editing"><button class="r-manual-cancel" type="button" :disabled="busy" @click="$emit('cancel')">取消</button><button class="r-manual-restore" type="button" :disabled="busy" @click="$emit('restore')">恢复系统计算</button><span class="footer-spacer"></span><span class="r-manual-msg"></span><button class="r-manual-save primary" type="button" :disabled="busy" @click="$emit('save')">填写原因、验证密码并保存</button></div>
    </div>
  </div>
</template>
