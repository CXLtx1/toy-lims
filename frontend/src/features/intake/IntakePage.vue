<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { request, download, upload } from '../../api/client'
import { useAppState, refreshMeta, navigate, markDirty } from '../../app/state'
import { showError } from '../../app/dialogs'
import PreparationEditor from './PreparationEditor.vue'
import { applyTemplate, detailDraft, newDraft, parseAnalytes, removesTasks, samplePayload, sampleType, templatePayload,
  type IntakeMeta, type MutationResult, type Preparation, type Sample, type SampleDetail, type SampleDraft, type SampleType, type StatusHistory } from './domain'

const app = useAppState()
const meta = ref<IntakeMeta | null>(null)
const samples = ref<Sample[]>([])
const total = ref(0), page = ref(0), pageSize = ref(50)
const typeFilter = ref<SampleType | 'all'>('all'), query = ref(''), showCancelled = ref(false)
const today = new Date().toLocaleDateString('sv-SE')
const dateFrom = ref(`${today.slice(0, 8)}01`), dateTo = ref(today), workspaceMessage = ref(''), message = ref('')
const editorOpen = ref(false), draft = ref<SampleDraft | null>(null), baseline = ref('')
const editingId = ref<number | null>(null), copiedId = ref<number | null>(null)
const original = ref<SampleDetail | null>(null)
const selectedTemplate = ref<number | ''>(''), tagInput = ref('')
const busy = ref(false), loading = ref(false)
const editor = ref<HTMLElement | null>(null), nameInput = ref<HTMLInputElement | null>(null), searchInput = ref<HTMLInputElement | null>(null)
const createFile = ref<HTMLInputElement | null>(null), planFile = ref<HTMLInputElement | null>(null)
const tagControl = ref<HTMLInputElement | null>(null)
let searchTimer: ReturnType<typeof setTimeout> | undefined
let listSequence = 0, detailSequence = 0, handledSampleId: number | null = null, returnY = 0
let listController: AbortController | null = null
let disposed = false
const dirty = computed(() => editorOpen.value && draft.value !== null && (JSON.stringify(draft.value) !== baseline.value || !!tagInput.value.trim()))
const locked = computed(() => editingId.value !== null && ['reviewed', 'reported', 'cancelled'].includes(original.value?.sample.status ?? ''))
const specialMethodLocked = computed(() => editingId.value !== null && Object.keys(original.value?.special?.raw_data ?? {}).length > 0)
const liquid = computed(() => draft.value?.type === 'liquid' || draft.value?.type === 'water_quality')
const analytes = computed(() => parseAnalytes(draft.value?.analyteText ?? '', meta.value?.analytes ?? []))
const xrfAnalytes = computed(() => parseAnalytes(draft.value?.xrfText ?? '', meta.value?.analytes ?? []))
const xrfMethods = computed(() => meta.value?.methods.filter(m => m.itype === 'xrf' && (m.active !== 0 || m.id === draft.value?.xrfMethodId)) ?? [])
const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const filterTypes: { value: SampleType | 'all'; label: string }[] = [{ value: 'all', label: '全部' }, { value: 'solid', label: '固体样' }, { value: 'liquid', label: '液体样' }, { value: 'water_quality', label: '水质样' }, { value: 'special', label: '其他样' }]
const formTypes: { value: SampleType; radio: string; label: string }[] = [{ value: 'solid', radio: '0', label: '固体' }, { value: 'liquid', radio: '1', label: '液体样' }, { value: 'water_quality', radio: 'water_quality', label: '水质样' }, { value: 'special', radio: 'special', label: '其他样' }]
const stages: Record<string, number> = { received: 0, queued: 1, measuring: 2, partially_done: 2, completed: 3, reviewed: 4 }
const stageLabels = ['未制样', '未测量', '测量中', '待审核', '已审核']
const actions: Record<string, string> = { received: '登记样品', queued: '制样完成', measuring: '开始测量', completed: '确认测量完成', reviewed: '审核确认', cancelled: '作废样品' }
const compactActions: Record<string, string> = { received: '登记', queued: '制样', measuring: '开始测量', completed: '测量完成', reviewed: '审核', cancelled: '作废' }
watch(dirty, value => markDirty('intake', value), { flush: 'sync' })
function statusLabel(status: string): string { return meta.value?.sample_statuses[status] ?? status }
function rollback(current: string, target: string): boolean { return (stages[target] ?? -1) < (stages[current] ?? -1) }
function transitionLabel(current: string, target: string): string { return rollback(current, target) ? `退回${statusLabel(target)}` : actions[target] ?? statusLabel(target) }
function nextStatuses(sample: Sample): string[] { return (meta.value?.sample_transitions[sample.status] ?? []).filter(status => !['cancelled', 'reviewed'].includes(status) && meta.value?.allowed_status_targets.includes(status)) }
function canCancel(sample: Sample): boolean { return !!meta.value?.sample_transitions[sample.status]?.includes('cancelled') && meta.value.allowed_status_targets.includes('cancelled') }
function history(sample: Sample): StatusHistory[] { return sample.status_history?.length ? sample.status_history : sample.status_operator ? [{ action: sample.status_action ?? '', operator: sample.status_operator, at: sample.status_changed_at }] : [] }
function historyLabel(item: StatusHistory): string { return item.rollback ? item.action === 'completed' ? '撤回审核' : `退回${statusLabel(item.action)}` : compactActions[item.action] ?? actions[item.action] ?? item.action }
function cardAnalytes(sample: Sample): string[] { return sample.workflow_type === 'special' ? sample.special_method_name ? [sample.special_method_name] : [] : (sample.analyte_names ?? '').split(', ').filter(Boolean) }
function kindClass(sample: Sample): string { return sampleType(sample).replace('_', '-') }
function kindLabel(sample: Sample): string { return ({ special: '其他', water_quality: '水质', liquid: '液体', solid: '固体' })[sampleType(sample)] }
function confirmDiscard(): boolean { return !dirty.value || window.confirm('当前样品有未保存的修改，确定放弃这些修改吗？') }
function clean(): void { baseline.value = JSON.stringify(draft.value); markDirty('intake', false) }
async function readMeta(): Promise<void> { const result = await request<IntakeMeta>('/api/meta'); if (!disposed) meta.value = result }
async function loadSamples(): Promise<void> {
  const sequence = ++listSequence
  listController?.abort(); listController = new AbortController()
  const params = new URLSearchParams({ paged: '1', limit: String(pageSize.value), offset: String(page.value * pageSize.value), type: typeFilter.value,
    include_cancelled: showCancelled.value ? '1' : '0', q: query.value.trim() })
  app.tags.forEach(tag => params.append('tag', tag))
  try {
    const result = await request<{ rows: Sample[]; total: number }>(`/api/samples?${params}`, { signal: listController.signal })
    if (sequence !== listSequence || disposed) return
    samples.value = result.rows; total.value = result.total
    const last = Math.max(0, Math.ceil(result.total / pageSize.value) - 1)
    if (page.value > last) { page.value = last; await loadSamples() }
  } catch (error) { if (sequence === listSequence && !disposed && !listController?.signal.aborted) showError(error) }
}
async function refreshAfterWrite(): Promise<void> {
  await refreshMeta()
  await readMeta()
  await loadSamples()
}
async function focusEditor(select = false): Promise<void> {
  await nextTick()
  editor.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  if (select) nameInput.value?.select()
}
async function openSample(id: number, copy = false, force = false): Promise<void> {
  if (!meta.value || busy.value || !force && !confirmDiscard()) return
  const sequence = ++detailSequence, draftAtRequest = JSON.stringify(draft.value), tagAtRequest = tagInput.value
  loading.value = true
  try {
    const detail = await request<SampleDetail>(`/api/samples/${id}`)
    if (disposed || busy.value || app.page !== 'intake' || sequence !== detailSequence || JSON.stringify(draft.value) !== draftAtRequest || tagInput.value !== tagAtRequest) return
    returnY = window.scrollY
    original.value = detail; editingId.value = copy ? null : id; copiedId.value = copy ? id : null
    draft.value = detailDraft(detail, meta.value, copy)
    selectedTemplate.value = ''; tagInput.value = ''; message.value = ''; clean(); editorOpen.value = true
    if (!copy) { handledSampleId = id; navigate('intake', id) }
    await focusEditor(copy)
  } catch (error) { if (sequence === detailSequence && !disposed) showError(error) }
  finally { if (sequence === detailSequence) loading.value = false }
}
async function newSample(): Promise<void> {
  if (!meta.value || busy.value || !confirmDiscard()) return
  ++detailSequence; loading.value = false; returnY = window.scrollY
  editingId.value = null; copiedId.value = null; original.value = null
  draft.value = newDraft(meta.value, typeFilter.value === 'all' ? 'solid' : typeFilter.value, app.tags)
  selectedTemplate.value = ''; tagInput.value = ''; message.value = ''; clean(); editorOpen.value = true
  handledSampleId = app.currentSampleId
  await focusEditor(); nameInput.value?.focus()
}
function closeEditor(): void {
  if (busy.value || !confirmDiscard()) return
  ++detailSequence; loading.value = false; editorOpen.value = false; editingId.value = null; clean()
}
function setType(type: SampleType): void {
  if (!draft.value || locked.value || busy.value) return
  draft.value.type = type
}
function workflowDisabled(type: SampleType): boolean {
  return locked.value || busy.value || editingId.value !== null && ((type === 'special') !== (original.value?.sample.workflow_type === 'special'))
}
function enableXrf(): void { if (draft.value?.xrf && !draft.value.xrfMethodId && xrfMethods.value.length === 1) draft.value.xrfMethodId = xrfMethods.value[0]?.id ?? null }
function preset(target: 'elements' | 'oxides' | 'clear'): void {
  if (draft.value) draft.value.xrfText = { elements: 'Si, Al, Fe, Ca, Mg, Ti, Na, K, Mn, P', oxides: 'SiO2, Al2O3, Fe2O3, CaO, MgO, TiO2, Na2O, K2O, MnO, P2O5', clear: '' }[target]
}
function addTag(): void {
  if (!draft.value || locked.value || busy.value) return
  const tag = tagInput.value.trim().replace(/^#+/, '').trim()
  if (!tag) return
  if (tag.length > 30) { showError('标签不能超过 30 个字符。'); return }
  if (draft.value.tags.length >= 20) { showError('每个样品最多添加 20 个标签。'); return }
  if (!draft.value.tags.some(t => t.toLowerCase() === tag.toLowerCase())) draft.value.tags.push(tag)
  tagInput.value = ''; tagControl.value?.focus()
}
function filterTag(event: Event): void {
  if (!(event.target instanceof HTMLSelectElement)) return
  const tag = event.target.value
  if (tag && !app.tags.includes(tag)) app.tags = [...app.tags, tag]
  event.target.value = ''
}
function useTemplate(): void {
  if (locked.value || busy.value || !confirmDiscard()) return
  const template = meta.value?.templates.find(t => t.id === selectedTemplate.value)
  if (template && draft.value && meta.value) applyTemplate(draft.value, template, meta.value)
}
async function saveTemplate(): Promise<void> {
  if (!draft.value || !meta.value || busy.value) return
  const name = window.prompt('模板名称', draft.value.name.trim() || '新模板')?.trim()
  if (!name) return
  busy.value = true
  try {
    const result = await request<MutationResult>('/api/templates', { method: 'POST', body: templatePayload(draft.value, meta.value, name) })
    await refreshMeta(); await readMeta(); selectedTemplate.value = result.id; message.value = '方案已保存为模板'
  } catch (error) { showError(error) } finally { busy.value = false }
}
async function saveSample(): Promise<void> {
  if (!draft.value || !meta.value || busy.value || locked.value) return
  if (tagInput.value.trim()) { addTag(); if (tagInput.value.trim()) return }
  busy.value = true
  try {
    const body = samplePayload(draft.value, meta.value), id = editingId.value
    if (id !== null && original.value?.sample.updated_at) body.expected_updated_at = original.value.sample.updated_at
    if (id !== null && original.value && draft.value.type !== 'special' && removesTasks(original.value, body.preps as Preparation[]) &&
      !window.confirm('本次修改会删除检测任务或更换仪器/方法，对应的已有读数和结果可能被清除。确定保存吗？')) return
    ++detailSequence; loading.value = false
    const result = await request<MutationResult>(id === null ? '/api/samples' : `/api/samples/${id}`, { method: id === null ? 'POST' : 'PUT', body })
    handledSampleId = result.id; editorOpen.value = false; editingId.value = null; clean()
    workspaceMessage.value = `${id === null ? '已创建' : '已保存'} #${result.id}`
    navigate('intake', result.id)
    await refreshAfterWrite()
  } catch (error) { showError(error) } finally { busy.value = false }
}
async function changeStatus(sample: Sample, target: string): Promise<void> {
  if (busy.value) return
  if (editingId.value === sample.id && dirty.value) { showError('请先保存或放弃当前样品的修改，再变更状态。'); return }
  if (rollback(sample.status, target) && !window.confirm(`确定将样品从“${statusLabel(sample.status)}”退回到“${statusLabel(target)}”吗？\n\n本次退回会写入审计历史；现有样品和检测记录不会自动删除。`)) return
  busy.value = true
  try {
    await request(`/api/samples/${sample.id}/status`, { method: 'PUT', body: { status: target } })
    if (editingId.value === sample.id && original.value) original.value.sample.status = target
    await refreshAfterWrite()
  }
  catch (error) { showError(error) } finally { busy.value = false }
}
async function cancelSample(sample: Sample): Promise<void> {
  if (busy.value || editingId.value === sample.id && !confirmDiscard()) return
  const reason = window.prompt('请输入作废原因。样品和历史结果将保留，但不能继续录入。', '登记错误')?.trim()
  if (!reason) return
  busy.value = true
  try {
    await request(`/api/samples/${sample.id}`, { method: 'DELETE', body: { reason } })
    if (editingId.value === sample.id) { editorOpen.value = false; editingId.value = null; clean() }
    if (app.currentSampleId === sample.id) { handledSampleId = null; navigate('intake', null) }
    await refreshAfterWrite()
  } catch (error) { showError(error) } finally { busy.value = false }
}
async function exportFile(url: string): Promise<void> { try { await download(url) } catch (error) { showError(error) } }
function exportOverview(): void {
  if (!dateFrom.value || !dateTo.value) { showError('请选择总览的开始和结束日期。'); return }
  if (dateFrom.value > dateTo.value) { showError('开始日期不能晚于结束日期。'); return }
  const params = new URLSearchParams({ date_from: dateFrom.value, date_to: dateTo.value, type: typeFilter.value, q: query.value.trim(), include_cancelled: showCancelled.value ? '1' : '0' })
  void exportFile(`/api/excel/samples-overview?${params}`)
}
async function importExcel(event: Event, overwrite: boolean): Promise<void> {
  const input = event.target
  if (!(input instanceof HTMLInputElement)) return
  const file = input.files?.[0], id = editingId.value
  if (!file || busy.value || overwrite && id === null) { input.value = ''; return }
  try {
    if (!file.name.toLowerCase().endsWith('.xlsx')) throw new Error('请选择 .xlsx 格式的业务工作簿。')
    if (file.size > 20 * 1024 * 1024) throw new Error('文件超过 20 MB，无法上传。')
    const confirmation = overwrite ? `确定用“${file.name}”覆盖当前样品方案？删除或改变的检测任务可能清除对应结果。` : `确定根据“${file.name}”新建样品？系统会生成新的 LIMS 编号。`
    if (!window.confirm(confirmation) || !confirmDiscard()) return
    busy.value = true
    const result = await upload<MutationResult>(overwrite ? `/api/excel/samples/${id}/detail` : '/api/excel/samples/create', file)
    editorOpen.value = false; clean()
    await refreshAfterWrite()
    busy.value = false
    await openSample(overwrite ? id! : result.id, false, true)
    message.value = result.message ?? (overwrite ? '样品方案已覆盖' : `已创建 ${result.lims_no ?? result.id}`)
    workspaceMessage.value = message.value
  } catch (error) { showError(error) } finally { input.value = ''; busy.value = false }
}
function summaryKey(event: KeyboardEvent, id: number): void {
  if (event.target instanceof Element && event.target.closest('button')) return
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); void openSample(id) }
}
function summaryClick(event: MouseEvent, id: number): void { if (!(event.target instanceof Element) || !event.target.closest('button')) void openSample(id) }
function keydown(event: KeyboardEvent): void {
  if (event.defaultPrevented || app.page !== 'intake' || document.querySelector('.dialog-backdrop:not([hidden]),.authorization-dialog:not([hidden])')) return
  const typing = event.target instanceof Element && !!event.target.closest('input,select,textarea,[contenteditable="true"]')
  if (event.key === 'Escape') {
    if (typing && event.target instanceof HTMLElement) { event.target.blur(); return }
    if (editorOpen.value) { event.preventDefault(); closeEditor(); if (!editorOpen.value) window.scrollTo({ top: returnY }) }
    return
  }
  // Global navigation/search/export shortcuts belong to the root; these IDs remain its targets.
}
watch(query, () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { page.value = 0; void loadSamples() }, 180) })
watch([typeFilter, showCancelled, pageSize, () => app.tags.join('\u0000')], () => { page.value = 0; if (meta.value) void loadSamples() })
watch(() => app.currentSampleId, id => {
  if (app.page === 'intake' && meta.value && id !== null && id !== handledSampleId && !dirty.value && !busy.value) void openSample(id, false, true)
})
watch(() => app.page, value => {
  if (value !== 'intake' || !meta.value) return
  if (!dirty.value) void loadSamples()
  if (app.currentSampleId !== null && app.currentSampleId !== handledSampleId && !dirty.value && !busy.value) void openSample(app.currentSampleId, false, true)
})
watch(() => app.refreshRevision, async () => {
  if (!meta.value || dirty.value || busy.value || app.page !== 'intake') return
  try {
    await readMeta(); await loadSamples()
    if (editorOpen.value && editingId.value !== null && !dirty.value && !busy.value) await openSample(editingId.value, false, true)
  } catch (error) { showError(error) }
})
onMounted(async () => {
  document.addEventListener('keydown', keydown)
  try { await readMeta(); await loadSamples(); if (app.page === 'intake' && app.currentSampleId !== null) await openSample(app.currentSampleId, false, true) }
  catch (error) { showError(error) }
})
onBeforeUnmount(() => { disposed = true; ++detailSequence; ++listSequence; listController?.abort(); clearTimeout(searchTimer); document.removeEventListener('keydown', keydown); markDirty('intake', false) })
defineExpose({ newSample, editSample: openSample, refresh: loadSamples, exportOverview, focusSearch: () => searchInput.value?.focus(), dirty })
</script>

<template>
  <section id="page-intake" class="page" :class="{ active: app.page === 'intake' }">
    <div class="panel sample-workspace" :class="{ editing: editorOpen }">
      <div class="sample-toolbar">
        <button id="s-new" type="button" class="primary" :disabled="!meta || busy" @click="newSample">+ 新建样品</button>
        <button id="s-excel-create" type="button" :disabled="busy || !meta" @click="createFile?.click()">从 Excel 新建</button>
        <input id="s-excel-create-file" ref="createFile" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden @change="importExcel($event, false)">
        <div id="s-type-filter" class="segmented"><button v-for="type in filterTypes" :key="type.value" type="button" :class="{ active: typeFilter === type.value }" :data-type="type.value" @click="typeFilter = type.value">{{ type.label }}</button></div>
        <input id="s-list-search" ref="searchInput" v-model="query" class="table-search" type="search" placeholder="搜索名称、编号或元素">
        <label class="inline"><input id="s-show-cancelled" v-model="showCancelled" type="checkbox"> 显示已作废</label>
        <span class="excel-date-range"><label>从 <input id="s-excel-date-from" v-model="dateFrom" type="date"></label><label>至 <input id="s-excel-date-to" v-model="dateTo" type="date"></label></span>
        <button id="s-excel-overview" type="button" @click="exportOverview">导出总览</button><span id="s-workspace-msg" role="status">{{ loading ? '正在读取样品…' : workspaceMessage }}</span>
      </div>
      <div class="sample-tag-row">
        <div id="s-tag-filter" class="sample-tag-filter" data-tag-filter><b>标签筛选</b><select aria-label="添加标签筛选" @change="filterTag"><option value="">+ 添加标签</option><option v-for="tag in meta?.sample_tags.filter(t => !app.tags.includes(t.name)) ?? []" :key="tag.name" :value="tag.name">#{{ tag.name }}</option></select><button v-if="app.tags.length" type="button" class="sample-tag-clear" @click="app.tags = []">清除</button><div class="sample-tag-filter-selected"><button v-for="tag in app.tags" :key="tag" type="button" class="active" :data-tag="tag" title="移除筛选" @click="app.tags = app.tags.filter(t => t !== tag)">#{{ tag }} ×</button><span v-if="!app.tags.length" class="hint">未选择</span></div></div>
        <span class="pager sample-top-pager"><span id="s-list-count">共 {{ total }} 个，当前 {{ total ? page * pageSize + 1 : 0 }}-{{ Math.min((page + 1) * pageSize, total) }}</span><label>每页 <select id="s-page-size" v-model="pageSize"><option v-for="size in [20, 50, 100, 200]" :key="size" :value="size">{{ size }}</option></select></label><button id="s-page-prev" type="button" title="上一页" :disabled="page === 0" @click="page--; loadSamples()">‹</button><span id="s-page-label">{{ page + 1 }} / {{ pages }}</span><button id="s-page-next" type="button" title="下一页" :disabled="page + 1 >= pages" @click="page++; loadSamples()">›</button></span>
      </div>

      <div id="sample-editor-panel" ref="editor" class="sample-editor" :hidden="!editorOpen">
        <template v-if="draft && meta">
          <div class="section-head"><h2 id="s-form-title">{{ copiedId !== null ? `复制 #${copiedId} 为新样品` : editingId !== null ? `编辑 #${editingId} ${original?.sample.name ?? ''}` : '新建样品' }}</h2><button id="s-cancel-edit" type="button" :disabled="busy" @click="closeEditor">收起</button></div>
          <div class="row">
            <label>来样序号 <input id="s-name" ref="nameInput" v-model="draft.name" placeholder="如 RY2888" :disabled="locked || busy"></label>
            <label>样品名称 <input id="s-category" v-model="draft.category" list="s-categories" placeholder="如 Zn(OH)2沉淀" :disabled="locked || busy"><datalist id="s-categories"><option v-for="category in meta.categories" :key="category" :value="category" /></datalist></label>
            <label :hidden="draft.type === 'special'">模板 <select id="s-template" v-model="selectedTemplate" :disabled="locked || busy"><option value="">— 不使用 —</option><option v-for="template in meta.templates" :key="template.id" :value="template.id">{{ template.name }}</option></select><button id="s-apply-tpl" type="button" :disabled="locked || busy" @click="useTemplate">应用</button><button id="s-save-template" type="button" :disabled="busy" @click="saveTemplate">保存当前方案</button></label>
            <label>顺序模板 <select id="s-order-template" v-model="draft.orderTemplateId" :disabled="locked || busy"><option v-for="order in meta.result_order_templates" :key="order.id" :value="order.id">{{ order.name }}{{ order.is_default ? '（系统默认）' : '' }}</option></select></label>
            <label>类型 <label v-for="type in formTypes" :key="type.value" class="inline"><input type="radio" name="s-liquid" :value="type.radio" :checked="draft.type === type.value" :disabled="workflowDisabled(type.value)" @change="setType(type.value)"> {{ type.label }}</label></label>
            <label id="s-density-wrap" class="sample-density" :hidden="draft.type !== 'liquid'">液体密度 <span><input id="s-density" v-model="draft.density" type="number" min="0.000001" step="0.001" placeholder="可不填" :disabled="locked || busy"> g/mL</span><small>填写后可换算质量单位</small></label>
            <label class="inline" :hidden="draft.type === 'special'"><input id="s-xrf" v-model="draft.xrf" type="checkbox" :disabled="locked || busy" @change="enableXrf"> 打荧光(XRF粗扫)</label>
          </div>
          <div class="sample-tag-editor"><b>样品标签</b><div id="s-sample-tags" class="sample-tag-values"><button v-for="tag in draft.tags" :key="tag" type="button" :data-tag="tag" title="移除标签" :disabled="locked || busy" @click="draft.tags = draft.tags.filter(t => t !== tag)">#{{ tag }} ×</button><span v-if="!draft.tags.length" class="hint">暂无标签</span></div><input id="s-tag-input" ref="tagControl" v-model="tagInput" list="sample-tag-options" placeholder="输入或选择标签，如 实验样" :disabled="locked || busy" @keydown.enter.prevent="addTag"><button id="s-tag-add" type="button" :disabled="locked || busy" @click="addTag">添加标签</button></div>
          <div id="s-special-config" class="special-config" :hidden="draft.type !== 'special'"><h3>专项检测</h3><label>特殊方法 <select id="s-special-method" v-model="draft.specialMethodId" :disabled="locked || busy || specialMethodLocked"><option :value="null">— 选择专项方法 —</option><option v-for="method in meta.special_methods" :key="method.id" :value="method.id">{{ method.name }} · {{ method.instrument }}</option></select></label><p class="hint">专项样不建立溶样、定容和常规元素任务；原始数据与计算结果独立保存。</p></div>
          <div id="s-regular-config" :hidden="draft.type === 'special'">
            <div class="analyte-entry"><h3>溶样后待测元素 / 指标（不含 XRF）</h3><div class="row"><input id="s-analyte-text" v-model="draft.analyteText" placeholder="输入需要分配到 ICP、AAS、滴定等仪器的项目，如 Cu, Ag, Ni" :disabled="locked || busy"></div><div id="s-chips" class="tagbox"><span v-for="analyte in analytes.matched" :key="analyte.id" class="tag ok">{{ analyte.name }}</span><span v-for="(token, index) in analytes.unmatched" :key="index" class="tag bad">{{ token }}?</span></div></div>
            <div id="s-xrf-config" class="xrf-config" :hidden="!draft.xrf"><h3>XRF 方法与报告默认项目</h3><div class="row"><input id="s-xrf-text" v-model="draft.xrfText" placeholder="报告默认项目，可空，如 Fe, SiO2, CaO" style="width:min(680px,100%)" :disabled="locked || busy"><label>XRF 方法 <select id="s-xrf-method" v-model="draft.xrfMethodId" :disabled="locked || busy"><option :value="null">— 选择 XRF 方法 —</option><option v-for="method in xrfMethods" :key="method.id" :value="method.id">{{ method.name }}</option></select></label></div><div class="row xrf-presets"><span class="hint">快速口径：</span><button type="button" class="xrf-preset" data-target="s-xrf-text" data-preset="elements" :disabled="locked || busy" @click="preset('elements')">元素口径</button><button type="button" class="xrf-preset" data-target="s-xrf-text" data-preset="oxides" :disabled="locked || busy" @click="preset('oxides')">氧化物口径</button><button type="button" class="xrf-preset" data-target="s-xrf-text" data-preset="clear" :disabled="locked || busy" @click="preset('clear')">清空</button></div><div id="s-xrf-chips" class="tagbox"><span v-for="analyte in xrfAnalytes.matched" :key="analyte.id" class="tag ok">{{ analyte.name }}</span><span v-for="(token, index) in xrfAnalytes.unmatched" :key="index" class="tag">{{ token }}</span></div><p class="hint">仪器返回的全部定量项目都会保存；这里填写的项目默认参与最终结果计算（同一元素族先填的口径优先），之后可在结果页调整。</p></div>
            <h3>溶样（每一路 = 称样 → 定容 → 稀释 → 测定项目）</h3><p class="hint">每一路直接在横向看板中选择测定项目并分配仪器：点击标签可多选，再拖到或点击目标栏；拖到“不测”表示该溶样不建立这些项目的检测任务。</p>
            <PreparationEditor v-model="draft.preps" :meta="meta" :analyte-ids="analytes.matched.map(a => a.id)" :sample-name="draft.name" :liquid="liquid" :disabled="locked || busy" :default-instrument-map="draft.instrumentMap" />
          </div>
          <div class="editor-footer"><button id="s-excel-plan-export" type="button" :hidden="editingId === null" @click="exportFile(`/api/excel/samples/${editingId}/detail`)">导出样品方案</button><button id="s-excel-plan-import" type="button" :hidden="editingId === null" :disabled="locked || busy" @click="planFile?.click()">Excel 覆盖方案</button><input id="s-excel-plan-file" ref="planFile" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden @change="importExcel($event, true)"><span class="footer-spacer"></span><span id="s-msg" role="status">{{ locked ? '已审核、已出报告或已作废的样品不能直接修改' : message }}</span><button id="s-submit" class="primary" :disabled="locked || busy" @click="saveSample">{{ busy ? '正在保存…' : copiedId !== null ? '创建副本' : editingId !== null ? '保存修改' : '创建样品' }}</button></div>
        </template>
      </div>

      <div id="s-card-list" class="sample-card-list"><article v-for="sample in samples" :key="sample.id" class="sample-card" :class="[`status-${sample.status}`, { current: app.currentSampleId === sample.id, cancelled: sample.status === 'cancelled', expanded: editorOpen && editingId === sample.id }]" :data-sid="sample.id">
        <div class="sample-card-summary" role="button" tabindex="0" @click="summaryClick($event, sample.id)" @keydown="summaryKey($event, sample.id)">
          <div class="sample-identity"><span class="sample-lims-no">{{ sample.lims_no || `#${sample.id}` }}</span><span class="sample-name-block"><b>{{ sample.name }}</b><small v-if="sample.tags?.length"><i v-for="tag in sample.tags" :key="tag">#{{ tag }}</i></small></span><span class="sample-category" :class="{ empty: !sample.category }" :aria-hidden="!sample.category || undefined">{{ sample.category || '占位' }}</span><span class="sample-kind" :class="kindClass(sample)">{{ kindLabel(sample) }}</span><span v-if="sample.status !== 'cancelled'" class="sample-stage-track" :class="`stage-${stages[sample.status] ?? 0}`" :style="{ '--stage': stages[sample.status] ?? 0 }" :title="stageLabels[stages[sample.status] ?? 0]" :aria-label="stageLabels[stages[sample.status] ?? 0]"><i v-for="(_, index) in stageLabels" :key="index" :class="{ passed: index <= (stages[sample.status] ?? 0) }" /></span><span class="sample-status" :class="sample.status">{{ statusLabel(sample.status) }}</span></div>
          <div class="sample-analytes"><span v-for="(name, index) in cardAnalytes(sample)" :key="index">{{ name }}</span><i v-if="!cardAnalytes(sample).length">尚无待测项目</i></div>
          <div class="sample-card-meta"><span>{{ sample.workflow_type === 'special' ? sample.special_instrument || '专项检测' : `${sample.prep_count} 路溶样` }}</span><span v-if="sample.xrf">XRF</span><time>{{ sample.created_at }}</time><span v-if="history(sample).length" class="status-history"><span v-for="(item, index) in history(sample)" :key="index" class="status-history-item" :class="{ rollback: item.rollback, 'review-rollback': item.rollback && item.action === 'completed' }" :title="[item.at || '时间未知', item.reason].filter(Boolean).join(' · ')"><b>{{ historyLabel(item) }}</b><em>{{ item.operator || '系统' }}</em></span></span></div>
          <div class="sample-card-actions"><template v-if="sample.status !== 'cancelled'"><button class="enter-data" type="button" @click.stop="navigate('data', sample.id)">录数据</button><button v-for="status in nextStatuses(sample)" :key="status" class="status-next" :data-status="status" type="button" :disabled="busy" @click.stop="changeStatus(sample, status)">{{ transitionLabel(sample.status, status) }}</button><button class="duplicate" type="button" title="复制为新样品" :disabled="busy" @click.stop="openSample(sample.id, true)">复制新建</button><button v-if="canCancel(sample)" class="del" type="button" title="作废样品" :disabled="busy" @click.stop="cancelSample(sample)">作废</button><button class="expand" type="button" title="展开全部内容" :disabled="busy" @click.stop="openSample(sample.id)">⌄</button></template></div>
        </div>
      </article></div>
    </div>
  </section>
</template>
