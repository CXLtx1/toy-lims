<script setup lang="ts">
import { computed } from 'vue';
import { useAppState } from '../../app/state';
const props = defineProps<{ id: string; known: { name: string }[] }>();
const state = useAppState();
const available = computed(() => props.known.filter(tag => !state.tags.includes(tag.name)));
function add(event: Event) {
  const select = event.target;
  if (!(select instanceof HTMLSelectElement)) return;
  if (select.value && !state.tags.includes(select.value)) state.tags = [...state.tags, select.value];
  select.value = '';
}
</script>
<template>
  <div :id="id" class="sample-tag-filter" data-tag-filter>
    <b>标签筛选</b><select aria-label="添加标签筛选" @change="add"><option value="">+ 添加标签</option><option v-for="tag in available" :key="tag.name" :value="tag.name">#{{ tag.name }}</option></select>
    <button v-if="state.tags.length" type="button" class="sample-tag-clear" @click="state.tags = []">清除</button>
    <div class="sample-tag-filter-selected"><button v-for="tag in state.tags" :key="tag" type="button" class="active" :data-tag="tag" title="移除筛选" @click="state.tags = state.tags.filter((item: string) => item !== tag)">#{{ tag }} ×</button><span v-if="!state.tags.length" class="hint">未选择</span></div>
  </div>
</template>
