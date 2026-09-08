import { nextTick, onBeforeUnmount, onMounted, reactive, type Ref } from 'vue'
import { showError } from '../../app/dialogs'

interface Point { row: number; col: number }
export function usePreparationGrid(table: Ref<HTMLTableElement | null>, append: () => void, disabled: () => boolean) {
  const state = reactive<{ anchor: Point | null; focus: Point | null; dragging: boolean; filling: boolean; fillRow: number | null; status: string }>({
    anchor: null, focus: null, dragging: false, filling: false, fillRow: null, status: '',
  })
  const cellAt = (row: number, col: number) => table.value?.querySelector<HTMLTableCellElement>(`td[data-row="${row}"][data-col="${col}"]`) ?? null
  const point = (cell: HTMLElement): Point => ({ row: Number(cell.dataset.row), col: Number(cell.dataset.col) })
  const control = (cell: HTMLElement | null) => cell?.querySelector<HTMLInputElement | HTMLSelectElement>('input:not([type="hidden"]),select') ?? null
  function eventCell(event: Event): HTMLTableCellElement | null {
    if (!(event.target instanceof Element) || event.target.closest('.p-routing-cell,.prep-row-actions')) return null
    const cell = event.target.closest<HTMLTableCellElement>('td.grid-cell')
    return cell && table.value?.contains(cell) ? cell : null
  }
  function bounds() {
    const a = state.anchor, b = state.focus
    return a && b ? { r0: Math.min(a.row, b.row), r1: Math.max(a.row, b.row), c0: Math.min(a.col, b.col), c1: Math.max(a.col, b.col) } : null
  }
  function paint(): void {
    const range = bounds()
    if (range) state.status = `${range.r1 - range.r0 + 1} 行 × ${range.c1 - range.c0 + 1} 列`
  }
  function cellClass(row: number, col: number): Record<string, boolean> {
    const range = bounds()
    return { selected: !!range && row >= range.r0 && row <= range.r1 && col >= range.c0 && col <= range.c1,
      active: row === state.focus?.row && col === state.focus.col,
      'fill-preview': state.filling && col === state.focus?.col && row >= state.focus.row && row <= (state.fillRow ?? state.focus.row) }
  }
  function valueOf(cell: HTMLElement | null): string {
    const input = control(cell)
    return input instanceof HTMLSelectElement ? input.selectedOptions[0]?.textContent?.trim() ?? '' : input?.value ?? cell?.querySelector<HTMLInputElement>('input[type="hidden"]')?.value ?? cell?.textContent?.trim() ?? ''
  }
  function matrix(): string {
    const range = bounds()
    return range ? Array.from({ length: range.r1 - range.r0 + 1 }, (_, r) => Array.from({ length: range.c1 - range.c0 + 1 }, (_, c) => valueOf(cellAt(range.r0 + r, range.c0 + c))).join('\t')).join('\n') : ''
  }
  async function copy(): Promise<void> {
    const text = matrix()
    if (text) try { await navigator.clipboard.writeText(text) } catch (error) { showError(error, '复制失败，请使用 Ctrl+C') }
  }
  function onCopy(event: ClipboardEvent): void {
    if (!eventCell(event) && event.target !== table.value) return
    const text = matrix()
    if (text && event.clipboardData) { event.preventDefault(); event.clipboardData.setData('text/plain', text) }
  }
  function write(row: number, col: number, value: string): boolean {
    if (disabled()) return false
    const input = control(cellAt(row, col))
    if (!input || input.disabled) return false
    if (input instanceof HTMLSelectElement) {
      const option = Array.from(input.options).find(o => o.value === value.trim() || o.textContent?.trim() === value.trim())
      if (!option) return false
      input.value = option.value
    } else input.value = value
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
    return true
  }
  async function onPaste(event: ClipboardEvent): Promise<void> {
    if (disabled() || !state.focus || !eventCell(event) && event.target !== table.value) return
    const text = event.clipboardData?.getData('text/plain')
    if (text === undefined) return
    event.preventDefault()
    const rows = text.replace(/\r/g, '').replace(/\n$/, '').split('\n').map(row => row.split('\t'))
    if (rows.length > 1000) { showError('每次最多粘贴 1000 行。'); return }
    const start = { ...state.focus }
    const existing = table.value?.tBodies[0]?.rows.length ?? 0
    for (let index = existing; index < start.row + rows.length; index++) append()
    await nextTick()
    let changed = 0
    rows.forEach((row, r) => row.forEach((value, c) => { if (write(start.row + r, start.col + c, value)) changed++ }))
    state.status = changed ? `已粘贴 ${changed} 个单元格` : '选区没有可写入的数值格'
  }
  function fillDown(targetRow: number | null = null): void {
    const range = bounds()
    if (!range || disabled()) return
    const values = Array.from({ length: range.r1 - range.r0 + 1 }, (_, r) => valueOf(cellAt(range.r0 + r, range.c0)))
    let changed = 0
    if (targetRow === null) {
      for (let row = range.r0 + 1; row <= range.r1; row++) if (write(row, range.c0, values[0] ?? '')) changed++
    } else {
      const numbers = values.map(Number)
      const series = values.length > 1 && values.every(v => v.trim() !== '') && numbers.every(Number.isFinite)
      const last = numbers.at(-1) ?? 0, step = last - (numbers.at(-2) ?? last)
      for (let row = range.r1 + 1; row <= targetRow; row++) {
        const value = series ? String(Number((last + step * (row - range.r1)).toPrecision(12))) : values[(row - range.r0) % values.length] ?? ''
        if (write(row, range.c0, value)) changed++
      }
    }
    if (changed) state.status = `已向下填充 ${changed} 个单元格`
  }
  function mousedown(event: MouseEvent): void {
    if (event.button !== 0) return
    const cell = eventCell(event)
    if (!cell) return
    const p = point(cell)
    if (!event.shiftKey || !state.anchor) state.anchor = p
    state.focus = p; state.dragging = true; paint()
  }
  function mouseover(event: MouseEvent): void {
    const cell = eventCell(event)
    if (cell && state.dragging) { state.focus = point(cell); paint() }
  }
  function beginFill(): void {
    if (disabled()) return
    state.filling = true; state.fillRow = null; document.body.classList.add('grid-filling')
  }
  function mousemove(event: MouseEvent): void {
    if (!state.filling) return
    const cell = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>('td.grid-cell')
    if (cell && table.value?.contains(cell) && Number(cell.dataset.col) === state.focus?.col) state.fillRow = Number(cell.dataset.row)
  }
  function mouseup(): void {
    state.dragging = false
    if (state.filling && state.fillRow !== null) fillDown(state.fillRow)
    state.filling = false; state.fillRow = null; document.body.classList.remove('grid-filling')
  }
  function keydown(event: KeyboardEvent): void {
    if (!eventCell(event) && event.target !== table.value) return
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'd') { event.preventDefault(); fillDown(); return }
    if (event.key === 'Escape') {
      event.preventDefault(); event.stopPropagation(); table.value?.focus({ preventScroll: true }); return
    }
    const moves: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }
    const move = moves[event.key], currentCell = eventCell(event)
    const current = currentCell ? point(currentCell) : state.focus
    if (!move || !current) return
    event.preventDefault()
    const inputs = Array.from(currentCell?.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input:not([type="hidden"]),select') ?? [])
    const index = inputs.findIndex(input => input === event.target)
    const adjacent = move[1] && index >= 0 ? inputs[index + move[1]] : undefined
    if (adjacent) { adjacent.focus(); return }
    let col = current.col + move[1]
    let target = cellAt(current.row + move[0], col)
    while (target?.style.display === 'none' && move[1]) { col += move[1]; target = cellAt(current.row + move[0], col) }
    if (!target) return
    state.focus = point(target)
    if (!event.shiftKey || !state.anchor) state.anchor = state.focus
    paint()
    const input = control(target)
    if (input && !input.disabled) { input.focus(); if (input instanceof HTMLInputElement) input.select() }
    else table.value?.focus({ preventScroll: true })
  }
  function reset(): void { state.anchor = null; state.focus = null; state.status = ''; mouseup() }
  onMounted(() => { document.addEventListener('mouseup', mouseup); document.addEventListener('mousemove', mousemove) })
  onBeforeUnmount(() => { document.removeEventListener('mouseup', mouseup); document.removeEventListener('mousemove', mousemove); document.body.classList.remove('grid-filling') })
  return { state, cellClass, copy, onCopy, onPaste, fillDown, mousedown, mouseover, beginFill, keydown, reset }
}
