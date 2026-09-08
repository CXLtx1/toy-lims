<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import IntakePage from './features/intake/IntakePage.vue';
import DataEntryPage from './features/data-entry/DataEntryPage.vue';
import InstrumentsPage from './features/instruments/InstrumentsPage.vue';
import ResultsPage from './features/results/ResultsPage.vue';
import ReportsPage from './features/reports/ReportsPage.vue';
import AuditPage from './features/audit/AuditPage.vue';
import UsersPage from './features/users/UsersPage.vue';
import SettingsPage from './features/settings/SettingsPage.vue';
import AboutPage from './features/about/AboutPage.vue';
import { bootstrapSession, logout, network, request } from './api/client';
import type { CurrentSample, PageName, SiteStatus } from './api/types';
import { pages } from './api/types';
import { dialogs, finishAuthorization, showError } from './app/dialogs';
import { hasUnsavedChanges, initializeNavigation, navigate, pageLabels, refreshMeta, useAppState } from './app/state';

const state = useAppState();
const clock = ref<Date | null>(null);
const clientClockAtSync = ref(0);
const clockTick = ref(0);
const authorizationPassword = ref('');
const authorizationInput = ref<HTMLInputElement | null>(null);
const errorClose = ref<HTMLButtonElement | null>(null);
const contextOpen = ref(false);
const contextX = ref(0), contextY = ref(0);
const contextTarget = ref<Element | null>(null);
const latestChange = ref<SiteStatus['latest_change']>();
let source: EventSource | null = null;
let statusTimer: ReturnType<typeof setInterval> | undefined;
let clockTimer: ReturnType<typeof setInterval> | undefined;
let sampleGeneration = 0;
let stopNavigation: (() => void) | undefined;
let disposed = false;

const serverClock = computed(() => {
  // Reading the ticker ref wires this computed to the one-second interval.
  // eslint-disable-next-line @typescript-eslint/no-unused-expressions
  clockTick.value;
  if (!clock.value) return '服务器时间 --:--:--';
  const date = new Date(clock.value.getTime() + Date.now() - clientClockAtSync.value);
  const day = date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).replaceAll('/', '-');
  return `服务器 ${day} ${date.toLocaleTimeString('zh-CN', { hour12: false })}`;
});
const terminal = computed(() => state.meta?.terminal);
const user = computed(() => state.meta?.authorized_user || state.meta?.current_user);
const authorized = computed(() => !!state.meta?.authorized_user && terminal.value?.kind === 'standard');
const modalOpen = computed(() => dialogs.authorization || !!dialogs.error || !!document.querySelector('.dialog-backdrop:not([hidden])'));

function syncClock(value: string): void {
  const parsed = new Date(value);
  if (!Number.isNaN(parsed.getTime())) { clock.value = parsed; clientClockAtSync.value = Date.now(); }
}
function applyRevision(revision: number): void {
  if (!Number.isFinite(revision) || revision <= state.refreshRevision) return;
  if (state.dirty.size || network.writes || document.hidden) state.pendingRevision = Math.max(state.pendingRevision, revision);
  else { state.refreshRevision = revision; state.pendingRevision = 0; }
}
async function pollStatus(): Promise<void> {
  try {
    const result = await request<SiteStatus>('/api/site-status');
    if (result.server_time) syncClock(result.server_time);
    applyRevision(Number(result.revision || 0));
  } catch { /* SSE and the next poll retry collaboration status. */ }
}
function startEvents(): void {
  if (typeof EventSource === 'undefined' || source) return;
  source = new EventSource('/api/events');
  source.onmessage = event => {
    try {
      const value = JSON.parse(event.data) as Partial<SiteStatus>;
      if (typeof value.server_time === 'string') syncClock(value.server_time);
      applyRevision(Number(value.revision || 0));
    } catch { /* Ignore malformed event frames. */ }
  };
}
async function loadCurrentSample(id: number | null): Promise<void> {
  const generation = ++sampleGeneration;
  if (id === null) { state.currentSample = null; return; }
  try {
    const detail = await request<{ sample: CurrentSample }>(`/api/samples/${id}`);
    if (generation === sampleGeneration && !disposed) state.currentSample = detail.sample;
  } catch (error) { if (generation === sampleGeneration && !disposed) { state.currentSample = null; showError(error, '当前样品读取失败'); } }
}
function selectPage(page: PageName): void { navigate(page); contextOpen.value = false; }
async function clearAuthorization(): Promise<void> {
  try { await request('/api/authorization/clear', { method: 'POST', body: {} }); await refreshMeta(); }
  catch (error) { showError(error); }
}
async function submitAuthorization(): Promise<void> {
  if (!authorizationPassword.value || dialogs.authorizing) return;
  dialogs.authorizing = true; dialogs.authorizationError = '';
  try {
    await request('/api/authorize', { method: 'POST', body: { password: authorizationPassword.value }, authorize: false });
    authorizationPassword.value = '';
    finishAuthorization(true);
    void refreshMeta().catch(error => showError(error, '身份刷新失败'));
  } catch (error) {
    dialogs.authorizationError = error instanceof Error ? error.message : String(error);
    authorizationPassword.value = '';
    await nextTick(); authorizationInput.value?.focus();
  } finally { dialogs.authorizing = false; }
}
function cancelAuthorization(): void { if (!dialogs.authorizing) { authorizationPassword.value = ''; finishAuthorization(false); } }
function closeError(): void { dialogs.error = ''; }
function editable(target: EventTarget | null): boolean { return target instanceof Element && !!target.closest('input,textarea,select,[contenteditable="true"]'); }
function clickButton(id: string): boolean {
  const button = document.getElementById(id);
  if (!(button instanceof HTMLButtonElement) || button.disabled || button.hidden || button.offsetParent === null) return false;
  button.click(); return true;
}
function globalKey(event: KeyboardEvent): void {
  if (event.defaultPrevented || event.ctrlKey || event.altKey || event.metaKey || event.isComposing || modalOpen.value) return;
  if (event.key === 'Escape' && editable(event.target)) { event.preventDefault(); (event.target as HTMLElement).blur(); return; }
  if (editable(event.target)) return;
  if (/^[1-9]$/.test(event.key)) { const page = pages[Number(event.key) - 1]; if (page) { event.preventDefault(); selectPage(page); } return; }
  const searches: Partial<Record<PageName, string>> = { intake: 's-list-search', data: 'd-sample-search', instrument: 'xrf-scan-search', results: 'results-search', report: 'report-search', audit: 'audit-search' };
  if (event.key === '/') { const input = document.getElementById(searches[state.page] || ''); if (input instanceof HTMLInputElement) { event.preventDefault(); input.focus(); input.select(); } return; }
  if (event.key.toLowerCase() === 'n' && state.page === 'intake') { if (clickButton('s-new')) event.preventDefault(); return; }
  const exports: Partial<Record<PageName, string>> = { intake: 's-excel-overview', data: 'd-excel-export', results: 'results-excel', report: 'r-excel-export' };
  if (event.key.toLowerCase() === 'e') { const id = exports[state.page]; if (id && clickButton(id)) event.preventDefault(); return; }
  const pagers: Partial<Record<PageName, [string, string]>> = { intake: ['s-page-prev', 's-page-next'], results: ['results-page-prev', 'results-page-next'], report: ['report-page-prev', 'report-page-next'] };
  if (event.key === '[' || event.key === ']') { const ids = pagers[state.page]; if (ids && clickButton(ids[event.key === '[' ? 0 : 1])) event.preventDefault(); }
}
function selectedText(): string {
  const target = contextTarget.value;
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
    const start = target.selectionStart ?? 0, end = target.selectionEnd ?? 0;
    if (end > start) return target.value.slice(start, end);
  }
  return window.getSelection()?.toString() || '';
}
async function contextCopy(): Promise<void> {
  const text = selectedText(); contextOpen.value = false;
  if (!text) return;
  try { await navigator.clipboard.writeText(text); }
  catch { showError('浏览器未允许自动复制，请使用 Ctrl+C。'); }
}
function openContext(event: MouseEvent): void {
  event.preventDefault(); contextTarget.value = event.target instanceof Element ? event.target : null;
  contextX.value = Math.max(6, Math.min(event.clientX, innerWidth - 316));
  contextY.value = Math.max(6, Math.min(event.clientY, innerHeight - 280));
  contextOpen.value = true; latestChange.value = undefined;
  const id = state.currentSampleId;
  if (id !== null) void request<SiteStatus>(`/api/site-status?entity_type=sample&entity_id=${id}`).then(result => { latestChange.value = result.latest_change ?? null; }).catch(() => { latestChange.value = null; });
}
async function initialize(): Promise<void> {
  try {
    const session = await bootstrapSession();
    if (session.setup_required) { location.assign('/setup'); return; }
    if (!session.authenticated) { location.assign('/login'); return; }
    stopNavigation = initializeNavigation();
    await refreshMeta();
    state.ready = true;
    await Promise.all([pollStatus(), loadCurrentSample(state.currentSampleId)]);
    startEvents();
  } catch (error) { showError(error, '系统初始化失败'); }
}
watch(() => state.currentSampleId, id => { void loadCurrentSample(id); });
watch(() => [state.dirty.size, network.writes, document.hidden], () => {
  if (!state.dirty.size && !network.writes && !document.hidden && state.pendingRevision > state.refreshRevision) {
    state.refreshRevision = state.pendingRevision; state.pendingRevision = 0;
  }
});
watch(() => dialogs.authorization, async open => { document.body.classList.toggle('authorization-open', open); if (open) { await nextTick(); authorizationInput.value?.focus(); } });
watch(() => dialogs.error, async error => { if (error) { await nextTick(); errorClose.value?.focus(); } });
watch(() => network.sessionLost, lost => { if (lost) location.assign('/login'); });
function beforeUnload(event: BeforeUnloadEvent): void { if (hasUnsavedChanges()) event.preventDefault(); }
function visibility(): void { if (!document.hidden) { void pollStatus(); } }
onMounted(() => {
  void initialize();
  window.addEventListener('keydown', globalKey);
  window.addEventListener('beforeunload', beforeUnload);
  window.addEventListener('contextmenu', openContext);
  window.addEventListener('mousedown', event => { if (!(event.target instanceof Element) || !event.target.closest('#site-context-menu')) contextOpen.value = false; });
  document.addEventListener('visibilitychange', visibility);
  statusTimer = setInterval(pollStatus, 15000); clockTimer = setInterval(() => clockTick.value++, 1000);
});
onBeforeUnmount(() => { disposed = true; source?.close(); clearInterval(statusTimer); clearInterval(clockTimer); stopNavigation?.(); window.removeEventListener('keydown', globalKey); window.removeEventListener('beforeunload', beforeUnload); window.removeEventListener('contextmenu', openContext); document.removeEventListener('visibilitychange', visibility); });
</script>

<template>
  <Teleport to="body">
    <header>
      <h1 class="site-brand"><img src="../../server/static/mes.png?v=20260902" alt=""><span>LabFlow 化验室执行系统</span></h1>
      <nav><button v-for="page in pages" :key="page" class="tab" :class="{ active: state.page === page }" :data-page="page" type="button" @click="selectPage(page)">{{ pageLabels[page] }}</button></nav>
      <button id="current-sample" type="button" :hidden="!state.currentSample" title="返回当前样品资料" @click="state.currentSample && navigate('intake', state.currentSample.id)">{{ state.currentSample?.lims_no || `#${state.currentSample?.id}` }} · {{ state.currentSample?.name }}</button>
      <time id="server-clock" :datetime="clock?.toISOString() || ''" title="服务器时间">{{ serverClock }}</time>
      <div class="session-identity"><span id="current-terminal" :data-kind="terminal?.kind">{{ terminal ? `${terminal.name} · ${terminal.kind === 'admin' ? '管理终端' : terminal.kind === 'personal' ? '个人终端' : '普通终端'}` : '' }}</span><span id="current-user">{{ user ? `当前用户：${user.display_name || user.username}` : terminal?.kind === 'standard' ? '浏览模式 · 修改时验证用户' : '' }}</span></div>
      <button id="clear-authorization" type="button" :hidden="!authorized" @click="clearAuthorization">结束授权</button>
      <form class="logout-form" @submit.prevent="logout().catch(showError)"><button type="submit">退出终端</button></form>
    </header>
    <main v-if="state.ready">
      <IntakePage /><DataEntryPage /><InstrumentsPage /><ResultsPage /><ReportsPage /><AuditPage /><UsersPage /><SettingsPage /><AboutPage />
    </main>
    <main v-else><section class="panel"><p class="hint">正在连接 LabFlow…</p></section></main>
    <datalist id="sample-tag-options"><option v-for="tag in state.meta?.sample_tags || []" :key="tag.name" :value="tag.name" /></datalist>
    <footer class="site-footer"><b>LabFlow</b><span>Laboratory MES · 实验室执行系统</span></footer>

    <div id="site-context-menu" class="site-context-menu" role="menu" :hidden="!contextOpen" :style="{ left: `${contextX}px`, top: `${contextY}px` }">
      <button id="ctx-copy" type="button" role="menuitem" :disabled="!selectedText()" @click="contextCopy"><span>复制</span><kbd>Ctrl+C</kbd></button><div class="context-separator"></div>
      <div id="ctx-sample-status" class="context-sample-status" role="status"><b v-if="state.currentSample">{{ state.currentSample.lims_no || `#${state.currentSample.id}` }}&#x3000;{{ state.currentSample.name }}</b><b v-else>尚未选择样品</b><small>{{ state.currentSample ? `当前状态：${state.meta?.sample_statuses[state.currentSample.status] || state.currentSample.status}` : '请先在来样页选择样品' }}</small></div>
      <div class="context-separator"></div><div id="ctx-last-change" class="context-last-change" role="status"><b>当前样品 · 上一次修改</b><small v-if="latestChange === undefined">正在读取……</small><small v-else-if="!latestChange">尚无修改记录</small><template v-else><small>{{ latestChange.created_at }} · {{ latestChange.display_name || latestChange.username }}</small><div class="context-change-list"><div v-for="change in latestChange.changes.slice(0, 6)" :key="change.label"><span>{{ change.label }}</span><del>{{ change.before ?? '—' }}</del><i>→</i><ins>{{ change.after ?? '—' }}</ins></div></div></template></div>
      <div class="context-separator"></div><div class="context-page-title">快速切换</div><div class="context-page-buttons"><button v-for="page in pages.slice(0, 5)" :key="page" type="button" role="menuitem" :class="{ active: state.page === page }" @click="selectPage(page)">{{ pageLabels[page] }}</button></div>
    </div>

    <section id="authorization-dialog" class="authorization-dialog" role="dialog" aria-modal="true" aria-labelledby="authorization-title" aria-describedby="authorization-explanation" :hidden="!dialogs.authorization" @keydown.esc.prevent.stop="cancelAuthorization">
      <div class="authorization-mark" aria-hidden="true">权限</div><h2 id="authorization-title">需要用户授权</h2><p id="authorization-explanation">{{ dialogs.explanation }}</p>
      <form id="authorization-form" @submit.prevent="submitAuthorization"><label for="authorization-password">用户密码</label><input id="authorization-password" ref="authorizationInput" v-model="authorizationPassword" type="password" autocomplete="current-password" required :disabled="dialogs.authorizing"><div id="authorization-error" class="authorization-error" role="alert" aria-live="polite">{{ dialogs.authorizationError }}</div><div class="authorization-actions"><button id="authorization-cancel" type="button" :disabled="dialogs.authorizing" @click="cancelAuthorization">取消</button><button id="authorization-confirm" type="submit" class="primary" :disabled="dialogs.authorizing">{{ dialogs.authorizing ? '正在核验…' : '确认授权' }}</button></div></form>
    </section>
    <div id="error-dialog-backdrop" class="dialog-backdrop" :hidden="!dialogs.error" @mousedown.self="closeError" @keydown.esc.prevent.stop="closeError"><section class="error-dialog" role="alertdialog" aria-modal="true" aria-labelledby="error-dialog-title" aria-describedby="error-dialog-message"><button id="error-dialog-x" class="dialog-x" type="button" aria-label="关闭" @click="closeError">×</button><h2 id="error-dialog-title">{{ dialogs.title }}</h2><div id="error-dialog-message">{{ dialogs.error }}</div><div class="dialog-actions"><button id="error-dialog-close" ref="errorClose" type="button" class="primary" @click="closeError">知道了</button></div></section></div>
  </Teleport>
</template>
