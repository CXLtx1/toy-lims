<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { request } from '../../api/client';
import { markDirty, refreshMeta } from '../../app/state';
import { showError } from '../../app/dialogs';
import { finalStatuses } from '../data-entry/types';
import type { XrfReference, XrfSample, XrfTarget } from './types';
const props = defineProps<{ sampleId: number; open: boolean; readonly?: boolean }>();
const emit = defineEmits<{ close: []; saved: [sampleId: number] }>();
const reference = ref<XrfReference | null>(null), rows = ref<XrfTarget[]>([]), busy = ref(false), loaded = ref(false), locked = ref(false), dirty = ref(false);
let sequence = 0, loadedId: number | null = null;
const drafts = new Map<number, XrfTarget[]>();
function changed() { dirty.value = true; markDirty(`xrf-targets:${loadedId}`, true); }
function options(row: XrfTarget) {
  const element = reference.value?.elements.find(item => item.symbol.toLowerCase() === row.family);
  const candidates = element ? [{ value: element.symbol, label: `${element.symbol} ${element.name_zh}` }] : [];
  for (const oxide of reference.value?.oxides.filter(item => item.element_symbol.toLowerCase() === row.family) || []) candidates.push({ value: oxide.formula, label: `${oxide.formula}${oxide.is_conventional ? '（惯用）' : ''}` });
  if (candidates.length && !candidates.some(item => item.value.toLowerCase() === row.target.toLowerCase())) candidates.push({ value: row.target, label: row.target });
  return candidates;
}
function close() { if (busy.value) return; if (dirty.value && !confirm('口径修改尚未保存，确定放弃？')) return; sequence++; if (loadedId != null) drafts.delete(loadedId); markDirty(`xrf-targets:${loadedId}`, false); dirty.value = false; loaded.value = false; emit('close'); }
function add() {
  const text = prompt('输入报告项目，如 Fe2O3、CaO 或 Fe（同一元素族只保留一个口径）', '');
  for (const token of text?.split(/[,，、;；\s]+/).filter(Boolean) || []) {
    const element = reference.value?.elements.find(item => item.symbol.toLowerCase() === token.toLowerCase());
    const oxide = reference.value?.oxides.find(item => item.formula.toLowerCase() === token.toLowerCase());
    const family = (oxide?.element_symbol || element?.symbol || token).toLowerCase();
    const existing = rows.value.find(row => row.family === family);
    if (existing) { existing.target = oxide?.formula || element?.symbol || token; existing.include = true; }
    else rows.value.push({ family, target: oxide?.formula || element?.symbol || token, include: true, allow_conversion: true });
    changed();
  }
}
async function load() {
  const current = ++sequence, id = props.sampleId;
  if (dirty.value && loadedId != null) drafts.set(loadedId, rows.value.map(row => ({ ...row })));
  if (!props.open) return;
  const cached = drafts.get(id);
  dirty.value = !!cached;
  rows.value = cached || [];
  loaded.value = false; loadedId = id;
  try {
    const [refData, scan] = await Promise.all([request<XrfReference>('/api/xrf/reference'), request<XrfSample>(`/api/xrf/samples/${id}`)]);
    if (current !== sequence || !props.open || id !== props.sampleId) return;
    reference.value = refData; locked.value = finalStatuses.includes(scan.sample.status);
    if (cached) { loaded.value = true; return; }
    const targets = scan.targets.map(row => ({ ...row }));
    const known = new Set(targets.map(row => row.family));
    for (const analysis of scan.analyses) for (const value of analysis.values) for (const name of [value.name, value.alt_name]) {
      if (!name) continue;
      const oxide = refData.oxides.find(item => item.formula.toLowerCase() === name.toLowerCase());
      const element = refData.elements.find(item => item.symbol.toLowerCase() === name.toLowerCase());
      const family = (oxide?.element_symbol || element?.symbol)?.toLowerCase();
      if (!family || known.has(family)) continue;
      known.add(family); targets.push({ family, target: oxide?.formula || element?.symbol || name, include: false, allow_conversion: true });
    }
    const order = new Map(refData.elements.map(item => [item.symbol.toLowerCase(), item.atomic_number]));
    rows.value = targets.sort((a, b) => (order.get(a.family) ?? 999) - (order.get(b.family) ?? 999));
    loaded.value = true;
  } catch (error) { if (current === sequence) void showError(error); }
}
async function save() {
  if (busy.value || !loaded.value || locked.value || props.readonly || loadedId == null) return;
  const id = loadedId;
  const targets = rows.value.map(row => ({ family: row.family, target: row.target.trim(), include: Boolean(row.include), allow_conversion: Boolean(row.allow_conversion ?? true) }));
  busy.value = true;
  try {
    await request(`/api/xrf/samples/${id}/targets`, { method: 'PUT', body: { targets } });
    drafts.delete(id); markDirty(`xrf-targets:${id}`, false);
    if (loadedId === id) dirty.value = false;
    emit('saved', id);
    if (loadedId === id && props.sampleId === id && props.open) emit('close');
    await refreshMeta();
  } catch (error) { void showError(error); } finally { busy.value = false; }
}
watch(() => [props.open, props.sampleId], () => { void load(); }, { immediate: true });
onBeforeUnmount(() => { sequence++; if (!dirty.value) markDirty(`xrf-targets:${loadedId}`, false); });
</script>
<template>
  <Teleport to="body"><div v-if="open" id="xrf-target-dialog" class="dialog-backdrop" @click.self="close" @keydown.esc="close"><section class="xrf-assign-dialog" role="dialog" aria-modal="true" aria-labelledby="xrf-target-title"><button id="xrf-target-close" class="dialog-x" type="button" aria-label="关闭" :disabled="busy" @click="close">×</button><h2 id="xrf-target-title">XRF 报告口径</h2><p class="hint">每个元素族只选一个报告口径；勾选后参与最终报告，缺项时按化学计量自动换算。</p><div id="xrf-target-rows" class="xrf-target-rows"><p v-if="!loaded" class="hint">正在加载…</p><div v-for="(row, index) in rows" v-else :key="index" class="xrf-target-row" :data-family="row.family"><label class="inline"><input v-model="row.include" type="checkbox" class="xrf-target-include" :disabled="readonly || locked || busy" @change="changed">参与</label><b>{{ row.family.toUpperCase() }}</b><span class="hint">{{ reference?.elements.find(item => item.symbol.toLowerCase() === row.family)?.name_zh || row.family }}</span><select v-if="options(row).length" v-model="row.target" class="xrf-target-select" :disabled="readonly || locked || busy" @change="changed"><option v-for="option in options(row)" :key="option.value" :value="option.value">{{ option.label }}</option></select><input v-else v-model="row.target" class="xrf-target-custom" title="自定义项目" :disabled="readonly || locked || busy" @input="changed"></div><p v-if="loaded && !rows.length" class="hint">暂无候选项目；请先在数据页关联 XRF 扫描，或点击"添加口径"。</p></div><div class="row xrf-presets"><button id="xrf-target-add" type="button" :disabled="!loaded || readonly || locked || busy" @click="add">+ 添加口径</button><span class="footer-spacer"></span><button id="xrf-target-save" type="button" class="primary" :disabled="!loaded || readonly || locked || busy" @click="save">保存口径</button></div></section></div></Teleport>
</template>
