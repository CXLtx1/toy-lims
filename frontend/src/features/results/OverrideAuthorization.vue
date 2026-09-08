<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue';
import { refreshMeta } from '../../app/state';
import { errorText, write } from '../reports/model';
const open = ref(false);
const password = ref('');
const explanation = ref('');
const error = ref('');
const busy = ref(false);
const input = ref<HTMLInputElement | null>(null);
const dialog = ref<HTMLElement | null>(null);
let resolve: ((authorized: boolean) => void) | undefined;
let returnFocus: Element | null = null;
let alive = true;
function close(authorized = false) {
  open.value = false; password.value = ''; error.value = '';
  document.body.classList.remove('authorization-open');
  resolve?.(authorized); resolve = undefined;
  if (returnFocus instanceof HTMLElement && returnFocus.isConnected) returnFocus.focus();
}
async function confirm(text: string): Promise<boolean> {
  if (open.value) return false;
  explanation.value = text; returnFocus = document.activeElement;
  open.value = true; document.body.classList.add('authorization-open');
  const result = new Promise<boolean>(done => { resolve = done; });
  await nextTick(); input.value?.focus();
  return result;
}
async function submit() {
  if (busy.value || !password.value) return;
  busy.value = true; error.value = '';
  try {
    await write('/api/authorize', { password: password.value, purpose: 'result_override' }, 'POST');
    if (!alive) return;
    // Identity refresh must not prevent the one-shot authorized operation.
    close(true);
    void Promise.resolve(refreshMeta()).catch(() => undefined);
  } catch (cause) { error.value = errorText(cause); password.value = ''; input.value?.focus(); }
  finally { busy.value = false; }
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); if (!busy.value) close(); }
  if (event.key !== 'Tab') return;
  const controls = Array.from(dialog.value?.querySelectorAll<HTMLElement>('input:not(:disabled),button:not(:disabled)') || []);
  const first = controls[0]; const last = controls[controls.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
}
onBeforeUnmount(() => { alive = false; close(); });
defineExpose({ confirm });
</script>
<template>
  <Teleport to="body"><section v-if="open" id="results-authorization-dialog" ref="dialog" class="authorization-dialog" role="dialog" aria-modal="true" aria-labelledby="results-authorization-title" aria-describedby="results-authorization-explanation" @keydown="keydown">
    <div class="authorization-mark" aria-hidden="true">权限</div><h2 id="results-authorization-title">需要用户授权</h2><p id="results-authorization-explanation">{{ explanation }}</p>
    <form id="results-authorization-form" @submit.prevent="submit"><label for="results-authorization-password">用户密码</label><input id="results-authorization-password" ref="input" v-model="password" type="password" autocomplete="current-password" required :disabled="busy"><div id="results-authorization-error" class="authorization-error" role="alert" aria-live="polite">{{ error }}</div><div class="authorization-actions"><button id="results-authorization-cancel" type="button" :disabled="busy" @click="close()">取消</button><button id="results-authorization-confirm" type="submit" class="primary" :disabled="busy">确认授权</button></div></form>
  </section></Teleport>
</template>
