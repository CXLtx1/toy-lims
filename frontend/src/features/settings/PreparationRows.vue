<script setup lang="ts">
import RoutingBoard from './RoutingBoard.vue';
import type { Prep, SettingsMeta } from './types';
const props = defineProps<{ meta: SettingsMeta; combination?: boolean; liquid?: boolean; analyteIds?: number[] }>();
const rows = defineModel<Prep[]>({ required: true });
const emit = defineEmits<{ method: [id: number | null, select: (id: number | null) => void, analyte: string] }>();
function volumes(current: number | null) {
  const result = props.meta.volume_presets.filter(v => v.active || v.volume_ml === current).map(v => ({ value: v.volume_ml, active: v.active }));
  if (current && !result.some(v => v.value === current)) result.push({ value: current, active: 0 });
  return result;
}
function copy(index: number) { const row = rows.value[index]; if (row) rows.value.splice(index + 1, 0, JSON.parse(JSON.stringify(row)) as Prep); }
function addDilution(row: Prep) { const id = row.dilution_ids[row.dilution_ids.length - 1] ?? props.meta.dilutions.find(d => d.active)?.id; if (id && row.dilution_ids.length < 8) row.dilution_ids.push(id); }
</script>
<template>
  <tbody><tr v-for="(row, index) in rows" :key="index">
    <td v-if="combination"><input v-model="row.name" class="pc-row-name" placeholder="留空自动生成"></td>
    <td v-show="combination || !liquid" :class="combination ? undefined : 't-solid-only'"><input v-model.number="row.mass_g" :class="combination ? 'pc-mass' : 'tp-mass'" type="number" min="0.000001" step="0.0001"></td>
    <td v-show="combination || !liquid" :class="combination ? undefined : 't-solid-only'"><select v-model="row.volume_ml" :class="combination ? 'pc-vol' : 'tp-vol'"><option v-for="volume in volumes(row.volume_ml)" :key="volume.value" :value="volume.value">{{ volume.value }} mL{{ volume.active ? '' : '（历史值）' }}</option></select></td>
    <td><div class="dilution-chain" :data-select-class="combination ? 'pc-dil' : 'tp-dil'"><span v-for="(id, step) in row.dilution_ids" :key="step" class="dilution-step"><select v-model="row.dilution_ids[step]" :class="combination ? 'pc-dil' : 'tp-dil'"><option v-for="d in meta.dilutions.filter(d => d.active || d.id === id)" :key="d.id" :value="d.id">{{ d.label }}{{ d.active ? '' : '（停用）' }}</option></select><button class="dilution-remove" type="button" title="删除这一级" :disabled="row.dilution_ids.length <= 1" @click="row.dilution_ids.splice(step, 1)">×</button></span><button class="dilution-add" type="button" title="追加一级稀释" :disabled="row.dilution_ids.length >= 8" @click="addDilution(row)">+</button></div></td>
    <td v-if="!combination"><input v-model.number="row.count" class="tp-count" type="number" min="1" max="10" step="1" title="平行份数，大于 1 时自动生成 -1、-2 后缀"></td>
    <td v-if="!combination" class="p-routing-cell"><RoutingBoard v-model="row.instrument_map" :meta="meta" :analyte-ids="analyteIds || []" @method="(id, select, analyte) => emit('method', id, select, analyte)" /></td>
    <td class="prep-row-actions"><button class="copy-row" type="button" title="复制整行" @click="copy(index)">⧉</button><button class="del" type="button" @click="rows.splice(index, 1)">×</button></td>
  </tr></tbody>
</template>
