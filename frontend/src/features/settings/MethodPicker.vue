<script setup lang="ts">
import { computed, nextTick, ref } from 'vue';
import { constantsText, type Method } from './types';
const props = defineProps<{ methods: Method[] }>();
const opened = ref(false), query = ref(''), selected = ref<number | null>(null), search = ref<HTMLInputElement>();
const detail = ref<Method | null>(null);
let callback: ((id: number | null) => void) | null = null;
let returnFocus: HTMLElement | null = null;
const filtered = computed(() => props.methods.filter(m => m.itype !== 'xrf' && m.active !== 0 && `${m.name} ${m.target}`.toLowerCase().includes(query.value.trim().toLowerCase())));
async function open(id: number | null, onSelect: (id: number | null) => void, analyte = '') {
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  selected.value = id; callback = onSelect; query.value = analyte; opened.value = true;
  await nextTick(); search.value?.focus(); search.value?.select();
}
function close() { opened.value = false; callback = null; returnFocus?.focus(); }
function choose(id: number | null) { const fn = callback; close(); fn?.(id); }
async function showDetail(method: Method) {
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  detail.value = method; await nextTick(); document.getElementById('method-detail-close')?.focus();
}
function closeDetail() { detail.value = null; returnFocus?.focus(); }
function trapFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !(event.currentTarget instanceof HTMLElement)) return;
  const items = [...event.currentTarget.querySelectorAll<HTMLElement>('input, button:not(:disabled)')];
  const first = items[0], last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
}
defineExpose({ open, showDetail });
</script>
<template>
  <Teleport to="body">
    <div v-if="opened" id="method-picker-backdrop" class="dialog-backdrop" @mousedown.self="close" @keydown.esc.prevent.stop="close" @keydown="trapFocus">
      <section class="method-picker-dialog" role="dialog" aria-modal="true" aria-labelledby="method-picker-title"><button id="method-picker-x" class="dialog-x" type="button" aria-label="关闭" @click="close">×</button>
        <div class="method-picker-heading"><div><span>公式方法</span><h2 id="method-picker-title">选择滴定方法</h2></div><b id="method-picker-count">{{ filtered.length }} 个方法</b></div>
        <label class="method-picker-search"><span aria-hidden="true">⌕</span><input id="method-picker-search" ref="search" v-model="query" type="search" autocomplete="off" placeholder="搜索方法名称或检测对象"></label>
        <div id="method-picker-list" class="method-picker-list"><button v-for="(method, index) in filtered" :key="method.id" type="button" class="method-picker-item" :class="{ selected: selected === method.id }" :data-method-id="method.id" @click="choose(method.id)"><span class="method-picker-index">{{ String(index + 1).padStart(2, '0') }}</span><span class="method-picker-copy"><b><span v-if="method.target" class="method-picker-target">{{ method.target }}</span>{{ method.name }}</b><code>{{ method.formula || '未设置公式' }}</code><small v-if="method.note">{{ method.note }}</small></span><span class="method-picker-constants"><b>{{ method.output_unit || '%' }}</b><small v-if="constantsText(method)">{{ constantsText(method) }}</small></span><span class="method-picker-check">{{ selected === method.id ? '✓' : '' }}</span></button><div v-if="!filtered.length" class="method-picker-empty"><b>没有匹配的方法</b><span>换一个方法名称试试</span></div></div>
        <div class="method-picker-footer"><button id="method-picker-clear" type="button" @click="choose(null)">不选择方法</button><span>可在设置页调整显示顺序</span></div>
      </section>
    </div>
    <div v-if="detail" id="method-detail-backdrop" class="dialog-backdrop" @mousedown.self="closeDetail" @keydown.esc.prevent.stop="closeDetail" @keydown="trapFocus"><section class="method-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="method-detail-title"><button id="method-detail-x" class="dialog-x" type="button" aria-label="关闭" @click="closeDetail">×</button><h2 id="method-detail-title">{{ detail.name }}</h2><dl class="method-detail-meta"><dt>输出单位</dt><dd id="method-detail-output-unit">{{ detail.output_unit || '%' }}</dd><dt>公式</dt><dd id="method-detail-formula">{{ detail.formula || '—' }}</dd><dt>固定参数</dt><dd id="method-detail-constants">{{ constantsText(detail) || '—' }}</dd></dl><h3>滴定说明</h3><div id="method-detail-note">{{ detail.note || '暂无说明' }}</div><div class="dialog-actions"><button id="method-detail-close" type="button" class="primary" @click="closeDetail">关闭</button></div></section></div>
  </Teleport>
</template>
