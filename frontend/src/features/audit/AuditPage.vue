<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { request } from '../../api/client';
import { useAppState } from '../../app/state';
import { showError } from '../../app/dialogs';
interface AuditRecord { id: number; created_at: string; username: string; terminal_name: string | null; action: string; entity_type: string; entity_id: string | null; reason: string | null; ip_address: string | null; changes: { label: string; field: string; before: unknown; after: unknown }[] }
const actionLabels: Record<string, string> = {
  setup: '初始化系统', login: '终端登录', logout: '终端退出', session_replaced: '会话被其他设备顶下线', heartbeat: '仪器状态心跳', instrument_login: '标准客户端用户登录', create: '新建', update: '修改', delete: '删除', disable: '停用', restore: '恢复', reorder: '调整顺序', capabilities: '修改仪器能力', status_change: '修改状态', cancel: '作废', result_update: '修改结果', report_use: '修改结果参与计算', report_meta: '修改报告信息', report_order: '修改报告顺序', report_print: '修改报告打印项', report_override: '旧版手工修改报告', result_override: '特权补录结果', instrument_import: '导入仪器结果', instrument_reading: '仪器录入读数', instrument_submit: '仪器批量提交', xrf_assign: '关联 XRF 扫描', xrf_unassign: '解绑 XRF 扫描', xrf_report_use: '修改 XRF 结果参与计算', special_result: '修改专项检测数据', excel_plan_create: '从 Excel 新建样品', excel_plan_overwrite: '从 Excel 覆盖样品方案', excel_data_overwrite: '从 Excel 覆盖检测数据',
};
const entityLabels: Record<string, string> = { sample: '样品', sample_analyte: '检测任务', reading: '读数', result: '结果', session: '登录会话', instrument_client: '仪器客户端', standard_submission: '标准客户端提交', xrf_analysis: 'XRF 扫描', xrf_value: 'XRF 结果', uq_analysis: 'UniQuant 分析', analyte: '分析项目', instrument: '仪器', dilution: '稀释方式', method: '分析方法', template: '样品模板', volume_preset: '定容容量', preparation_combination: '溶样组合', report_profile: '报告版式', result_order_template: '结果顺序模板', user: '用户', terminal: '终端' };
const actionLabel = (value: string) => actionLabels[value] || value || '未知动作';
const entityLabel = (value: string) => entityLabels[value] || value || '未知对象';
const text = (value: unknown): string => value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
const app = useAppState(), records = ref<AuditRecord[]>([]), query = ref(''), action = ref(''), entity = ref(''), loading = ref(false);
const actions = computed(() => [...new Set(records.value.map(r => r.action).filter(Boolean))].sort((a, b) => actionLabel(a).localeCompare(actionLabel(b), 'zh-CN')));
const entities = computed(() => [...new Set(records.value.map(r => r.entity_type).filter(Boolean))].sort((a, b) => entityLabel(a).localeCompare(entityLabel(b), 'zh-CN')));
const filtered = computed(() => records.value.filter(r => (!action.value || r.action === action.value) && (!entity.value || r.entity_type === entity.value) && [r.created_at, r.username, r.terminal_name, actionLabel(r.action), r.action, entityLabel(r.entity_type), r.entity_type, r.entity_id, r.reason, r.ip_address, ...(r.changes || []).flatMap(c => [c.label, c.field, c.before, c.after])].map(text).join(' ').toLocaleLowerCase('zh-CN').includes(query.value.trim().toLocaleLowerCase('zh-CN'))));
async function load() {
  if (loading.value) return;
  loading.value = true;
  try { records.value = await request<AuditRecord[]>('/api/audit?limit=500'); if (!actions.value.includes(action.value)) action.value = ''; if (!entities.value.includes(entity.value)) entity.value = ''; }
  catch (error) { showError(error); } finally { loading.value = false; }
}
function details(item: AuditRecord) {
  const changes = item.changes?.length ? item.changes.map(c => `${c.label || c.field}：${text(c.before)} → ${text(c.after)}`).join('\n') : '未找到有效字段变化';
  showError(`时间：${item.created_at}\n操作者：${item.username}${item.terminal_name ? ` @ ${item.terminal_name}` : ''}\n动作：${actionLabel(item.action)}\n对象：${entityLabel(item.entity_type)} ${item.entity_id || ''}\n原因：${item.reason || '—'}\nIP：${item.ip_address || '—'}\n\n真正变化：\n${changes}`, '审计详情');
}
watch(() => [app.page, app.refreshRevision], () => { if (app.page === 'audit') void load(); }, { immediate: true });
</script>
<template>
  <section id="page-audit" class="page" :class="{ active: app.page === 'audit' }"><div class="panel audit-page-panel">
    <div class="section-head"><h2>审计记录</h2><button id="audit-refresh" type="button" :disabled="loading" @click="load">刷新</button></div>
    <div class="audit-toolbar"><input id="audit-search" v-model="query" type="search" placeholder="搜索操作者、终端、动作、对象、原因、IP 或变更内容"><select id="audit-action-filter" v-model="action"><option value="">全部动作</option><option v-for="value in actions" :key="value" :value="value">{{ actionLabel(value) }}</option></select><select id="audit-entity-filter" v-model="entity"><option value="">全部对象</option><option v-for="value in entities" :key="value" :value="value">{{ entityLabel(value) }}</option></select><button id="audit-clear" type="button" @click="query = ''; action = ''; entity = ''">清除过滤</button><span id="audit-count">显示 {{ filtered.length }} / {{ records.length }} 条</span></div>
    <div class="table-shell audit-table-shell"><table id="audit-table" class="data-grid"><thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>对象</th><th>原因</th><th>网络位置</th><th></th></tr></thead><tbody><tr v-for="item in filtered" :key="item.id" :data-audit-id="item.id"><td>{{ item.created_at }}</td><td>{{ item.username }}<small v-if="item.terminal_name" class="audit-terminal">@ {{ item.terminal_name }}</small></td><td>{{ actionLabel(item.action) }}</td><td>{{ entityLabel(item.entity_type) }} {{ item.entity_id || '' }}</td><td>{{ item.reason || '—' }}</td><td>{{ item.ip_address || '—' }}</td><td><button class="audit-detail" type="button" @click="details(item)">详情</button></td></tr><tr v-if="!filtered.length"><td colspan="7" class="audit-empty">没有符合当前过滤条件的审计记录。</td></tr></tbody></table></div>
  </div></section>
</template>
