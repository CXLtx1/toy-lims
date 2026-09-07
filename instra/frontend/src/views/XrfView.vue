<template>
  <div>
    <n-tabs v-model:value="tab" type="line" animated>
      <n-tab-pane name="quant"><template #tab>定量扫描</template></n-tab-pane>
      <n-tab-pane name="uq"><template #tab>UniQuant</template></n-tab-pane>
    </n-tabs>

    <div class="filter-bar">
      <n-input v-model:value="keyword" placeholder="搜索样品 / LIMS 编号 / 方法 / 批次 / 扫描编号"
               clearable style="width: 320px" @keyup.enter="search" />
      <n-date-picker v-model:value="dateRange" type="daterange" clearable
                     placeholder="分析日期范围" style="width: 260px" />
      <n-button type="primary" @click="search">查询</n-button>
      <span style="flex: 1"></span>
      <n-button quaternary size="small" :disabled="!expanded.size"
                @click="collapseAll">全部收起</n-button>
      <span class="hint">已选 {{ checked.size }} 条</span>
      <n-button :disabled="!checked.size" @click="drawerOpen = true">导出</n-button>
    </div>

    <n-spin :show="isFetching">
      <p v-if="isError" class="hint" style="color: var(--danger)">加载失败：{{ error?.message }}</p>
      <div class="scan-list">
        <section v-for="item in items" :key="item.id" class="scan-row"
                 :class="[item.kind, { open: expanded.has(item.id) }]">
          <div class="scan-head" title="点击展开；Ctrl+点击选择"
               @click="handleScanClick($event, item.id)">
            <div class="s-check" @click.stop>
              <n-checkbox :checked="checked.has(item.id)"
                          @update:checked="(v: boolean) => toggle(item.id, v)" />
            </div>
            <div class="s-main">
              <div class="s-line1">
                <span class="s-name">{{ item.sample_name }}</span>
                <span class="s-time">{{ fmtTime(item.analyzed_at) }}</span>
                <span v-if="item.lims_name" class="link-pill linked">关联 {{ item.lims_name }} {{ item.lims_no }}</span>
                <span v-else class="link-pill unlinked">未关联 LIMS</span>
              </div>
              <div class="s-meta">
                <span>扫描 <b>{{ item.external_id }}</b></span>
                <span>方法 <b>{{ item.method || "—" }}</b></span>
                <template v-if="item.kind === 'quant'">
                  <span v-if="(item as QuantListItem).batch">批次 <b>{{ (item as QuantListItem).batch }}</b></span>
                  <span v-if="(item as QuantListItem).remark">{{ (item as QuantListItem).remark }}</span>
                </template>
                <template v-else>
                  <span>膜片 <b>{{ (item as UqListItem).film || "—" }}</b></span>
                  <span v-if="(item as UqListItem).processed !== null">
                    {{ (item as UqListItem).processed ? "已再处理" : "未再处理" }}
                  </span>
                </template>
              </div>
              <div class="s-top">
                <span v-for="v in item.top_values" :key="v.name" class="analyte-chip">
                  {{ v.name }} {{ fmtXrfValue(v.value) }}
                </span>
                <span v-if="item.value_count > item.top_values.length" class="hint">
                  另有 {{ item.value_count - item.top_values.length }} 项
                </span>
              </div>
            </div>
            <span class="s-toggle">{{ expanded.has(item.id) ? "收起 ▲" : "展开 ▼" }}</span>
          </div>
          <div v-if="expanded.has(item.id)" class="scan-body" @click.stop>
            <ScanDetail :kind="tab" :id="item.id" />
          </div>
        </section>
        <p v-if="!isFetching && !items.length" class="hint">没有符合条件的扫描。</p>
      </div>
    </n-spin>
    <div class="pager">
      <n-pagination v-model:page="page" :item-count="total" :page-size="perPage" />
    </div>

    <!-- 导出参数抽屉 -->
    <n-drawer v-model:show="drawerOpen" :width="430" placement="right">
      <n-drawer-content title="导出参数" closable>
        <n-form label-placement="top">
          <n-form-item label="排序方式">
            <n-radio-group v-model:value="orderMode">
              <n-radio-button value="template">顺序模板</n-radio-button>
              <n-radio-button value="content">按含量</n-radio-button>
            </n-radio-group>
          </n-form-item>
          <p v-if="orderMode === 'content'" class="hint" style="margin: -12px 0 14px">
            xlsx 按所选样品中各项目的最高元素含量；PDF 按各样品自身含量
          </p>
          <n-form-item v-if="orderMode === 'template'" label="元素顺序模板">
            <n-select v-model:value="orderTemplateId" :options="templateOptions" />
          </n-form-item>
          <n-form-item v-if="tab === 'uq'" label="xlsx 口径（PDF 始终左右对应）">
            <n-radio-group v-model:value="basis">
              <n-radio-button value="element">元素</n-radio-button>
              <n-radio-button value="oxide">氧化物</n-radio-button>
            </n-radio-group>
          </n-form-item>
          <n-form-item label="有效数字">
            <n-input-number v-model:value="significantDigits" :min="1" :max="8" :precision="0"
                            style="width: 100%" />
          </n-form-item>
        </n-form>
        <div class="export-unit-head">
          <div>
            <b>结果单位</b>
            <p>自动：≥0.1% 用 %；≥1 ppm 用 ppm；其余用 ppb</p>
          </div>
          <n-space :size="4">
            <n-button size="tiny" @click="setAllUnits('auto')">自动</n-button>
            <n-button size="tiny" @click="setAllUnits('%')">全 %</n-button>
            <n-button size="tiny" @click="setAllUnits('ppm')">全 ppm</n-button>
            <n-button size="tiny" @click="setAllUnits('ppb')">全 ppb</n-button>
          </n-space>
        </div>
        <n-spin :show="unitFieldsFetching">
          <p v-if="unitFieldsError" class="hint" style="color: var(--danger)">
            单位项目加载失败：{{ unitFieldsError.message }}
          </p>
          <div class="export-unit-list">
            <div v-for="field in unitFields" :key="field.key" class="export-unit-row">
              <span :title="field.label">{{ field.label }}</span>
              <n-select :value="unitOverrides[field.key] ?? field.default_unit"
                        :options="unitOptions" size="small" style="width: 92px"
                        @update:value="(value: XrfUnit) => setUnit(field.key, value)" />
            </div>
          </div>
          <p v-if="!unitFieldsFetching && !unitFields.length" class="hint">没有可配置的结果项目。</p>
        </n-spin>
        <template #footer>
          <n-space vertical style="width: 100%">
            <n-button type="primary" block :loading="exporting" @click="exportXlsx">
              导出 xlsx（{{ checked.size }} 条）
            </n-button>
            <n-button v-if="tab === 'uq'" block :loading="exporting" @click="exportPdf">
              逐个下载 PDF（{{ checked.size }} 份）
            </n-button>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { useQuery } from "@tanstack/vue-query";
import {
  NButton, NCheckbox, NDatePicker, NDrawer, NDrawerContent, NForm, NFormItem,
  NInput, NInputNumber, NPagination, NRadioButton, NRadioGroup, NSelect, NSpace, NSpin,
  NTabPane, NTabs, useMessage,
} from "naive-ui";
import dayjs from "dayjs";
import { api, downloadFile } from "../api/client";
import { useCardExpansion } from "../composables/useCardExpansion";
import { useKeyboardShortcuts } from "../composables/useKeyboardShortcuts";
import type {
  OrderTemplate, Paged, QuantListItem, UqListItem, XrfUnit, XrfUnitField,
} from "../api/types";
import { fmtTime, fmtXrfValue } from "../utils";
import ScanDetail from "../components/ScanDetail.vue";

const message = useMessage();
const route = useRoute();
const tab = ref<"quant" | "uq">(route.query.tab === "uq" ? "uq" : "quant");
const orderMode = ref<"template" | "content">(tab.value === "uq" ? "content" : "template");
const keyword = ref("");
const dateRange = ref<[number, number] | null>(null);
const page = ref(1);
const perPage = 25;
const checked = ref<Set<number>>(new Set());
const { expanded, toggle: toggleExpand, closeLast, collapseAll } = useCardExpansion<number>();
const drawerOpen = ref(false);
const exporting = ref(false);
const orderTemplateId = ref<number | null>(null);
const basis = ref<"element" | "oxide">("element");
const significantDigits = ref(5);
const unitOverrides = ref<Record<string, XrfUnit>>({});
const unitOptions = ["%", "ppm", "ppb"].map((value) => ({ label: value, value }));

const active = ref({ keyword: "", date_from: "", date_to: "" });

function search() {
  page.value = 1;
  active.value = {
    keyword: keyword.value.trim(),
    date_from: dateRange.value ? dayjs(dateRange.value[0]).format("YYYY-MM-DD") : "",
    date_to: dateRange.value ? dayjs(dateRange.value[1]).format("YYYY-MM-DD") : "",
  };
}

watch(tab, () => {
  checked.value = new Set();
  collapseAll();
  page.value = 1;
  unitOverrides.value = {};
  orderMode.value = tab.value === "uq" ? "content" : "template";
});

const queryParams = computed(() => {
  const params = new URLSearchParams();
  if (active.value.keyword) params.set("keyword", active.value.keyword);
  if (active.value.date_from) params.set("date_from", active.value.date_from);
  if (active.value.date_to) params.set("date_to", active.value.date_to);
  params.set("page", String(page.value));
  params.set("per_page", String(perPage));
  return params.toString();
});

type AnyScan = QuantListItem | UqListItem;

const { data, isFetching, isError, error } = useQuery({
  queryKey: computed(() => ["xrf", tab.value, queryParams.value]),
  queryFn: () => api<Paged<AnyScan>>(`/api/xrf/${tab.value}?${queryParams.value}`),
});
const items = computed(() => data.value?.items ?? []);
const total = computed(() => data.value?.total ?? 0);

const { data: templates } = useQuery({
  queryKey: ["order-templates"],
  queryFn: () => api<{ ok: boolean; items: OrderTemplate[] }>("/api/order-templates"),
});
const templateOptions = computed(() =>
  (templates.value?.items ?? []).map((t) => ({
    label: `${t.name}${t.is_default ? "（系统默认）" : ""}`, value: t.id,
  })));
watch(templates, (list) => {
  if (orderTemplateId.value === null && list?.items?.length) {
    orderTemplateId.value = list.items.find((t) => t.is_default)?.id ?? list.items[0].id;
  }
}, { immediate: true });

const selectedIds = computed(() => [...checked.value].sort((a, b) => a - b));
const { data: unitFieldData, isFetching: unitFieldsFetching,
  isError: unitFieldsIsError, error: unitFieldsQueryError } = useQuery({
  queryKey: computed(() => [
    "xrf-unit-fields", tab.value, selectedIds.value.join(","), orderTemplateId.value,
    orderMode.value,
  ]),
  enabled: computed(() => drawerOpen.value && selectedIds.value.length > 0),
  queryFn: () => api<{ ok: boolean; items: XrfUnitField[] }>("/api/export/xrf/unit-fields", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ids: selectedIds.value,
      kind: tab.value,
      order_template_id: orderTemplateId.value,
      order_mode: orderMode.value,
    }),
  }),
});
const unitFields = computed(() => unitFieldData.value?.items ?? []);
const unitFieldsError = computed(() =>
  unitFieldsIsError.value ? unitFieldsQueryError.value as Error : null);
watch(unitFields, (fields) => {
  const next: Record<string, XrfUnit> = {};
  for (const field of fields) {
    next[field.key] = unitOverrides.value[field.key] ?? field.default_unit;
  }
  unitOverrides.value = next;
});

function toggle(id: number, value: boolean) {
  const next = new Set(checked.value);
  if (value) next.add(id); else next.delete(id);
  checked.value = next;
}

function handleScanClick(event: MouseEvent, id: number) {
  if (event.ctrlKey || event.metaKey) {
    toggle(id, !checked.value.has(id));
    return;
  }
  toggleExpand(id);
}

useKeyboardShortcuts([
  { key: "Escape", enabled: () => !drawerOpen.value && expanded.value.size > 0, run: closeLast },
  { key: "ArrowLeft", enabled: (event) => !drawerOpen.value && tab.value !== "quant"
      && !event.ctrlKey && !event.altKey && !event.metaKey,
    run: () => { tab.value = "quant"; } },
  { key: "ArrowRight", enabled: (event) => !drawerOpen.value && tab.value !== "uq"
      && !event.ctrlKey && !event.altKey && !event.metaKey,
    run: () => { tab.value = "uq"; } },
]);

function setUnit(key: string, unit: XrfUnit) {
  unitOverrides.value = { ...unitOverrides.value, [key]: unit };
}

function setAllUnits(unit: XrfUnit | "auto") {
  unitOverrides.value = Object.fromEntries(unitFields.value.map((field) => [
    field.key, unit === "auto" ? field.default_unit : unit,
  ]));
}

async function exportXlsx() {
  exporting.value = true;
  try {
    await downloadFile(`/api/export/xrf/${tab.value}.xlsx`, {
      ids: [...checked.value],
      order_template_id: orderTemplateId.value,
      units: unitOverrides.value,
      significant_digits: significantDigits.value,
      order_mode: orderMode.value,
      ...(tab.value === "uq" ? { basis: basis.value } : {}),
    });
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    exporting.value = false;
  }
}

async function exportPdf() {
  exporting.value = true;
  let failed = 0;
  try {
    for (const id of checked.value) {
      try {
        await downloadFile("/api/export/xrf/uq.pdf", {
          id,
          order_template_id: orderTemplateId.value,
          units: unitOverrides.value,
          significant_digits: significantDigits.value,
          order_mode: orderMode.value,
        });
      } catch {
        failed += 1;
      }
    }
    if (failed) message.warning(`${failed} 份 PDF 生成失败`);
    else message.success("已全部下载");
    drawerOpen.value = false;
  } finally {
    exporting.value = false;
  }
}
</script>
