<template>
  <div>
    <div class="filter-bar">
      <n-input v-model:value="keyword" placeholder="搜索来样序号 / LIMS 编号 / 描述 / 标签"
               clearable style="width: 280px" @keyup.enter="search" />
      <n-select v-model:value="selectedTags" :options="tagOptions" multiple filterable
                placeholder="标签筛选" clearable style="width: 220px" />
      <n-select v-model:value="status" :options="statusOptions" placeholder="全部状态"
                clearable style="width: 130px" />
      <n-date-picker v-model:value="dateRange" type="daterange" clearable
                     placeholder="登记日期范围" style="width: 240px" />
      <n-button type="primary" @click="search">查询</n-button>
      <span style="flex: 1"></span>
      <n-button quaternary size="small" :disabled="!expanded.size" @click="collapseAll">全部收起</n-button>
    </div>

    <n-spin :show="isFetching">
      <p v-if="isError" class="hint" style="color: var(--danger)">加载失败：{{ error?.message }}</p>
      <div class="sample-list-full">
        <section v-for="item in items" :key="item.id" class="sample-block"
                 :class="{ open: expanded.has(item.id) }">
          <!-- 列表行：直接展示详细信息 -->
          <div class="sb-head" @click="toggleExpand(item.id)">
            <div class="sb-title">
              <span class="sb-name">{{ item.name }}</span>
              <span class="sb-lims">{{ item.lims_no }}</span>
              <span class="badge" :class="`status-${item.status}`">{{ statusLabel(item.status) }}</span>
              <span class="badge type">{{ item.type }}</span>
              <span v-if="item.xrf" class="badge xrf">XRF</span>
              <span v-for="tag in item.tags" :key="tag" class="tag-chip"
                    @click.stop="quickTag(tag)">#{{ tag }}</span>
            </div>
            <div class="sb-sub">
              <span v-if="item.category">{{ item.category }}</span>
              <span>{{ item.prep_count }} 路溶样</span>
              <span v-if="item.xrf_scan_count">XRF {{ item.xrf_scan_count }} 次</span>
              <span>登记 {{ fmtTime(item.created_at) }}</span>
              <span v-if="item.analyst">检测 {{ item.analyst }}</span>
              <span v-if="item.reviewer">审核 {{ item.reviewer }}</span>
            </div>
            <div class="sb-analytes">
              <span v-for="a in item.analytes" :key="a" class="analyte-chip">{{ a }}</span>
            </div>
            <span class="sb-toggle">{{ expanded.has(item.id) ? "收起 ▲" : "展开 ▼" }}</span>
          </div>
          <!-- 点开更详细：完整聚合 -->
          <div v-if="expanded.has(item.id)" class="sb-body">
            <SampleAggregate :sample-id="item.id" />
          </div>
        </section>
        <p v-if="!isFetching && !items.length && !isError" class="hint">没有符合条件的样品。</p>
      </div>
    </n-spin>
    <div class="pager">
      <n-pagination v-model:page="page" :item-count="total" :page-size="perPage" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useQuery } from "@tanstack/vue-query";
import {
  NButton, NDatePicker, NInput, NPagination, NSelect, NSpin,
} from "naive-ui";
import dayjs from "dayjs";
import { api } from "../api/client";
import { useCardExpansion } from "../composables/useCardExpansion";
import { useKeyboardShortcuts } from "../composables/useKeyboardShortcuts";
import type { Paged, SampleListItem } from "../api/types";
import { fmtTime, statusLabel } from "../utils";
import SampleAggregate from "../components/SampleAggregate.vue";

const keyword = ref("");
const selectedTags = ref<string[]>([]);
const status = ref<string | null>(null);
const dateRange = ref<[number, number] | null>(null);
const page = ref(1);
const perPage = 20;
const { expanded, toggle: toggleExpand, closeLast, collapseAll } = useCardExpansion<number>();

const statusOptions = [
  { label: "已登记", value: "received" },
  { label: "测量中", value: "measuring" },
  { label: "部分完成", value: "partially_done" },
  { label: "待审核", value: "completed" },
  { label: "已审核", value: "reviewed" },
  { label: "已出报告", value: "reported" },
  { label: "已作废", value: "cancelled" },
];

// 查询参数快照：点“查询”才生效，避免输入过程反复请求
const active = ref({ keyword: "", tags: [] as string[], status: "", date_from: "", date_to: "" });

function search() {
  page.value = 1;
  active.value = {
    keyword: keyword.value.trim(),
    tags: [...selectedTags.value],
    status: status.value || "",
    date_from: dateRange.value ? dayjs(dateRange.value[0]).format("YYYY-MM-DD") : "",
    date_to: dateRange.value ? dayjs(dateRange.value[1]).format("YYYY-MM-DD") : "",
  };
}

/** 点击行内标签 = 直接加入筛选并查询 */
function quickTag(tag: string) {
  if (!selectedTags.value.includes(tag)) selectedTags.value = [...selectedTags.value, tag];
  search();
}

const { data: tagData } = useQuery({
  queryKey: ["tags"],
  queryFn: () => api<{ ok: boolean; items: { tag: string; count: number }[] }>("/api/tags"),
});
const tagOptions = computed(() =>
  (tagData.value?.items ?? []).map((t) => ({ label: `#${t.tag}（${t.count}）`, value: t.tag })));

const queryParams = computed(() => {
  const params = new URLSearchParams();
  if (active.value.keyword) params.set("keyword", active.value.keyword);
  for (const tag of active.value.tags) params.append("tag", tag);
  if (active.value.status) params.set("status", active.value.status);
  if (active.value.date_from) params.set("date_from", active.value.date_from);
  if (active.value.date_to) params.set("date_to", active.value.date_to);
  params.set("page", String(page.value));
  params.set("per_page", String(perPage));
  return params.toString();
});

const { data, isFetching, isError, error } = useQuery({
  queryKey: computed(() => ["samples", queryParams.value]),
  queryFn: () => api<Paged<SampleListItem>>(`/api/samples?${queryParams.value}`),
});

const items = computed(() => data.value?.items ?? []);
const total = computed(() => data.value?.total ?? 0);

useKeyboardShortcuts([
  { key: "Escape", enabled: () => expanded.value.size > 0, run: closeLast },
]);
</script>
