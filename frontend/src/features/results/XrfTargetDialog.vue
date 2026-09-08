<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { request } from '../../api/client';
import { markDirty } from '../../app/state';
import { showError } from '../../app/dialogs';
import { write, type Target } from '../reports/model';
const props = defineProps<{ sampleId: number }>();
const emit = defineEmits<{ close: []; saved: [] }>();
interface ElementReference { symbol: string; name_zh: string; atomic_number: number }
interface OxideReference { formula: string; element_symbol: string; is_conventional: boolean | number }
interface Reference { ok: boolean; elements: ElementReference[]; oxides: OxideReference[] }
interface Scan { ok: boolean; sample: { id: number; status: string }; targets: Target[]; analyses: { values: { name: string; alt_name?: string }[] }[] }
const reference = ref<Reference>({ ok: true, elements: [], oxides: [] });
const targets = ref<Target[]>([]);
const busy = ref(true);
const loaded = ref(false);
const dirty = ref(false);
const dialog = ref<HTMLElement | null>(null);
const elements = computed(() => new Map(reference.value.elements.map(element => [element.symbol.toLowerCase(), element])));
const returnFocus = document.activeElement;
const controller = new AbortController();
function candidates(target: Target) {
  const element = elements.value.get(target.family);
  const options = element ? [{ value: element.symbol, label: `${element.symbol} ${element.name_zh}` }] : [];
  options.push(...reference.value.oxides.filter(oxide => oxide.element_symbol.toLowerCase() === target.family).map(oxide => ({ value: oxide.formula, label: `${oxide.formula}${oxide.is_conventional ? '（惯用）' : ''}` })));
  if (options.length && !options.some(option => option.value.toLowerCase() === target.target.toLowerCase())) options.push({ value: target.target, label: target.target });
  return options;
}
function edit() { dirty.value = true; markDirty('results-xrf-targets', true); }
function close() {
  if (busy.value) return;
  if (dirty.value && !window.confirm('放弃未保存的 XRF 报告口径？')) return;
  emit('close');
}
function add() {
  const text = window.prompt('输入报告项目，如 Fe2O3、CaO 或 Fe（同一元素族只保留一个口径）', '');
  if (!text?.trim()) return;
  for (const token of text.split(/[,，、;；\s]+/).filter(Boolean)) {
    const oxide = reference.value.oxides.find(item => item.formula.toLowerCase() === token.toLowerCase());
    const family = oxide?.element_symbol.toLowerCase() || token.toLowerCase();
    const existing = targets.value.find(target => target.family === family);
    if (existing) { existing.target = oxide?.formula || elements.value.get(family)?.symbol || token; existing.include = true; }
    else targets.value.push({ family, target: oxide?.formula || elements.value.get(family)?.symbol || token, include: true, allow_conversion: true });
  }
  edit();
}
async function save() {
  if (busy.value || !loaded.value) return;
  if (targets.value.some(target => !target.target.trim())) { showError(new Error('报告目标不能为空')); return; }
  busy.value = true;
  try {
    await write(`/api/xrf/samples/${props.sampleId}/targets`, { targets: targets.value.map(target => ({ ...target, target: target.target.trim(), include: !!target.include, allow_conversion: target.allow_conversion !== 0 && target.allow_conversion !== false })) });
    if (controller.signal.aborted) return;
    dirty.value = false; markDirty('results-xrf-targets', false); emit('saved');
  } catch (error) { if (!controller.signal.aborted) showError(error); }
  finally { busy.value = false; }
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
  if (event.key !== 'Tab') return;
  const controls = Array.from(dialog.value?.querySelectorAll<HTMLElement>('input:not(:disabled),select:not(:disabled),button:not(:disabled)') || []);
  const first = controls[0]; const last = controls[controls.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
}
onMounted(async () => {
  await nextTick(); dialog.value?.focus();
  try {
    const [refData, scan] = await Promise.all([request<Reference>('/api/xrf/reference', { signal: controller.signal }), request<Scan>(`/api/xrf/samples/${props.sampleId}`, { signal: controller.signal })]);
    if (controller.signal.aborted) return;
    if (!refData.ok || !scan.ok || scan.sample?.id !== props.sampleId || !Array.isArray(refData.elements) || !Array.isArray(refData.oxides) || !Array.isArray(scan.targets) || !Array.isArray(scan.analyses)) throw new Error('XRF 参考数据或扫描响应无效');
    if (['reviewed', 'reported', 'cancelled'].includes(scan.sample.status)) throw new Error('样品已锁定，不能修改报告口径');
    reference.value = refData;
    targets.value = scan.targets.map(target => ({ ...target, include: !!target.include }));
    const known = new Set(targets.value.map(target => target.family));
    for (const analysis of scan.analyses) for (const value of analysis.values) for (const name of [value.name, value.alt_name]) {
      const key = (name || '').toLowerCase();
      const oxide = refData.oxides.find(item => item.formula.toLowerCase() === key);
      const family = oxide ? oxide.element_symbol.toLowerCase() : elements.value.has(key) ? key : null;
      if (!family || known.has(family)) continue;
      known.add(family);
      targets.value.push({ family, target: oxide?.formula || elements.value.get(family)?.symbol || key, include: false, allow_conversion: true });
    }
    targets.value.sort((a, b) => (elements.value.get(a.family)?.atomic_number ?? 999) - (elements.value.get(b.family)?.atomic_number ?? 999));
    loaded.value = true;
  } catch (error) { if (!controller.signal.aborted) showError(error); }
  finally { busy.value = false; }
});
onBeforeUnmount(() => { controller.abort(); markDirty('results-xrf-targets', false); if (returnFocus instanceof HTMLElement && returnFocus.isConnected) returnFocus.focus(); });
</script>
<template>
  <Teleport to="body"><div id="xrf-target-dialog" class="dialog-backdrop" :data-sid="sampleId" @click.self="close" @keydown="keydown"><section ref="dialog" class="xrf-assign-dialog" role="dialog" aria-modal="true" aria-labelledby="xrf-target-title" tabindex="-1"><button id="xrf-target-close" class="dialog-x" type="button" aria-label="关闭" :disabled="busy" @click="close">×</button><h2 id="xrf-target-title">XRF 报告口径</h2><p class="hint">每个元素族只选一个报告口径；勾选后参与最终报告，缺项时按化学计量自动换算。</p>
    <div id="xrf-target-rows" class="xrf-target-rows"><div v-for="target in targets" :key="target.family" class="xrf-target-row" :data-family="target.family"><label class="inline"><input v-model="target.include" type="checkbox" class="xrf-target-include" :disabled="busy" @change="edit">参与</label><b>{{ target.family.toUpperCase() }}</b><span class="hint">{{ elements.get(target.family)?.name_zh || target.family }}</span><select v-if="candidates(target).length" v-model="target.target" class="xrf-target-select" :disabled="busy" @change="edit"><option v-for="option in candidates(target)" :key="option.value" :value="option.value">{{ option.label }}</option></select><input v-else v-model="target.target" class="xrf-target-custom" title="自定义项目" :disabled="busy" @input="edit"></div><p v-if="!targets.length" class="hint">{{ busy ? '正在读取 XRF 报告口径…' : '暂无候选项目；请先在数据页关联 XRF 扫描，或点击"添加口径"。' }}</p></div>
    <div class="row xrf-presets"><button id="xrf-target-add" type="button" :disabled="busy || !loaded" @click="add">+ 添加口径</button><span class="footer-spacer"></span><button id="xrf-target-save" type="button" class="primary" :disabled="busy || !loaded" @click="save">保存口径</button></div>
  </section></div></Teleport>
</template>
