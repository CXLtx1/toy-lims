<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { request, download, upload } from '../../api/client';
import { useAppState, refreshMeta, navigate as appNavigate } from '../../app/state';
import { showError } from '../../app/dialogs';
import { lockedStatuses, sampleKind, type EntryMeta, type Sample, type SampleDetail } from './types';
import { useEntryDrafts, type EntryDraft } from './use-entry-drafts';
import EntryGrid from './EntryGrid.vue';
import StatusHistory from './StatusHistory.vue';
import DataXrfPanel from '../instruments/DataXrfPanel.vue';

const app = useAppState();
const meta = ref<EntryMeta | null>(null), loading = ref(false), errorText = ref(''), message = ref('');
const search = ref(''), options = ref<Sample[]>([]), pickerOpen = ref(false), selectedOption = ref(-1), fileInput = ref<HTMLInputElement | null>(null);
const stageOrder = ['received', 'queued', 'measuring', 'partially_done', 'completed', 'reviewed'];
const actions: Record<string, string> = { received: '登记样品', queued: '制样完成', measuring: '开始测量', completed: '确认测量完成' };
let loadSequence = 0, metaSequence = 0, searchSequence = 0, searchTimer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
const refreshTimers = new Map<number, ReturnType<typeof setTimeout>>();
const store = useEntryDrafts(id => {
  if (disposed) return;
  clearTimeout(refreshTimers.get(id));
  refreshTimers.set(id, setTimeout(() => { refreshTimers.delete(id); if (app.currentSampleId === id && active.value) void load(); }, 300));
});
const active = computed(() => app.page === 'data');
const draft = computed(() => app.currentSampleId == null ? undefined : store.drafts.get(app.currentSampleId));
const sample = computed(() => draft.value?.detail.sample);
const readonly = computed(() => !sample.value || lockedStatuses.includes(sample.value.status) || !!draft.value?.busy);
const stageLocked = computed(() => ['received', 'queued'].includes(sample.value?.status || ''));
const transitions = computed(() => sample.value && !stageLocked.value ? (meta.value?.sample_transitions[sample.value.status] || []).filter(status => !['cancelled', 'reviewed'].includes(status) && meta.value?.allowed_status_targets.includes(status)) : []);
const preparationCards = computed(() => {
  const d = draft.value;
  if (!d) return [];
  if (d.detail.sample.workflow_type === 'special') return [{ name: d.detail.special?.method_name || '专项检测', steps: d.detail.special?.instrument || '按专项方法完成前处理', tasks: '' }];
  if (!d.detail.preps.length) return [{ name: '原样测量', steps: '无需溶样，请确认样品与仪器已就绪', tasks: '' }];
  return d.detail.preps.map(prep => {
    const tasks = d.detail.items.filter(task => task.preparation_id === prep.id);
    const analytes = [...new Set(tasks.map(task => task.analyte).filter(Boolean))].join('、') || '待测项目';
    const instruments = [...new Set(tasks.map(task => task.instrument).filter(Boolean))].join('、');
    return { name: prep.name, steps: (d.detail.sample.is_liquid ? [prep.dilution_label] : [prep.mass_g != null ? `称样 ${prep.mass_g} g` : '按方案称样', prep.volume_ml != null ? `定容 ${prep.volume_ml} mL` : '', prep.dilution_label]).filter(Boolean).join(' · '), tasks: analytes + (instruments ? ` · ${instruments}` : '') };
  });
});
const hint = computed(() => {
  if (message.value) return message.value;
  const s = sample.value;
  if (!s) return '';
  if (s.status === 'cancelled') return '样品已作废，数据只读';
  if (['reviewed', 'reported'].includes(s.status)) return '样品已锁定，数据只读';
  if (s.workflow_type === 'special') return stageLocked.value ? '开始测量后开放专项数据录入' : '原始字段失焦后自动保存并重新计算';
  return readonly.value ? 'XRF 正常显示；其余项目在开始测量后开放录入' : '';
});
async function load() {
  const id = app.currentSampleId;
  if (id == null || !active.value) return;
  const sequence = ++loadSequence, original = store.drafts.get(id), generation = original?.generation;
  loading.value = !original;
  try {
    const detail = await request<SampleDetail>(`/api/samples/${id}`);
    if (sequence !== loadSequence || app.currentSampleId !== id) return;
    const current = store.drafts.get(id);
    if (current && (store.dirty(current) || current.focused || current.generation !== generation)) {
      // Locks/status remain live even while editable values are protected from refresh.
      current.detail.sample = detail.sample;
    } else store.install(detail);
    errorText.value = '';
  } catch (error) { if (sequence === loadSequence) { errorText.value = error instanceof Error ? error.message : String(error); void showError(error); } }
  finally { if (sequence === loadSequence) loading.value = false; }
}
async function loadMeta() {
  const sequence = ++metaSequence;
  try { const data = await request<EntryMeta>('/api/meta'); if (sequence === metaSequence) meta.value = data; }
  catch (error) { if (sequence === metaSequence) void showError(error); }
}
async function findSamples(all = false) {
  const sequence = ++searchSequence, q = all ? '' : search.value.replace(/^#\d+\s*/, '').trim();
  try {
    const found = await request<Sample[]>(`/api/samples?limit=30&q=${encodeURIComponent(q)}`);
    if (sequence !== searchSequence) return;
    options.value = found; selectedOption.value = -1; pickerOpen.value = true;
  } catch (error) { if (sequence === searchSequence) void showError(error); }
}
function searchChanged() { searchSequence++; clearTimeout(searchTimer); searchTimer = setTimeout(() => { void findSamples(); }, 180); }
async function leave(page: 'data' | 'intake' | 'results', id: number) {
  const d = draft.value;
  if (d?.busy) return;
  if (d && store.dirty(d)) {
    if (readonly.value) { void showError('仍有未保存的草稿，请先处理保存错误。'); return; }
    store.setBusy(d, true);
    try { if (!await store.flush(d)) { void showError('仍有未保存的草稿，请先处理保存错误。'); return; } }
    finally { store.setBusy(d, false); }
  }
  pickerOpen.value = false; searchSequence++;
  appNavigate(page, id);
}
const navigate = leave;
function choose(next: Sample) { return leave('data', next.id); }
function pickerKey(event: KeyboardEvent) {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); selectedOption.value = Math.max(0, Math.min(options.value.length - 1, selectedOption.value + (event.key === 'ArrowDown' ? 1 : -1))); }
  else if (event.key === 'Enter') { const option = options.value[selectedOption.value]; if (option) { event.preventDefault(); choose(option); } }
  else if (event.key === 'Escape') { pickerOpen.value = false; searchSequence++; }
}
function transitionLabel(target: string): string {
  return stageOrder.indexOf(target) < stageOrder.indexOf(sample.value?.status || '') ? `退回${meta.value?.sample_statuses[target] || target}` : actions[target] || meta.value?.sample_statuses[target] || target;
}
async function transition(target: string) {
  const d = draft.value;
  if (!d || d.busy) return;
  const s = d.detail.sample;
  if (stageOrder.indexOf(target) < stageOrder.indexOf(s.status) && !confirm(`确定将样品从“${meta.value?.sample_statuses[s.status] || s.status}”退回到“${meta.value?.sample_statuses[target] || target}”吗？\n\n本次退回会写入审计历史；现有样品和检测记录不会自动删除。`)) return;
  store.setBusy(d, true);
  try {
    if (!await store.flush(d)) { void showError('仍有未保存的草稿，请先处理保存错误。'); return; }
    await request(`/api/samples/${s.id}/status`, { method: 'PUT', body: { status: target } }); await refreshMeta(); await loadMeta();
  }
  catch (error) { void showError(error); }
  finally { store.setBusy(d, false); if (app.currentSampleId === s.id) await load(); }
}
async function exportExcel() {
  const d = draft.value;
  if (!d || d.busy) return;
  if (store.dirty(d) && (readonly.value || !await store.flush(d))) { void showError('请先保存当前草稿，再导出数据。'); return; }
  try { await download(`/api/excel/samples/${d.detail.sample.id}/data`); } catch (error) { void showError(error); }
}
async function importExcel(event: Event) {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) return;
  const file = input.files?.[0], d = draft.value;
  input.value = '';
  if (!file || !d || readonly.value) return;
  if (!/\.xlsx$/i.test(file.name) || file.size > 20 * 1024 * 1024) { void showError('请选择不超过 20 MB 的 .xlsx 文件。'); return; }
  if (store.dirty(d)) { void showError('请先保存当前草稿并重新导出工作簿，再覆盖数据。'); return; }
  if (!confirm(`确定用“${file.name}”覆盖工作簿中列出的检测任务数据？此操作会替换这些任务的现有读数。`)) return;
  const id = d.detail.sample.id;
  store.setBusy(d, true);
  try {
    const result = await upload<{ message?: string }>(`/api/excel/samples/${id}/data`, file);
    // Only this sample's clean snapshot is invalidated; other sample drafts survive.
    store.drafts.delete(id);
    if (app.currentSampleId === id) message.value = result.message || '检测数据已覆盖';
    await refreshMeta();
  } catch (error) { void showError(error); }
  finally { store.setBusy(d, false); if (app.currentSampleId === id) await load(); }
}
function specialInput(d: EntryDraft, key: string, event: Event) {
  if (readonly.value || !(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement)) return;
  d.raw[key] = event.target.value; store.editSpecial(d);
}
function focusIn(d: EntryDraft, event: FocusEvent) { if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) d.focused = true; }
function focusOut(d: EntryDraft, event: FocusEvent) {
  const next = event.relatedTarget, current = event.currentTarget;
  d.focused = next instanceof HTMLElement && current instanceof HTMLElement && current.contains(next) && ['INPUT', 'TEXTAREA', 'SELECT'].includes(next.tagName);
}
watch(() => app.currentSampleId, (_id, previous) => {
  loadSequence++; pickerOpen.value = false; message.value = ''; errorText.value = ''; loading.value = false;
  if (previous != null) { const old = store.drafts.get(previous); if (old) { old.focused = false; if (!lockedStatuses.includes(old.detail.sample.status)) void store.flush(old); } }
  const s = draft.value?.detail.sample; search.value = s ? `#${s.id} ${s.name}` : '';
  if (active.value) void load();
}, { immediate: true });
watch(() => [app.page, app.refreshRevision], () => {
  if (active.value) { void load(); if (!meta.value) void loadMeta(); }
  else { loadSequence++; if (draft.value) { draft.value.focused = false; if (!readonly.value) void store.flush(draft.value); } }
}, { immediate: true });
watch(() => app.meta, () => { if (active.value) void loadMeta(); });
watch(() => sample.value?.id, () => { if (sample.value && !pickerOpen.value) search.value = `#${sample.value.id} ${sample.value.name}`; });
onBeforeUnmount(() => { disposed = true; loadSequence++; metaSequence++; searchSequence++; clearTimeout(searchTimer); for (const timer of refreshTimers.values()) clearTimeout(timer); });
</script>
<template>
  <section id="page-data" class="page" :class="{ active }"><div class="panel"><h2>原始数据录入</h2>
    <div class="row"><label>样品 <span class="sample-picker"><input id="d-sample-search" v-model="search" type="search" autocomplete="off" placeholder="搜索样品名称或编号" @focus="findSamples(true)" @input="searchChanged" @keydown="pickerKey" @blur="pickerOpen = false; searchSequence++"><input id="d-sample" type="hidden" :value="app.currentSampleId || ''"><span class="sample-options" :class="{ open: pickerOpen }"><button v-for="(option, index) in options" :key="option.id" type="button" :data-id="option.id" :class="{ active: selectedOption === index }" @mousedown.prevent="choose(option)"><b>#{{ option.id }}</b><span>{{ option.name }}</span><small>{{ sampleKind(option) }} · {{ option.created_at }}</small></button><span v-if="!options.length" class="empty">没有匹配的样品</span></span></span></label>
      <button id="d-edit-sample" type="button" title="编辑当前样品" :disabled="!sample" @click="sample && navigate('intake', sample.id)">样品资料</button><button id="d-view-report" type="button" :disabled="!sample" @click="sample && navigate('results', sample.id)">查看结果</button><button id="d-manual-result" type="button" :disabled="!sample || !['completed', 'reviewed'].includes(sample.status)" title="需要特权权限、操作原因和再次密码确认" @click="sample && navigate('results', sample.id)">手工补录结果</button><button id="d-excel-export" type="button" :disabled="!sample || draft?.busy" @click="exportExcel">导出数据 Excel</button><button id="d-excel-import" type="button" :disabled="readonly" :title="readonly ? '当前样品状态不能通过 Excel 覆盖检测数据' : ''" @click="fileInput?.click()">{{ draft?.busy ? '正在处理…' : 'Excel 覆盖数据' }}</button><input id="d-excel-file" ref="fileInput" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden @change="importExcel">
      <span id="d-info"><template v-if="sample">{{ sampleKind(sample) }} <span class="sample-status" :class="sample.status">{{ meta?.sample_statuses[sample.status] || sample.status }}</span><StatusHistory :sample="sample" :labels="meta?.sample_statuses" /></template></span><span id="d-status-actions" class="status-actions"><button v-for="target in transitions" :key="target" type="button" :data-status="target" :disabled="draft?.busy" @click="transition(target)">{{ transitionLabel(target) }}</button></span>
    </div>
    <p v-if="loading" class="hint" role="status">正在加载…</p><p v-if="errorText" class="bad-text" role="alert">{{ errorText }} <button type="button" @click="load">重试</button></p>
    <DataXrfPanel v-if="sample" :sample="sample" :revision="app.refreshRevision" :active="active" @changed="load" />
    <div id="d-stage-workspace" class="data-stage-workspace" :class="{ 'stage-locked': stageLocked, 'stage-unprepared': sample?.status === 'received', 'stage-prepared': sample?.status === 'queued' }">
      <div id="d-stage-overlay" class="data-stage-overlay" :hidden="!stageLocked"><div v-if="sample && stageLocked" class="data-stage-dialog"><span class="data-stage-kicker">{{ sample.status === 'received' ? '步骤 1 / 2' : '步骤 2 / 2' }}</span><h3>{{ sample.status === 'received' ? '请先按方案完成制样' : '制样已完成，是否开始测量？' }}</h3><p>{{ sample.status === 'received' ? '完成下列前处理后再进入待测阶段。XRF 数据仍会正常显示和同步。' : '请确认样品、仪器和方法均已就绪。开始测量后开放数据录入。' }}</p><div class="prep-method-list"><div v-for="(card, index) in preparationCards" :key="index" class="prep-method-card"><b>{{ card.name }}</b><span>{{ card.steps }}</span><small v-if="card.tasks">{{ card.tasks }}</small></div></div><button type="button" class="data-stage-action primary" :data-target="sample.status === 'received' ? 'queued' : 'measuring'" :disabled="draft?.busy" @click="transition(sample.status === 'received' ? 'queued' : 'measuring')">{{ sample.status === 'received' ? '制样完成' : '开始测量' }}</button><StatusHistory :sample="sample" :labels="meta?.sample_statuses" /></div></div>
      <div id="d-stage-content" class="data-stage-content" @focusin="draft && focusIn(draft, $event)" @focusout="draft && focusOut(draft, $event)">
        <div id="d-regular-panel" :hidden="sample?.workflow_type === 'special'"><EntryGrid v-if="draft && sample?.workflow_type !== 'special'" :key="sample?.id" :draft="draft" :store="store" :meta="meta" :readonly="readonly" /></div>
        <div id="d-special-panel" class="special-data-panel" :hidden="sample?.workflow_type !== 'special'"><template v-if="draft?.detail.special"><div class="special-form-head"><div><h3>{{ draft.detail.special.schema.title }}</h3><p>{{ draft.detail.special.method_name }} · {{ draft.detail.special.instrument }}</p></div><span class="sample-status" :class="draft.detail.special.status">{{ draft.detail.special.status === 'completed' ? '数据完整' : '待录完整' }}</span></div><fieldset v-for="(group, index) in draft.detail.special.schema.groups" :key="index" class="special-fieldset"><legend>{{ group.name }}</legend><div class="special-fields"><label v-for="field in group.fields" :key="field.key" class="special-field" :class="{ calculated: field.formula }"><span>{{ field.label }}{{ field.required ? ' *' : '' }}</span><span class="special-input-wrap"><input :data-key="field.key" :type="field.type || (field.unit ? 'number' : 'text')" :step="(field.type || (field.unit ? 'number' : 'text')) === 'number' ? 'any' : undefined" :value="field.formula ? draft.detail.special.calculated_data[field.key] : draft.raw[field.key] || ''" :disabled="!!field.formula || readonly" @input="specialInput(draft, field.key, $event)" @change="store.saveSpecial(draft)"><em v-if="field.unit">{{ field.unit }}</em></span></label></div></fieldset><label class="special-note">备注<textarea data-key="note" :value="draft.raw.note || ''" :disabled="readonly" @input="specialInput(draft, 'note', $event)" @change="store.saveSpecial(draft)"></textarea></label><p class="hint">带 * 的原始字段填齐后可标记检测完成；灰色字段由专项方法公式自动计算。</p><span role="status">{{ draft.error || (draft.saving ? '正在保存…' : draft.dirty ? '待保存' : draft.savedAt ? `✓ 已存 ${draft.savedAt}` : '') }}</span><button v-if="draft.error" type="button" :disabled="readonly" @click="store.saveSpecial(draft)">重试保存</button></template></div>
      </div>
    </div><div class="row"><span id="d-msg">{{ hint }}</span></div>
  </div></section>
</template>
