<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { download } from '../../api/client';
import { markDirty, useAppState } from '../../app/state';
import { showError } from '../../app/dialogs';
import { errorText, fetchMeta, fetchReport, fetchSamples, write, type FeatureMeta, type Group, type Measurement, type Report, type Sample } from '../reports/model';
import TagFilter from './TagFilter.vue';
import ResultDetail, { type ManualDraft } from './ResultDetail.vue';
import OverrideAuthorization from './OverrideAuthorization.vue';
import XrfTargetDialog from './XrfTargetDialog.vue';

const state = useAppState();
const meta = ref<FeatureMeta | null>(null);
const samples = ref<Sample[]>([]);
const search = ref('');
const size = ref(50);
const page = ref(0);
const total = ref(0);
const templateId = ref<number | ''>('');
const selected = reactive(new Set<number>());
const expanded = ref<number[]>([]);
const details = reactive(new Map<number, Report>());
const drafts = reactive(new Map<number, ManualDraft>());
const detailErrors = reactive(new Map<number, string>());
const detailLoading = reactive(new Set<number>());
const loading = ref(false);
const busy = ref(false);
const targetId = ref<number | null>(null);
const authorization = ref<InstanceType<typeof OverrideAuthorization> | null>(null);
const pages = computed(() => Math.max(1, Math.ceil(total.value / size.value)));
const allChecked = computed(() => !!samples.value.length && samples.value.every(sample => selected.has(sample.id)));
const someChecked = computed(() => samples.value.some(sample => selected.has(sample.id)));
const dirty = computed(() => [...drafts.values()].some(draft => draft.editing));
let listGeneration = 0;
let listController: AbortController | undefined;
const detailControllers = new Map<number, AbortController>();
let alive = true;

function draftFor(id: number): ManualDraft {
  let draft = drafts.get(id);
  if (!draft) { draft = reactive({ editing: false, rows: [] }); drafts.set(id, draft); }
  return draft;
}
async function loadDetail(id: number) {
  if (!alive || drafts.get(id)?.editing || !expanded.value.includes(id)) return;
  detailControllers.get(id)?.abort();
  const controller = new AbortController();
  detailControllers.set(id, controller); detailLoading.add(id); detailErrors.delete(id);
  try {
    const report = await fetchReport(id, controller.signal);
    if (!alive || controller.signal.aborted || !expanded.value.includes(id) || drafts.get(id)?.editing) return;
    details.set(id, report); draftFor(id);
    const sample = samples.value.find(item => item.id === id);
    if (sample) Object.assign(sample, report.sample);
  } catch (error) { if (!controller.signal.aborted && alive) { detailErrors.set(id, errorText(error)); showError(error, '结果读取失败'); } }
  finally { if (detailControllers.get(id) === controller) { detailControllers.delete(id); detailLoading.delete(id); } }
}
async function loadList() {
  if (!alive) return;
  const generation = ++listGeneration;
  listController?.abort();
  const controller = new AbortController(); listController = controller;
  loading.value = true;
  try {
    const params = new URLSearchParams({ paged: '1', limit: String(size.value), offset: String(page.value * size.value), type: 'all', status: 'queued,measuring,partially_done,completed,reviewed', q: search.value.trim() });
    state.tags.forEach(tag => params.append('tag', tag));
    const result = await fetchSamples(params, controller.signal);
    if (!alive || generation !== listGeneration) return;
    total.value = result.total;
    if (page.value >= pages.value) { page.value = pages.value - 1; return; }
    samples.value = result.rows;
    // Off-page drafts stay in the parent map; only clean off-page details are evicted.
    const visible = new Set(result.rows.map(sample => sample.id));
    for (const id of [...expanded.value]) if (!visible.has(id) && !drafts.get(id)?.editing) collapse(id, false);
    if (!busy.value && !targetId.value) await Promise.all(expanded.value.filter(id => visible.has(id)).map(id => loadDetail(id)));
  } catch (error) { if (!controller.signal.aborted && alive) showError(error); }
  finally { if (generation === listGeneration) loading.value = false; }
}
function collapse(id: number, ask = true): boolean {
  if (busy.value) return false;
  if (ask && drafts.get(id)?.editing && !window.confirm('收起会丢弃该样品未保存的手工补录，是否继续？')) return false;
  detailControllers.get(id)?.abort(); detailControllers.delete(id); detailLoading.delete(id);
  expanded.value = expanded.value.filter(value => value !== id);
  details.delete(id); drafts.delete(id); detailErrors.delete(id);
  return true;
}
function collapseAll() {
  if (busy.value) return;
  if (dirty.value && !window.confirm('全部收起会丢弃未保存的手工补录，是否继续？')) return;
  for (const id of [...expanded.value]) collapse(id, false);
}
async function expand(sample: Sample, event?: MouseEvent) {
  if (event?.target instanceof Element && event.target.closest('input')) return;
  if (event?.ctrlKey || event?.metaKey) { toggleSelection(sample.id); return; }
  if (expanded.value.includes(sample.id)) { collapse(sample.id); return; }
  expanded.value.push(sample.id); draftFor(sample.id);
  await loadDetail(sample.id);
  await nextTick();
  document.querySelector(`#results-list .result-detail-row[data-sid="${sample.id}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
function toggleSelection(id: number) { if (selected.has(id)) selected.delete(id); else selected.add(id); }
function selectAll(event: Event) {
  if (!(event.target instanceof HTMLInputElement)) return;
  for (const sample of samples.value) if (event.target.checked) selected.add(sample.id); else selected.delete(sample.id);
}
async function mutate(id: number, url: string, body: unknown, method = 'PUT'): Promise<boolean> {
  if (busy.value) return false;
  busy.value = true;
  try { await write(url, body, method); if (!alive) return false; await loadDetail(id); return true; }
  catch (error) { if (alive) showError(error); return false; }
  finally { busy.value = false; }
}
function unit(id: number, group: Group, current: string) {
  const units = group.available_units || [];
  const next = units[(Math.max(0, units.indexOf(current)) + 1) % units.length];
  if (next && next !== current) void mutate(id, `/api/samples/${id}/result-unit`, { key: group.key, unit: next });
}
function useResult(id: number, row: Measurement, use: boolean) {
  const url = row.xrf_value_id ? `/api/xrf/values/${row.xrf_value_id}/report-use` : row.sample_analyte_id ? `/api/sample-analytes/${row.sample_analyte_id}/report-use` : null;
  if (url) void mutate(id, url, { use });
}
async function review(id: number) {
  if (busy.value || drafts.get(id)?.editing) return;
  const sample = details.get(id)?.sample;
  if (!sample || !['reviewed', 'completed'].includes(sample.status)) return;
  if (sample.status === 'completed') { if (await mutate(id, `/api/samples/${id}/status`, { status: 'reviewed' })) void loadList(); return; }
  const reason = window.prompt('请输入审核退回原因。该原因会写入审计历史。', '结果需复核')?.trim();
  if (!reason) return;
  busy.value = true;
  try {
    if (!await authorization.value?.confirm('审核退回是特权操作。请输入具备“审核退回与手工结果补录”权限的用户密码。')) return;
    if (!alive) return;
    await write(`/api/samples/${id}/status`, { status: 'completed', reason });
    await loadDetail(id);
  } catch (error) { if (alive) showError(error); }
  finally { busy.value = false; }
}
function editManual(id: number) {
  const report = details.get(id);
  if (!report || busy.value || drafts.get(id)?.editing || !['completed', 'reviewed'].includes(report.sample.status) || report.sample.workflow_type === 'special') return;
  detailControllers.get(id)?.abort();
  const draft = draftFor(id);
  draft.rows = report.report_rows.map(row => ({ item: row.item, result: row.result == null ? '' : String(row.result), unit: row.unit || '', note: row.note || '', include: true }));
  draft.rows.push({ item: '', result: '', unit: '', note: '', include: true });
  draft.editing = true;
  void nextTick(() => document.querySelector<HTMLInputElement>(`#results-list .result-detail-row[data-sid="${id}"] .mr-item`)?.focus());
}
function cancelManual(id: number) {
  if (busy.value) return;
  const draft = drafts.get(id);
  if (draft) { draft.editing = false; draft.rows = []; }
  void loadDetail(id);
}
async function saveManual(id: number, restore = false) {
  if (busy.value) return;
  const report = details.get(id); const draft = drafts.get(id);
  if (!report || !draft) return;
  if (restore && !report.manual_report) { cancelManual(id); return; }
  const rows = draft.rows.map(row => ({ item: row.item.trim(), result: row.result.trim(), unit: row.unit.trim(), note: row.note.trim(), include: true })).filter(row => row.item || row.result || row.unit || row.note);
  if (!restore && (!rows.length || rows.length > 200 || rows.some(row => !row.item || !row.result))) { showError(new Error('请填写 1 至 200 条结果，每条必须包含结果项目和报告结果。')); return; }
  if (restore && !window.confirm('确认删除手工补录内容并恢复系统计算结果？此操作会记录审计。')) return;
  const reason = window.prompt(restore ? '请输入恢复系统计算的原因。' : '请输入手工补录原因。该原因会写入审计记录。', restore ? '撤销手工补录' : '补录检测结果')?.trim();
  if (!reason) return;
  busy.value = true;
  try {
    if (!await authorization.value?.confirm('本次操作会改变最终结果，必须重新输入具备“审核退回与手工结果补录”权限的用户密码。本次确认仅用于这一次保存。')) return;
    if (!alive) return;
    const fresh = await fetchReport(id);
    if (!alive) return;
    if (fresh.sample.status !== report.sample.status || JSON.stringify(fresh.manual_report) !== JSON.stringify(report.manual_report) ||
        JSON.stringify(fresh.default_report_rows) !== JSON.stringify(report.default_report_rows)) {
      throw new Error('样品结果已被其他操作修改；手工草稿已保留，请取消补录后重新读取并核对结果。');
    }
    await write(`/api/reports/${id}/manual`, restore ? { reason } : { rows, reason }, restore ? 'DELETE' : 'PUT');
    draft.editing = false; draft.rows = [];
    await loadDetail(id);
  } catch (error) { if (alive) showError(error); }
  finally { busy.value = false; }
}
async function exportExcel() {
  if (!selected.size || busy.value) return;
  if (selected.size > 200) { showError(new Error('每次最多导出 200 个样品，请减少勾选。')); return; }
  if ([...selected].some(id => drafts.get(id)?.editing) && !window.confirm('导出使用已保存结果，不包含未保存的手工补录。继续？')) return;
  const params = new URLSearchParams({ sample_ids: [...selected].join(',') });
  if (templateId.value) params.set('template_id', String(templateId.value));
  try { await download(`/api/excel/results-report?${params}`); } catch (error) { showError(error); }
}
function escape(event: KeyboardEvent) {
  if (event.key !== 'Escape' || event.defaultPrevented || state.page !== 'results' || busy.value || targetId.value) return;
  if (event.target instanceof Element && event.target.closest('input,textarea,select,[contenteditable="true"],[role="dialog"]')) return;
  const id = expanded.value[expanded.value.length - 1];
  if (id !== undefined) { event.preventDefault(); collapse(id); }
}
watch([dirty, busy], ([edited, saving]) => markDirty('results', edited || saving), { flush: 'sync' });
watch([search, size, () => state.tags.join('\u0000')], () => { page.value = 0; void loadList(); });
watch(page, () => void loadList());
watch(() => state.refreshRevision, () => {
  if (!dirty.value && !busy.value && !targetId.value) { void loadList(); void fetchMeta().then(value => { if (alive) meta.value = value; }).catch(showError); }
});
onMounted(async () => {
  window.addEventListener('keydown', escape);
  try { meta.value = await fetchMeta(); } catch (error) { showError(error); }
  if (alive) void loadList();
});
onBeforeUnmount(() => { alive = false; listController?.abort(); detailControllers.forEach(controller => controller.abort()); window.removeEventListener('keydown', escape); markDirty('results', false); });
</script>
<template>
  <section id="page-results" class="page" :class="{ active: state.page === 'results' }">
    <div class="panel results-workspace"><div class="results-toolbar"><h2>检测结果</h2><input id="results-search" v-model="search" type="search" placeholder="搜索样品名称或编号"><button id="results-collapse-all" type="button" :disabled="!expanded.length || busy" @click="collapseAll">全部收起</button><button id="results-clear-selection" type="button" :disabled="!selected.size" @click="selected.clear()">全部取消</button><label>通用顺序 <select id="results-template" v-model="templateId"><option value="">系统默认</option><option v-for="item in meta?.result_order_templates || []" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><button id="results-excel" type="button" :disabled="!selected.size || busy" @click="exportExcel">导出结果报告 Excel</button><span id="results-count">共 {{ total }} 个，当前 {{ total ? page * size + 1 : 0 }}-{{ Math.min((page + 1) * size, total) }} · 已选 {{ selected.size }} 个</span><label>每页 <select id="results-page-size" v-model.number="size"><option :value="50">50</option><option :value="100">100</option><option :value="200">200</option></select></label><span class="results-pager"><button id="results-page-prev" type="button" :disabled="page === 0 || loading" @click="page--">上一页</button><span id="results-page-label">{{ page + 1 }} / {{ pages }}</span><button id="results-page-next" type="button" :disabled="page + 1 >= pages || loading" @click="page++">下一页</button></span></div>
      <TagFilter id="results-tag-filter" :known="meta?.sample_tags || []" />
      <div class="table-shell results-list-shell"><table id="results-list" class="data-grid" :aria-busy="loading"><thead><tr><th><input id="results-check-all" type="checkbox" aria-label="全选" :checked="allChecked" :indeterminate="someChecked && !allChecked" @change="selectAll"></th><th>LIMS 编号</th><th>来样序号</th><th>标签</th><th>样品名称</th><th>状态</th><th>结果摘要</th><th>审核</th><th></th></tr></thead><tbody>
        <template v-for="sample in samples" :key="sample.id"><tr class="result-row" :class="{ expanded: expanded.includes(sample.id) }" :data-sid="sample.id" :aria-expanded="expanded.includes(sample.id)" @click="expand(sample, $event)"><td><input class="result-select" type="checkbox" :checked="selected.has(sample.id)" :aria-label="`选择 ${sample.name}`" @change="toggleSelection(sample.id)"></td><td><b>{{ sample.lims_no || '#' + sample.id }}</b></td><td>{{ sample.name }}</td><td><div v-if="sample.tags?.length" class="result-summary result-tags"><span v-for="tag in sample.tags" :key="tag">{{ tag }}</span></div><template v-else>—</template></td><td>{{ sample.category || '—' }}</td><td><span class="sample-status" :class="sample.status">{{ meta?.sample_statuses[sample.status] || sample.status }}</span></td><td><div class="result-summary"><template v-if="sample.analyte_names"><span v-for="name in sample.analyte_names.split(', ').slice(0, 8)" :key="name">{{ name }}</span><small v-if="sample.analyte_names.split(', ').length > 8">+{{ sample.analyte_names.split(', ').length - 8 }}</small></template><i v-else>展开查看结果</i></div></td><td>{{ sample.reviewer || (sample.status === 'completed' ? '待审核' : '—') }}</td><td><button class="result-expand" type="button">{{ expanded.includes(sample.id) ? '收起' : '展开' }}</button></td></tr>
          <tr v-if="expanded.includes(sample.id)" class="result-detail-row" :data-sid="sample.id"><td colspan="9"><p v-if="detailErrors.has(sample.id)" class="hint" role="alert">{{ detailErrors.get(sample.id) }} <button type="button" :disabled="busy || detailLoading.has(sample.id)" @click="loadDetail(sample.id)">重试读取</button></p>
            <ResultDetail v-if="details.get(sample.id)" :report="details.get(sample.id)!" :draft="draftFor(sample.id)" :statuses="meta?.sample_statuses || {}" :busy="busy || detailLoading.has(sample.id) || detailErrors.has(sample.id)" @review="review(sample.id)" @unit="(group: Group, current: string) => unit(sample.id, group, current)" @use="(row: Measurement, use: boolean) => useResult(sample.id, row, use)" @targets="targetId = sample.id" @edit="editManual(sample.id)" @cancel="cancelManual(sample.id)" @save="saveManual(sample.id)" @restore="saveManual(sample.id, true)" />
            <p v-else-if="!detailErrors.has(sample.id)" class="hint">正在读取结果明细…</p>
          </td></tr>
        </template><tr v-if="!samples.length"><td colspan="9" class="xrf-empty">{{ loading ? '正在读取样品…' : '没有已制样或后续阶段的样品' }}</td></tr>
      </tbody></table></div>
    </div>
    <OverrideAuthorization ref="authorization" />
    <XrfTargetDialog v-if="targetId" :sample-id="targetId" @close="targetId = null" @saved="() => { const id = targetId; targetId = null; if (id) loadDetail(id); }" />
  </section>
</template>
