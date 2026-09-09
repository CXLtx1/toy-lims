<script setup lang="ts">
import { computed, ref } from 'vue';
import { fields, fixedValues, variables, type EntryMeta, type Task } from './types';
import type { EntryDraft, ReadingDraft, TaskDraft, useEntryDrafts } from './use-entry-drafts';
import { useGrid, type Point } from './use-grid';
const props = defineProps<{ draft: EntryDraft; store: ReturnType<typeof useEntryDrafts>; meta: EntryMeta | null; readonly: boolean }>();
const method = ref<Task | null>(null);
const unitMap: Record<string, string> = { xrf: '%', ppm: 'ppm', ppb: 'ppb', mol: 'mol/L', percent: '%', ph: 'pH' };
const groups = computed(() => {
  const order = new Map(props.meta?.instruments.map((item, index) => [item.id, index]));
  const analytes = new Map(props.meta?.analytes.map((item, index) => [item.id, index]));
  const map = new Map<number, TaskDraft[]>();
  for (const task of props.draft.tasks) { const id = task.task.instrument_id || 0; const group = map.get(id) || []; group.push(task); map.set(id, group); }
  let index = 0;
  return [...map.entries()].sort(([a], [b]) => (order.get(a) ?? Infinity) - (order.get(b) ?? Infinity)).map(([id, tasks]) => ({ id, label: id ? tasks[0]?.task.instrument : '未选仪器', rows: tasks.sort((a, b) =>
    (a.task.prep_name || '原样').localeCompare(b.task.prep_name || '原样', 'zh-CN') || (analytes.get(a.task.analyte_id) ?? Infinity) - (analytes.get(b.task.analyte_id) ?? Infinity) || a.task.id - b.task.id).map(task => ({ task, index: index++ })) }));
});
const rows = computed(() => groups.value.flatMap(group => group.rows.map(row => row.task)));
function value(point: Point): string {
  const row = rows.value[point.row]; if (!row) return '';
  const rd = row.readings[0];
  return [row.task.analyte, row.task.prep_name || '原样', [row.task.instrument, row.task.method_name].filter(Boolean).join(''), row.task.itype === 'function' ? rd?.extra[variables(row.task)[0] || ''] || '' : rd?.raw || '', row.expected, stateText(row)][point.col] || '';
}
function editable(point: Point): boolean { const task = rows.value[point.row]; return !props.readonly && point.col === 3 && !!task?.task.itype && !!task.readings[0] && !task.readings[0].deleting && (task.task.itype !== 'function' || variables(task.task).length > 0); }
function write(point: Point, text: string): boolean {
  if (!editable(point) || (text.trim() !== '' && !Number.isFinite(Number(text)))) return false;
  const task = rows.value[point.row], rd = task?.readings[0]; if (!task || !rd) return false;
  if (task.task.itype === 'function') rd.extra[variables(task.task)[0] || ''] = text; else rd.raw = text;
  props.store.editReading(props.draft, task, rd); void props.store.saveReading(props.draft, task, rd); return true;
}
const grid = useGrid(() => rows.value.length, value, write, editable);
function stateText(task: TaskDraft) {
  if (task.error || task.readings.some(rd => rd.error)) return task.error || task.readings.find(rd => rd.error)?.error || '';
  if (task.saving || task.readings.some(rd => rd.saving || rd.deleting)) return '正在保存…';
  if (task.dirty || task.readings.some(rd => rd.dirty)) return '待保存';
  const time = task.savedAt || task.readings.find(rd => rd.savedAt)?.savedAt;
  return time ? `✓ 已存 ${time}` : '';
}
function hasValue(task: TaskDraft) { return task.readings.some(rd => rd.raw !== '' || Object.values(rd.extra).some(value => value !== '')); }
function coeff(task: TaskDraft) { return task.use && Number(task.expected) && Number(task.measured) ? `×${(Number(task.expected) / Number(task.measured)).toFixed(4)}` : ''; }
function readingInput(row: TaskDraft, rd: ReadingDraft, event: Event, key?: string) {
  if (props.readonly || !(event.target instanceof HTMLInputElement)) return;
  if (key) rd.extra[key] = event.target.value; else rd.raw = event.target.value;
  props.store.editReading(props.draft, row, rd);
}
function auxInput(row: TaskDraft, key: 'expected' | 'measured', event: Event) {
  if (props.readonly || !(event.target instanceof HTMLInputElement)) return;
  row[key] = event.target.value; props.store.editAux(props.draft, row);
}
</script>
<template>
  <div class="grid-toolbar noprint"><button type="button" class="grid-copy" title="复制选区 (Ctrl+C)" @click="grid.copy">⧉</button><button type="button" class="grid-fill" title="向下填充 (Ctrl+D)" :disabled="readonly" @click="grid.fillDown()">↓</button><span id="d-grid-status">{{ grid.status.value }}</span></div>
  <div class="table-shell"><table id="d-table" class="data-grid spreadsheet" tabindex="0" @copy="grid.copyEvent" @paste="grid.paste" @keydown="grid.keydown"><thead><tr><th>项目</th><th>溶样</th><th>仪器/方法</th><th>原始值</th><th>辅助数据</th><th>状态</th></tr></thead><tbody>
    <template v-for="group in groups" :key="group.id"><tr class="group"><td colspan="6"><b>{{ group.label }}</b></td></tr>
      <tr v-for="{ task: row, index } in group.rows" :key="row.task.id" :class="{ 'task-completed': row.task.status === 'completed' || hasValue(row) }" :data-said="row.task.id" :data-itype="row.task.itype || ''" :data-analyte="row.task.analyte" :data-prep="row.task.prep_name || '原样'">
        <td v-for="col in [0, 1, 2, 3, 4, 5]" :key="col" class="grid-cell" :class="{ readonly: [0, 1, 2, 5].includes(col), st: col === 5, selected: grid.selected({ row: index, col }), active: grid.active({ row: index, col }), 'fill-preview': grid.preview({ row: index, col }) }" :data-row="index" :data-col="col" @mousedown="grid.start({ row: index, col }, $event)" @mouseenter="grid.enter({ row: index, col })">
          <template v-if="col === 0">{{ row.task.analyte }}</template><template v-else-if="col === 1">{{ row.task.prep_name || '原样' }}</template>
          <template v-else-if="col === 2"><template v-if="row.task.instrument">{{ row.task.instrument }}</template><i v-else class="bad-text">未分配（请到来样页设置）</i><small v-if="row.task.method_name">{{ row.task.method_name }}</small></template>
          <template v-else-if="col === 3"><i v-if="!row.task.itype" style="color: #999">先选仪器</i><template v-else>
            <template v-if="row.task.itype === 'function'"><span class="method-label">{{ row.task.method_name || '未设置公式方法' }}</span> <span v-if="fixedValues(row.task)" class="hint">{{ fixedValues(row.task) }}</span> <button v-if="row.task.method_id" class="method-detail" type="button" :data-method-id="row.task.method_id" @click="method = row.task">详情</button></template>
            <div class="readings"><div v-for="rd in row.readings" :key="rd.key" class="reading" :class="{ 'has-value': rd.raw !== '' || Object.values(rd.extra).some(value => value !== '') }" :data-rid="rd.id || ''">
              <span v-if="row.task.itype === 'function'" class="tit-inputs"><template v-for="key in variables(row.task)" :key="key">{{ key }}=<input :value="rd.extra[key]" type="number" step="any" class="rd-var" :data-var="key" :aria-label="`${row.task.analyte} ${key}`" :disabled="readonly || rd.deleting" @input="readingInput(row, rd, $event, key)" @change="store.saveReading(draft, row, rd)"></template></span>
              <span v-else class="input-unit"><input :value="rd.raw" type="number" step="any" class="rd-raw" data-field="raw" :aria-label="`${row.task.analyte} 原始值`" :disabled="readonly || rd.deleting" @input="readingInput(row, rd, $event)" @change="store.saveReading(draft, row, rd)"> <span>{{ unitMap[row.task.itype || ''] || '' }}</span></span>
              <label v-if="row.readings.length > 1" class="inline rd-use-label" title="勾选后参与结果计算"><input v-model="rd.included" type="checkbox" class="rd-use" :disabled="readonly || rd.deleting" @change="store.participation(draft, row)">参与</label>
              <button v-if="row.readings.length > 1" class="del rd-del" type="button" title="删除这遍" :disabled="readonly || rd.deleting || rd.uncertain" @click="store.deleteReading(draft, row, rd)">删</button>
            </div></div><button class="rd-add" type="button" :disabled="readonly" @click="store.addReading(draft, row)">+ 再测一遍</button>
          </template></template>
          <span v-else-if="col === 4" class="aux-box">标称<input :value="row.expected" type="number" step="any" class="aux-std" style="width: 55px" :disabled="readonly" @input="auxInput(row, 'expected', $event)" @change="store.saveAux(draft, row)"> 回读<input :value="row.measured" type="number" step="any" class="aux-read" style="width: 55px" :disabled="readonly" @input="auxInput(row, 'measured', $event)" @change="store.saveAux(draft, row)"> <label class="inline" title="带标计算"><input v-model="row.use" type="checkbox" class="aux-use" :disabled="readonly" @change="store.editAux(draft, row); store.saveAux(draft, row)">带标</label><span class="aux-show">{{ coeff(row) }}</span></span>
          <template v-else><span role="status">{{ stateText(row) }}</span><button v-if="row.error || row.readings.some(rd => rd.error && !rd.uncertain)" type="button" :disabled="readonly" @click="store.flush(draft)">重试保存</button></template>
          <span v-if="grid.active({ row: index, col }) && editable({ row: index, col })" class="fill-handle" title="拖动填充" @mousedown.stop.prevent="grid.filling.value = true"></span>
        </td>
      </tr>
    </template>
  </tbody></table></div>
  <p class="hint">同仪器自动归为一组；“+再测一遍”可增加平行读数。多遍读数只需勾选是否“参与”：勾选多遍自动取平均，只勾选一遍就直接采用该遍。辅助数据填标称/回读并勾“带标”即按 标称÷回读 校正；所有输入失焦即自动保存。</p>
  <Teleport to="body"><div v-if="method" id="method-detail-backdrop" class="dialog-backdrop" @click.self="method = null" @keydown.esc="method = null"><section class="method-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="method-detail-title"><button id="method-detail-x" class="dialog-x" type="button" aria-label="关闭" @click="method = null">×</button><h2 id="method-detail-title">{{ method.method_name }}</h2><dl class="method-detail-meta"><dt>输出单位</dt><dd id="method-detail-output-unit">{{ method.method_output_unit || '%' }}</dd><dt>公式</dt><dd id="method-detail-formula">{{ method.formula || '未设置' }}</dd><dt>固定参数</dt><dd id="method-detail-constants">{{ Object.entries(fields(method.method_constants)).map(([key, value]) => `${key}=${value}`).join('，') || '无' }}</dd></dl><h3>滴定说明</h3><div id="method-detail-note">{{ method.method_note?.trim() || '尚未填写滴定说明。' }}</div><div class="dialog-actions"><button id="method-detail-close" type="button" class="primary" @click="method = null">关闭</button></div></section></div></Teleport>
</template>
