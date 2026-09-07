<template>
  <n-spin :show="isFetching">
    <template v-if="quant">
      <div class="xrf-values">
        <div v-for="v in quant.values" :key="v.name" class="xrf-value"
             :title="v.alt_name ? `另一口径：${v.alt_name}` : ''">
          <b>{{ v.name }}</b><span class="mono">{{ fmtXrfValue(v.value) }}</span>
        </div>
      </div>
      <p class="hint" style="margin-top: 8px">
        共 {{ quant.values.length }} 项 · 导出 xlsx 全量输出
      </p>
    </template>

    <template v-else-if="uq">
      <div class="section-title" style="margin-top: 4px">
        最终组成 · {{ uqPairs.length }} 项 · 左氧化物 / 右元素
      </div>
      <div class="uq-pairs">
        <div v-for="(p, i) in uqPairs" :key="i" class="uq-pair"
             :title="p.oxide_name && p.element_name ? `${p.oxide_name} ↔ ${p.element_name}` : ''">
          <span class="pair-cell">
            <b>{{ p.oxide_name ?? "—" }}</b>
            <span class="mono">{{ p.oxide_display }}</span>
          </span>
          <span class="pair-cell element">
            <b>{{ p.element_name ?? "—" }}</b>
            <span class="mono">{{ p.element_display }}</span>
          </span>
        </div>
      </div>
      <template v-if="optionEntries.length">
        <div class="section-title">UniQuant 关键选项</div>
        <div class="p-meta" style="display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 12px; color: var(--ink-2)">
          <span v-for="[k, v] in optionEntries" :key="k"><b>{{ k }}</b> {{ v }}</span>
        </div>
      </template>
      <template v-if="reportedChannels.length">
        <div class="section-title">谱线通道 · {{ reportedChannels.length }} 条已报出</div>
        <n-data-table :columns="channelColumns" :data="reportedChannels" size="small"
                      :pagination="{ pageSize: 8 }" />
      </template>
      <p v-else class="hint">无谱线级明细（该扫描未同步 UniQuant 通道数据）。</p>
    </template>
  </n-spin>
</template>

<script setup lang="ts">
import { computed, h } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { NDataTable, NSpin } from "naive-ui";
import { api } from "../api/client";
import type { QuantListItem, UqChannel, UqDetail, XrfValue } from "../api/types";
import { defaultXrfUnit, fmtNumber, fmtXrfValue } from "../utils";

const props = defineProps<{ kind: "quant" | "uq"; id: number }>();

const { data, isFetching } = useQuery({
  queryKey: computed(() => ["scan-detail", props.kind, props.id]),
  queryFn: () => api<{ ok: boolean; item: unknown }>(`/api/xrf/${props.kind}/${props.id}`),
});

const quant = computed(() =>
  props.kind === "quant" ? (data.value?.item as QuantListItem & { values: XrfValue[] }) : null);
const uq = computed(() => (props.kind === "uq" ? (data.value?.item as UqDetail) : null));

const uqPairs = computed(() => (uq.value?.pairs ?? []).map((pair) => {
  const unit = defaultXrfUnit(pair.oxide_value, pair.element_value);
  return {
    ...pair,
    oxide_display: fmtXrfValue(pair.oxide_value, unit),
    element_display: fmtXrfValue(pair.element_value, unit),
  };
}));

/** 与 toy-lims server/app.py option_labels 一致的白名单 + 值转换。 */
const optionEntries = computed(() => {
  const options = (uq.value?.options ?? {}) as Record<string, unknown>;
  const out: [string, string][] = [];
  const seen = new Set<string>();
  const push = (label: string, value: unknown) => {
    if (value === undefined || value === null || value === "" || Array.isArray(value)) return;
    if (typeof value === "object") return;
    if (seen.has(label)) return;
    seen.add(label);
    out.push([label, String(value)]);
  };
  const chemistry = options.chemistry;
  push("化学表示",
       chemistry === 1 || chemistry === "1" ? "氧化物"
         : chemistry === 0 || chemistry === "0" ? "元素" : chemistry);
  push("Shape", options.shape);
  push("Case", options.case_nb ?? options.case_number);
  push("Kappa", options.kappas ?? options.kappa_list);
  push("气氛", options.atmosphere === 0 || options.atmosphere === "0" ? "真空" : options.atmosphere);
  push("报告限(ppm)", options.report_level);
  push("Sector", options.sector);
  push("面积", options.area);
  push("直径", options.diameter);
  push("总直径", options.gross_diameter);
  push("质量", options.mass);
  push("总质量", options.gross_mass);
  push("高度", options.height);
  push("密度", options.rho);
  push("阴影损耗", options.shadow_loss);
  push("已知浓度", options.known_conc);
  push("Rest", options.rest);
  push("DoS", options.do_s);
  push("膜片", options.film ?? uq.value?.film);
  return out;
});

const reportedChannels = computed(() =>
  (uq.value?.channels ?? []).filter((c) => c.is_reported));

const channelColumns = [
  { title: "谱线", key: "name" },
  { title: "强度(cps)", key: "int_cps", render: (r: UqChannel) => fmtNumber(r.int_cps) },
  { title: "含量", key: "conc", render: (r: UqChannel) => fmtNumber(r.conc) },
  { title: "σ(conc)", key: "sigma_conc", render: (r: UqChannel) => fmtNumber(r.sigma_conc) },
  { title: "标准误差", key: "std_err", render: (r: UqChannel) => fmtNumber(r.std_err) },
  {
    title: "重叠元素", key: "overlapping_elements",
    render: (r: UqChannel) => r.overlapping_elements || "—",
  },
];
</script>
