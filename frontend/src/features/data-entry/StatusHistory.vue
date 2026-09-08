<script setup lang="ts">
import { computed } from 'vue';
import type { Sample } from './types';
const props = defineProps<{ sample: Sample; labels?: Record<string, string> }>();
const history = computed(() => props.sample.status_history?.length ? props.sample.status_history : props.sample.status_operator
  ? [{ action: props.sample.status_action || '', operator: props.sample.status_operator, at: props.sample.status_changed_at }] : []);
const compact: Record<string, string> = { received: '登记', queued: '制样', measuring: '开始测量', completed: '测量完成', reviewed: '审核', cancelled: '作废' };
</script>
<template>
  <span v-if="history.length" class="status-history"><span v-for="(item, index) in history" :key="index" class="status-history-item" :class="{ rollback: item.rollback, 'review-rollback': item.rollback && item.action === 'completed' }" :title="[item.at || '时间未知', item.reason].filter(Boolean).join(' · ')"><b>{{ item.rollback ? (item.action === 'completed' ? '撤回审核' : `退回${labels?.[item.action] || item.action}`) : compact[item.action] || item.action || '状态' }}</b><em>{{ item.operator || '系统' }}</em></span></span>
</template>
