<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import MethodPicker from './MethodPicker.vue'
import RoutingBoard from './RoutingBoard.vue'
import { assignedIds, cloneMap, createPrep, preparationNames, type IntakeMeta, type InstrumentMap, type PrepDraft } from './domain'
import { usePreparationGrid } from './usePreparationGrid'

const props = withDefaults(defineProps<{ modelValue: PrepDraft[]; meta: IntakeMeta; analyteIds: number[]; sampleName: string;
  liquid?: boolean; disabled?: boolean; defaultInstrumentMap?: InstrumentMap; idPrefix?: string }>(), { idPrefix: 'p' })
const emit = defineEmits<{ 'update:modelValue': [rows: PrepDraft[]] }>()
const table = ref<HTMLTableElement | null>(null)
const combination = ref<number | ''>('')
const methodTarget = ref<{ key: number; aid: number } | null>(null)
const methodRow = computed(() => props.modelValue.find(row => row.key === methodTarget.value?.key))
const grid = usePreparationGrid(table, add, () => !!props.disabled)
watch(() => props.modelValue.map(row => row.key).join(','), () => grid.reset())
function update(row: PrepDraft, change: Partial<PrepDraft>): void {
  if (props.disabled) return
  // Clipboard writes several cells before Vue's next render; keep the current row live.
  Object.assign(row, change)
  emit('update:modelValue', props.modelValue)
}
function text(event: Event): string { return event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement ? event.target.value : '' }
function add(): void {
  if (props.disabled) return
  emit('update:modelValue', [...props.modelValue, createPrep(props.meta, {}, props.defaultInstrumentMap)])
}
function copy(row: PrepDraft, index: number): void {
  const copy = { ...row, key: createPrep(props.meta).key, id: undefined, instrumentMap: cloneMap(row.instrumentMap), dilutionIds: [...row.dilutionIds] }
  emit('update:modelValue', [...props.modelValue.slice(0, index + 1), copy, ...props.modelValue.slice(index + 1)])
}
function remove(row: PrepDraft): void { emit('update:modelValue', props.modelValue.filter(item => item.key !== row.key)) }
function volumes(current: number) {
  const choices = props.meta.volume_presets.filter(v => v.active || v.volume_ml === current)
  return choices.some(v => v.volume_ml === current) ? choices : [...choices, { id: null, volume_ml: current, active: 0 }]
}
function dilution(row: PrepDraft, index: number, event: Event): void {
  const ids = [...row.dilutionIds]; ids[index] = Number(text(event)); update(row, { dilutionIds: ids })
}
function addDilution(row: PrepDraft): void {
  const id = row.dilutionIds.at(-1) ?? props.meta.dilutions.find(d => d.active)?.id
  if (id !== undefined && row.dilutionIds.length < 8) update(row, { dilutionIds: [...row.dilutionIds, id] })
}
function appendCombination(): void {
  const entry = props.meta.preparation_combinations.find(c => c.id === combination.value)
  if (entry) emit('update:modelValue', [...props.modelValue, ...entry.rows.map(row => createPrep(props.meta, row, props.defaultInstrumentMap))])
}
function selectMethod(id: number | null): void {
  const row = methodRow.value, aid = methodTarget.value?.aid
  if (row && aid !== undefined) {
    const map = cloneMap(row.instrumentMap), setting = map[String(aid)]
    if (setting) { setting.method_id = id; update(row, { instrumentMap: map }) }
  }
  methodTarget.value = null
}
function names(row: PrepDraft): string[] { return preparationNames(row, props.sampleName, props.analyteIds, props.meta) }
function hasHandle(row: number, col: number): boolean { return !props.disabled && grid.state.focus?.row === row && grid.state.focus.col === col }
defineExpose({ add, copySelection: grid.copy, fillDown: grid.fillDown })
</script>

<template>
  <div class="grid-toolbar"><button type="button" class="prep-grid-copy" title="复制选区 (Ctrl+C)" @click="grid.copy">⧉</button><button type="button" class="prep-grid-fill" title="向下填充 (Ctrl+D)" :disabled="disabled" @click="grid.fillDown()">↓</button><span :id="`${idPrefix}-grid-status`">{{ grid.state.status }}</span></div>
  <div class="table-shell prep-shell"><table :id="`${idPrefix}-table`" ref="table" class="data-grid spreadsheet" tabindex="0" @mousedown="grid.mousedown" @mouseover="grid.mouseover" @copy="grid.onCopy" @paste="grid.onPaste" @keydown="grid.keydown">
    <thead><tr><th>溶样名称（可改）</th><th v-show="!liquid" class="solid-only">称样(g)</th><th v-show="!liquid" class="solid-only">定容(mL)</th><th>稀释（可多级）</th><th title="平行份数，大于 1 时自动生成 -1、-2 后缀">平行</th><th>测定项目与仪器分配（横向拖拽）</th><th></th></tr></thead>
    <tbody><tr v-for="(row, index) in modelValue" :key="row.key" :data-pid="row.id ?? ''">
      <td class="grid-cell p-name-cell" :class="grid.cellClass(index, 0)" :data-row="index" data-col="0"><input class="p-name" :value="row.autoName ? names(row)[0] : row.name" placeholder="留空自动生成" :disabled="disabled" @input="update(row, { name: text($event), autoName: !text($event).trim() })"><small class="p-preview">结果：{{ names(row).join(' / ') }}</small><span v-if="hasHandle(index, 0)" class="fill-handle" title="拖动填充" @mousedown.stop.prevent="grid.beginFill" /></td>
      <td v-show="!liquid" class="solid-only grid-cell" :class="grid.cellClass(index, 1)" :data-row="index" data-col="1"><input class="p-mass" type="number" step="0.0001" :value="row.mass" :disabled="disabled" @input="update(row, { mass: text($event) })"><span v-if="hasHandle(index, 1)" class="fill-handle" title="拖动填充" @mousedown.stop.prevent="grid.beginFill" /></td>
      <td v-show="!liquid" class="solid-only grid-cell" :class="grid.cellClass(index, 2)" :data-row="index" data-col="2"><select class="p-vol" :value="row.volume" :disabled="disabled" @change="update(row, { volume: Number(text($event)) })"><option v-for="volume in volumes(row.volume)" :key="volume.volume_ml" :value="volume.volume_ml">{{ volume.volume_ml }} mL{{ volume.active ? '' : '（历史值）' }}</option></select><span v-if="hasHandle(index, 2)" class="fill-handle" title="拖动填充" @mousedown.stop.prevent="grid.beginFill" /></td>
      <td class="grid-cell" :class="grid.cellClass(index, 3)" :data-row="index" data-col="3"><div class="dilution-chain" data-select-class="p-dil"><span v-for="(id, step) in row.dilutionIds" :key="step" class="dilution-step"><select class="p-dil" :value="id" :disabled="disabled" @change="dilution(row, step, $event)"><option v-for="choice in meta.dilutions.filter(d => d.active || d.id === id)" :key="choice.id" :value="choice.id">{{ choice.label }}{{ choice.active ? '' : '（停用）' }}</option></select><button class="dilution-remove" type="button" title="删除这一级" :disabled="disabled || row.dilutionIds.length <= 1" @click="update(row, { dilutionIds: row.dilutionIds.filter((_, i) => i !== step) })">×</button></span><button class="dilution-add" type="button" title="追加一级稀释" :disabled="disabled || row.dilutionIds.length >= 8" @click="addDilution(row)">+</button></div><span v-if="hasHandle(index, 3)" class="fill-handle" title="拖动填充" @mousedown.stop.prevent="grid.beginFill" /></td>
      <td class="grid-cell" :class="grid.cellClass(index, 4)" :data-row="index" data-col="4"><input class="p-count" type="number" min="1" max="10" step="1" :value="row.count" title="平行份数，大于 1 时自动生成 -1、-2 后缀" :disabled="disabled" @input="update(row, { count: text($event) })"><span v-if="hasHandle(index, 4)" class="fill-handle" title="拖动填充" @mousedown.stop.prevent="grid.beginFill" /></td>
      <td class="grid-cell p-routing-cell" :class="grid.cellClass(index, 5)" :data-row="index" data-col="5"><input class="p-analytes" type="hidden" :value="assignedIds(row, analyteIds, meta).map(id => meta.analytes.find(a => a.id === id)?.name).join(', ')"><RoutingBoard :meta="meta" :analyte-ids="analyteIds" :model-value="row.instrumentMap" :disabled="disabled" @update:model-value="update(row, { instrumentMap: $event })" @method="methodTarget = { key: row.key, aid: $event }" /></td>
      <td class="grid-cell readonly prep-row-actions" :class="grid.cellClass(index, 6)" :data-row="index" data-col="6"><button class="copy-row" type="button" title="复制整行" :disabled="disabled" @click="copy(row, index)">⧉</button><button class="del" type="button" title="删除" :disabled="disabled" @click="remove(row)">×</button></td>
    </tr></tbody>
  </table></div>
  <div class="editor-footer"><button :id="`${idPrefix}-add`" type="button" :disabled="disabled" @click="add">+ 加一路溶样</button><span class="footer-spacer"></span><label class="prep-combination-picker">溶样组合 <select :id="`${idPrefix}-combination`" v-model="combination" :disabled="disabled"><option value="">— 选择组合 —</option><option v-for="entry in meta.preparation_combinations" :key="entry.id" :value="entry.id">{{ entry.name }}（{{ entry.rows.length }}路）</option></select></label><button :id="`${idPrefix}-combination-add`" type="button" :disabled="disabled || !meta.preparation_combinations.length" @click="appendCombination">追加组合</button></div>
  <MethodPicker v-if="methodTarget && methodRow" :methods="meta.methods" :selected-id="methodRow.instrumentMap[String(methodTarget.aid)]?.method_id ?? null" :initial-search="meta.analytes.find(a => a.id === methodTarget?.aid)?.name" @select="selectMethod" @close="methodTarget = null" />
</template>
