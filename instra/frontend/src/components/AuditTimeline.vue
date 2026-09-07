<template>
  <div class="audit-section">
    <div class="section-title" style="cursor: pointer" @click="open = !open">
      审计记录{{ data ? ` · ${data.total} 条` : "" }}
      <span class="hint" style="font-weight: 400">{{ open ? "▲ 收起" : "▼ 展开" }}</span>
    </div>
    <n-spin v-if="open" :show="isFetching">
      <p v-if="isError" class="hint" style="color: var(--danger)">加载失败：{{ error?.message }}</p>
      <div v-else-if="data" class="audit-timeline">
        <div v-for="entry in data.items" :key="entry.id" class="audit-entry">
          <div class="a-rail"><span class="a-dot"></span></div>
          <div class="a-body">
            <div class="a-head">
              <b>{{ entry.action_label }}</b>
              <span class="a-entity">{{ entry.entity_label }}</span>
              <span class="a-who">{{ entry.username }}<template v-if="entry.terminal_name"> @ {{ entry.terminal_name }}</template></span>
              <span class="a-time">{{ entry.created_at }}</span>
              <span v-if="entry.ip_address" class="a-ip">{{ entry.ip_address }}</span>
            </div>
            <div v-if="entry.reason" class="a-reason">备注：{{ entry.reason }}</div>
            <div v-if="entry.changes.length" class="a-changes">
              <div v-for="(change, i) in entry.changes" :key="i" class="a-change">
                <span class="a-field">{{ change.label }}</span>
                <span class="a-before">{{ display(change.before) }}</span>
                <span class="a-arrow">→</span>
                <span class="a-after">{{ display(change.after) }}</span>
              </div>
            </div>
            <div v-else-if="entry.has_snapshot" class="hint">（快照无字段差异或为创建/删除类事件）</div>
          </div>
        </div>
        <p v-if="!data.items.length" class="hint">暂无审计记录。</p>
      </div>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { NSpin } from "naive-ui";
import { api } from "../api/client";

interface AuditChange { label: string; before: unknown; after: unknown }
interface AuditEntry {
  id: number; created_at: string; username: string; terminal_name: string | null;
  ip_address: string; action: string; action_label: string; entity_label: string;
  reason: string; changes: AuditChange[]; has_snapshot: boolean;
}

const props = defineProps<{ sampleId: number }>();
const open = ref(false);

const { data, isFetching, isError, error } = useQuery({
  queryKey: computed(() => ["audit", props.sampleId]),
  queryFn: () => api<{ ok: boolean; total: number; items: AuditEntry[] }>(
    `/api/samples/${props.sampleId}/audit`),
  enabled: open,  // 展开才拉取
});

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
</script>
