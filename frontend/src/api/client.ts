import { reactive } from 'vue';
import { requestAuthorization } from '../app/dialogs';
import type { Session } from './types';

export class ApiError extends Error {
  constructor(message: string, public status = 0, public code = '', public retryAfter: number | null = null) { super(message); this.name = 'ApiError'; }
}
export interface RequestOptions {
  method?: string; body?: unknown; signal?: AbortSignal; authorize?: boolean; timeout?: number;
}
export const network = reactive({ writes: 0, lastWrite: 0, sessionLost: false });
let session: Session | null = null;
let sessionPromise: Promise<Session> | null = null;

function apiUrl(url: string): string {
  const target = new URL(url, location.origin);
  if (target.origin !== location.origin || !target.pathname.startsWith('/api/')) throw new ApiError('只允许访问同源 API。');
  return target.href;
}
function object(value: unknown): Record<string, unknown> { return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
async function fetchResponse(url: string, init: RequestInit, timeout: number): Promise<Response> {
  const controller = new AbortController();
  const abort = () => controller.abort(init.signal?.reason);
  if (init.signal?.aborted) abort(); else init.signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => controller.abort(new DOMException('请求超时，请核对保存状态后重试。', 'TimeoutError')), timeout);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal, credentials: 'same-origin', cache: 'no-store' });
    // Detect session loss even for non-JSON responses; operator password failures are separate.
    if (response.status === 401 && new URL(url, location.origin).pathname !== '/api/authorize') network.sessionLost = true;
    return response;
  }
  catch (error) {
    if (init.signal?.aborted) throw init.signal.reason ?? new DOMException('Aborted', 'AbortError');
    if (controller.signal.aborted) throw new ApiError('请求超时。写入可能已经完成，请核对数据后再重试。', 0, 'timeout');
    throw new ApiError(error instanceof Error ? `无法连接服务器：${error.message}` : '无法连接服务器', 0, 'network_error');
  } finally { clearTimeout(timer); init.signal?.removeEventListener('abort', abort); }
}
async function json(response: Response): Promise<unknown> {
  const text = await response.text();
  try { return text ? JSON.parse(text) as unknown : {}; }
  catch { throw new ApiError(`服务器返回了无法解析的响应 (${response.status})`, response.status, 'invalid_response'); }
}
function failure(response: Response, data: Record<string, unknown>): ApiError {
  if (data.code === 'csrf_invalid') session = null;
  const retry = response.headers.get('Retry-After');
  return new ApiError(typeof data.error === 'string' ? data.error : `请求失败 (${response.status})`, response.status,
    typeof data.code === 'string' ? data.code : '', retry && /^\d+$/.test(retry) ? Number(retry) : null);
}
export async function bootstrapSession(force = false): Promise<Session> {
  if (force) session = null;
  if (session) return session;
  if (!sessionPromise) sessionPromise = (async () => {
    const response = await fetchResponse(apiUrl('/api/session'), {}, 30000);
    const data = object(await json(response));
    if (!response.ok) throw failure(response, data);
    if (typeof data.csrf_token !== 'string' || typeof data.authenticated !== 'boolean' || typeof data.setup_required !== 'boolean') throw new ApiError('会话响应格式错误。', response.status, 'invalid_response');
    session = data as unknown as Session;
    network.sessionLost = !session.authenticated && !session.setup_required;
    return session;
  })().finally(() => { sessionPromise = null; });
  return sessionPromise;
}
async function send(url: string, options: RequestOptions, form?: FormData): Promise<Response> {
  const method = (options.method || 'GET').toUpperCase();
  const writing = !['GET', 'HEAD', 'OPTIONS'].includes(method);
  const headers: Record<string, string> = {};
  if (writing) headers['X-CSRF-Token'] = (await bootstrapSession()).csrf_token;
  if (!form && options.body !== undefined) headers['Content-Type'] = 'application/json';
  const init: RequestInit = { method, headers, signal: options.signal, body: form ?? (options.body === undefined ? undefined : JSON.stringify(options.body)) };
  const response = await fetchResponse(apiUrl(url), init, options.timeout ?? (form ? 120000 : 30000));
  if (response.status === 428 && options.authorize !== false && url !== '/api/authorize') {
    const data = object(await json(response));
    if (data.code !== 'authorization_required') throw failure(response, data);
    if (!await requestAuthorization(typeof data.error === 'string' ? data.error : '请输入用户密码以确认本次修改')) throw new ApiError('已取消授权，输入已保留。', 428, 'authorization_cancelled');
    if (options.signal?.aborted) throw options.signal.reason;
    return send(url, { ...options, authorize: false }, form);
  }
  return response;
}
async function execute<T>(url: string, options: RequestOptions, form?: FormData): Promise<T> {
  const writing = !['GET', 'HEAD', 'OPTIONS'].includes((options.method || 'GET').toUpperCase());
  if (writing) network.writes++;
  try {
    const response = await send(url, options, form);
    const data = await json(response);
    if (!response.ok || object(data).ok === false) {
      throw failure(response, object(data));
    }
    return data as T;
  } finally { if (writing) { network.writes--; network.lastWrite = Date.now(); } }
}
export function request<T = unknown>(url: string, options: RequestOptions = {}): Promise<T> { return execute<T>(url, options); }
export function upload<T>(url: string, file: File): Promise<T> {
  if (!/\.xlsx$/i.test(file.name) || file.size > 20 * 1024 * 1024) return Promise.reject(new ApiError('请选择不超过 20 MB 的 .xlsx 文件。'));
  const form = new FormData(); form.append('file', file);
  return execute<T>(url, { method: 'POST' }, form);
}
export async function download(url: string): Promise<void> {
  const response = await send(url, { timeout: 120000 });
  if (!response.ok) throw failure(response, object(await json(response)));
  const disposition = response.headers.get('Content-Disposition') || '';
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  let name = disposition.match(/filename="([^"]+)"/i)?.[1] || 'labflow.xlsx';
  if (encoded) { try { name = decodeURIComponent(encoded); } catch { /* Use the plain filename. */ } }
  const blobUrl = URL.createObjectURL(await response.blob());
  const link = document.createElement('a'); link.href = blobUrl;
  // eslint-disable-next-line no-control-regex -- stripping control characters from a server filename is intentional
  link.download = name.replace(/[\\/\x00-\x1f]/g, '_');
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}
export async function logout(): Promise<void> {
  const token = (await bootstrapSession()).csrf_token;
  const response = await fetchResponse('/logout', { method: 'POST', headers: { 'X-CSRF-Token': token } }, 30000);
  if (!response.ok) throw new ApiError('退出失败，请重试。', response.status);
  session = null; location.assign('/login');
}
