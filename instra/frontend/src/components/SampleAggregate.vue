<template>
  <div v-if="data" class="aggregate">
    <!-- 溶样方案：每路的称样/定容/稀释 + 测定项目与仪器分配 -->
    <template v-if="data.preps.length">
      <div class="section-title">溶样方案 · {{ data.preps.length }} 路</div>
      <div class="prep-plan-grid">
        <section v-for="prep in data.preps" :key="prep.id" class="plan-card">
          <header class="plan-head">
            <span class="plan-name">{{ prep.name }}</span>
            <span class="plan-meta mono">
              {{ prep.mass_g ?? "—" }} g → {{ prep.volume_ml ?? "—" }} mL
              <template v-if="prep.dilution_factor !== 1"> · {{ prep.dilution_label }}（×{{ prep.dilution_factor }}）</template>
              <template v-else> · {{ prep.dilution_label }}</template>
            </span>
          </header>
          <div v-if="prep.dilution_steps.length > 1" class="plan-steps">
            <span v-for="(step, i) in prep.dilution_steps" :key="i" class="step-chip mono">{{ step }}</span>
          </div>
          <div class="plan-tasks">
            <span v-for="t in prep.tasks" :key="t.analyte + t.instrument" class="task-chip"
                  :class="{ pending: t.status === 'pending' }"
                  :title="`状态：${t.status}`">
              {{ t.analyte }}<em>{{ [t.instrument, t.method].filter(Boolean).join("/") || "未分配" }}</em>
            </span>
            <span v-if="!prep.tasks.length" class="hint">未分配测定项目</span>
          </div>
        </section>
      </div>
    </template>

    <!-- 关联 XRF -->
    <template v-if="data.xrf_analyses.length">
      <div class="section-title">关联 XRF 扫描 · {{ data.xrf_analyses.length }} 次</div>
      <section v-for="xa in data.xrf_analyses" :key="xa.id" class="xrf-card">
        <div class="x-head">
          <span class="m">{{ xa.kind === "uq" ? "UniQuant" : "常规 XRF" }} · {{ xa.method || "XRF" }}</span>
          <span>扫描 {{ xa.external_id }}</span>
          <span v-if="xa.batch">批次 {{ xa.batch }}</span>
          <span>{{ fmtTime(xa.analyzed_at) }}</span>
          <span v-if="xa.remark">{{ xa.remark }}</span>
        </div>
        <div class="xrf-values">
          <div v-for="v in xa.values" :key="v.name" class="xrf-value"
               :title="v.alt_name ? `另一口径：${v.alt_name}` : ''">
            <b>{{ v.name }}</b><span class="mono">{{ fmtXrfValue(v.value) }}</span>
          </div>
        </div>
      </section>
    </template>

    <!-- 分析项目结果 -->
    <div class="section-title">分析项目 · {{ data.groups.length }} 项</div>
    <div v-if="data.groups.length" class="group-grid">
      <section v-for="group in data.groups" :key="group.analyte" class="group-card">
        <header class="g-head">
          <span class="g-name">{{ group.analyte }}</span>
          <span v-if="group.final" class="g-final">
            <span class="v mono">{{ fmtNumber(group.final.value) }}</span>
            <span class="u">{{ group.final.unit }}</span>
            <span class="m">{{ group.final.mode }}{{ group.final.based_on > 1 ? ` × ${group.final.based_on}` : "" }}</span>
          </span>
          <span v-else class="g-final empty"><span class="v">暂无最终值</span></span>
        </header>
        <div v-for="row in group.rows" :key="row.sample_analyte_id" class="prep-card">
          <div class="p-head">
            <span class="p-name">{{ row.prep }}</span>
            <span class="p-value mono" :class="{ none: row.value === null }">
              <template v-if="row.value !== null">{{ fmtNumber(row.value) }} {{ row.unit }}</template>
              <template v-else>{{ row.unit || "未录入" }}</template>
            </span>
          </div>
          <div class="p-meta">
            <span v-if="row.mass_g !== null">称样 {{ row.mass_g }} g</span>
            <span v-if="row.volume_ml !== null">定容 {{ row.volume_ml }} mL</span>
            <span v-if="row.dilution && row.dilution !== '原液'">稀释 {{ row.dilution }}</span>
            <span v-if="row.selection === 'exclude'" style="color: var(--warn)">不参与</span>
          </div>
          <div class="p-foot">
            <span class="tag-chip">{{ [row.instrument, row.method].filter(Boolean).join(" / ") || "未分配仪器" }}</span>
            <div v-if="row.readings.length" class="reading-chips">
              <span v-for="(rd, i) in row.readings" :key="i" class="reading-chip mono"
                    :class="{ used: rd.used, final: rd.is_final, excluded: !rd.used && rd.value !== null }"
                    :title="rd.is_final ? '终值' : rd.used ? '参与' : '不参与'">
                {{ rd.value !== null ? `${fmtNumber(rd.corrected_value ?? rd.value)} ${rd.unit}` : (rd.unit || "—") }}
              </span>
            </div>
          </div>
        </div>
      </section>
    </div>
    <p v-else class="hint">该样品暂无分析项目。</p>

    <!-- 完整审计时间线 -->
    <AuditTimeline :sample-id="data.sample.id" />
  </div>
  <n-spin v-else-if="isFetching" style="display: block; margin: 30px auto" />
  <p v-else-if="isError" class="hint" style="color: var(--danger)">加载失败：{{ error?.message }}</p>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { NSpin } from "naive-ui";
import { api } from "../api/client";
import type { Aggregate } from "../api/types";
import { fmtNumber, fmtTime, fmtXrfValue } from "../utils";
import AuditTimeline from "./AuditTimeline.vue";

const props = defineProps<{ sampleId: number }>();

const { data, isFetching, isError, error } = useQuery({
  queryKey: computed(() => ["aggregate", props.sampleId]),
  queryFn: () => api<Aggregate>(`/api/samples/${props.sampleId}/aggregate`),
});
</script>
