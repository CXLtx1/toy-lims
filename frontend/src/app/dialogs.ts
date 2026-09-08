import { reactive } from 'vue';

export const dialogs = reactive({ error: '', title: '操作未完成', authorization: false, explanation: '', authorizationError: '', authorizing: false });
let authorizationPromise: Promise<boolean> | null = null;
let resolveAuthorization: ((allowed: boolean) => void) | null = null;

export function showError(error: unknown, title = '操作未完成'): void {
  if (error instanceof DOMException && error.name === 'AbortError') return;
  if (error instanceof Error && 'code' in error && error.code === 'authorization_cancelled') return;
  if (error instanceof Error && 'code' in error && error.code === 'version_conflict') {
    dialogs.error = '数据已被其他操作修改或已过期，本次保存未覆盖服务器内容；请重新载入后再试。';
  } else {
    dialogs.error = error instanceof Error ? error.message : String(error);
  }
  dialogs.title = title;
}
export function requestAuthorization(explanation: string): Promise<boolean> {
  if (authorizationPromise) return authorizationPromise;
  dialogs.authorization = true;
  dialogs.explanation = explanation;
  dialogs.authorizationError = '';
  authorizationPromise = new Promise(resolve => { resolveAuthorization = resolve; });
  return authorizationPromise;
}
export function finishAuthorization(allowed: boolean): void {
  dialogs.authorization = false;
  dialogs.authorizationError = '';
  resolveAuthorization?.(allowed);
  resolveAuthorization = null;
  authorizationPromise = null;
}
