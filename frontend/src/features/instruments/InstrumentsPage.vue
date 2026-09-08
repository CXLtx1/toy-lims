<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { request } from '../../api/client';
import { useAppState, markDirty, refreshMeta } from '../../app/state';
import { showError } from '../../app/dialogs';
import { finalStatuses, type Sample } from '../data-entry/types';
import { xrfValueText, type Monitor, type Scan, type StandardClient } from './types';
const app = useAppState();
const result = ref<Monitor | null>(null), query = ref(''), kind = ref('all'), match = ref('all'), pageSize = ref(25), page = ref(1);
const busy = ref(false), errorText = ref(''), expanded = ref(new Set<number>()), assignment = ref<Scan | null>(null), sampleQuery = ref(''), samples = ref<Sample[]>([]), assigning = ref(false), searching = ref(false);
const sampleInput = ref<HTMLInputElement | null>(null);
let sequence = 0, sampleSequence = 0, timer: ReturnType<typeof setTimeout> | undefined, sampleTimer: ReturnType<typeof setTimeout> | undefined, interval: ReturnType<typeof setInterval> | undefined;
const active = computed(() => app.page === 'instrument');
const state = computed(() => result.value?.client?.online === false ? 'offline' : result.value?.client?.state || 'idle');
const stateLabels: Record<string, string> = { offline: '离线', idle: '待机', reading: '测量中', uploading: '上传结果', error: '错误' };
const clientFields = computed(() => { const c = result.value?.client; return c ? [['终端', c.machine_name || c.client_id || 'XRF终端'], ['当前样品', c.current_sample], ['当前方法', c.current_method], ['当前批次', c.current_batch], ['运行编号', c.current_run_id], ['位置', c.current_position], ['开始时间', c.current_started_at], ['最近心跳', c.seen_at]] : []; });
function recent(client: StandardClient) { const r = client.recent_entry; return r ? `${r.at || ''} · ${r.items.join('，') || `${r.count || 0} 条读数`}${r.count > r.items.length ? ` 等 ${r.count} 条` : ''}` : '尚无录入'; }
async function load(silent = false) {
  if (!active.value) return;
  const current = ++sequence;
  busy.value = true;
  try {
    const params = new URLSearchParams({ page: String(page.value), limit: String(pageSize.value), q: query.value.trim(), kind: kind.value, match: match.value });
    const data = await request<Monitor>(`/api/xrf/monitor?${params}`);
    if (current !== sequence) return;
    result.value = data; page.value = data.page; errorText.value = '';
  } catch (error) { if (current === sequence) { errorText.value = error instanceof Error ? error.message : String(error); if (!silent) void showError(error); } }
  finally { if (current === sequence) busy.value = false; }
}
function searchChanged() { clearTimeout(timer); sequence++; busy.value = false; timer = setTimeout(() => { page.value = 1; void load(); }, 250); }
function filtersChanged() { page.value = 1; void load(); }
function toggle(id: number) { if (expanded.value.has(id)) expanded.value.delete(id); else expanded.value.add(id); }
function close() { if (assigning.value) return; assignment.value = null; sampleSequence++; searching.value = false; clearTimeout(sampleTimer); }
async function open(scan: Scan) { if (assigning.value) return; clearTimeout(sampleTimer); sampleSequence++; assignment.value = scan; sampleQuery.value = ''; samples.value = []; searching.value = true; await nextTick(); sampleInput.value?.focus(); void findSamples(); }
async function findSamples() {
  if (!assignment.value || !active.value) return;
  const current = ++sampleSequence, id = assignment.value?.id, q = sampleQuery.value.trim();
  searching.value = true;
  try {
    const data = await request<Sample[]>(`/api/samples?xrf=1&xrf_available=1&status=received,queued,measuring,partially_done,completed&limit=30&q=${encodeURIComponent(q)}`);
    if (current === sampleSequence && id === assignment.value?.id && q === sampleQuery.value.trim()) samples.value = data;
  } catch (error) { if (current === sampleSequence) void showError(error); }
  finally { if (current === sampleSequence) searching.value = false; }
}
function sampleChanged() { clearTimeout(sampleTimer); sampleSequence++; samples.value = []; searching.value = true; sampleTimer = setTimeout(() => { void findSamples(); }, 180); }
async function link(scan: Scan, sample?: Sample) {
  if (assigning.value || (scan.sample_status && finalStatuses.includes(scan.sample_status))) return;
  if (!sample && !confirm('确定解除该 XRF 扫描与 LIMS 样品的关联？')) return;
  assigning.value = true;
  markDirty(`xrf-assignment:${scan.id}`, true);
  try {
    await request(`/api/xrf/analyses/${scan.id}/sample`, { method: sample ? 'PUT' : 'DELETE', body: sample ? { sample_id: sample.id } : undefined });
    assignment.value = null; sampleSequence++; await refreshMeta(); await load();
  } catch (error) { void showError(error); } finally { assigning.value = false; markDirty(`xrf-assignment:${scan.id}`, false); }
}
function poll() { if (active.value && !document.hidden && !busy.value && !assignment.value) void load(true); }
watch(() => [app.page, app.refreshRevision], () => { if (active.value) void load(true); else { sequence++; busy.value = false; clearTimeout(timer); close(); } }, { immediate: true });
onMounted(() => { interval = setInterval(poll, 2000); document.addEventListener('visibilitychange', poll); });
onBeforeUnmount(() => { sequence++; sampleSequence++; clearInterval(interval); clearTimeout(timer); clearTimeout(sampleTimer); document.removeEventListener('visibilitychange', poll); });
</script>
<template>
  <section id="page-instrument" class="page" :class="{ active }"><div class="panel instrument-monitor">
    <div class="section-head"><h2>标准仪器客户端</h2><button id="instrument-refresh" type="button" :disabled="busy" @click="load()">刷新</button></div>
    <p v-if="errorText" class="bad-text" role="alert">{{ errorText }}（保留上次数据）</p>
    <div id="standard-client-status" class="standard-client-list"><article v-for="client in result?.standard_clients || []" :key="client.client_id" class="standard-client-card"><div class="standard-client-head"><span class="instrument-state connected">已连接</span><strong>{{ client.instrument_name || '标准仪器' }}</strong><small>{{ client.machine_name || client.client_id || '标准客户端' }}</small></div><div class="standard-client-fields"><div><b>网络位置</b><span>{{ client.network_position || '—' }}</span></div><div><b>当前用户</b><span>{{ client.display_name || client.username || '未登录' }}</span></div><div class="standard-client-recent"><b>最近录入</b><span>{{ recent(client) }}</span></div><div><b>最近心跳</b><span>{{ client.seen_at || '—' }}</span></div></div></article><p v-if="!result?.standard_clients.length" class="hint">标准客户端尚未连接；客户端连接 LIMS 后自动显示。</p></div>
    <div class="section-head instrument-subhead"><h2>XRF 仪器状态与扫描记录</h2></div><div id="instrument-status" class="instrument-status"><template v-if="result?.client"><div class="instrument-state" :class="state">{{ stateLabels[state] || state }}</div><div v-for="[label, value] in clientFields" :key="label"><b>{{ label }}</b><span>{{ value || '—' }}</span></div><div v-if="result.client.message" class="instrument-message"><b>说明</b><span>{{ result.client.message }}</span></div></template><p v-else class="hint">XRF 终端尚未上报状态；启动客户端并连接 LIMS 后自动显示。</p></div>
    <div class="xrf-monitor-controls"><input id="xrf-scan-search" v-model="query" type="search" autocomplete="off" placeholder="搜索样品、LIMS 编号、方法、批次或扫描编号" @input="searchChanged"><select id="xrf-scan-kind" v-model="kind" aria-label="扫描类型" @change="filtersChanged"><option value="all">全部类型</option><option value="quant">普通定量</option><option value="uq">UniQuant</option></select><select id="xrf-scan-match" v-model="match" aria-label="登记情况" @change="filtersChanged"><option value="all">全部样品</option><option value="matched">已登记 LIMS</option><option value="unmatched">未登记 LIMS</option></select><label class="xrf-page-size-label">每页<select id="xrf-scan-page-size" v-model="pageSize" aria-label="每页条数" @change="filtersChanged"><option :value="25">25</option><option :value="50">50</option><option :value="100">100</option></select></label><span id="xrf-scan-count">共 {{ result?.total || 0 }} 条扫描</span></div>
    <div class="table-shell xrf-history-shell"><table id="xrf-scan-history" class="data-grid"><thead><tr><th>时间</th><th>类型</th><th>原始样品</th><th>LIMS 关联</th><th>方法 / 选项</th><th>最终结果</th><th></th></tr></thead><tbody>
      <template v-for="scan in result?.scans || []" :key="scan.id"><tr class="xrf-scan-row" :data-scan-id="scan.id" tabindex="0" :aria-expanded="expanded.has(scan.id)" @click="toggle(scan.id)" @keydown.enter.self.prevent="toggle(scan.id)"><td>{{ scan.analyzed_at || scan.created_at || '' }}</td><td><span class="xrf-type" :class="scan.kind === 'uq' ? 'uq' : 'quant'">{{ scan.kind === 'uq' ? 'UniQuant' : '普通定量' }}</span></td><td><strong>{{ scan.sample_name || '—' }}</strong><small>扫描 {{ scan.external_id || '—' }}</small></td><td><template v-if="scan.matched"><strong>{{ scan.lims_sample_name || '' }}</strong><small>{{ scan.lims_no || '' }}</small><button v-if="!finalStatuses.includes(scan.sample_status || '')" type="button" class="xrf-unassign-open" :data-analysis-id="scan.id" :disabled="assigning" @click.stop="link(scan)">解绑</button></template><template v-else><span class="xrf-unmatched">未关联 LIMS</span><button type="button" class="xrf-assign-open" :data-analysis-id="scan.id" @click.stop="open(scan)">关联样品</button></template></td><td><strong>{{ scan.method || '—' }}</strong><span v-if="scan.kind === 'uq'" class="xrf-option-badge" :class="scan.oxide ? 'oxide' : 'element'">{{ scan.oxide ? '氧化物' : '元素' }}</span><small v-else-if="scan.batch">批次 {{ scan.batch }}</small></td><td><div class="xrf-result-preview"><span v-for="(value, index) in scan.top_values || []" :key="index">{{ value }}</span><span v-if="!scan.top_values?.length" class="hint">无终值</span></div><small v-if="(scan.value_count || 0) > (scan.top_values?.length || 0)">另有 {{ (scan.value_count || 0) - (scan.top_values?.length || 0) }} 项</small></td><td><button type="button" class="xrf-expand" aria-label="展开最终结果" @click.stop="toggle(scan.id)">{{ expanded.has(scan.id) ? '收起' : '展开' }}</button></td></tr>
      <tr class="xrf-scan-detail" :data-detail-id="scan.id" :hidden="!expanded.has(scan.id)"><td colspan="7"><div class="xrf-expanded-grid"><section><h4>最终组成 <small>{{ scan.value_count || 0 }} 项 · Wt%</small></h4><div class="xrf-result-list"><div v-for="value in scan.values" :key="value.id"><b>{{ value.name }}</b><span>{{ xrfValueText(value.value) }}%</span></div><span v-if="!scan.values.length" class="hint">无最终组成</span></div></section><section><h4>{{ scan.kind === 'uq' ? 'UniQuant 关键选项' : '扫描信息' }}</h4><div class="xrf-option-list"><div v-for="option in scan.option_details || []" :key="option.label"><b>{{ option.label }}</b><span>{{ Array.isArray(option.value) ? option.value.join(', ') : option.value }}</span></div><div><b>方法</b><span>{{ scan.method || '—' }}</span></div><div v-if="scan.batch"><b>批次</b><span>{{ scan.batch }}</span></div><div><b>扫描编号</b><span>{{ scan.external_id || '—' }}</span></div></div></section></div></td></tr></template>
      <tr v-if="!result?.scans.length"><td colspan="7" class="xrf-empty">没有符合条件的 XRF 扫描。</td></tr>
    </tbody></table></div><div class="pager xrf-pager"><span id="xrf-page-summary">{{ result?.scans.length ? `本页 ${result.scans.length} 条` : '' }}</span><button id="xrf-page-prev" type="button" title="上一页" :disabled="busy || page <= 1" @click="page--; load()">‹</button><span id="xrf-page-label">{{ page }} / {{ result?.pages || 1 }}</span><button id="xrf-page-next" type="button" title="下一页" :disabled="busy || page >= (result?.pages || 1)" @click="page++; load()">›</button></div>
  </div></section>
  <Teleport to="body"><div v-if="assignment && active" id="xrf-assign-dialog" class="dialog-backdrop" @click.self="close" @keydown.esc="close"><section class="xrf-assign-dialog" role="dialog" aria-modal="true" aria-labelledby="xrf-assign-title"><button id="xrf-assign-close" class="dialog-x" type="button" aria-label="关闭" :disabled="assigning" @click="close">×</button><h2 id="xrf-assign-title">关联 LIMS 样品</h2><p id="xrf-assign-scan" class="hint">XRF 扫描：{{ assignment.sample_name || assignment.external_id || 'XRF 扫描' }}</p><input id="xrf-assign-sample-search" ref="sampleInput" v-model="sampleQuery" type="search" autocomplete="off" placeholder="搜索来样序号、样品名称或 LIMS 编号" @input="sampleChanged"><div id="xrf-assign-sample-options" class="xrf-assign-sample-options"><p v-if="searching" class="hint">正在加载可关联样品…</p><template v-else><button v-for="sample in samples" :key="sample.id" type="button" :data-sample-id="sample.id" :disabled="assigning" @click="link(assignment, sample)"><b>{{ sample.name || '未命名样品' }}</b><span>{{ sample.category || '未填写样品名称' }}</span><small>{{ sample.lims_no || `#${sample.id}` }} · {{ app.meta?.sample_statuses?.[sample.status] || sample.status }}</small></button><p v-if="!samples.length" class="hint">没有可关联的 XRF 样品。</p></template></div></section></div></Teleport>
</template>
