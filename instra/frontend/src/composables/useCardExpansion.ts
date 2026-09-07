import { shallowRef } from "vue";

/** 多卡片展开状态；额外记录打开顺序，以便关闭最近打开的一项。 */
export function useCardExpansion<T extends string | number>() {
  const expanded = shallowRef<Set<T>>(new Set());
  let openOrder: T[] = [];

  function toggle(id: T) {
    const next = new Set(expanded.value);
    if (next.has(id)) {
      next.delete(id);
      openOrder = openOrder.filter((item) => item !== id);
    } else {
      next.add(id);
      openOrder.push(id);
    }
    expanded.value = next;
  }

  function closeLast() {
    const id = openOrder.pop();
    if (id === undefined) return;
    const next = new Set(expanded.value);
    next.delete(id);
    expanded.value = next;
  }

  function collapseAll() {
    openOrder = [];
    expanded.value = new Set();
  }

  return { expanded, toggle, closeLast, collapseAll };
}
