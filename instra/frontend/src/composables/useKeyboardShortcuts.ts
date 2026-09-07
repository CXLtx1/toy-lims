import { onMounted, onUnmounted } from "vue";

interface KeyboardShortcut {
  key: string;
  run: (event: KeyboardEvent) => void;
  enabled?: (event: KeyboardEvent) => boolean;
  allowInEditable?: boolean;
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/** 页面级快捷键；默认不劫持输入框、下拉框和可编辑区域。 */
export function useKeyboardShortcuts(shortcuts: KeyboardShortcut[]) {
  function handleKeydown(event: KeyboardEvent) {
    const shortcut = shortcuts.find((item) => item.key === event.key);
    if (!shortcut || shortcut.enabled?.(event) === false) return;
    if (!shortcut.allowInEditable && isEditable(event.target)) return;
    event.preventDefault();
    shortcut.run(event);
  }

  onMounted(() => window.addEventListener("keydown", handleKeydown));
  onUnmounted(() => window.removeEventListener("keydown", handleKeydown));
}
