<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { download } from '../../api/client';
import { markDirty, navigate, useAppState } from '../../app/state';
import { showError } from '../../app/dialogs';
import TagFilter from '../results/TagFilter.vue';
import CalculationDetails from './CalculationDetails.vue';
import RawTicket from './RawTicket.vue';
import FinalTicket from './FinalTicket.vue';
import { errorText, fetchMeta, fetchReport, fetchSamples, mixedWater, reportDate, uniqueSampleValues, write, type FeatureMeta, type Metadata, type Report, type Sample } from './model';

const state = useAppState();
const meta = ref<FeatureMeta | null>(null);
const search = ref('');
const page = ref(0);
const size = ref(20);
const total = ref(0);
const samples = ref<Sample[]>([]);
const known = reactive(new Map<number, Sample>());
const selected = ref<number[]>([]);
const reports = ref<Report[]>([]);
const loading = ref(false);
const batchLoading = ref(false);
const busy = ref(false);
const batchError = ref('');
const message = ref('');
const templateId = ref<number | ''>('');
const form = reactive<Metadata>({ report_profile_id: null, customer: '', report_no: '', analysis_date: '', analyst: '' });
const touched = reactive(new Set<keyof Metadata>());
const baselines = new Map<number, Sample>();
const failedIds = ref<number[]>([]);
const dirty = computed(() => touched.size > 0 || failedIds.value.length > 0);
const pages = computed(() => Math.max(1, Math.ceil(total.value / size.value)));
const disabled = computed(() => busy.value || batchLoading.value);
const displayed = computed(() => [...selected.value.map(id => known.get(id)).filter((sample): sample is Sample => !!sample), ...samples.value.filter(sample => !selected.value.includes(sample.id))]);
const preview = computed(() => reports.value.map(report => {
  const sample = { ...report.sample };
  if (touched.has('customer')) sample.customer = form.customer;
  if (touched.has('report_no')) sample.report_no = form.report_no;
  if (touched.has('analysis_date')) sample.analysis_date = form.analysis_date;
  if (touched.has('analyst')) sample.analyst = form.analyst;
  const profile = touched.has('report_profile_id') ? meta.value?.report_profiles.find(item => item.id === form.report_profile_id) || meta.value?.report_profiles[0] : undefined;
  return { ...report, sample, report_profile: profile || report.report_profile };
}));
const canPrint = computed(() => !!reports.value.length && reports.value.length === selected.value.length && !mixedWater(reports.value) && !batchError.value && !disabled.value);
let listController: AbortController | undefined;
let batchController: AbortController | undefined;
let listGeneration = 0;
let batchGeneration = 0;
let alive = true;

function initializeForm() {
  const first = reports.value[0];
  if (!first || dirty.value) return;
  const counts = new Map<string, number>();
  for (const report of reports.value) for (const editor of report.data_editors || []) if (editor.name.trim()) counts.set(editor.name.trim(), (counts.get(editor.name.trim()) || 0) + editor.count);
  const analysts = [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh')).map(([name]) => name).join(' ');
  Object.assign(form, { report_profile_id: first.report_profile.id, customer: first.sample.customer || '', report_no: first.sample.report_no || '', analysis_date: reportDate(first.sample), analyst: analysts || first.sample.analyst || '' });
}
function edit(key: keyof Metadata) {
  if (!touched.has(key)) for (const report of reports.value) {
    const baseline = baselines.get(report.sample.id) || { ...report.sample };
    Object.assign(baseline, { [key]: report.sample[key] });
    baselines.set(report.sample.id, baseline);
  }
  touched.add(key);
  failedIds.value = [];
  message.value = '票面预览尚未保存；打印不会自动保存。';
}
async function loadList() {
  const generation = ++listGeneration;
  listController?.abort();
  const controller = new AbortController();
  listController = controller;
  loading.value = true;
  try {
    const params = new URLSearchParams({ paged: '1', limit: String(size.value), offset: String(page.value * size.value), type: 'all', status: 'reviewed', q: search.value.trim() });
    state.tags.forEach(tag => params.append('tag', tag));
    const result = await fetchSamples(params, controller.signal);
    if (!alive || generation !== listGeneration) return;
    total.value = result.total;
    if (page.value >= pages.value) { page.value = pages.value - 1; return; }
    samples.value = result.rows;
    result.rows.forEach(sample => known.set(sample.id, sample));
  } catch (error) { if (!controller.signal.aborted && alive) showError(error); }
  finally { if (generation === listGeneration) loading.value = false; }
}
async function loadBatch(): Promise<boolean> {
  const generation = ++batchGeneration;
  batchController?.abort();
  const controller = new AbortController();
  batchController = controller;
  batchLoading.value = true;
  batchError.value = '';
  try {
    const ids = [...selected.value];
    const payloads: Report[] = [];
    // Bound concurrent requests; never silently print a partial batch.
    for (let offset = 0; offset < ids.length; offset += 6) {
      if (!alive || controller.signal.aborted) return false;
      payloads.push(...await Promise.all(ids.slice(offset, offset + 6).map(id => fetchReport(id, controller.signal))));
    }
    if (!alive || generation !== batchGeneration) return false;
    const invalid = payloads.filter(report => report.sample.status !== 'reviewed');
    if (invalid.length) throw new Error(`以下样品已不在已审核状态，请取消勾选：${invalid.map(report => report.sample.lims_no || report.sample.id).join('、')}`);
    if (touched.size) for (const report of payloads) {
      if (!baselines.has(report.sample.id)) baselines.set(report.sample.id, { ...report.sample });
    }
    reports.value = payloads;
    payloads.forEach(report => known.set(report.sample.id, report.sample));
    initializeForm();
    return true;
  } catch (error) {
    if (!controller.signal.aborted && alive && generation === batchGeneration) {
      batchError.value = errorText(error);
      reports.value = [];
      showError(error, '报告读取失败');
    }
    return false;
  } finally { if (generation === batchGeneration) batchLoading.value = false; }
}
function select(id: number, use: boolean) {
  if (disabled.value) return;
  if (use && selected.value.includes(id)) return;
  if (!use && dirty.value && (selected.value.length === 1 || failedIds.value.includes(id))) {
    const warning = selected.value.length === 1 ? '取消最后一个样品会丢弃未保存的票面信息，是否继续？' : '该样品的票面信息尚未确认保存成功，取消勾选将放弃重试，是否继续？';
    if (!window.confirm(warning)) return;
  }
  selected.value = use ? [...new Set([...selected.value, id])] : selected.value.filter(value => value !== id);
  failedIds.value = failedIds.value.filter(sid => selected.value.includes(sid));
  if (use && failedIds.value.length) failedIds.value.push(id);
  if (!use) baselines.delete(id);
  if (!selected.value.length) { touched.clear(); baselines.clear(); message.value = ''; }
  void loadBatch();
}
function selectionChange(id: number, event: Event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  select(id, target.checked);
  // A confirmation can reject the browser's tentative checkbox change.
  void nextTick(() => { target.checked = selected.value.includes(id); });
}
function move(id: number, step: number) {
  if (disabled.value) return;
  const ids = [...selected.value];
  const index = ids.indexOf(id);
  const other = ids[index + step];
  if (index < 0 || other === undefined) return;
  ids[index] = other; ids[index + step] = id;
  selected.value = ids;
  reports.value = ids.map(sid => reports.value.find(report => report.sample.id === sid)).filter((report): report is Report => !!report);
}
async function saveMetadata() {
  if (disabled.value || !reports.value.length || reports.value.length !== selected.value.length || batchError.value) return;
  if (!touched.size) { message.value = '没有未保存的票面修改。'; return; }
  busy.value = true;
  const ids = failedIds.value.length ? [...failedIds.value] : [...selected.value];
  const edits = { ...form, customer: form.customer.trim(), report_no: form.report_no.trim(), analyst: form.analyst.trim() };
  const failed: number[] = [];
  const errors: string[] = [];
  // The endpoint replaces every field. Merge edits per sample, never copy the first
  // sample's untouched metadata over the rest of the batch.
  for (const id of ids) {
    if (!alive) break;
    const report = reports.value.find(item => item.sample.id === id);
    if (!report) { failed.push(id); errors.push(`#${id}: 报告未读取`); continue; }
    try {
      const fresh = await fetchReport(id);
      if (!alive) return;
      if (fresh.sample.status !== 'reviewed') throw new Error('样品已不在已审核状态，请重新读取报告');
      for (const key of touched) {
        const empty = key === 'report_profile_id' ? null : '';
        const current = fresh.sample[key] ?? empty;
        if (current !== ((baselines.get(id) || report.sample)[key] ?? empty) && current !== edits[key]) {
          throw new Error('票面信息已被其他操作修改；草稿已保留且未覆盖服务器内容，请取消勾选后重新选择并核对修改');
        }
      }
      const sample = fresh.sample;
      const saved: Metadata = {
        report_profile_id: touched.has('report_profile_id') ? edits.report_profile_id : sample.report_profile_id ?? null,
        customer: touched.has('customer') ? edits.customer : sample.customer || '',
        report_no: touched.has('report_no') ? edits.report_no : sample.report_no || '',
        analysis_date: touched.has('analysis_date') ? edits.analysis_date : sample.analysis_date || '',
        analyst: touched.has('analyst') ? edits.analyst : sample.analyst || '',
      };
      // Reject the write when the sample changed between the fetch above and now.
      const payload = typeof sample.updated_at === 'string' && sample.updated_at
        ? { ...saved, expected_updated_at: sample.updated_at } : saved;
      const written = await write(`/api/samples/${id}/report-meta`, payload);
      if (!alive) return;
      Object.assign(report, fresh);
      Object.assign(report.sample, saved);
      if (typeof written.updated_at === 'string') report.sample.updated_at = written.updated_at;
      baselines.set(id, { ...report.sample });
      if (touched.has('report_profile_id')) {
        report.report_profile = meta.value?.report_profiles.find(profile => profile.id === payload.report_profile_id) || meta.value?.report_profiles[0] || report.report_profile;
      }
    } catch (error) { failed.push(id); errors.push(`#${id}: ${errorText(error)}`); }
  }
  if (!alive) return;
  failedIds.value = failed;
  if (failed.length) {
    message.value = `已保存 ${ids.length - failed.length}/${ids.length} 个；未确认成功：${failed.map(id => '#' + id).join('、')}。再次保存仅重试这些样品。`;
    showError(new Error(errors.join('\n')), '整组保存未全部成功');
  } else { touched.clear(); baselines.clear(); message.value = `✓ 已保存到 ${selected.value.length} 个样品`; }
  busy.value = false;
}
async function saveArrangement(ids: number[], suffix: string, body: unknown) {
  if (disabled.value) return;
  busy.value = true;
  const failures: string[] = [];
  for (const id of ids) {
    if (!alive) return;
    try { await write(`/api/samples/${id}/${suffix}`, body); }
    catch (error) { failures.push(`#${id}: ${errorText(error)}`); }
  }
  if (!alive) return;
  if (failures.length) showError(new Error(failures.join('\n')), '编排未全部保存');
  await loadBatch();
  busy.value = false;
}
function order(id: number, analyteId: number, step: number) {
  const ids = reports.value.find(report => report.sample.id === id)?.groups.map(group => group.analyte_id).filter((aid): aid is number => typeof aid === 'number') || [];
  const index = ids.indexOf(analyteId);
  const other = ids[index + step];
  if (index < 0 || other === undefined) return;
  ids[index] = other; ids[index + step] = analyteId;
  void saveArrangement([id], 'report-order', { analyte_ids: ids });
}
function printUse(id: number, key: string, use: boolean) {
  const report = reports.value.find(item => item.sample.id === id);
  if (!report) return;
  const excludes = new Set(report.manual_report ? report.report_rows.filter(row => row.include === false).map(row => `m:${row.item.toLowerCase()}`) : report.groups.filter(group => group.print === false).map(group => group.key));
  // Exclusions for the other result source may not have a visible checkbox.
  if (report.sample.report_excludes) {
    try {
      const stored: unknown = JSON.parse(report.sample.report_excludes);
      if (!Array.isArray(stored) || !stored.every((item: unknown) => typeof item === 'string')) throw new Error('打印排除列表格式无效');
      for (const item of stored as string[]) excludes.add(item);
    } catch (error) { showError(error); return; }
  }
  if (use) excludes.delete(key); else excludes.add(key);
  void saveArrangement([id], 'report-print', { excludes: [...excludes] });
}
function clearPrintMode() {
  document.body.classList.remove('print-raw', 'print-final');
  document.getElementById('ticket-page-style')?.remove();
}
async function print(kind: 'raw' | 'final') {
  if (!canPrint.value) return;
  busy.value = true;
  try {
    if (!await loadBatch() || mixedWater(reports.value) || !reports.value.length) return;
    await nextTick();
    if (!alive || state.page !== 'report') return;
    clearPrintMode();
    document.body.classList.add(kind === 'raw' ? 'print-raw' : 'print-final');
    const style = document.createElement('style');
    style.id = 'ticket-page-style';
    style.textContent = kind === 'raw' ? '@page { size: A4 landscape; margin: 8mm; }' : '@page { size: A5 portrait; margin: 7mm; }';
    document.head.appendChild(style);
    window.print();
  } catch (error) { clearPrintMode(); showError(error); }
  finally { busy.value = false; }
}
async function exportExcel() {
  const id = selected.value[0];
  if (selected.value.length !== 1 || !id || disabled.value) return;
  if (dirty.value && !window.confirm('Excel 导出使用已保存的票面信息，不包含当前未保存预览。继续导出？')) return;
  try { await download(`/api/excel/reports/${id}`); } catch (error) { showError(error); }
}
async function focusSample() {
  if (state.page !== 'report' || !state.currentSampleId || selected.value.includes(state.currentSampleId) || disabled.value) return;
  try {
    const report = await fetchReport(state.currentSampleId);
    if (!alive || state.page !== 'report' || report.sample.id !== state.currentSampleId || selected.value.includes(report.sample.id)) return;
    if (report.sample.status !== 'reviewed') return;
    known.set(report.sample.id, report.sample);
    select(report.sample.id, true);
  } catch (error) { if (alive) showError(error); }
}
watch([dirty, busy], ([edited, saving]) => markDirty('reports', edited || saving), { flush: 'sync' });
watch([search, size, () => state.tags.join('\u0000')], () => { page.value = 0; void loadList(); });
watch(page, () => void loadList());
watch(() => state.refreshRevision, () => {
  if (!dirty.value && !disabled.value) { void loadList(); void loadBatch(); void fetchMeta().then(value => { if (alive) meta.value = value; }).catch(showError); }
});
watch([() => state.page, () => state.currentSampleId], () => void focusSample());
onMounted(async () => {
  window.addEventListener('afterprint', clearPrintMode);
  try { meta.value = await fetchMeta(); templateId.value = meta.value.default_order_template_id || ''; } catch (error) { showError(error); }
  if (alive) { void loadList(); void focusSample(); }
});
onBeforeUnmount(() => { alive = false; listController?.abort(); batchController?.abort(); window.removeEventListener('afterprint', clearPrintMode); clearPrintMode(); markDirty('reports', false); });
defineExpose({ print, saveMetadata });
</script>

<template>
  <section id="page-report" class="page" :class="{ active: state.page === 'report' }">
    <div class="panel report-print-workspace">
      <div class="report-queue-toolbar noprint"><h2>报告编排</h2><input id="report-search" v-model="search" type="search" placeholder="搜索已审核样品"><label>每页 <select id="report-page-size" v-model.number="size"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option></select></label><span class="results-pager"><button id="report-page-prev" type="button" :disabled="page === 0 || loading" @click="page--">上一页</button><span id="report-page-label">{{ page + 1 }} / {{ pages }}</span><button id="report-page-next" type="button" :disabled="page + 1 >= pages || loading" @click="page++">下一页</button></span><span id="report-count">已审核 {{ total }} 个，当前 {{ total ? page * size + 1 : 0 }}-{{ Math.min((page + 1) * size, total) }} · 已选 {{ selected.length }} 个</span></div>
      <TagFilter id="report-tag-filter" class="noprint" :known="meta?.sample_tags || []" />
      <div class="report-print-layout noprint"><div id="report-samples" class="report-sample-list" :aria-busy="loading || batchLoading">
        <div v-for="sample in displayed" :key="sample.id" class="report-sample-option" :data-sid="sample.id" @click.self="select(sample.id, true)"><input type="checkbox" :value="sample.id" :checked="selected.includes(sample.id)" :disabled="disabled" :aria-label="`选择 ${sample.name}`" @change="selectionChange(sample.id, $event)"><span class="report-selection-order" @click="select(sample.id, true)">{{ selected.includes(sample.id) ? selected.indexOf(sample.id) + 1 : '' }}</span><span class="report-sample-identity" @click="select(sample.id, true)"><b>{{ sample.name || '未填来样序号' }}</b><em>{{ sample.category || '未填样品名称' }}</em></span><small @click="select(sample.id, true)">{{ sample.lims_no || '#' + sample.id }} · {{ sample.reviewer || '已审核' }}</small><span class="report-sample-move"><template v-if="selected.includes(sample.id)"><button type="button" data-step="-1" :disabled="disabled || selected.indexOf(sample.id) === 0" title="前移" @click="move(sample.id, -1)">↑</button><button type="button" data-step="1" :disabled="disabled || selected.indexOf(sample.id) === selected.length - 1" title="后移" @click="move(sample.id, 1)">↓</button></template></span></div><p v-if="!displayed.length" class="hint">{{ loading ? '正在读取样品…' : '没有匹配的已审核样品' }}</p>
      </div><p class="hint">这里只显示已审核样品。勾选后会在下方同时展开全部样品内容；使用卡片或样品标题中的上下按钮调整整组报告顺序。</p><p v-if="batchError" class="hint" role="alert">{{ batchError }} <button type="button" :disabled="disabled" @click="loadBatch">重试读取</button></p></div>
      <input id="r-sample" type="hidden" :value="selected[0] || ''" @change="focusSample"><input id="r-sample-search" type="hidden" :value="reports[0] ? `#${reports[0].sample.id} ${reports[0].sample.name}` : ''">
      <div class="report-compose noprint" :hidden="!selected.length">
        <div class="row report-compose-toolbar"><button id="r-edit-sample" type="button" hidden @click="navigate('intake', selected[0])">样品资料</button><button id="r-enter-data" type="button" hidden @click="navigate('data', selected[0])">录入数据</button><span id="r-status-info" class="page-status-info"><span class="sample-status reviewed">已选 {{ reports.length }} 个已审核样品</span></span></div>
        <section id="r-regular-details" class="calculation-details"><div class="calculation-title"><h3 id="r-calculation-title">所选样品结果编排</h3><label class="noprint">通用顺序 <select id="r-order-template" v-model="templateId" :disabled="disabled"><option value="">系统默认</option><option v-for="item in meta?.result_order_templates || []" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><button id="r-order-apply" class="noprint" type="button" :disabled="disabled || !reports.length" @click="saveArrangement([...selected], 'report-order', { order_template_id: templateId || null, analyte_ids: [] })">应用到所选样品</button><button id="r-order-default" type="button" title="清除所选样品的手工微调，恢复各自选择的通用顺序" :disabled="disabled || !reports.length" @click="saveArrangement([...selected], 'report-order', { analyte_ids: [] })">清除手工调整</button></div>
          <CalculationDetails :reports="reports" :busy="disabled" @move="move" @order="order" @reset="(id: number) => saveArrangement([id], 'report-order', { analyte_ids: [] })" @print-use="printUse" />
        </section><section id="r-special-details" class="calculation-details" hidden></section>
        <div class="report-meta"><label>报告版式 <select id="r-report-profile" v-model="form.report_profile_id" :disabled="disabled" @change="edit('report_profile_id')"><option v-for="profile in meta?.report_profiles || []" :key="profile.id || 0" :value="profile.id">{{ profile.name }} · {{ profile.company_name_cn }}</option></select></label><label>来样单位 <input id="r-customer" v-model="form.customer" placeholder="可留空" :disabled="disabled" @input="edit('customer')"></label><label>报告编号 <input id="r-report-no" v-model="form.report_no" placeholder="如 0005547" :disabled="disabled" @input="edit('report_no')"></label><label>分析日期 <input id="r-analysis-date" v-model="form.analysis_date" type="date" :disabled="disabled" @input="edit('analysis_date')"></label><label>分析人员 <input id="r-analyst" v-model="form.analyst" :disabled="disabled" @input="edit('analyst')"></label><label>审核人员 <input id="r-reviewer" :value="uniqueSampleValues(reports, 'reviewer')" readonly disabled title="由实际执行审核的用户自动填写，不能手工修改"></label><button id="r-save-meta" type="button" :disabled="disabled || !reports.length || !!batchError" :title="`保存到全部 ${selected.length} 个样品`" @click="saveMetadata">保存整组票面信息</button><span id="r-meta-msg" role="status">{{ message || `票面信息将统一应用到全部 ${selected.length} 个样品` }}</span></div>
        <div class="report-actions"><button id="r-excel-export" type="button" :disabled="selected.length !== 1 || disabled || !!batchError" :title="selected.length > 1 ? '单样品 Excel 请只保留一个勾选样品' : ''" @click="exportExcel">导出 Excel 报告</button><button id="r-print-raw" type="button" :disabled="!canPrint" :title="mixedWater(reports) ? '水质样与其他样品请分开选择后打印' : '打印当前预览，不保存票面信息'" @click="print('raw')">打印合并原始分析记录（{{ selected.length ? `${selected.length}个样品 / ` : '' }}A4横向）</button><button id="r-print-final" type="button" :disabled="!canPrint" title="打印当前预览，不保存票面信息" @click="print('final')">打印分析报告票（A5纵向）</button></div>
      </div>
      <div class="ticket-preview-shell"><RawTicket :reports="preview" /></div><div class="ticket-preview-shell final-preview"><FinalTicket :reports="preview" /></div>
    </div>
  </section>
</template>
