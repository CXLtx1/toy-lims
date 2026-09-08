<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { markDirty } from '../../app/state';
import { showError } from '../../app/dialogs';
import PreparationRows from './PreparationRows.vue';
import { newPrep, parseAnalytes, stored, tokens, type InstrumentMap, type Prep, type Routing, type SampleTemplate, type SettingsMeta } from './types';
const props = defineProps<{ meta: SettingsMeta; busy: boolean; save: (url: string, method: string, body?: unknown) => Promise<boolean> }>();
const emit = defineEmits<{ method: [id: number | null, select: (id: number | null) => void, analyte: string] }>();
interface TemplateConfig { [key: string]: Routing | number | number[] | string | null | undefined; __xrf_method_id?: number | null; __xrf_report_items?: string; __xrf_analyte_ids?: number[]; __report_order?: number[] }
const editId = ref<number | null>(null);
const form = reactive({ name: '', category: '', tags: '', sampleType: 'solid', orderId: props.meta.default_order_template_id, xrf: false, xrfText: '', xrfMethod: null as number | null, analyteText: '', routing: {} as InstrumentMap, preps: [newPrep(props.meta)] });
const parsed = computed(() => parseAnalytes(form.analyteText, props.meta.analytes));
const xrfParsed = computed(() => parseAnalytes(form.xrfText, props.meta.analytes));
const ids = computed(() => parsed.value.matched.map(a => a.id));
let baseline = JSON.stringify(form);
watch(form, () => markDirty('settings-template', JSON.stringify(form) !== baseline), { deep: true, flush: 'sync' });
onBeforeUnmount(() => markDirty('settings-template', false));
watch(() => form.xrf, enabled => { const methods = props.meta.methods.filter(m => m.itype === 'xrf' && m.active !== 0); if (enabled && !form.xrfMethod && methods.length === 1) form.xrfMethod = methods[0]?.id ?? null; });
function edit(template?: SampleTemplate) {
  if (JSON.stringify(form) !== baseline && !window.confirm('放弃当前模板的未保存修改？')) return;
  const config = stored<TemplateConfig>(template?.instrument_config, {});
  const selectedIds = stored<number[]>(template?.analyte_ids, []);
  const order = config.__report_order || [];
  const ordered = [...order.filter(id => selectedIds.includes(id)), ...selectedIds.filter(id => !order.includes(id))];
  const routing: InstrumentMap = {};
  for (const [key, value] of Object.entries(config)) if (!key.startsWith('__') && value && typeof value === 'object' && !Array.isArray(value)) routing[key] = { ...value };
  const preps = stored<Partial<Prep>[]>(template?.prep_config, []);
  editId.value = template?.id ?? null;
  Object.assign(form, { name: template?.name || '', category: template?.category || '', tags: stored<string[]>(template?.tags_json, []).map(t => `#${t}`).join(', '), sampleType: template?.is_water_quality ? 'water_quality' : template?.is_liquid ? 'liquid' : 'solid', orderId: template?.order_template_id ?? props.meta.default_order_template_id, xrf: Boolean(template?.xrf), xrfMethod: config.__xrf_method_id ?? null, xrfText: template?.xrf ? config.__xrf_report_items ?? (config.__xrf_analyte_ids || selectedIds).map(id => props.meta.analytes.find(a => a.id === id)?.name).filter(Boolean).join(', ') : '', analyteText: ordered.map(id => props.meta.analytes.find(a => a.id === id)?.name).filter(Boolean).join(', '), routing,
    preps: (preps.length ? preps : [{ dilution_id: template?.dilution_id }]).map(p => newPrep(props.meta, { ...p, volume_ml: p.volume_ml || props.meta.default_volume_ml, instrument_map: p.instrument_map || JSON.parse(JSON.stringify(routing)) as InstrumentMap })) });
  baseline = JSON.stringify(form); markDirty('settings-template', false);
}
function setInstrument(id: number, event: Event) {
  if (!(event.target instanceof HTMLSelectElement)) return;
  const instrumentId = Number(event.target.value);
  if (!instrumentId) delete form.routing[id]; else form.routing[id] = { instrument_id: instrumentId, method_id: null };
}
function chooseMethod(id: number) { emit('method', form.routing[id]?.method_id ?? null, methodId => { if (form.routing[id]) form.routing[id].method_id = methodId; }, props.meta.analytes.find(a => a.id === id)?.name || ''); }
function move(id: number, delta: number) { const items = [...parsed.value.matched], index = items.findIndex(a => a.id === id), target = index + delta; const a = items[index], b = items[target]; if (!a || !b) return; items[index] = b; items[target] = a; form.analyteText = items.map(a => a.name).join(', '); }
function remove(id: number) { delete form.routing[id]; form.analyteText = parsed.value.matched.filter(a => a.id !== id).map(a => a.name).join(', '); for (const prep of form.preps) delete prep.instrument_map[id]; }
function addPrep() { form.preps.push(newPrep(props.meta, { instrument_map: JSON.parse(JSON.stringify(form.routing)) as InstrumentMap })); }
function cleanRouting(map: InstrumentMap): InstrumentMap {
  return Object.fromEntries(Object.entries(map).filter(([id, route]) => ids.value.includes(Number(id)) && props.meta.instruments.some(i => i.id === route.instrument_id && i.itype !== 'xrf' && i.analytes.includes(Number(id)))));
}
async function saveTemplate() {
  if (!form.name.trim()) { showError('模板名称不能为空'); return; }
  if (!ids.value.length && !form.xrf) { showError('模板的溶样方案和 XRF 至少需要有一项。'); return; }
  if (parsed.value.unmatched.length) { showError(`请先添加或移除未登记的分析项目：${parsed.value.unmatched.join('、')}`); return; }
  if (form.xrf && !form.xrfMethod) { showError('请选择模板的 XRF 方法。'); return; }
  const liquid = form.sampleType !== 'solid';
  const preps = form.preps.map(p => { const map = cleanRouting(p.instrument_map); return { mass_g: liquid ? null : Number(p.mass_g) || null, volume_ml: liquid ? null : p.volume_ml, dilution_ids: p.dilution_ids, dilution_id: p.dilution_ids[0] || null, count: Math.min(10, Math.max(1, Math.floor(Number(p.count) || 1))), analyte_ids: Object.keys(map).map(Number), instrument_map: map }; });
  const body = { name: form.name.trim(), category: form.category.trim(), tags: tokens(form.tags).map(t => t.replace(/^#+/, '')).filter(Boolean), is_liquid: Number(liquid), is_water_quality: Number(form.sampleType === 'water_quality'), order_template_id: form.orderId, xrf: Number(form.xrf), dilution_id: preps[0]?.dilution_id || null, analyte_ids: ids.value, preps, instrument_map: { ...cleanRouting(form.routing), __xrf_method_id: form.xrf ? form.xrfMethod : null, __xrf_report_items: form.xrf ? form.xrfText.trim() : '', __xrf_analyte_ids: form.xrf ? xrfParsed.value.matched.map(a => a.id) : [], __report_order: ids.value } };
  if (await props.save(editId.value ? `/api/templates/${editId.value}` : '/api/templates', editId.value ? 'PUT' : 'POST', body)) { baseline = JSON.stringify(form); edit(); }
}
async function deleteTemplate(template: SampleTemplate) {
  if (!window.confirm('确定删除这个模板？')) return;
  if (await props.save(`/api/templates/${template.id}`, 'DELETE') && editId.value === template.id) { baseline = JSON.stringify(form); edit(); }
}
function summary(template: SampleTemplate) {
  const config = stored<TemplateConfig>(template.instrument_config, {});
  return { config, tags: stored<string[]>(template.tags_json, []), regular: stored<number[]>(template.analyte_ids, []).length, xrf: tokens(config.__xrf_report_items || '').length,
    preps: stored<Partial<Prep>[]>(template.prep_config, [{}]).reduce((sum, p) => sum + Math.max(1, Number(p.count) || 1), 0), instruments: Object.keys(config).filter(k => !k.startsWith('__')).length, method: props.meta.methods.find(m => m.id === config.__xrf_method_id)?.name };
}
function preset(kind: string) {
  if (kind === 'clear') form.xrfText = '';
  else form.xrfText = kind === 'elements' ? 'Si, Al, Fe, Ca, Mg, Ti, Na, K, Mn, P' : 'SiO2, Al2O3, Fe2O3, CaO, MgO, TiO2, Na2O, K2O, MnO, P2O5';
}
</script>
<template>
  <div class="panel template-panel">
    <div class="section-head"><h2 id="t-editor-title">{{ editId ? `编辑模板 #${editId}` : '新建样品模板' }}</h2><button id="t-cancel" type="button" :hidden="!editId" :disabled="busy" @click="edit()">取消编辑</button></div>
    <div class="row"><input id="t-name" v-model="form.name" placeholder="模板名称"><input id="t-category" v-model="form.category" placeholder="样品名称（应用模板时带入）"><input id="t-tags" v-model="form.tags" list="sample-tag-options" placeholder="标签，如 实验样, 二组"><label>样品类型 <select id="t-sample-type" v-model="form.sampleType"><option value="solid">固体</option><option value="liquid">液体样</option><option value="water_quality">水质样</option></select></label><label>顺序模板 <select id="t-order-template" v-model="form.orderId"><option :value="null">系统默认</option><option v-for="t in meta.result_order_templates" :key="t.id" :value="t.id">{{ t.name }}{{ t.is_default ? '（系统默认）' : '' }}</option></select></label><label class="inline"><input id="t-xrf" v-model="form.xrf" type="checkbox"> 打荧光(XRF粗扫)</label></div>
    <div id="t-xrf-config" class="xrf-config" :hidden="!form.xrf"><h3>XRF 方法与报告默认项目</h3><div class="row"><input id="t-xrf-text" v-model="form.xrfText" placeholder="报告默认项目，可空，如 Fe, SiO2, CaO" style="width:min(680px,100%)"><label id="t-xrf-method-wrap">XRF 方法 <select id="t-xrf-method" v-model="form.xrfMethod"><option :value="null">— 选择 XRF 方法 —</option><option v-for="m in meta.methods.filter(m => m.itype === 'xrf' && (m.active !== 0 || m.id === form.xrfMethod))" :key="m.id" :value="m.id">{{ m.name }}{{ m.active === 0 ? '（已停用）' : '' }}</option></select></label></div><div class="row xrf-presets"><span class="hint">快速口径：</span><button type="button" class="xrf-preset" data-target="t-xrf-text" data-preset="elements" @click="preset('elements')">元素口径</button><button type="button" class="xrf-preset" data-target="t-xrf-text" data-preset="oxides" @click="preset('oxides')">氧化物口径</button><button type="button" class="xrf-preset" data-target="t-xrf-text" data-preset="clear" @click="preset('clear')">清空</button></div><div id="t-xrf-chips" class="tagbox"><span v-for="a in xrfParsed.matched" :key="a.id" class="tag ok">{{ a.name }}</span><span v-for="a in xrfParsed.unmatched" :key="a" class="tag">{{ a }}</span></div><p class="hint">仪器返回的全部定量项目都会保存；这里填写的项目在应用模板后默认参与最终结果计算（同一元素族先填的口径优先）。</p></div>
    <h3>测定项目与默认仪器</h3><div class="template-analyte-input"><input id="t-analyte-text" v-model="form.analyteText" placeholder="输入项目，如 Cu Ni Sn（空格或逗号分隔）"><span class="hint">输入后可在下方调整顺序和默认仪器</span></div><div id="t-analyte-chips" class="tagbox"><span v-for="a in parsed.matched" :key="a.id" class="tag ok">{{ a.name }}</span><span v-for="a in parsed.unmatched" :key="a" class="tag bad">{{ a }}?</span></div>
    <div id="t-analytes" class="template-analytes"><div v-for="(a, index) in parsed.matched" :key="a.id" class="template-analyte-row enabled" :data-aid="a.id"><b>{{ a.name }}</b><span class="template-order-actions"><button class="ta-up" type="button" title="上移" :disabled="index === 0" @click="move(a.id, -1)">↑</button><button class="ta-down" type="button" title="下移" :disabled="index === parsed.matched.length - 1" @click="move(a.id, 1)">↓</button></span><select class="ta-instrument" :value="form.routing[a.id]?.instrument_id || ''" @change="setInstrument(a.id, $event)"><option value="">— 默认仪器 —</option><option v-for="i in meta.instruments.filter(i => i.itype !== 'xrf' && i.analytes.includes(a.id))" :key="i.id" :value="i.id">{{ i.name }}</option></select><button type="button" class="method-picker-trigger ta-method" :data-method-id="form.routing[a.id]?.method_id || ''" :disabled="meta.instruments.find(i => i.id === form.routing[a.id]?.instrument_id)?.itype !== 'function'" :style="{ visibility: meta.instruments.find(i => i.id === form.routing[a.id]?.instrument_id)?.itype === 'function' ? 'visible' : 'hidden' }" title="选择公式方法" @click="chooseMethod(a.id)"><span>{{ meta.methods.find(m => m.id === form.routing[a.id]?.method_id)?.name || '选择方法' }}</span><i aria-hidden="true">⌄</i></button><button class="del ta-remove" type="button" title="移除项目" @click="remove(a.id)">×</button></div></div>
    <h3>溶样设置</h3><div class="table-shell prep-shell"><table id="t-prep-table" class="data-grid"><thead><tr><th v-show="form.sampleType === 'solid'" class="t-solid-only">称样(g)</th><th v-show="form.sampleType === 'solid'" class="t-solid-only">定容(mL)</th><th>稀释（可多级）</th><th title="平行份数，大于 1 时自动生成 -1、-2 后缀">平行</th><th>测定项目与仪器分配（点击标签多选，拖到或点击仪器栏）</th><th></th></tr></thead><PreparationRows v-model="form.preps" :meta="meta" :liquid="form.sampleType !== 'solid'" :analyte-ids="ids" @method="(id, select, analyte) => emit('method', id, select, analyte)" /></table></div>
    <div class="editor-footer"><button id="t-prep-add" type="button" @click="addPrep">+ 加一路溶样</button><span class="footer-spacer"></span><button id="t-add" class="primary" :disabled="busy" @click="saveTemplate">{{ editId ? '保存修改' : '保存模板' }}</button></div>
    <h3>已有模板</h3><div class="table-shell"><table id="t-table" class="data-grid"><thead><tr><th>名称</th><th>类型</th><th>顺序模板</th><th>项目</th><th>溶样</th><th>仪器预设</th><th>操作</th></tr></thead><tbody><tr v-for="t in meta.templates" :key="t.id"><td><b>{{ t.name }}</b><small v-if="t.category || summary(t).tags.length" class="template-sample-defaults">{{ t.category ? `样品：${t.category}` : '' }} {{ summary(t).tags.map(tag => `#${tag}`).join(' ') }}</small></td><td>{{ t.is_water_quality ? '水质' : t.is_liquid ? '液体' : '固体' }}{{ t.xrf ? ` / XRF${summary(t).method ? `：${summary(t).method}` : '（未选方法）'}` : '' }}</td><td>{{ meta.result_order_templates.find(o => o.id === t.order_template_id)?.name || '系统默认' }}</td><td>{{ t.xrf ? `常规 ${summary(t).regular} / XRF ${summary(t).xrf}` : summary(t).regular }}</td><td>{{ summary(t).preps }} 路</td><td>{{ summary(t).instruments }}</td><td class="actions"><button class="t-edit" :data-tid="t.id" :disabled="busy" @click="edit(t)">编辑</button><button class="del" :data-tid="t.id" :disabled="busy" @click="deleteTemplate(t)">删除</button></td></tr></tbody></table></div>
  </div>
</template>
