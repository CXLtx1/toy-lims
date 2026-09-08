<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { showError } from '../../app/dialogs'
import { cloneMap, type IntakeMeta, type InstrumentMap } from './domain'

const props = defineProps<{ meta: IntakeMeta; analyteIds: number[]; modelValue: InstrumentMap; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: InstrumentMap]; method: [aid: number] }>()
const selected = ref<number[]>([])
const dragging = ref<number | null>(null)
const dragOver = ref<number | null>(null)
const instruments = computed(() => props.meta.instruments.filter(i => i.itype !== 'xrf' && props.analyteIds.some(id => i.analytes.includes(id))))
const zones = computed(() => [{ id: 0, name: '不测', kind: 'excluded' }, ...instruments.value.map(i => ({ id: i.id, name: i.name, kind: 'instrument' }))].map(zone => ({ ...zone,
  ids: props.analyteIds.filter(id => {
    const instrument = instruments.value.find(i => i.id === props.modelValue[String(id)]?.instrument_id && i.analytes.includes(id))
    return (instrument?.id ?? 0) === zone.id
  }),
})))
watch(() => props.analyteIds, ids => { selected.value = selected.value.filter(id => ids.includes(id)) })
function toggle(id: number): void {
  if (props.disabled) return
  selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : [...selected.value, id]
}
function startDrag(event: DragEvent, id: number): void {
  if (props.disabled) { event.preventDefault(); return }
  if (!selected.value.includes(id)) selected.value = [id]
  dragging.value = id
  if (event.dataTransfer) { event.dataTransfer.setData('text/plain', String(id)); event.dataTransfer.effectAllowed = 'move' }
}
function move(iid: number, dragged = 0): void {
  if (props.disabled) return
  const moving = selected.value.length ? selected.value : dragged && props.analyteIds.includes(dragged) ? [dragged] : []
  if (!moving.length) return
  const map = cloneMap(props.modelValue), rejected: string[] = []
  const instrument = instruments.value.find(i => i.id === iid)
  for (const id of moving) {
    if (!iid) delete map[String(id)]
    else if (instrument?.analytes.includes(id)) map[String(id)] = { instrument_id: iid,
      method_id: map[String(id)]?.instrument_id === iid ? map[String(id)]?.method_id ?? null : null }
    else rejected.push(props.meta.analytes.find(a => a.id === id)?.name ?? String(id))
  }
  if (rejected.length) showError(`${instrument?.name} 未配置测定：${rejected.join('、')}`, '无法分配仪器')
  selected.value = []; dragOver.value = null
  emit('update:modelValue', map)
}
function drop(event: DragEvent, iid: number): void { move(iid, Number(event.dataTransfer?.getData('text/plain'))) }
function methodName(id: number): string {
  const method = props.meta.methods.find(m => m.id === props.modelValue[String(id)]?.method_id)
  return method ? `${method.name}${method.active === 0 ? '（已停用）' : ''}` : '选择方法'
}
</script>

<template>
  <div class="p-routing">
    <div class="route-tools"><button type="button" class="route-select-all" :disabled="disabled" @click="selected = [...analyteIds]">全选标签</button><button type="button" class="route-clear-select" :disabled="disabled" @click="selected = []">取消选择</button></div>
    <div class="route-zones">
      <div v-for="zone in zones" :key="zone.id" class="route-zone" :class="[zone.kind, { 'drag-over': dragOver === zone.id }]" :data-kind="zone.kind" :data-iid="zone.id" @mousedown.stop @click="move(zone.id)" @dragover.prevent="dragOver = zone.id" @dragleave="dragOver = null" @drop.prevent="drop($event, zone.id)">
        <b>{{ zone.name }}</b><div class="route-items">
          <span v-for="id in zone.ids" :key="id" class="route-chip-wrap">
            <span class="route-chip" :class="{ selected: selected.includes(id), dragging: dragging === id }" role="button" :aria-pressed="selected.includes(id)" :tabindex="disabled ? -1 : 0" :draggable="!disabled" :data-aid="id" @mousedown.stop @click.stop="toggle(id)" @keydown.enter.stop.prevent="toggle(id)" @keydown.space.stop.prevent="toggle(id)" @dragstart.stop="startDrag($event, id)" @dragend="dragging = null">{{ meta.analytes.find(a => a.id === id)?.name ?? id }}</span>
            <button v-if="meta.instruments.find(i => i.id === zone.id)?.itype === 'function'" type="button" class="method-picker-trigger route-method" :data-aid="id" :data-method-id="modelValue[String(id)]?.method_id ?? ''" title="选择公式方法" :disabled="disabled" @click.stop="emit('method', id)"><span>{{ methodName(id) }}</span><i aria-hidden="true">⌄</i></button>
          </span>
          <i v-if="!zone.ids.length">拖到这里</i>
        </div>
      </div>
    </div>
  </div>
</template>
