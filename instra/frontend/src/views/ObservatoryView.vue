<template>
  <div class="observatory" :class="{ 'is-depth': depth, 'is-travelling': travelling }">
    <header class="port-nav">
      <router-link class="port-brand" to="/observatory" aria-label="实验星港首页">
        <svg viewBox="0 0 36 36" aria-hidden="true"><path d="M18 2 33 10v16l-15 8L3 26V10Z M18 9l9 5v9l-9 5-9-5v-9Z M18 2v7M33 10l-6 4M33 26l-6-3M18 34v-6M3 26l6-3M3 10l6 4" /></svg>
        <span>INSTRA <small>LABORATORY OBSERVATORY</small></span>
      </router-link>
      <nav aria-label="页面导航">
        <span class="port-nav-active">01 / 实验星港</span>
        <router-link to="/samples">02 / 样品聚合</router-link>
        <router-link to="/xrf">03 / XRF 数据</router-link>
      </nav>
      <span class="port-readonly"><i></i> READ ONLY</span>
    </header>

    <main class="port-main">
      <section class="port-heading">
        <div><p class="port-eyebrow">OPERATIONS THEATRE / 实验室全域观测</p>
          <h1>实验星港<span>THE SPACEPORT</span></h1>
          <p class="port-subtitle">每一份样品，都有航迹。每一次修改，都留有回声。</p>
        </div>
        <div class="port-sync">
          <span :class="{ 'sync-error': overviewError }"><i></i>{{ overviewError ? '数据同步中断' : overviewFetching || refreshing ? '正在同步数据' : '只读数据链路' }}</span>
          <time>{{ overview ? fmtTime(overview.generated_at) : '等待首次同步' }}</time>
          <button type="button" @click="refresh" :disabled="overviewFetching || refreshing">{{ overviewFetching || refreshing ? '同步中' : '重新同步' }} <span aria-hidden="true">↻</span></button>
        </div>
      </section>

      <p v-if="overviewError" class="port-error" role="alert">总览加载失败：{{ overviewError.message }}。保留上次成功数据，可重新同步。</p>

      <section class="port-telemetry" aria-label="全局工作量">
        <div><span class="metric-index">01</span><span class="metric-label">样品总档案<small>SAMPLE ARCHIVE</small></span><strong>{{ count(overview?.samples.total) }}</strong></div>
        <div><span class="metric-index">02</span><span class="metric-label">未审核样品<small>ACTIVE MANIFEST</small></span><strong class="signal-amber">{{ overview ? activeCount : '—' }}</strong></div>
        <div><span class="metric-index">03</span><span class="metric-label">仪器档案<small>INSTRUMENT REGISTRY</small></span><strong>{{ count(overview?.instruments.length) }}</strong></div>
        <div><span class="metric-index">04</span><span class="metric-label">待分配任务<small>UNASSIGNED TASKS</small></span><strong>{{ count(overview?.unassigned.open_tasks) }}</strong></div>
        <router-link to="/xrf"><span class="metric-index">05</span><span class="metric-label">XRF 待关联<small>AWAITING SCAN</small></span><strong>{{ count(overview?.xrf.awaiting_scan) }}</strong></router-link>
      </section>

      <div class="port-chamber" :class="{ 'depth-active': depth }">
        <section class="harbor-view" :inert="depth" :aria-hidden="depth">
          <div class="port-panel-top">
            <div><span class="port-square"></span><h2>轨道总览 <small>ORBITAL OVERVIEW</small></h2></div>
            <button ref="orbitEntry" type="button" class="port-text-button" @click="enterDepth(null, $event)">进入全局时间深井 <span aria-hidden="true">↘</span></button>
          </div>
          <div class="harbor-layout">
            <div class="port-stage">
              <div class="stage-coordinates" aria-hidden="true"><span>AZ / 032.8</span><span>DECK / 01</span><span>PROJECTION : ISOMETRIC</span></div>
              <div class="stage-crosshair crosshair-a" aria-hidden="true"></div><div class="stage-crosshair crosshair-b" aria-hidden="true"></div>
              <div class="stage-perspective">
                <div class="orbital-deck">
                  <div class="deck-grid" aria-hidden="true"></div>
                  <div class="orbit orbit-outer" aria-hidden="true"></div><div class="orbit orbit-middle" aria-hidden="true"></div>
                  <div class="orbit orbit-inner" aria-hidden="true"></div><div class="orbit-ticks" aria-hidden="true"></div>
                  <svg class="orbital-links" viewBox="0 0 1000 700" aria-hidden="true">
                    <path v-for="link in connections" :key="link.key" :d="link.path" :class="{ lit: instrumentId === link.instrument }" />
                  </svg>
                  <button type="button" class="port-core" @click="enterDepth(null, $event)" aria-label="穿过中央舱门，进入全局时间深井">
                    <span class="core-outer"><span class="core-rotor"></span></span>
                    <span class="core-label"><small>CHRONO / ACCESS</small><b>时间深井</b><span>ENTER ↓</span></span>
                  </button>
                  <button v-for="(station, index) in visibleStations" :key="station.id" type="button"
                          class="port-station" :class="{ selected: instrumentId === station.id, loaded: station.open_tasks > 0 }"
                          :style="stationStyle(index)" :aria-pressed="instrumentId === station.id"
                          @click="selectInstrument(station.id)" :title="`${station.name} · ${station.open_tasks} 项待办；点击筛选关联样品`">
                    <span class="station-ribs" aria-hidden="true"></span><span class="station-code">ST / {{ String(station.id).padStart(2, '0') }} <i></i></span>
                    <strong>{{ station.name }}</strong><span v-if="station.itype === 'xrf'" class="station-work">XRF 扫描独立统计</span><span v-else class="station-work"><b>{{ station.open_tasks }}</b> 待办 / {{ station.open_samples }} 样品</span>
                    <span class="station-base" aria-hidden="true"></span>
                  </button>
                  <button v-for="(sample, index) in samples" :key="sample.id" type="button" class="sample-capsule"
                          :class="sampleTone(sample.status)" :style="capsuleStyle(index)"
                          :title="`${sample.name} / ${sample.lims_no || sample.id} · ${label(sample.status)} · 点击查看档案和修改轨迹`"
                          @click="enterDepth(sample.id, $event)">
                    <i></i><span>{{ sample.name }}</span><small>{{ String(sample.id).padStart(4, '0') }}</small>
                  </button>
                </div>
              </div>
              <div v-if="samplesFetching && !samplePage" class="stage-message" role="status">正在接入样品轨道…</div>
              <div v-else-if="!samples.length" class="stage-message">{{ samplesError ? '样品链路中断，请重试' : '当前筛选下没有停泊样品' }}</div>
              <div class="stage-bottom">
                <div class="stage-legend"><span><i class="amber-dot"></i>待推进</span><span><i></i>已审核</span><span>胶囊 = 当前页样品</span></div>
                <div v-if="stationPages > 1" class="station-pager"><button type="button" :disabled="stationPage === 0" @click="stationPage--" aria-label="上一组仪器">←</button><span>仪器 {{ stationPage + 1 }}/{{ stationPages }}</span><button type="button" :disabled="stationPage + 1 >= stationPages" @click="stationPage++" aria-label="下一组仪器">→</button></div>
              </div>
            </div>

            <aside class="port-signal-feed" aria-label="最新全局修改">
              <div class="signal-feed-title"><span>变更信号</span><small>EVENT UPLINK <i></i></small></div>
              <p class="feed-caption">真实审计事件 / 每 30 秒同步</p>
              <TransitionGroup name="uplink-event" tag="div" class="signal-items">
                <button v-for="entry in overview?.recent_audits.items.slice(0, 7)" :key="entry.id" type="button"
                        class="signal-event" @click="enterDepth(auditSampleId(entry), $event)">
                  <span class="event-serial">{{ String(entry.id).padStart(5, '0') }}</span>
                  <div><time>{{ fmtTime(entry.created_at) }}</time><strong>{{ entry.action_label || '数据变更' }}</strong>
                    <p>{{ entry.entity_label }} #{{ entry.entity_id }}</p><small>{{ entry.username || '系统' }}</small></div>
                  <span class="event-arrow" aria-hidden="true">↗</span>
                </button>
                <p v-if="overview && !overview.recent_audits.items.length" key="empty" class="port-empty">尚无审计信号</p>
              </TransitionGroup>
              <button type="button" class="feed-all" @click="enterDepth(null, $event)">展开全局修改轨迹 <span aria-hidden="true">↘</span></button>
            </aside>
          </div>

          <section class="port-manifest">
            <div class="manifest-title"><h2>停泊清单 <small>SAMPLE MANIFEST</small></h2><span>{{ samplePage?.total ?? '—' }} 份匹配 / 可检索全部样品</span></div>
            <form class="manifest-filters" @submit.prevent="search">
              <label class="port-search"><span aria-hidden="true">⌕</span><input v-model="draftKeyword" aria-label="搜索样品" placeholder="搜索样品编号、LIMS 编号、描述或标签" /><kbd>ENTER</kbd></label>
              <select v-model="status" aria-label="按样品状态筛选"><option value="">全部状态</option><option v-for="item in statuses" :key="item" :value="item">{{ label(item) }} · {{ overview?.samples.by_status[item] ?? 0 }}</option></select>
              <select :value="instrumentId ?? ''" @change="changeInstrument" aria-label="按仪器筛选"><option value="">全部仪器</option><option v-for="item in overview?.instruments" :key="item.id" :value="item.id">{{ item.name }} · {{ item.open_tasks }} 待办</option></select>
              <button type="submit" class="port-solid-button">检索</button>
              <button v-if="keyword || status || instrumentId !== null" type="button" class="port-text-button" @click="resetFilters">重置筛选</button>
            </form>
            <p v-if="selectedInstrument" class="instrument-context">当前轨道：<b>{{ selectedInstrument.name }}</b> · {{ selectedInstrument.task_total }} 项历史任务 / {{ selectedInstrument.completed }} 项已完成 / {{ selectedInstrument.open_tasks }} 项待办。这里只统计任务分配，不代表设备在线或运行状态。</p>
            <p v-if="selectedInstrument?.itype === 'xrf'" class="instrument-context">XRF 扫描与样品直接关联，不归属具体仪器档案。<router-link to="/xrf" class="port-text-button">前往 XRF 数据查看扫描与关联 →</router-link></p>
            <p v-if="samplesError" role="alert" class="port-error">样品加载失败：{{ samplesError.message }} <button type="button" @click="refetchSamples()">重试</button></p>
            <div class="manifest-grid" :aria-busy="samplesFetching">
              <button v-for="sample in samples" :key="sample.id" type="button" class="manifest-sample" :class="sampleTone(sample.status)" @click="enterDepth(sample.id, $event)">
                <div class="manifest-sample-head"><b>{{ sample.name }}</b><span>{{ label(sample.status) }}</span></div>
                <p>{{ sample.lims_no || `ARCHIVE / ${sample.id}` }}<span>{{ sample.type }}</span></p>
                <div class="manifest-analytes">{{ sample.analytes.join(' / ') || '暂无分析项目' }}</div>
                <div class="manifest-sample-bottom"><span>{{ sample.task_completed }}/{{ sample.task_total }} 任务完成</span><span>{{ sample.xrf ? 'XRF / ' : '' }}{{ sample.prep_count }} 路溶样 <b aria-hidden="true">↘</b></span></div>
                <span class="sample-progress" :style="{ width: `${sample.task_total ? sample.task_completed / sample.task_total * 100 : 0}%` }"></span>
              </button>
            </div>
            <p v-if="!samplesFetching && !samples.length && !samplesError" class="port-empty">没有匹配样品，试试调整筛选条件。</p>
            <div class="manifest-footer"><span>选择胶囊或档案卡，进入该样品的时间深井</span><div><button type="button" :disabled="page === 1 || samplesFetching" @click="page--">← 上一页</button><span>{{ page }} / {{ samplePages }}</span><button type="button" :disabled="page >= samplePages || samplesFetching" @click="page++">下一页 →</button></div></div>
          </section>
        </section>

        <section v-if="depth" class="timewell-view" aria-label="时间深井">
          <div class="timewell-top">
            <button type="button" class="return-orbit" @click="leaveDepth"><span aria-hidden="true">↖</span> 返回星港 <kbd>ESC</kbd></button>
            <span>CHRONOLOGICAL ARCHIVE / {{ selectedId === null ? 'GLOBAL' : `SAMPLE ${selectedId}` }}</span>
          </div>
          <div class="timewell-heading"><div><p class="port-eyebrow">BENEATH THE SURFACE / 历史有迹可循</p><h2 ref="depthHeading" tabindex="-1">时间深井<span>THE TIME WELL</span></h2></div><div class="well-depth-mark">T<span>−</span>∞<small>TRACE EVERY CHANGE</small></div></div>
          <div class="well-layout">
            <aside class="well-dossier">
              <div class="dossier-emblem" aria-hidden="true"><div></div><span>{{ selectedId === null ? 'ALL' : String(selectedId).padStart(4, '0') }}</span></div>
              <p class="port-eyebrow">{{ selectedId === null ? 'GLOBAL EVENT ARCHIVE' : 'SAMPLE FLIGHT RECORDER' }}</p>
              <h3>{{ selectedId === null ? '全局修改轨迹' : aggregate?.sample.name || `样品 #${selectedId}` }}</h3>
              <p class="dossier-number">{{ aggregate?.sample.lims_no || (selectedId === null ? '全实验室 / 审计事件' : '正在读取样品档案') }}</p>
              <template v-if="selectedId !== null">
                <p v-if="aggregateError" class="port-error" role="alert">档案加载失败：{{ aggregateError.message }} <button type="button" @click="refetchAggregate()">重试</button></p>
                <dl v-if="aggregate" class="dossier-meta"><div><dt>当前状态</dt><dd>{{ label(aggregate.sample.status) }}</dd></div><div><dt>登记时间</dt><dd>{{ fmtTime(aggregate.sample.created_at) }}</dd></div><div><dt>检测人员</dt><dd>{{ aggregate.sample.analyst || '未指定' }}</dd></div><div><dt>溶样 / XRF</dt><dd>{{ aggregate.preps.length }} 路 / {{ aggregate.xrf_analyses.length }} 次</dd></div></dl>
                <div v-if="aggregate" class="dossier-results"><h4>结果截面 <small>CURRENT RESULTS</small></h4><div v-for="group in aggregate.groups" :key="group.analyte"><b>{{ group.analyte }}</b><span>{{ group.final ? `${fmtNumber(group.final.value)} ${group.final.unit}` : '暂无最终值' }}</span></div><p v-if="!aggregate.groups.length" class="port-empty">暂无常规分析结果</p><section v-for="scan in aggregate.xrf_analyses" :key="scan.id" class="dossier-xrf"><h4>{{ scan.kind === 'uq' ? 'UniQuant' : 'XRF' }} / {{ scan.external_id }}</h4><div v-for="value in scan.values" :key="value.name"><b>{{ value.name }}</b><span>{{ fmtXrfValue(value.value) }}</span></div></section></div>
                <button type="button" class="feed-all" @click="showGlobal">切换到全局修改轨迹 ↗</button>
              </template>
              <template v-else><p class="dossier-description">沿着时间轴下潜，查看登记、结果录入、审核和修改。每个节点均来自真实审计记录，而非模拟活动。</p><dl class="dossier-meta"><div><dt>已载入事件</dt><dd>{{ globalEntries.length }}</dd></div><div><dt>排序方向</dt><dd>最新 → 更早</dd></div></dl></template>
              <p class="dossier-note">{{ selectedId === null ? '全局记录不展示原始快照或 IP。样品类事件可进一步进入单样品档案。' : '展示当前关联对象最近 300 条审计；删除或重新关联的对象可能不在此轨迹中。结果截面为当前值，不是历史回放。' }}</p>
            </aside>
            <div class="well-history">
              <div class="well-history-header"><span><i></i>{{ selectedId === null ? '全局事件流' : '样品修改轨迹' }}</span><small>NEWEST FIRST / 向下回溯</small></div>
              <p v-if="historyFetching && !historyEntries.length" class="port-empty" role="status">正在打捞时间记录…</p>
              <p v-if="historyError" class="port-error" role="alert">轨迹加载失败：{{ historyError.message }} <button type="button" @click="retryHistory">重新读取</button></p>
              <div class="history-shaft">
                <article v-for="(entry, index) in historyEntries" :key="entry.id" class="history-stratum" :style="{ '--stratum': Math.min(index, 8) }">
                  <div class="stratum-rail"><span>{{ String(index + 1).padStart(2, '0') }}</span><i></i></div>
                  <div class="stratum-card"><header><time>{{ fmtTime(entry.created_at) }}</time><span>LOG / {{ entry.id }}</span></header>
                    <h3>{{ entry.action_label || entry.action }} <small>{{ entry.entity_label }}{{ entry.entity_id ? ` #${entry.entity_id}` : '' }}</small></h3>
                    <p class="stratum-author">操作人 <b>{{ entry.username || '系统' }}</b></p>
                    <p v-if="entry.reason" class="stratum-reason">{{ entry.reason }}</p>
                    <div v-if="'changes' in entry && entry.changes.length" class="stratum-changes"><div v-for="(change, i) in entry.changes" :key="i"><b>{{ change.label }}</b><del>{{ displayValue(change.before) }}</del><span aria-hidden="true">→</span><ins>{{ displayValue(change.after) }}</ins></div></div>
                    <p v-else-if="'has_snapshot' in entry && entry.has_snapshot" class="stratum-note">创建 / 删除快照，或无可展示的字段差异</p>
                    <button v-if="canOpenScene(entry)" type="button" class="scene-trigger"
                            :aria-expanded="selectedSceneId === entry.id" @click="toggleScene(entry)">
                      <span aria-hidden="true">▣</span>{{ selectedSceneId === entry.id ? '关闭原始现场' : '在原始界面中查看这次修改' }}<b aria-hidden="true">{{ selectedSceneId === entry.id ? '收合 ↑' : '反向定位 ↘' }}</b>
                    </button>
                    <section v-if="selectedSceneId === entry.id" class="source-scene" aria-label="LabFlow 原始录入现场">
                      <header><div><span>LIVE CONTEXT / ARCHIVE VALUE</span><strong>LabFlow 只读现场</strong></div><small>审计 #{{ entry.id }} · 原始数据录入</small></header>
                      <p v-if="sceneContextFetching" class="scene-state" role="status">正在沿审计索引定位原始数据…</p>
                      <p v-else-if="sceneContextError" class="scene-state error" role="alert">现场定位失败：{{ sceneContextError.message }} <button type="button" @click="refetchSceneContext()">重试</button></p>
                      <p v-else-if="sceneContext && !sceneContext.supported" class="scene-state">这条记录无法可靠还原。当前只支持普通数值型仪器的原始读数修改。</p>
                      <template v-else-if="sceneContext?.supported && sceneContext.values">
                        <nav class="scene-modes" aria-label="审计现场时态">
                          <button v-for="mode in sceneModes" :key="mode.value" type="button" :class="{ active: sceneMode === mode.value }"
                                  :disabled="!sceneContext.values[mode.value].available" @click="setSceneMode(mode.value)">
                            <small>{{ mode.code }}</small>{{ mode.label }}
                            <b>{{ sceneContext.values[mode.value].available ? displayValue(sceneContext.values[mode.value].value) : '不可用' }}</b>
                          </button>
                        </nav>
                        <div class="scene-frame" :class="{ loading: sceneFrameLoading }">
                          <div class="scene-frame-rivets" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
                          <iframe :key="sceneSrc" :src="sceneSrc" title="LabFlow 原始数据录入只读现场"
                                  sandbox="allow-scripts allow-same-origin" referrerpolicy="no-referrer" @load="sceneFrameLoading = false"></iframe>
                        </div>
                        <p class="scene-disclaimer">修改前/后仅覆盖该审计保存的原始值；相邻行、项目、溶样、仪器、方法及单位来自当前数据库。所有输入均已禁用，不会启动 toy-lims 的保存逻辑。</p>
                      </template>
                    </section>
                    <button v-if="selectedId === null && auditSampleId(entry) !== null" type="button" class="port-text-button" @click="openAuditSample(entry)">追踪该样品 ↘</button>
                  </div>
                </article>
              </div>
              <p v-if="!historyFetching && !historyEntries.length && !historyError" class="port-empty">此处尚无审计记录。</p>
              <button v-if="selectedId === null && hasNextPage" type="button" class="load-deeper" :disabled="isFetchingNextPage" @click="fetchNextPage()">{{ isFetchingNextPage ? '正在读取更早记录…' : '继续下潜 / 载入更早记录' }} <span aria-hidden="true">↓</span></button>
              <p v-else-if="historyEntries.length" class="history-end">{{ selectedId === null ? '已抵达当前档案底部' : '当前关联轨迹终点 / 最多展示最近 300 条' }}<span>END OF TRANSMISSION</span></p>
            </div>
          </div>
        </section>

        <div v-if="travelling" class="flight-transition" :class="{ reverse: !depth }" aria-hidden="true"><div class="flight-axis"><i v-for="n in 7" :key="n" :style="{ '--ring': n }"></i></div><div class="flight-reticle"></div><span>{{ depth ? 'DESCENDING INTO THE ARCHIVE' : 'RETURNING TO ORBIT' }}</span></div>
      </div>

      <footer class="port-footer"><span>INSTRA / OBSERVATORY 01</span><span>仪器表示任务分配，不代表实时设备状态 · 空间位置为可视化布局</span><span>ALL SYSTEMS READ ONLY</span></footer>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import { useInfiniteQuery, useQuery } from "@tanstack/vue-query";
import { api } from "../api/client";
import type { Aggregate, Paged } from "../api/types";
import type { AuditPage, AuditSceneContext, Overview, PortAudit, PortSample, SampleAudit } from "../api/overview";
import { fmtNumber, fmtTime, fmtXrfValue, statusLabel } from "../utils";
import { useKeyboardShortcuts } from "../composables/useKeyboardShortcuts";
import "../observatory.css";

const page = ref(1);
const perPage = 24;
const keyword = ref("");
const draftKeyword = ref("");
const status = ref("");
const instrumentId = ref<number | null>(null);
const stationPage = ref(0);
const depth = ref(false);
const travelling = ref(false);
const refreshing = ref(false);
const selectedId = ref<number | null>(null);
const selectedSceneId = ref<number | null>(null);
const sceneMode = ref<"before" | "after" | "current">("after");
const sceneFrameLoading = ref(false);
const depthHeading = ref<HTMLElement>();
const orbitEntry = ref<HTMLElement>();
let flightTimer: ReturnType<typeof setTimeout> | undefined;
let returnFocus: HTMLElement | null = null;

const { data: overview, error: overviewError, isFetching: overviewFetching, refetch: refetchOverview } = useQuery({
  queryKey: ["observatory"], queryFn: ({ signal }) => api<Overview>("/api/overview", { signal }),
  refetchInterval: 30_000,
});
const activeCount = computed(() => Object.entries(overview.value?.samples.by_status ?? {})
  .reduce((sum, [state, n]) => sum + (["reviewed", "reported", "cancelled"].includes(state) ? 0 : n), 0));
const statuses = computed(() => [...new Set(["received", "queued", "measuring", "partially_done", "completed", "reviewed", "cancelled", ...Object.keys(overview.value?.samples.by_status ?? {})])]);
const label = (value: string) => value === "queued" ? "未测量" : statusLabel(value);
const count = (value?: number) => value === undefined ? "—" : value.toLocaleString("en-US");
const sampleTone = (value: string) => ["reviewed", "reported"].includes(value) ? "is-complete" : value === "cancelled" ? "is-cancelled" : "is-active";
const params = computed(() => {
  const query = new URLSearchParams({ page: String(page.value), per_page: String(perPage) });
  if (keyword.value) query.set("keyword", keyword.value);
  if (status.value) query.set("status", status.value);
  if (instrumentId.value !== null) query.set("instrument_id", String(instrumentId.value));
  return query.toString();
});
const { data: samplePage, error: samplesError, isFetching: samplesFetching, refetch: refetchSamples } = useQuery({
  queryKey: computed(() => ["port-samples", params.value]),
  queryFn: ({ signal }) => api<Paged<PortSample>>(`/api/samples?${params.value}`, { signal }),
  refetchInterval: computed(() => depth.value ? false : 30_000),
});
const samples = computed(() => samplePage.value?.items ?? []);
const samplePages = computed(() => Math.max(1, Math.ceil((samplePage.value?.total ?? 0) / perPage)));
const stationPages = computed(() => Math.max(1, Math.ceil((overview.value?.instruments.length ?? 0) / 6)));
const visibleStations = computed(() => overview.value?.instruments.slice(stationPage.value * 6, stationPage.value * 6 + 6) ?? []);
const selectedInstrument = computed(() => overview.value?.instruments.find((item) => item.id === instrumentId.value));
watch([keyword, status, instrumentId], () => { page.value = 1; });
watch(stationPages, (pages) => { stationPage.value = Math.min(stationPage.value, pages - 1); });
watch(samplePages, (pages) => { if (samplePage.value && page.value > pages) page.value = pages; });

function search() { keyword.value = draftKeyword.value.trim(); page.value = 1; }
function resetFilters() { draftKeyword.value = ""; keyword.value = ""; status.value = ""; instrumentId.value = null; }
function selectInstrument(id: number) { instrumentId.value = instrumentId.value === id ? null : id; }
function changeInstrument(event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  instrumentId.value = value ? Number(value) : null;
  const index = overview.value?.instruments.findIndex((item) => item.id === instrumentId.value) ?? -1;
  if (index >= 0) stationPage.value = Math.floor(index / 6);
}
async function refresh() {
  refreshing.value = true;
  try {
    const requests: Promise<unknown>[] = [refetchOverview(), refetchSamples()];
    if (depth.value) {
      if (selectedId.value === null) requests.push(refetchGlobalAudit());
      else requests.push(refetchAggregate(), refetchSampleAudit());
      if (selectedSceneId.value !== null) requests.push(refetchSceneContext());
      await Promise.all(requests);
    } else await Promise.all(requests);
  } finally { refreshing.value = false; }
}

function stationPoint(index: number) {
  const angle = (index * 60 - 120) * Math.PI / 180;
  return { x: 50 + 40 * Math.cos(angle), y: 48 + 37 * Math.sin(angle) };
}
function capsulePoint(index: number) {
  const ring = Math.floor(index / 12);
  const angle = ((index % 12) * 30 - 90 + ring * 15) * Math.PI / 180;
  return { x: 50 + (ring ? 28 : 19) * Math.cos(angle), y: 48 + (ring ? 26 : 17) * Math.sin(angle) };
}
function stationStyle(index: number) { const point = stationPoint(index); return { left: `${point.x}%`, top: `${point.y}%` }; }
function capsuleStyle(index: number) { const point = capsulePoint(index); return { left: `${point.x}%`, top: `${point.y}%` }; }
const connections = computed(() => samples.value.flatMap((sample, index) => visibleStations.value.flatMap((station, stationIndex) => {
  if (!sample.instrument_ids.includes(station.id)) return [];
  const a = stationPoint(stationIndex), b = capsulePoint(index);
  return [{ key: `${sample.id}-${station.id}`, instrument: station.id,
    path: `M ${a.x * 10} ${a.y * 7} Q 500 336 ${b.x * 10} ${b.y * 7}` }];
})));

const { data: aggregate, error: aggregateError, refetch: refetchAggregate } = useQuery({
  queryKey: computed(() => ["aggregate", selectedId.value]),
  queryFn: ({ signal }) => api<Aggregate>(`/api/samples/${selectedId.value}/aggregate`, { signal }),
  enabled: computed(() => depth.value && selectedId.value !== null),
});
const { data: sampleAudit, error: sampleAuditError, isFetching: sampleAuditFetching, refetch: refetchSampleAudit } = useQuery({
  queryKey: computed(() => ["port-sample-audit", selectedId.value]),
  queryFn: ({ signal }) => api<{ items: SampleAudit[] }>(`/api/samples/${selectedId.value}/audit`, { signal }),
  enabled: computed(() => depth.value && selectedId.value !== null),
});
const { data: auditPages, error: globalAuditError, isFetching: globalAuditFetching, fetchNextPage, hasNextPage, isFetchingNextPage, refetch: refetchGlobalAudit } = useInfiniteQuery({
  queryKey: ["port-global-audits"], initialPageParam: null as number | null,
  queryFn: ({ pageParam, signal }) => api<AuditPage>(`/api/overview/audits?limit=30${pageParam === null ? "" : `&before_id=${pageParam}`}`, { signal }),
  getNextPageParam: (last) => last.has_more ? last.next_before_id : undefined,
  enabled: computed(() => depth.value && selectedId.value === null),
});
const globalEntries = computed(() => auditPages.value?.pages.flatMap((batch) => batch.items) ?? []);
const historyEntries = computed<(PortAudit | SampleAudit)[]>(() => selectedId.value === null ? globalEntries.value : sampleAudit.value?.items ?? []);
const historyError = computed(() => selectedId.value === null ? globalAuditError.value : sampleAuditError.value);
const historyFetching = computed(() => selectedId.value === null ? globalAuditFetching.value : sampleAuditFetching.value);
const { data: sceneContext, error: sceneContextError, isFetching: sceneContextFetching, refetch: refetchSceneContext } = useQuery({
  queryKey: computed(() => ["audit-scene-context", selectedSceneId.value]),
  queryFn: ({ signal }) => api<AuditSceneContext>(`/api/audits/${selectedSceneId.value}/context`, { signal }),
  enabled: computed(() => depth.value && selectedId.value !== null && selectedSceneId.value !== null),
});
const sceneModes = [
  { value: "before" as const, label: "修改前", code: "T−1" },
  { value: "after" as const, label: "修改后", code: "T+0" },
  { value: "current" as const, label: "当前", code: "NOW" },
];
const sceneSrc = computed(() => selectedSceneId.value === null ? "about:blank" : `/api/audits/${selectedSceneId.value}/scene?mode=${sceneMode.value}`);
function retryHistory() { if (selectedId.value === null) void refetchGlobalAudit(); else void refetchSampleAudit(); }
function auditSampleId(entry: PortAudit | SampleAudit) {
  if (entry.entity_type !== "sample" || !/^\d+$/.test(entry.entity_id ?? "")) return null;
  const id = Number(entry.entity_id);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}
function displayValue(value: unknown) {
  return value === null || value === undefined || value === "" ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
}
function canOpenScene(entry: PortAudit | SampleAudit) {
  return "changes" in entry && entry.entity_type === "reading" && entry.action === "update"
    && entry.changes.some((change) => change.field === "raw" && change.before !== change.after);
}
function toggleScene(entry: PortAudit | SampleAudit) {
  if (selectedSceneId.value === entry.id) {
    selectedSceneId.value = null;
    return;
  }
  selectedSceneId.value = entry.id;
  sceneMode.value = "after";
  sceneFrameLoading.value = true;
}
function setSceneMode(mode: "before" | "after" | "current") {
  if (sceneMode.value === mode) return;
  sceneMode.value = mode;
  sceneFrameLoading.value = true;
}
function fly() {
  clearTimeout(flightTimer);
  travelling.value = true;
  flightTimer = setTimeout(() => { travelling.value = false; }, window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 1450);
}
async function enterDepth(id: number | null, event: MouseEvent) {
  returnFocus = event.currentTarget as HTMLElement;
  selectedId.value = id;
  depth.value = true;
  fly();
  await nextTick();
  depthHeading.value?.focus({ preventScroll: true });
  depthHeading.value?.scrollIntoView({ behavior: "instant", block: "start" });
}
async function leaveDepth() {
  selectedSceneId.value = null;
  depth.value = false;
  fly();
  await nextTick();
  const target = returnFocus?.isConnected ? returnFocus : orbitEntry.value;
  target?.focus({ preventScroll: true });
  target?.scrollIntoView({ behavior: "instant", block: "center" });
}
function showGlobal() { selectedSceneId.value = null; selectedId.value = null; depthHeading.value?.focus({ preventScroll: true }); }
function openAuditSample(entry: PortAudit | SampleAudit) { selectedSceneId.value = null; selectedId.value = auditSampleId(entry); depthHeading.value?.scrollIntoView({ behavior: "instant", block: "start" }); depthHeading.value?.focus({ preventScroll: true }); }
useKeyboardShortcuts([{ key: "Escape", enabled: () => depth.value, run: () => { void leaveDepth(); } }]);
onUnmounted(() => { clearTimeout(flightTimer); });
</script>
