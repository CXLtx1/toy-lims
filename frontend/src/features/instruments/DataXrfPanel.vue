<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { request } from '../../api/client';
import { markDirty, refreshMeta } from '../../app/state';
import { showError } from '../../app/dialogs';
import { finalStatuses, type Sample } from '../data-entry/types';
import { xrfValueText, type Monitor, type Scan, type XrfSample } from './types';
const props = defineProps<{ sample: Sample; revision: number; active: boolean }>();
const emit = defineEmits<{ changed: [] }>();
const result = ref<XrfSample | null>(null), candidates = ref<Scan[]>([]), query = ref(''), searched = ref(false), busy = ref(false);
let sequence = 0, searchSequence = 0, timer: ReturnType<typeof setTimeout> | undefined;
const latest = computed(() => result.value?.analyses[0]);
const editable = computed(() => !finalStatuses.includes(props.sample.status));
const visible = computed(() => props.sample.workflow_type !== 'special' && (props.sample.xrf || result.value?.analyses.length));
const meta = computed(() => {
  const scan = latest.value;
  return scan ? `${scan.kind === 'uq' ? 'UniQuant' : '常规 XRF'} · ${scan.analyzed_at || scan.created_at || ''} · ${scan.method || props.sample.method_name || 'XRF'}${scan.batch ? ` · 批次 ${scan.batch}` : ''}${scan.remark ? ` · ${scan.remark}` : ''} · 共 ${result.value?.analyses.length || 0} 次分析` : '尚未收到扫描结果';
});
async function load() {
  if (!props.active || props.sample.workflow_type === 'special') return;
  const current = ++sequence, id = props.sample.id;
  try { const data = await request<XrfSample>(`/api/xrf/samples/${id}`); if (current === sequence && id === props.sample.id) result.value = data; }
  catch (error) { if (current === sequence) void showError(error); }
}
async function search() {
  if (!props.active || !editable.value) return;
  const current = ++searchSequence, id = props.sample.id, q = query.value.trim();
  try {
    const data = await request<Monitor>(`/api/xrf/monitor?match=unmatched&limit=10&q=${encodeURIComponent(q)}`);
    if (current !== searchSequence || id !== props.sample.id || q !== query.value.trim()) return;
    candidates.value = data.scans; searched.value = true;
  } catch (error) { if (current === searchSequence) void showError(error); }
}
function schedule() { clearTimeout(timer); searchSequence++; searched.value = false; timer = setTimeout(() => { void search(); }, 220); }
async function assign(scan: Scan, unlink = false) {
  if (busy.value || !editable.value || !props.active) return;
  if (unlink && !confirm(`确定解除当前样品与 XRF 扫描 ${scan.external_id || scan.id} 的关联？`)) return;
  const id = props.sample.id;
  busy.value = true;
  markDirty(`xrf-link:${id}`, true);
  try {
    await request(`/api/xrf/analyses/${scan.id}/sample`, { method: unlink ? 'DELETE' : 'PUT', body: unlink ? undefined : { sample_id: id } });
    if (id === props.sample.id) { query.value = ''; searched.value = false; candidates.value = []; searchSequence++; }
    await refreshMeta();
    if (id === props.sample.id) { await load(); emit('changed'); }
  } catch (error) { void showError(error); } finally { busy.value = false; markDirty(`xrf-link:${id}`, false); }
}
watch(() => props.sample.id, () => { sequence++; clearTimeout(timer); result.value = null; query.value = ''; searched.value = false; candidates.value = []; searchSequence++; void load(); }, { immediate: true });
watch(() => [props.active, props.revision], () => { if (props.active) void load(); else { sequence++; searchSequence++; clearTimeout(timer); } });
onBeforeUnmount(() => { sequence++; searchSequence++; clearTimeout(timer); });
</script>
<template>
  <section v-show="visible" id="d-xrf-panel" class="xrf-compact-panel">
    <div class="xrf-compact-head"><h3>XRF 分析结果</h3><span id="d-xrf-meta">{{ meta }}</span><button v-if="latest && editable" id="d-xrf-unassign" type="button" :disabled="busy" @click="assign(latest, true)">解绑当前扫描</button></div>
    <div id="d-xrf-values" class="xrf-value-grid"><template v-if="latest?.values.length"><div v-for="value in latest.values" :key="value.id" class="xrf-value" :class="{ used: value.use_report }" :title="value.use_report ? '参与最终结果计算' : '不参与最终结果计算'"><b>{{ value.name }}</b><span>{{ xrfValueText(value.value) }}%</span></div></template><p v-else class="hint">待 XRF 终端上传结果。</p></div>
    <div v-if="sample.xrf && editable && !latest" class="xrf-data-assign"><input id="d-xrf-scan-search" v-model="query" type="search" autocomplete="off" placeholder="搜索未关联扫描的原始样品、方法、批次或扫描编号" @focus="search" @input="schedule"><div id="d-xrf-scan-options" class="xrf-link-options"><template v-if="searched"><article v-for="scan in candidates" :key="scan.id"><div><strong>{{ scan.sample_name || '未命名扫描' }}</strong><span>{{ scan.kind === 'uq' ? 'UniQuant' : '普通定量' }} · {{ scan.analyzed_at || scan.created_at || '时间未知' }}</span><small>{{ scan.method || '方法未知' }} · 扫描 {{ scan.external_id || '—' }} · {{ scan.top_values?.join('，') }}</small></div><button type="button" :data-analysis-id="scan.id" :disabled="busy" @click="assign(scan)">关联当前样品</button></article><p v-if="!candidates.length" class="hint">{{ query ? '没有匹配的未关联 XRF 扫描。' : '当前没有未关联 XRF 扫描。' }}</p></template></div></div>
  </section>
</template>
