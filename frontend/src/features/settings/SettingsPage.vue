<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue';
import { request } from '../../api/client';
import { useAppState, refreshMeta, markDirty } from '../../app/state';
import { showError } from '../../app/dialogs';
import TemplatePanel from './TemplatePanel.vue';
import PreparationRows from './PreparationRows.vue';
import MethodPicker from './MethodPicker.vue';
import { constantsText, emptyMeta, newPrep, tokens, type Combination, type Method, type OrderTemplate, type Prep, type ReportProfile, type SettingsMeta } from './types';
const app = useAppState(), meta = ref<SettingsMeta>(emptyMeta()), loaded = ref(false), busy = ref(false);
const picker = ref<InstanceType<typeof MethodPicker>>();
const form = reactive({ analyte: '', instrument: '', instrumentType: 'xrf', volume: 250 as number | '', aliquot: '' as number | '', finalVolume: '' as number | '', orderName: '', orderItems: '', methodType: 'function', methodName: '', formula: '', constants: '', note: '', target: '', outputUnit: '%', profileName: '', companyCn: '', companyEn: '', rawCode: '', finalCode: '' });
const initialForm = JSON.stringify(form);
const combination = reactive({ id: null as number | null, name: '', rows: [] as Prep[] });
const combinationBaseline = ref(JSON.stringify(combination));
const dirty = reactive(new Set<string>()), openCaps = reactive(new Set<number>());
const orderTexts = reactive<Record<number, string>>({});
const outputUnits = ['%', 'ppm', 'ppb', 'mol/L', 'g/L'];
const resultUnits = ['', '%', 'ppm', 'ppb', 'g/L', 'mg/L', 'ug/L'];
watch(() => [form, combination, combinationBaseline.value, [...dirty]], () => markDirty('settings', JSON.stringify(form) !== initialForm || JSON.stringify(combination) !== combinationBaseline.value || dirty.size > 0), { deep: true, flush: 'sync' });
onBeforeUnmount(() => { ++loadSequence; markDirty('settings', false); });
let loadSequence = 0;
async function load() {
  const sequence = ++loadSequence;
  try {
    const fresh = await request<SettingsMeta>('/api/meta');
    if (sequence !== loadSequence) return;
    // Keep unsaved inline edits while other panels or live events refresh metadata.
    fresh.methods = fresh.methods.map(row => dirty.has(`method:${row.id}`) ? meta.value.methods.find(m => m.id === row.id) ?? row : row);
    fresh.report_profiles = fresh.report_profiles.map(row => dirty.has(`profile:${row.id}`) ? meta.value.report_profiles.find(p => p.id === row.id) ?? row : row);
    fresh.result_order_templates = fresh.result_order_templates.map(row => dirty.has(`order:${row.id}`) ? { ...(meta.value.result_order_templates.find(t => t.id === row.id) ?? row), is_default: row.is_default } : row);
    fresh.instruments = fresh.instruments.map(row => dirty.has(`cap:${row.id}`) ? { ...row, analytes: meta.value.instruments.find(i => i.id === row.id)?.analytes ?? row.analytes } : row);
    for (const order of fresh.result_order_templates) if (!dirty.has(`order:${order.id}`)) orderTexts[order.id] = order.items.join(', ');
    meta.value = fresh;
    if (!loaded.value) { combination.rows = [newPrep(fresh)]; combinationBaseline.value = JSON.stringify(combination); }
    loaded.value = true;
  } catch (error) { showError(error); }
}
watch(() => [app.page, app.refreshRevision], () => { if (app.page === 'settings' && !busy.value) void load(); }, { immediate: true });
async function save(url: string, method: string, body?: unknown, key?: string): Promise<boolean> {
  if (busy.value) return false;
  ++loadSequence;
  busy.value = true;
  try {
    await request(url, { method, body });
    if (key) dirty.delete(key);
    try { await refreshMeta(); } catch (error) { showError(error); }
    await load(); return true;
  } catch (error) { showError(error); return false; }
  finally { busy.value = false; }
}
async function remove(url: string, message = '确定删除这项配置？此操作不能撤销。', key?: string) { if (busy.value || !window.confirm(message)) return; await save(url, 'DELETE', undefined, key); }
async function add(kind: 'analyte' | 'instrument' | 'volume' | 'dilution' | 'order' | 'profile') {
  if (kind === 'analyte' && form.analyte.trim() && await save('/api/analytes', 'POST', { name: form.analyte.trim() })) form.analyte = '';
  if (kind === 'instrument' && form.instrument.trim() && await save('/api/instruments', 'POST', { name: form.instrument.trim(), itype: form.instrumentType })) form.instrument = '';
  if (kind === 'volume') {
    if (!Number.isFinite(Number(form.volume)) || Number(form.volume) <= 0) { showError('定容容量必须大于 0'); return; }
    if (await save('/api/volume-presets', 'POST', { volume_ml: Number(form.volume) })) form.volume = 250;
  }
  if (kind === 'dilution') {
    if (!Number.isFinite(Number(form.aliquot)) || !Number.isFinite(Number(form.finalVolume)) || Number(form.aliquot) <= 0 || Number(form.finalVolume) < Number(form.aliquot)) { showError('体积必须大于 0，且再次定容体积不能小于移取体积'); return; }
    if (await save('/api/dilutions', 'POST', { aliquot_ml: Number(form.aliquot), final_volume_ml: Number(form.finalVolume) })) { form.aliquot = ''; form.finalVolume = ''; }
  }
  if (kind === 'order' && await save('/api/result-order-templates', 'POST', { name: form.orderName.trim(), items: tokens(form.orderItems) })) { form.orderName = ''; form.orderItems = ''; }
  if (kind === 'profile' && await save('/api/report-profiles', 'POST', { name: form.profileName.trim(), company_name_cn: form.companyCn.trim(), company_name_en: form.companyEn.trim(), raw_code: form.rawCode.trim(), final_code: form.finalCode.trim() })) { form.profileName = ''; form.companyCn = ''; form.companyEn = ''; form.rawCode = ''; form.finalCode = ''; }
}
async function move(kind: 'instruments' | 'methods', id: number, delta: number) {
  const ids = meta.value[kind].map(i => i.id), index = ids.indexOf(id), target = index + delta;
  const a = ids[index], b = ids[target]; if (a === undefined || b === undefined) return;
  ids[index] = b; ids[target] = a; await save(`/api/${kind}/order`, 'PUT', { ids });
}
async function addMethod() {
  if (!form.methodName.trim() || (form.methodType === 'function' && !form.formula.trim())) { showError('请填写方法名称和公式'); return; }
  const constants: Record<string, number> = {};
  if (form.methodType !== 'xrf') for (const part of form.constants.split(/[,，;；\s]+/).filter(Boolean)) {
    const [key, value, ...rest] = part.split('=');
    if (!key || value === undefined || !value.trim() || rest.length || !Number.isFinite(Number(value))) { showError(`固定常数格式不正确：${part}`); return; }
    constants[key] = Number(value);
  }
  if (await save('/api/methods', 'POST', { name: form.methodName.trim(), itype: form.methodType, formula: form.methodType === 'xrf' ? '' : form.formula.trim(), constants, note: form.note.trim(), target: form.methodType === 'xrf' ? '' : form.target.trim(), output_unit: form.methodType === 'xrf' ? '%' : form.outputUnit })) { form.methodName = ''; form.formula = ''; form.constants = ''; form.note = ''; form.target = ''; }
}
function saveMethod(method: Method) { return save(`/api/methods/${method.id}/note`, 'PUT', { note: method.note, output_unit: method.output_unit || '%', active: method.active, ...(method.itype === 'xrf' ? {} : { target: method.target }) }, `method:${method.id}`); }
function saveOrder(order: OrderTemplate, isDefault = false) { return save(`/api/result-order-templates/${order.id}`, 'PUT', { name: order.name.trim(), items: tokens(orderTexts[order.id] || ''), ...(isDefault ? { is_default: true } : {}) }, `order:${order.id}`); }
function saveProfile(profile: ReportProfile) { return save(`/api/report-profiles/${profile.id}`, 'PUT', { name: profile.name.trim(), company_name_cn: profile.company_name_cn.trim(), company_name_en: (profile.company_name_en || '').trim(), raw_code: (profile.raw_code || '').trim(), final_code: (profile.final_code || '').trim() }, `profile:${profile.id}`); }
function editCombination(item?: Combination) {
  if (JSON.stringify(combination) !== combinationBaseline.value && !window.confirm('放弃当前溶样组合的未保存修改？')) return;
  combination.id = item?.id ?? null; combination.name = item?.name || '';
  combination.rows = (item?.rows.length ? JSON.parse(JSON.stringify(item.rows)) as Prep[] : [{}]).map(row => newPrep(meta.value, row));
  combinationBaseline.value = JSON.stringify(combination); markDirty('settings', dirty.size > 0 || JSON.stringify(form) !== initialForm);
}
async function saveCombination() {
  if (!combination.name.trim() || !combination.rows.length) { showError('请填写组合名称并至少添加一条溶样配置'); return; }
  const rows = combination.rows.map(row => ({ name: row.name?.trim() || '', mass_g: Number(row.mass_g) || null, volume_ml: row.volume_ml, dilution_id: row.dilution_ids[0] || null, dilution_ids: row.dilution_ids }));
  if (await save(combination.id ? `/api/preparation-combinations/${combination.id}` : '/api/preparation-combinations', combination.id ? 'PUT' : 'POST', { name: combination.name.trim(), rows })) { combinationBaseline.value = JSON.stringify(combination); editCombination(); }
}
async function removeCombination(item: Combination) {
  if (!window.confirm('确定删除这个溶样组合？已创建样品不会受影响。')) return;
  if (await save(`/api/preparation-combinations/${item.id}`, 'DELETE') && combination.id === item.id) { combinationBaseline.value = JSON.stringify(combination); editCombination(); }
}
function combinationSummary(item: Combination) { return item.rows.map(p => [p.name, [p.mass_g ? `${p.mass_g}g` : '', p.volume_ml ? `${p.volume_ml}mL` : ''].filter(Boolean).join('/'), (p.dilution_ids || (p.dilution_id ? [p.dilution_id] : [])).map(id => meta.value.dilutions.find(d => d.id === id)?.label || `#${id}`).join(' × ')].filter(Boolean).join(' · ')).join('；'); }
function openMethod(id: number | null, select: (id: number | null) => void, analyte: string) { void picker.value?.open(id, select, analyte); }
</script>

<template>
  <section id="page-settings" class="page active" :aria-busy="busy" :inert="busy || !loaded">
    <div class="grid2">
      <TemplatePanel v-if="loaded" :meta="meta" :busy="busy" :save="save" @method="openMethod" />
      <div class="panel result-order-template-panel"><h2>通用顺序模板</h2><p class="hint">用于来样、样品模板、数据、结果、报告和 Excel。模板外项目按系统默认顺序追加；可将任一模板设为系统默认。</p><div class="row"><input id="rot-name" v-model="form.orderName" placeholder="模板名称"><input id="rot-items" v-model="form.orderItems" placeholder="如 Fe, Al, Ca, Mg, Si" style="flex:1"><button id="rot-add" type="button" :disabled="busy" @click="add('order')">添加模板</button></div><div class="table-shell"><table id="rot-table" class="data-grid"><thead><tr><th>名称</th><th>项目顺序</th><th>默认</th><th>操作</th></tr></thead><tbody><tr v-for="order in meta.result_order_templates" :key="order.id" :data-rotid="order.id"><td><input v-model="order.name" class="rot-row-name" @input="dirty.add(`order:${order.id}`)"></td><td><input v-model="orderTexts[order.id]" class="rot-row-items" @input="dirty.add(`order:${order.id}`)"></td><td><input class="rot-default" type="radio" name="rot-default" title="设为系统默认顺序" :checked="Boolean(order.is_default)" :disabled="busy" @change="saveOrder(order, true)"></td><td class="actions"><button class="rot-save" type="button" :disabled="busy" @click="saveOrder(order)">保存</button><button class="del rot-delete" type="button" :disabled="busy" @click="remove(`/api/result-order-templates/${order.id}`, '确定删除这个通用顺序模板？使用它的样品和模板将改用系统默认顺序。', `order:${order.id}`)">删除</button></td></tr></tbody></table></div></div>
      <div class="panel"><h2>分析项目(元素/指标)</h2><p class="hint">显示顺序由系统默认通用顺序模板控制；无需在这里逐项移动。</p><div class="row"><input id="a-name" v-model="form.analyte" placeholder="如 Co"><button id="a-add" :disabled="busy" @click="add('analyte')">添加</button></div><div id="a-list" class="tagbox"><span v-for="a in meta.analytes" :key="a.id" class="tag analyte-unit-tag"><b>{{ a.name }}</b><select class="analyte-default-unit" :data-aid="a.id" title="默认结果单位" :value="a.default_unit || ''" :disabled="busy" @change="save(`/api/analytes/${a.id}`, 'PUT', { default_unit: ($event.target as HTMLSelectElement).value })"><option v-for="unit in resultUnits" :key="unit" :value="unit">{{ unit || '自动' }}</option></select><button class="del" :data-aid="a.id" :disabled="busy" @click="remove(`/api/analytes/${a.id}`)">×</button></span></div></div>
      <div class="panel"><h2>样品标签</h2><p class="hint">这里汇总当前样品正在使用的标签；标签在来样详情中新增或移除，仅用于筛选。</p><div id="sample-tag-settings" class="tagbox"><span v-for="tag in meta.sample_tags" :key="tag.name" class="tag sample-tag-summary">#{{ tag.name }} <small>{{ tag.count }} 个样品</small></span><span v-if="!meta.sample_tags.length" class="hint">当前没有样品标签</span></div></div>
      <div class="panel solution-instruments-panel"><h2>定容容量、二次稀释与仪器</h2><div class="solution-instruments-columns"><div><div class="setting-subsection"><h3>定容容量</h3><p class="hint">来样和样品模板从这些容量中选择；新建溶样默认使用 250 mL。</p><div class="row"><label>容量 <input id="vp-volume" v-model.number="form.volume" type="number" min="0.0001" step="0.1" style="width:90px"> mL</label><button id="vp-add" type="button" :disabled="busy" @click="add('volume')">添加容量</button></div><div id="vp-list" class="tagbox"><span v-for="v in meta.volume_presets.filter(v => v.active)" :key="v.id" class="tag">{{ v.volume_ml }} mL<template v-if="v.volume_ml === meta.default_volume_ml">（默认）</template><button v-else class="del" :data-vpid="v.id" :disabled="busy" @click="remove(`/api/volume-presets/${v.id}`, '从设置中移除这个定容容量？历史样品仍会保留原容量。')">×</button></span></div></div>
        <div class="setting-subsection"><h3>二次稀释方式</h3><p class="hint">按实际操作填写“移取多少 mL，再定容到多少 mL”。例如 5/100 会自动按 20 倍计算。</p><div class="row"><label>移取 <input id="dl-aliquot" v-model.number="form.aliquot" type="number" min="0.0001" step="0.1" placeholder="5" style="width:70px"> mL</label><span>→</span><label>定容至 <input id="dl-final-volume" v-model.number="form.finalVolume" type="number" min="0.0001" step="0.1" placeholder="100" style="width:78px"> mL</label><button id="dl-add" :disabled="busy" @click="add('dilution')">添加稀释方式</button></div><div id="dl-list" class="tagbox"><span v-for="d in meta.dilutions.filter(d => d.active)" :key="d.id" class="tag">{{ d.label }}（{{ d.factor }}倍）<button class="del" :data-did="d.id" :disabled="busy" @click="remove(`/api/dilutions/${d.id}`, '从设置中移除这个稀释方式？历史样品仍会保留原稀释参数和计算结果。')">×</button></span></div></div></div>
        <div class="setting-subsection"><h3>仪器与可测项目</h3><div class="row"><input id="i-name" v-model="form.instrument" placeholder="仪器名称"><select id="i-type" v-model="form.instrumentType"><option value="xrf">XRF（独立仪器数据）</option><option value="ppm">ppm（mg/L 换算）</option><option value="ppb">ppb（μg/L 换算）</option><option value="mol">mol（mol/L 直读）</option><option value="percent">percent（% 直读）</option><option value="function">function（公式换算）</option><option value="ph">pH（直读）</option></select><button id="i-add" :disabled="busy" @click="add('instrument')">添加仪器</button></div><div id="i-list"><div v-for="(i, index) in meta.instruments" :key="i.id" class="caprow"><button class="order-up" type="button" :data-iid="i.id" title="上移" :disabled="busy || index === 0" @click="move('instruments', i.id, -1)">↑</button><button class="order-down" type="button" :data-iid="i.id" title="下移" :disabled="busy || index === meta.instruments.length - 1" @click="move('instruments', i.id, 1)">↓</button><b>{{ i.name }}</b> <i>({{ i.itype }})</i><button class="del" :data-iid="i.id" :disabled="busy" @click="remove(`/api/instruments/${i.id}`, undefined, `cap:${i.id}`)">删除</button><button class="cap-edit" :data-iid="i.id" @click="openCaps.has(i.id) ? openCaps.delete(i.id) : openCaps.add(i.id)">可测项目</button><div :id="`cap-${i.id}`" v-show="openCaps.has(i.id)" class="cap-body"><label v-for="a in meta.analytes" :key="a.id" class="inline" style="margin-right:8px"><input v-model="i.analytes" type="checkbox" :value="a.id" @change="dirty.add(`cap:${i.id}`)"> {{ a.name }}</label><button class="cap-save" :data-iid="i.id" :disabled="busy" @click="save(`/api/instruments/${i.id}/capabilities`, 'PUT', { analyte_ids: i.analytes }, `cap:${i.id}`)">保存</button></div></div></div></div>
      </div></div>
      <div class="panel prep-combination-panel"><div class="section-head"><h2 id="pc-editor-title">{{ combination.id ? `编辑溶样组合 #${combination.id}` : '溶样组合' }}</h2><button id="pc-cancel" type="button" :hidden="!combination.id" :disabled="busy" @click="editCombination()">取消编辑</button></div><p class="hint">把常用的多路称样、定容和多级稀释保存为组合；在来样页选择后可一次追加全部配置。</p><div class="row"><input id="pc-name" v-model="combination.name" placeholder="组合名称，如 双平行+复稀"><button id="pc-row-add" type="button" :disabled="combination.rows.length >= 20" @click="combination.rows.push(newPrep(meta))">+ 加一行</button><button id="pc-save" class="primary" type="button" :disabled="busy" @click="saveCombination">{{ combination.id ? '保存修改' : '保存组合' }}</button></div><div class="table-shell"><table id="pc-prep-table" class="data-grid compact-prep-table"><thead><tr><th>溶样名称（可空）</th><th>称样(g)</th><th>定容(mL)</th><th>稀释（可多级）</th><th></th></tr></thead><PreparationRows v-model="combination.rows" :meta="meta" combination /></table></div><h3>已有组合</h3><div class="table-shell"><table id="pc-table" class="data-grid"><thead><tr><th>名称</th><th>配置</th><th>操作</th></tr></thead><tbody><tr v-for="c in meta.preparation_combinations" :key="c.id" :data-pcid="c.id"><td>{{ c.name }}</td><td>{{ combinationSummary(c) }}</td><td class="actions"><button class="pc-edit" type="button" :disabled="busy" @click="editCombination(c)">编辑</button><button class="del" type="button" :disabled="busy" @click="removeCombination(c)">删除</button></td></tr></tbody></table></div></div>
      <div class="panel method-panel"><h2>分析方法</h2><p class="hint">公式中的英文标识符会自动识别为变量，例如 (A1/A2)*50。m 固定取称样量(g)，v 固定取定容体积(mL)；其他变量可录入，或在方法常数中固定。</p><div class="row"><select id="m-type" v-model="form.methodType"><option value="function">公式方法</option><option value="xrf">XRF 方法</option></select><select id="m-output-unit" v-model="form.outputUnit" title="公式计算结果的单位" :disabled="form.methodType === 'xrf'"><option v-for="unit in outputUnits" :key="unit" :value="unit">输出 {{ unit }}</option></select><input id="m-name" v-model="form.methodName" placeholder="方法名，如 WUNI0820"><input id="m-formula" v-model="form.formula" placeholder="滴定公式（XRF 方法留空）" style="flex:1" :disabled="form.methodType === 'xrf'"><button id="m-add" :disabled="busy" @click="addMethod">添加</button></div><div class="row"><input id="m-target" v-model="form.target" placeholder="检测对象，如 Cu（可留空）" style="max-width:200px" maxlength="40" :disabled="form.methodType === 'xrf'"><input id="m-constants" v-model="form.constants" placeholder="固定常数，如 A2=10 或 M=65.38" :disabled="form.methodType === 'xrf'"><textarea id="m-note" v-model="form.note" rows="3" maxlength="2000" placeholder="滴定说明（可自定义，详情弹窗中显示）" style="flex:1"></textarea></div><p class="hint">方法在下表中的顺序，也是来样和模板中方法选择弹窗的显示顺序。</p><table id="m-table"><thead><tr><th>启用</th><th>类型</th><th>名称</th><th>检测对象</th><th>输出</th><th>公式</th><th>固定常数</th><th>备注</th><th></th></tr></thead><tbody><tr v-for="(m, index) in meta.methods" :key="m.id" :class="{ 'method-inactive': m.active === 0 }" @input="dirty.add(`method:${m.id}`)" @change="dirty.add(`method:${m.id}`)"><td><label class="method-active-toggle"><input v-model="m.active" class="m-row-active" type="checkbox" :true-value="1" :false-value="0"><span>{{ m.active !== 0 ? '启用' : '停用' }}</span></label></td><td>{{ m.itype === 'xrf' ? 'XRF' : '公式' }}</td><td tabindex="0" title="查看方法详情" @dblclick="picker?.showDetail(m)" @keydown.enter="picker?.showDetail(m)">{{ m.name }}</td><td><template v-if="m.itype === 'xrf'">—</template><input v-else v-model="m.target" class="m-row-target" maxlength="40" style="width:80px"></td><td><template v-if="m.itype === 'xrf'">—</template><select v-else v-model="m.output_unit" class="m-row-unit"><option v-for="unit in outputUnits" :key="unit" :value="unit">{{ unit }}</option></select></td><td><code>{{ m.formula || '—' }}</code></td><td>{{ constantsText(m) || '—' }}</td><td><textarea v-model="m.note" class="m-row-note" rows="2" maxlength="2000"></textarea></td><td><span class="method-order-actions"><button class="order-up" :data-mid="m.id" type="button" title="上移" :disabled="busy || index === 0" @click="move('methods', m.id, -1)">↑</button><button class="order-down" :data-mid="m.id" type="button" title="下移" :disabled="busy || index === meta.methods.length - 1" @click="move('methods', m.id, 1)">↓</button></span><button class="m-note-save" :data-mid="m.id" type="button" :disabled="busy" @click="saveMethod(m)">保存</button><button class="del" :data-mid="m.id" :disabled="busy" @click="remove(`/api/methods/${m.id}`, undefined, `method:${m.id}`)">删</button></td></tr></tbody></table></div>
      <div class="panel report-profile-panel"><h2>报告版式</h2><p class="hint">可建立多套公司抬头和文件编号；原始分析记录与分析报告票共用公司名称，分别使用各自编号。</p><div class="report-profile-form"><input id="rp-name" v-model="form.profileName" placeholder="版式名称，如 润虹默认"><input id="rp-company-cn" v-model="form.companyCn" placeholder="公司中文名"><input id="rp-company-en" v-model="form.companyEn" placeholder="公司英文名（可留空）"><input id="rp-raw-code" v-model="form.rawCode" placeholder="原始记录右上角编号"><input id="rp-final-code" v-model="form.finalCode" placeholder="报告票右上角编号"><button id="rp-add" type="button" :disabled="busy" @click="add('profile')">添加版式</button></div><div class="table-shell"><table id="rp-table" class="data-grid"><thead><tr><th>版式名称</th><th>公司中文名</th><th>公司英文名</th><th>原始记录编号</th><th>报告票编号</th><th>操作</th></tr></thead><tbody><tr v-for="p in meta.report_profiles" :key="p.id" :data-rpid="p.id" @input="dirty.add(`profile:${p.id}`)"><td><input v-model="p.name" class="rp-row-name"></td><td><input v-model="p.company_name_cn" class="rp-row-company-cn"></td><td><input v-model="p.company_name_en" class="rp-row-company-en"></td><td><input v-model="p.raw_code" class="rp-row-raw-code"></td><td><input v-model="p.final_code" class="rp-row-final-code"></td><td><button class="rp-save" type="button" :disabled="busy" @click="saveProfile(p)">保存</button><button class="del rp-delete" type="button" :disabled="busy" @click="remove(`/api/report-profiles/${p.id}`, '确定删除这套报告版式？使用它的样品将改用现存第一套版式。', `profile:${p.id}`)">删除</button></td></tr></tbody></table></div></div>
    </div>
    <MethodPicker ref="picker" :methods="meta.methods" />
  </section>
</template>
