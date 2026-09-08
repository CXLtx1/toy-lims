import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { showError } from '../../app/dialogs';
export interface Point { row: number; col: number }
export function useGrid(rows: () => number, value: (point: Point) => string, write: (point: Point, text: string) => boolean, editable: (point: Point) => boolean) {
  const anchor = ref<Point | null>(null), focus = ref<Point | null>(null);
  const dragging = ref(false), filling = ref(false), target = ref<Point | null>(null), message = ref('');
  const range = computed(() => anchor.value && focus.value ? {
    r0: Math.min(anchor.value.row, focus.value.row), r1: Math.max(anchor.value.row, focus.value.row),
    c0: Math.min(anchor.value.col, focus.value.col), c1: Math.max(anchor.value.col, focus.value.col),
  } : null);
  const status = computed(() => message.value || (range.value ? `${range.value.r1 - range.value.r0 + 1} 行 × ${range.value.c1 - range.value.c0 + 1} 列` : ''));
  function selected(point: Point) { const r = range.value; return !!r && point.row >= r.r0 && point.row <= r.r1 && point.col >= r.c0 && point.col <= r.c1; }
  function active(point: Point) { return focus.value?.row === point.row && focus.value.col === point.col; }
  function start(point: Point, event: MouseEvent) {
    if (event.button !== 0) return;
    if (!event.shiftKey || !anchor.value) anchor.value = point;
    focus.value = point; dragging.value = true; message.value = '';
  }
  function enter(point: Point) {
    if (dragging.value) focus.value = point;
    if (filling.value && point.col === focus.value?.col) target.value = point;
  }
  function text() {
    const r = range.value;
    return r ? Array.from({ length: r.r1 - r.r0 + 1 }, (_, row) => Array.from({ length: r.c1 - r.c0 + 1 }, (_, col) => value({ row: r.r0 + row, col: r.c0 + col })).join('\t')).join('\n') : '';
  }
  async function copy() { try { if (range.value) await navigator.clipboard.writeText(text()); } catch (error) { void showError(error, '复制失败'); } }
  function copyEvent(event: ClipboardEvent) {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
    if (range.value && event.clipboardData) { event.preventDefault(); event.clipboardData.setData('text/plain', text()); }
  }
  function paste(event: ClipboardEvent) {
    const start = focus.value;
    if (!start || !event.clipboardData) return;
    const content = event.clipboardData.getData('text/plain');
    // A single value pasted into a parallel/formula/aux input belongs to that input.
    if (event.target instanceof HTMLInputElement && !/[\t\r\n]/.test(content)) return;
    event.preventDefault();
    let changed = 0;
    const lines = content.replace(/\r/g, '').split('\n');
    if (lines.at(-1) === '') lines.pop();
    lines.forEach((line, row) => line.split('\t').forEach((text, col) => {
      const point = { row: start.row + row, col: start.col + col };
      if (point.row < rows() && editable(point) && write(point, text)) changed++;
    }));
    message.value = changed ? `已粘贴 ${changed} 个单元格` : '选区没有可写入的数值格';
  }
  function fillDown(to?: number) {
    const r = range.value;
    if (!r) return;
    const sources: Point[] = [];
    for (let col = r.c0; col <= r.c1 && !sources.length; col++) for (let row = r.r0; row <= r.r1; row++) if (editable({ row, col })) sources.push({ row, col });
    const first = sources[0], last = sources.at(-1);
    if (!first || !last) return;
    let changed = 0;
    if (to === undefined) {
      for (const point of sources.slice(1)) if (write(point, value(first))) changed++;
    } else {
      const values = sources.map(value), nums = values.map(Number);
      const series = values.length >= 2 && values.every(v => v.trim() !== '') && nums.every(Number.isFinite);
      const end = nums.at(-1) ?? 0, step = end - (nums.at(-2) ?? end);
      for (let row = last.row + 1; row <= Math.min(to, rows() - 1); row++) {
        const point = { row, col: first.col };
        const next = series ? String(end + step * (row - last.row)) : values[(row - first.row) % values.length] || '';
        if (editable(point) && write(point, next)) changed++;
      }
    }
    if (changed) message.value = `已向下填充 ${changed} 个单元格`;
  }
  function finish() { dragging.value = false; if (filling.value && target.value) fillDown(target.value.row); filling.value = false; target.value = null; }
  function preview(point: Point) { return filling.value && focus.value && target.value && point.col === focus.value.col && point.row >= focus.value.row && point.row <= target.value.row; }
  function keydown(event: KeyboardEvent) {
    const cell = event.target instanceof HTMLElement ? event.target.closest<HTMLElement>('[data-row][data-col]') : null;
    if (cell) {
      const point = { row: Number(cell.dataset.row), col: Number(cell.dataset.col) };
      if (!active(point)) { anchor.value = point; focus.value = point; }
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'd') { event.preventDefault(); fillDown(); return; }
    const table = event.currentTarget;
    if (!(table instanceof HTMLTableElement) || !focus.value) return;
    if (event.key === 'Escape') { event.preventDefault(); table.focus(); anchor.value = focus.value; return; }
    const moves: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    const move = moves[event.key];
    if (!move) return;
    event.preventDefault();
    const control = event.target;
    if (!event.shiftKey && move[1] && control instanceof HTMLInputElement) {
      const controls = [...(control.closest('td')?.querySelectorAll<HTMLInputElement>('.rd-raw:not(:disabled), .rd-var:not(:disabled)') || [])];
      const next = controls[controls.indexOf(control) + move[1]];
      if (next) { next.focus(); next.select(); return; }
    }
    const next = { row: focus.value.row + move[0], col: focus.value.col + move[1] };
    if (next.row < 0 || next.row >= rows() || next.col < 0 || next.col > 5) return;
    if (!event.shiftKey) anchor.value = next;
    focus.value = next; message.value = '';
    const input = table.querySelector<HTMLInputElement>(`[data-row="${next.row}"][data-col="${next.col}"] .rd-raw:not(:disabled), [data-row="${next.row}"][data-col="${next.col}"] .rd-var:not(:disabled)`);
    if (input && !event.shiftKey) { input.focus(); input.select(); } else table.focus();
  }
  onMounted(() => window.addEventListener('mouseup', finish));
  onBeforeUnmount(() => window.removeEventListener('mouseup', finish));
  return { focus, filling, status, selected, active, start, enter, preview, copy, copyEvent, paste, fillDown, keydown };
}
