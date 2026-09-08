import { reactive } from 'vue';
import { vi } from 'vitest';
import type { EntryMeta } from '../types';
export interface Options { method?: string; body?: unknown; signal?: AbortSignal }
export const requestMock = vi.fn<(url: string, options?: Options) => Promise<unknown>>();
export async function request<T>(url: string, options?: Options): Promise<T> { return await requestMock(url, options) as T; }
export const download = vi.fn<(url: string) => Promise<void>>().mockResolvedValue(undefined);
export const uploadMock = vi.fn<(url: string, file: File) => Promise<unknown>>();
export async function upload<T>(url: string, file: File): Promise<T> { return await uploadMock(url, file) as T; }
export const showError = vi.fn<(error: unknown, title?: string) => void>();
export const markDirty = vi.fn<(key: string, dirty: boolean) => void>();
export const refreshMeta = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);
export const app = reactive<{ meta: EntryMeta | null; currentSampleId: number | null; page: 'data' | 'instrument' | 'intake' | 'results'; tags: string[]; refreshRevision: number }>({ meta: null, currentSampleId: null, page: 'data', tags: [], refreshRevision: 0 });
export function useAppState() { return app; }
export function navigate(page: typeof app.page, sampleId?: number) { app.page = page; if (sampleId !== undefined) app.currentSampleId = sampleId; }
