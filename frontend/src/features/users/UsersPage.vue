<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { request } from '../../api/client';
import { useAppState, refreshMeta, markDirty } from '../../app/state';
import { showError } from '../../app/dialogs';

interface User { id: number; username: string; display_name: string; permissions: string[]; active: number }
interface Terminal { id: number; name: string; kind: string; active: number }
interface UserMeta { capabilities: Record<string, string>; terminal: { id: number } | null; current_user: { id: number | null; permissions: string[]; virtual?: boolean } | null }
const app = useAppState();
const meta = ref<UserMeta | null>(null);
const users = ref<User[]>([]), terminals = ref<Terminal[]>([]);
const newUser = reactive({ username: '', display_name: '', password: '', permissions: [] as string[] });
const newTerminal = reactive({ name: '', password: '', kind: 'standard' });
const busy = ref(false), loaded = ref(false);
const dirtyUsers = reactive(new Set<number>()), dirtyTerminals = reactive(new Set<number>());
const passwordTarget = ref<{ kind: 'users' | 'terminals'; id: number; name: string } | null>(null);
const password = ref(''), passwordConfirm = ref(''), passwordInput = ref<HTMLInputElement>();
let returnFocus: HTMLElement | null = null;
const capabilities = computed(() => Object.entries(meta.value?.capabilities ?? {}));
const can = (capability: string) => Boolean(meta.value?.current_user?.permissions.includes(capability));
const canGrant = (capability: string) => can(capability);
watch(() => [newUser, newTerminal, [...dirtyUsers], [...dirtyTerminals], password.value, passwordConfirm.value], () => {
  markDirty('users', Boolean(newUser.username || newUser.display_name || newUser.password || newUser.permissions.length || newTerminal.name || newTerminal.password || newTerminal.kind !== 'standard' || dirtyUsers.size || dirtyTerminals.size || password.value || passwordConfirm.value));
}, { deep: true, flush: 'sync' });
let loadSequence = 0;
onBeforeUnmount(() => { ++loadSequence; markDirty('users', false); });
async function load() {
  const sequence = ++loadSequence;
  try {
    const fresh = await request<UserMeta>('/api/meta');
    if (sequence !== loadSequence) return;
    const [userRows, terminalRows] = await Promise.all([
      fresh.current_user?.permissions.includes('user_manage') ? request<User[]>('/api/users') : Promise.resolve([]),
      fresh.current_user?.permissions.includes('terminal_manage') ? request<Terminal[]>('/api/terminals') : Promise.resolve([]),
    ]);
    if (sequence !== loadSequence) return;
    meta.value = fresh;
    users.value = userRows.map(row => dirtyUsers.has(row.id) ? { ...row, ...(users.value.find(u => u.id === row.id) ?? row), active: row.active } : row);
    terminals.value = terminalRows.map(row => dirtyTerminals.has(row.id) ? { ...row, ...(terminals.value.find(t => t.id === row.id) ?? row), active: row.active } : row);
    loaded.value = true;
  } catch (error) { showError(error); }
}
watch(() => [app.page, app.refreshRevision], () => { if (app.page === 'users' && !busy.value) void load(); }, { immediate: true });
async function mutate(url: string, method: string, body: unknown, success: () => void) {
  if (busy.value) return;
  ++loadSequence;
  busy.value = true;
  try {
    await request(url, { method, body }); success();
    try { await refreshMeta(); } catch (error) { showError(error); }
    await load();
  }
  catch (error) { showError(error); }
  finally {
    busy.value = false;
    await nextTick();
    if (!passwordTarget.value && returnFocus) { returnFocus.focus(); returnFocus = null; }
  }
}
function addUser() {
  if (newUser.password.length < 6) { showError('新密码至少需要 6 个字符'); return; }
  void mutate('/api/users', 'POST', { ...newUser, username: newUser.username.trim(), display_name: newUser.display_name.trim() }, () => Object.assign(newUser, { username: '', display_name: '', password: '', permissions: [] }));
}
function addTerminal() {
  if (newTerminal.password.length < 6) { showError('新密码至少需要 6 个字符'); return; }
  void mutate('/api/terminals', 'POST', { ...newTerminal, name: newTerminal.name.trim() }, () => Object.assign(newTerminal, { name: '', password: '', kind: 'standard' }));
}
function saveUser(user: User) { void mutate(`/api/users/${user.id}`, 'PUT', { username: user.username.trim(), display_name: user.display_name.trim(), permissions: user.permissions }, () => dirtyUsers.delete(user.id)); }
function saveTerminal(terminal: Terminal) { void mutate(`/api/terminals/${terminal.id}`, 'PUT', { name: terminal.name.trim(), kind: terminal.kind }, () => dirtyTerminals.delete(terminal.id)); }
function toggleActive(kind: 'users' | 'terminals', row: User | Terminal) {
  if (busy.value || row.active && kind === 'users' && row.id === meta.value?.current_user?.id || kind === 'terminals' && row.id === meta.value?.terminal?.id) return;
  if (row.active && !window.confirm('确定停用这个账号或终端？停用后将无法继续登录使用。')) return;
  void mutate(`/api/${kind}/${row.id}`, 'PUT', { active: !row.active }, () => {});
}
async function openPassword(kind: 'users' | 'terminals', id: number, name: string) {
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  passwordTarget.value = { kind, id, name }; password.value = ''; passwordConfirm.value = '';
  await nextTick(); passwordInput.value?.focus();
}
function closePassword() { if (busy.value || (password.value || passwordConfirm.value) && !window.confirm('放弃尚未保存的新密码？')) return; passwordTarget.value = null; password.value = ''; passwordConfirm.value = ''; returnFocus?.focus(); returnFocus = null; }
function resetPassword() {
  const target = passwordTarget.value;
  if (!target) return;
  if (password.value.length < 6) { showError('新密码至少需要 6 个字符'); return; }
  if (password.value !== passwordConfirm.value) { showError('两次输入的密码不一致'); return; }
  void mutate(`/api/${target.kind}/${target.id}`, 'PUT', { password: password.value }, () => {
    passwordTarget.value = null; password.value = ''; passwordConfirm.value = '';
  });
}
function trapFocus(event: KeyboardEvent) {
  const root = event.currentTarget;
  if (event.key !== 'Tab' || !(root instanceof HTMLElement)) return;
  const controls = [...root.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)')];
  const first = controls[0], last = controls[controls.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
}
</script>

<template>
  <section id="page-users" class="page" :class="{ active: app.page === 'users' }" :aria-busy="busy" :inert="busy || !loaded">
    <div class="grid2">
      <div v-show="!loaded || can('user_manage')" class="panel admin-only">
        <h2>用户与能力</h2>
        <div class="row"><input id="u-username" v-model="newUser.username" placeholder="登录用户名" minlength="3"><input id="u-display-name" v-model="newUser.display_name" placeholder="姓名">
          <input id="u-password" v-model="newUser.password" type="password" placeholder="初始密码" autocomplete="new-password" minlength="6">
          <button id="u-add" :disabled="busy" @click="addUser">添加用户</button></div>
        <p class="hint">新用户只能继承当前操作者已有的能力，不能获得更高权限。</p>
        <div id="u-new-permissions" class="permission-picker"><label v-for="[value, label] in capabilities" :key="value"><input v-model="newUser.permissions" type="checkbox" class="u-new-permission" :value="value" :disabled="!canGrant(value)"> {{ label }}</label></div>
        <div class="table-shell"><table id="u-table" class="data-grid"><thead><tr><th>用户名</th><th>姓名</th><th>能力</th><th>状态</th><th>操作</th></tr></thead><tbody>
          <tr v-for="user in users" :key="user.id" :data-uid="user.id" @input="dirtyUsers.add(user.id)" @change="dirtyUsers.add(user.id)">
            <td><input v-model="user.username" class="u-username"></td><td><input v-model="user.display_name" class="u-display"></td>
            <td><div class="permission-picker compact"><label v-for="[value, label] in capabilities" :key="value"><input v-model="user.permissions" type="checkbox" class="u-permission" :value="value" :disabled="!canGrant(value)"> {{ label }}</label></div></td>
            <td>{{ user.active ? '启用' : '停用' }}</td><td><button class="u-save" type="button" :disabled="busy" @click="saveUser(user)">保存</button>
              <button class="u-toggle" type="button" :disabled="busy || (user.active === 1 && user.id === meta?.current_user?.id)" @click="toggleActive('users', user)">{{ user.active ? '停用' : '启用' }}</button>
              <button class="u-password" type="button" :disabled="busy" @click="openPassword('users', user.id, user.username)">重置密码</button></td>
          </tr>
        </tbody></table></div>
      </div>
      <div v-show="!loaded || can('terminal_manage')" class="panel admin-only">
        <h2>终端管理</h2>
          <div class="row"><input id="terminal-name" v-model="newTerminal.name" placeholder="终端名称"><input id="terminal-password" v-model="newTerminal.password" type="password" placeholder="终端密码" autocomplete="new-password" minlength="6">
          <select id="terminal-kind" v-model="newTerminal.kind"><option value="standard">普通终端</option><option value="admin">管理终端</option></select><button id="terminal-add" type="button" :disabled="busy" @click="addTerminal">添加终端</button></div>
        <p class="hint">这里只维护需要终端密码的普通终端和管理终端。个人入口默认对所有启用用户开放，不需要添加终端。当前终端不能停用或切换类型；系统必须至少保留一个启用的管理终端。</p>
        <div class="table-shell"><table id="terminal-table" class="data-grid"><thead><tr><th>终端名称</th><th>类型</th><th>登录页顺序</th><th>状态</th><th>操作</th></tr></thead><tbody>
          <tr v-for="(terminal, index) in terminals" :key="terminal.id" :data-terminal-id="terminal.id" @input="dirtyTerminals.add(terminal.id)" @change="dirtyTerminals.add(terminal.id)">
            <td><input v-model="terminal.name" class="terminal-row-name"></td><td><select v-model="terminal.kind" class="terminal-row-kind" :disabled="terminal.id === meta?.terminal?.id"><option value="standard">普通终端</option><option value="admin">管理终端</option></select></td>
            <td><button class="terminal-move" data-direction="up" type="button" :disabled="busy || index === 0" @click="mutate(`/api/terminals/${terminal.id}/order`, 'PUT', { direction: 'up' }, () => {})">上移</button><button class="terminal-move" data-direction="down" type="button" :disabled="busy || index === terminals.length - 1" @click="mutate(`/api/terminals/${terminal.id}/order`, 'PUT', { direction: 'down' }, () => {})">下移</button></td>
            <td>{{ terminal.active ? '启用' : '停用' }}{{ terminal.id === meta?.terminal?.id ? ' · 当前' : '' }}</td><td><button class="terminal-save" type="button" :disabled="busy" @click="saveTerminal(terminal)">保存</button><button class="terminal-toggle" type="button" :disabled="busy || terminal.id === meta?.terminal?.id" @click="toggleActive('terminals', terminal)">{{ terminal.active ? '停用' : '启用' }}</button><button class="terminal-reset" type="button" :disabled="busy" @click="openPassword('terminals', terminal.id, terminal.name)">重置密码</button></td>
          </tr>
        </tbody></table></div>
      </div>
    </div>
    <Teleport to="body"><div v-if="passwordTarget" class="dialog-backdrop" @mousedown.self="closePassword" @keydown.esc.stop.prevent="closePassword" @keydown="trapFocus">
      <section class="error-dialog" role="dialog" aria-modal="true" aria-labelledby="password-reset-title" :inert="busy"><button class="dialog-x" type="button" aria-label="关闭" :disabled="busy" @click="closePassword">×</button><h2 id="password-reset-title">重置密码：{{ passwordTarget.name }}</h2>
        <form @submit.prevent="resetPassword"><label>新密码（至少 6 个字符）<input ref="passwordInput" v-model="password" type="password" minlength="6" required autocomplete="new-password"></label><label>确认新密码<input v-model="passwordConfirm" type="password" minlength="6" required autocomplete="new-password"></label><div class="dialog-actions"><button type="button" :disabled="busy" @click="closePassword">取消</button><button class="primary" type="submit" :disabled="busy">保存密码</button></div></form>
      </section>
    </div></Teleport>
  </section>
</template>
