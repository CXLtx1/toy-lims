<script setup lang="ts">
import { computed, ref } from 'vue';
import { showError } from '../../app/dialogs';
import type { InstrumentMap, SettingsMeta } from './types';
const props = defineProps<{ meta: SettingsMeta; analyteIds: number[] }>();
const map = defineModel<InstrumentMap>({ required: true });
const emit = defineEmits<{ method: [id: number | null, select: (id: number | null) => void, analyte: string] }>();
const selected = ref<number[]>([]), dragOver = ref<number | null>(null), dragging = ref<number | null>(null);
const zones = computed(() => [{ id: 0, name: '不测', itype: '', analytes: props.analyteIds }, ...props.meta.instruments.filter(i => i.itype !== 'xrf' && i.analytes.some(id => props.analyteIds.includes(id)))]);
const name = (id: number) => props.meta.analytes.find(a => a.id === id)?.name || String(id);
function assigned(id: number) { const route = map.value[id]; return zones.value.find(i => i.id === route?.instrument_id && i.analytes.includes(id))?.id || 0; }
function toggle(id: number) { selected.value = selected.value.includes(id) ? selected.value.filter(a => a !== id) : [...selected.value, id]; }
function move(iid: number, event?: DragEvent) {
  const fallback = Number(event?.dataTransfer?.getData('text/plain'));
  const ids = selected.value.length ? selected.value : fallback ? [fallback] : [];
  const instrument = props.meta.instruments.find(i => i.id === iid), next = { ...map.value }, rejected: string[] = [];
  for (const id of ids.filter(id => props.analyteIds.includes(id))) {
    if (!iid) delete next[id];
    else if (instrument?.analytes.includes(id)) next[id] = { instrument_id: iid, method_id: next[id]?.instrument_id === iid ? next[id]?.method_id ?? null : null };
    else rejected.push(name(id));
  }
  map.value = next; selected.value = []; dragOver.value = null;
  if (rejected.length) showError(`${instrument?.name} 未配置测定：${rejected.join('、')}`, '无法分配仪器');
}
function startDrag(id: number, event: DragEvent) { if (!selected.value.includes(id)) selected.value = [id]; dragging.value = id; event.dataTransfer?.setData('text/plain', String(id)); if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'; }
function pick(id: number) { emit('method', map.value[id]?.method_id ?? null, methodId => { const route = map.value[id]; if (route) map.value = { ...map.value, [id]: { ...route, method_id: methodId } }; }, name(id)); }
function methodName(id: number) { const m = props.meta.methods.find(m => m.id === map.value[id]?.method_id); return m ? `${m.name}${m.active === 0 ? '（已停用）' : ''}` : '选择方法'; }
</script>
<template>
  <div class="p-routing tp-routing"><div class="route-tools"><button type="button" class="route-select-all" @click="selected = [...analyteIds]">全选标签</button><button type="button" class="route-clear-select" @click="selected = []">取消选择</button></div><div class="route-zones">
    <div v-for="zone in zones" :key="zone.id" class="route-zone" :class="[zone.id ? 'instrument' : 'excluded', { 'drag-over': dragOver === zone.id }]" :data-kind="zone.id ? 'instrument' : 'excluded'" :data-iid="zone.id" @click="move(zone.id)" @dragover.prevent="dragOver = zone.id" @dragleave="dragOver = null" @drop.prevent.stop="move(zone.id, $event)"><b>{{ zone.name }}</b><div class="route-items">
      <span v-for="id in analyteIds.filter(id => assigned(id) === zone.id)" :key="id" class="route-chip-wrap"><span class="route-chip" :class="{ selected: selected.includes(id), dragging: dragging === id }" role="button" tabindex="0" draggable="true" :data-aid="id" :aria-pressed="selected.includes(id)" @click.stop="toggle(id)" @keydown.enter.stop.prevent="toggle(id)" @keydown.space.stop.prevent="toggle(id)" @dragstart.stop="startDrag(id, $event)" @dragend="dragging = null">{{ name(id) }}</span><button v-if="zone.itype === 'function'" type="button" class="method-picker-trigger route-method" :data-aid="id" :data-method-id="map[id]?.method_id || ''" title="选择公式方法" @click.stop="pick(id)"><span>{{ methodName(id) }}</span><i aria-hidden="true">⌄</i></button></span>
      <i v-if="!analyteIds.some(id => assigned(id) === zone.id)">拖到这里</i>
    </div></div>
  </div></div>
</template>
