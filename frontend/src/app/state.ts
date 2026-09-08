import { reactive, watch } from 'vue';
import { network, request } from '../api/client';
import { pages, type CurrentSample, type Meta, type PageName } from '../api/types';

export const pageLabels: Record<PageName, string> = { intake: '来样', data: '数据', instrument: '仪器', results: '结果', report: '报告', audit: '审计', users: '用户', settings: '设置', about: '关于' };
const state = reactive({ meta: null as Meta | null, currentSampleId: null as number | null, currentSample: null as CurrentSample | null,
  page: 'intake' as PageName, tags: [] as string[], refreshRevision: 0, pendingRevision: 0,
  resultIntent: null as { sampleId: number; kind: 'manual'; nonce: number } | null,
  dirty: new Set<string>(), ready: false });
let metaGeneration = 0;
export function useAppState() { return state; }
export function markDirty(key: string, dirty: boolean): void { if (dirty) state.dirty.add(key); else state.dirty.delete(key); }
export function hasUnsavedChanges(): boolean { return state.dirty.size > 0 || network.writes > 0; }
export async function refreshMeta(): Promise<void> {
  const generation = ++metaGeneration;
  const data = await request<Meta>('/api/meta');
  if (!data || data.sample_statuses === null || Array.isArray(data.sample_statuses) || typeof data.sample_statuses !== 'object' || !Array.isArray(data.sample_tags)) throw new Error('元数据响应格式错误。');
  if (generation === metaGeneration) state.meta = data;
}
export function navigate(page: PageName, sampleId?: number | null): void {
  if (state.page === page && (sampleId === undefined || sampleId === state.currentSampleId)) return;
  // Every visited page stays mounted: switching tabs retains its draft, but an
  // in-flight write must complete before another context can change authorization.
  if (network.writes) return;
  if (state.dirty.size && !window.confirm('仍有未保存的修改。切换后草稿会保留，关闭或刷新网页会丢失。是否继续切换？')) return;
  state.page = page;
  if (sampleId !== undefined) state.currentSampleId = sampleId;
  updateUrl();
}
export function navigateToManualResult(sampleId: number): void {
  navigate('results', sampleId);
  if (state.page === 'results' && state.currentSampleId === sampleId) {
    state.resultIntent = { sampleId, kind: 'manual', nonce: (state.resultIntent?.nonce ?? 0) + 1 };
  }
}
function updateUrl(): void {
  const url = new URL(location.href);
  url.searchParams.set('page', state.page);
  if (state.currentSampleId !== null) url.searchParams.set('sample', String(state.currentSampleId)); else url.searchParams.delete('sample');
  url.searchParams.delete('tag'); state.tags.forEach(tag => url.searchParams.append('tag', tag));
  history.replaceState(null, '', url);
}
export function initializeNavigation(): () => void {
  const params = new URL(location.href).searchParams;
  const page = params.get('page');
  if (pages.includes(page as PageName)) state.page = page as PageName;
  const sample = Number(params.get('sample'));
  if (Number.isSafeInteger(sample) && sample > 0) state.currentSampleId = sample;
  state.tags = [...new Set(params.getAll('tag').map(tag => tag.trim()).filter(Boolean))];
  return watch(() => state.tags.slice(), updateUrl, { deep: true });
}
