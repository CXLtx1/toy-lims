// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { createApp, nextTick, reactive, type App, type Component } from 'vue'
import IntakePage from './IntakePage.vue'
import SettingsPage from '../settings/SettingsPage.vue'
import UsersPage from '../users/UsersPage.vue'
import { emptyMeta } from '../settings/types'
import type { SampleDetail } from './domain'

const mocks = vi.hoisted(() => ({ request: vi.fn(), markDirty: vi.fn(), navigate: vi.fn(), refreshMeta: vi.fn(), showError: vi.fn() }))
const state = reactive({ page: 'intake', currentSampleId: null as number | null, tags: [] as string[], refreshRevision: 0, meta: null })
vi.mock('../../api/client', () => ({ request: mocks.request, download: vi.fn(), upload: vi.fn() }))
vi.mock('../../app/state', () => ({ useAppState: () => state, markDirty: mocks.markDirty, navigate: mocks.navigate, refreshMeta: mocks.refreshMeta }))
vi.mock('../../app/dialogs', () => ({ showError: mocks.showError }))

let app: App | undefined
const meta = () => ({ ...emptyMeta(), special_methods: [], sample_statuses: {}, sample_transitions: {}, allowed_status_targets: [], categories: [] })
async function settle() { for (let i = 0; i < 12; i++) await nextTick() }
async function mount(component: Component) {
  const root = document.createElement('div')
  document.body.append(root)
  app = createApp(component)
  app.mount(root)
  await settle()
}
function input(selector: string, value: string) {
  const element = document.querySelector<HTMLInputElement>(selector)!
  element.value = value
  element.dispatchEvent(new Event('input', { bubbles: true }))
}
function click(selector: string) { document.querySelector<HTMLButtonElement>(selector)!.click() }
beforeEach(() => {
  vi.resetAllMocks()
  Object.assign(state, { page: 'intake', currentSampleId: null, tags: [], refreshRevision: 0 })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})
afterEach(() => { app?.unmount(); app = undefined; document.body.replaceChildren(); vi.restoreAllMocks() })

test('a delayed intake detail response cannot navigate back after leaving the page', async () => {
  let resolve!: (detail: SampleDetail) => void
  const pending = new Promise<SampleDetail>(done => { resolve = done })
  mocks.request.mockImplementation((url: string) => url === '/api/meta' ? Promise.resolve(meta()) : url === '/api/samples/7' ? pending : Promise.resolve({ rows: [], total: 0 }))
  state.currentSampleId = 7
  await mount(IntakePage)
  expect(mocks.request).toHaveBeenCalledWith('/api/samples/7')
  state.page = 'settings'
  await nextTick()
  resolve({ sample: { id: 7, name: 'sample', workflow_type: 'special', tags: [] }, preps: [], items: [] } as unknown as SampleDetail)
  await settle()
  expect(mocks.navigate).not.toHaveBeenCalled()
  expect(document.querySelector('#sample-editor-panel')?.hasAttribute('hidden')).toBe(true)
  expect(mocks.showError).not.toHaveBeenCalled()
})

test('settings metadata initialization is clean and failed refresh does not make a successful create retryable', async () => {
  state.page = 'settings'
  let finish!: () => void
  mocks.request.mockImplementation((url: string) => url === '/api/meta' ? Promise.resolve(meta()) : new Promise<void>(resolve => { finish = resolve }))
  await mount(SettingsPage)
  expect(mocks.markDirty.mock.calls.filter(([key]) => key === 'settings').at(-1)).toEqual(['settings', false])
  input('#a-name', 'Co')
  click('#a-add')
  await nextTick()
  expect(document.querySelector('#page-settings')?.hasAttribute('inert')).toBe(true)
  mocks.refreshMeta.mockRejectedValueOnce(new Error('refresh failed'))
  finish()
  await settle()
  expect(document.querySelector<HTMLInputElement>('#a-name')?.value).toBe('')
  expect(mocks.request.mock.calls.filter(([url]) => url === '/api/analytes')).toHaveLength(1)
  expect(mocks.markDirty.mock.calls.filter(([key]) => key === 'settings').at(-1)).toEqual(['settings', false])
})

test('dirty order names survive refresh while the server default flag updates', async () => {
  state.page = 'settings'
  let isDefault = 0
  mocks.request.mockImplementation(() => Promise.resolve({ ...meta(), result_order_templates: [{ id: 1, name: 'original', items: ['Cu'], is_default: isDefault }] }))
  await mount(SettingsPage)
  input('.rot-row-name', 'draft')
  isDefault = 1
  state.refreshRevision++
  await settle()
  expect(document.querySelector<HTMLInputElement>('.rot-row-name')?.value).toBe('draft')
  expect(document.querySelector<HTMLInputElement>('.rot-default')?.checked).toBe(true)
})

test('disabling a dirty user updates the status without losing the unsaved name', async () => {
  state.page = 'users'
  let active = 1
  mocks.request.mockImplementation((url: string, options?: { method?: string; body?: unknown }) => {
    if (options?.method === 'PUT') { active = 0; return Promise.resolve({ ok: true }) }
    if (url === '/api/meta') return Promise.resolve({ capabilities: { user_manage: 'Manage' }, terminal: null, current_user: { id: 1, permissions: ['user_manage'] } })
    return Promise.resolve([{ id: 2, username: 'original', display_name: 'Name', permissions: [], active }])
  })
  await mount(UsersPage)
  input('.u-username', 'draft')
  click('.u-toggle')
  await settle()
  expect(window.confirm).toHaveBeenCalled()
  expect(document.querySelector<HTMLInputElement>('.u-username')?.value).toBe('draft')
  expect(document.querySelector('.u-toggle')?.textContent).toBe('启用')
  expect(mocks.request).toHaveBeenCalledWith('/api/users/2', { method: 'PUT', body: { active: false } })
  expect(mocks.markDirty).toHaveBeenLastCalledWith('users', true)
})
