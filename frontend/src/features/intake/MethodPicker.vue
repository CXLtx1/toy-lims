<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { parseJson, type Method } from './domain'

const props = defineProps<{ methods: Method[]; selectedId: number | null; initialSearch?: string }>()
const emit = defineEmits<{ select: [id: number | null]; close: [] }>()
const query = ref(props.initialSearch ?? '')
const search = ref<HTMLInputElement | null>(null)
const dialog = ref<HTMLElement | null>(null)
const returnFocus = document.activeElement
const methods = computed(() => props.methods.filter(method => {
  const type = method.itype === 'titration' ? 'function' : method.itype || 'function'
  const text = query.value.trim().toLowerCase()
  return type === 'function' && method.active !== 0 && (!text || [method.name, method.target, method.formula, method.note, method.constants].some(value => value?.toLowerCase().includes(text)))
}))
function constants(method: Method): string {
  return Object.entries(parseJson<Record<string, string | number>>(method.constants, {})).map(([key, value]) => `${key}=${value}`).join(' · ')
}
function keydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); emit('close') }
  if (event.key !== 'Tab') return
  const controls = Array.from(dialog.value?.querySelectorAll<HTMLElement>('input,button:not(:disabled)') ?? [])
  const target = event.shiftKey ? controls.at(-1) : controls[0]
  if (document.activeElement === (event.shiftKey ? controls[0] : controls.at(-1))) { event.preventDefault(); target?.focus() }
}
onMounted(async () => { window.addEventListener('keydown', keydown, true); await nextTick(); search.value?.focus(); search.value?.select() })
onBeforeUnmount(() => { window.removeEventListener('keydown', keydown, true); if (returnFocus instanceof HTMLElement && returnFocus.isConnected) returnFocus.focus() })
</script>

<template>
  <Teleport to="body">
    <div id="method-picker-backdrop" class="dialog-backdrop" @mousedown.self="emit('close')">
      <section ref="dialog" class="method-picker-dialog" role="dialog" aria-modal="true" aria-labelledby="method-picker-title">
        <button id="method-picker-x" class="dialog-x" type="button" aria-label="关闭" @click="emit('close')">×</button>
        <div class="method-picker-heading"><div><span>公式方法</span><h2 id="method-picker-title">选择滴定方法</h2></div><b id="method-picker-count">{{ methods.length }} 个方法</b></div>
        <label class="method-picker-search"><span aria-hidden="true">⌕</span><input id="method-picker-search" ref="search" v-model="query" type="search" autocomplete="off" placeholder="搜索方法名称或检测对象"></label>
        <div id="method-picker-list" class="method-picker-list">
          <button v-for="(method, index) in methods" :key="method.id" type="button" class="method-picker-item" :class="{ selected: method.id === selectedId }" :data-method-id="method.id" @click="emit('select', method.id)">
            <span class="method-picker-index">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="method-picker-copy"><b><span v-if="method.target" class="method-picker-target">{{ method.target }}</span>{{ method.name }}</b><code>{{ method.formula || '未设置公式' }}</code><small v-if="method.note">{{ method.note }}</small></span>
            <span class="method-picker-constants"><b>{{ method.output_unit || '%' }}</b><small v-if="constants(method)">{{ constants(method) }}</small></span><span class="method-picker-check">{{ method.id === selectedId ? '✓' : '' }}</span>
          </button>
          <div v-if="!methods.length" class="method-picker-empty"><b>没有匹配的方法</b><span>换一个方法名称试试</span></div>
        </div>
        <div class="method-picker-footer"><button id="method-picker-clear" type="button" @click="emit('select', null)">不选择方法</button><span>可在设置页调整显示顺序</span></div>
      </section>
    </div>
  </Teleport>
</template>
