/* toy-lims 前端逻辑 */
let META = null;   // analytes, instruments, dilutions, methods, templates
let SAMPLES = [];
let EDITING_SAMPLE_ID = null;
let SAMPLE_QUERY = "";
let SAMPLE_PAGE = 0;
let SAMPLE_TOTAL = 0;
let SAMPLE_TYPE = "solid";
let SHOW_CANCELLED = false;
let SAMPLE_PAGE_SIZE = 50;
let FORM_INSTRUMENT_MAP = {};
let CAPTURED_INSTRUMENT_MAP = {};
let FORM_REPORT_ORDER = [];
let TEMPLATE_EDIT_ID = null;
let TEMPLATE_INSTRUMENT_MAP = {};
let PREP_COMBINATION_EDIT_ID = null;
let CURRENT_SAMPLE = null;
let SITE_STATUS = null;
let CONTEXT_ENTITY = null;
let LAST_READING_TARGET = null;
let SERVER_TIME_AT_SYNC = null;
let CLIENT_TIME_AT_SYNC = 0;
let ERROR_DIALOG_RETURN_FOCUS = null;
let AUTHORIZATION_PROMISE = null;
let AUTHORIZATION_RETURN_FOCUS = null;
let AUTHORIZATION_PURPOSE = null;
let APPLIED_COLLAB_REVISION = null;
let COLLAB_POLLING = false;
let COLLAB_REFRESHING = false;
let INSTRUMENT_AUTO_REFRESHING = false;
let XRF_SCAN_PAGE = 1;
let XRF_SCAN_QUERY = "";
let XRF_SCAN_KIND = "all";
let XRF_SCAN_MATCH = "all";
let XRF_SCAN_SEARCH_TIMER = null;
let XRF_DATA_SEARCH_TIMER = null;
let XRF_ASSIGN_SEARCH_TIMER = null;
let XRF_ASSIGN_ANALYSIS_ID = null;
let INSTRUMENT_LOAD_SEQUENCE = 0;
let XRF_SCAN_PAGE_SIZE = 25;
const XRF_EXPANDED = new Set();
let AUDIT_RECORDS = [];
let RESULT_SAMPLES = [];
let RESULT_PAGE = 0;
let RESULT_PAGE_SIZE = 50;
let RESULT_TOTAL = 0;
const RESULT_EXPANDED = new Set();
const RESULT_EXPANDED_ORDER = [];
const RESULT_SELECTED = new Set();
const RESULT_DETAILS = new Map();
const RESULT_MANUAL_EDITING = new Set();
const RESULT_DETAIL_REQUESTS = new Map();
let resultDetailSequence = 0;
let REPORT_SAMPLES = [];
let REPORT_PAGE = 0;
let REPORT_PAGE_SIZE = 20;
let REPORT_TOTAL = 0;
const REPORT_KNOWN = new Map();
const REPORT_SELECTED = new Set();
let REPORT_FOCUS_ID = null;
let REPORT_QUEUE_SEQUENCE = 0;

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

function closeErrorDialog() {
  const backdrop = $("#error-dialog-backdrop");
  if (!backdrop || backdrop.hidden) return;
  backdrop.hidden = true;
  const focusTarget = ERROR_DIALOG_RETURN_FOCUS;
  ERROR_DIALOG_RETURN_FOCUS = null;
  if (focusTarget instanceof HTMLElement && document.contains(focusTarget)) focusTarget.focus();
}

function showError(message, title = "操作未完成") {
  const text = String(message || "发生了未知错误，请稍后重试。");
  const backdrop = $("#error-dialog-backdrop");
  if (!backdrop) return;
  ERROR_DIALOG_RETURN_FOCUS = document.activeElement;
  $("#error-dialog-title").textContent = title;
  $("#error-dialog-message").textContent = text;
  backdrop.hidden = false;
  closeSiteContextMenu?.();
  requestAnimationFrame(() => $("#error-dialog-close")?.focus());
}

$("#error-dialog-close").onclick = closeErrorDialog;
$("#error-dialog-x").onclick = closeErrorDialog;
$("#error-dialog-backdrop").addEventListener("mousedown", (event) => {
  if (event.target === event.currentTarget) closeErrorDialog();
});
window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || $("#error-dialog-backdrop").hidden) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  closeErrorDialog();
}, true);
window.addEventListener("unhandledrejection", (event) => {
  const message = event.reason?.message || String(event.reason || "页面操作失败");
  showError(message, "页面操作失败");
});

function authorizationIsActive(user = META?.current_user) {
  return Boolean(user?.is_authorized ?? user?.authorized ?? META?.authorization?.active ?? META?.authorized);
}

function renderAccessIdentity() {
  if (!META) return;
  const terminal = META.terminal || META.current_terminal || {};
  const user = META.current_user;
  const terminalKind = terminal.kind || META.terminal_kind || "standard";
  const authorized = authorizationIsActive(user);
  const terminalName = terminal.name || META.terminal_name || "当前终端";
  const terminalKindLabels = { admin: "管理终端", personal: "个人终端", standard: "标准终端" };
  $("#current-terminal").textContent = `${terminalName} · ${terminalKindLabels[terminalKind] || terminalKind}`;
  $("#current-terminal").dataset.kind = terminalKind;
  $("#current-user").textContent = (authorized || terminalKind !== "standard") && user
    ? `${user.display_name || user.username} · ${terminalKind === "admin" ? "终端管理身份" : terminalKind === "personal" ? "个人登录" : "用户已授权"}`
    : "浏览模式 · 未授权";
  $("#clear-authorization").hidden = terminalKind !== "standard" || !authorized;

  // Terminal browsing stays unrestricted; the backend applies the authorized user's role to every mutation.
  $('.tab[data-page="settings"]').hidden = false;
  $("#s-new").hidden = false;
  $("#r-save-meta").hidden = false;
}

function closeAuthorizationDialog(authorized) {
  const dialog = $("#authorization-dialog");
  dialog.hidden = true;
  document.body.classList.remove("authorization-open");
  $("#authorization-password").value = "";
  $("#authorization-error").textContent = "";
  const focusTarget = AUTHORIZATION_RETURN_FOCUS;
  AUTHORIZATION_RETURN_FOCUS = null;
  if (focusTarget instanceof HTMLElement && document.contains(focusTarget)) focusTarget.focus();
  const resolve = dialog._resolveAuthorization;
  dialog._resolveAuthorization = null;
  resolve?.(authorized);
}

async function submitAuthorization(event) {
  event.preventDefault();
  const password = $("#authorization-password").value;
  const errorBox = $("#authorization-error");
  const confirm = $("#authorization-confirm");
  errorBox.textContent = "";
  confirm.disabled = true;
  try {
    const response = await fetch("/api/authorize", {
      method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password, purpose: AUTHORIZATION_PURPOSE }),
    });
    let data = {};
    try { data = await response.json(); } catch (_) { data = {}; }
    if (response.status === 401) {
      errorBox.textContent = data.error || "密码错误，请重试。";
      $("#authorization-password").select();
      return;
    }
    if (!response.ok || !data.ok) {
      errorBox.textContent = data.error || `授权失败 (${response.status})`;
      return;
    }
    if (data.user) {
      META = { ...META, authorized: true, current_user: { ...data.user, is_authorized: true } };
      renderAccessIdentity();
    }
    closeAuthorizationDialog(true);
  } catch (error) {
    errorBox.textContent = "无法连接服务器：" + (error?.message || "网络连接失败");
  } finally {
    confirm.disabled = false;
  }
}

function requestAuthorization(explanation, purpose = null) {
  if (AUTHORIZATION_PROMISE) return AUTHORIZATION_PROMISE;
  const dialog = $("#authorization-dialog");
  AUTHORIZATION_RETURN_FOCUS = document.activeElement;
  AUTHORIZATION_PURPOSE = purpose;
  $("#authorization-explanation").textContent = explanation || "此操作会修改实验室数据。请输入用户密码，系统将核验该用户是否具备对应能力。";
  document.body.classList.add("authorization-open");
  dialog.hidden = false;
  AUTHORIZATION_PROMISE = new Promise((resolve) => { dialog._resolveAuthorization = resolve; })
    .finally(() => { AUTHORIZATION_PROMISE = null; AUTHORIZATION_PURPOSE = null; });
  requestAnimationFrame(() => $("#authorization-password").focus());
  return AUTHORIZATION_PROMISE;
}

async function api(url, method = "GET", body, canAuthorize = true) {
  let r;
  try {
    r = await fetch(url, {
      method,
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    const message = "无法连接服务器：" + (error?.message || "网络连接失败");
    showError(message, "服务器连接失败");
    return { ok: false, error: message };
  }
  const text = await r.text();
  let data, parseFailed = false;
  try { data = text ? JSON.parse(text) : {}; }
  catch (_) { parseFailed = true; data = { error: `服务器返回了无法解析的响应 (${r.status})` }; }
  if (r.status === 401) { location.href = "/login"; return { ok: false, error: "请重新登录" }; }
  if (r.status === 503 && data.error?.includes("初始化")) { location.href = "/setup"; return data; }
  if (r.status === 428 && data.code === "authorization_required" && canAuthorize) {
    if (!await requestAuthorization(data.error)) return { ok: false, error: "已取消授权", cancelled: true };
    return api(url, method, body, false);
  }
  if (!r.ok || parseFailed) {
    const error = data.error || `请求失败 (${r.status})`;
    showError(error, r.status === 403 ? "权限不足" : "操作未完成");
    return { ok: false, error };
  }
  return data;
}

async function uploadApi(url, formData, canAuthorize = true) {
  let r;
  try {
    r = await fetch(url, { method: "POST", cache: "no-store", body: formData });
  } catch (error) {
    const message = "无法连接服务器：" + (error?.message || "网络连接失败");
    showError(message, "服务器连接失败");
    return { ok: false, error: message };
  }
  const text = await r.text();
  let data, parseFailed = false;
  try { data = text ? JSON.parse(text) : {}; }
  catch (_) { parseFailed = true; data = { error: `服务器返回了无法解析的响应 (${r.status})` }; }
  if (r.status === 401) { location.href = "/login"; return { ok: false, error: "请重新登录" }; }
  if (r.status === 428 && data.code === "authorization_required" && canAuthorize) {
    if (!await requestAuthorization(data.error)) return { ok: false, error: "已取消授权", cancelled: true };
    return uploadApi(url, formData, false);
  }
  if (!r.ok || parseFailed) {
    const error = data.error || `请求失败 (${r.status})`;
    showError(error, r.status === 403 ? "权限不足" : "操作未完成");
    return { ok: false, error };
  }
  return data;
}

async function downloadApi(url) {
  let response;
  try {
    response = await fetch(url, { cache: "no-store" });
  } catch (error) {
    showError("无法连接服务器：" + (error?.message || "网络连接失败"), "服务器连接失败");
    return false;
  }
  if (response.status === 401) { location.href = "/login"; return false; }
  if (!response.ok) {
    let message = `下载失败 (${response.status})`;
    try { message = (await response.json()).error || message; } catch (_) { /* keep status message */ }
    showError(message, response.status === 403 ? "权限不足" : "下载未完成");
    return false;
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const quoted = disposition.match(/filename="([^"]+)"/i)?.[1];
  let filename = "toy-lims.xlsx";
  try { filename = decodeURIComponent(encoded || quoted || filename); } catch (_) { filename = quoted || filename; }
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  return true;
}

function selectedExcelFile(input) {
  const file = input.files[0];
  if (!file) return null;
  if (!file.name.toLowerCase().endsWith(".xlsx")) {
    showError("请选择 .xlsx 格式的业务工作簿。", "文件格式不支持");
    input.value = "";
    return null;
  }
  if (file.size > 20 * 1024 * 1024) {
    showError("文件超过 20 MB，无法上传。", "文件过大");
    input.value = "";
    return null;
  }
  return file;
}

async function uploadExcel(url, file) {
  const form = new FormData();
  form.append("file", file);
  return uploadApi(url, form);
}

const STATUS_ACTION_LABELS = {
  received: "登记样品", queued: "制样完成", measuring: "开始测量",
  completed: "确认测量完成", reviewed: "审核确认", cancelled: "作废样品",
};
const STATUS_ORDER = ["received", "queued", "measuring", "partially_done", "completed", "reviewed"];
const STATUS_STAGE = {
  received: 0, queued: 1, measuring: 2, partially_done: 2,
  completed: 3, reviewed: 4,
};
const STATUS_STAGE_LABELS = ["未制样", "已制样 / 未测量", "测量中", "待审核", "已审核"];

function isStatusRollback(current, target) {
  return STATUS_ORDER.indexOf(target) < STATUS_ORDER.indexOf(current);
}

function statusTransitionLabel(current, target) {
  return isStatusRollback(current, target)
    ? `退回${META.sample_statuses[target]}`
    : (STATUS_ACTION_LABELS[target] || META.sample_statuses[target]);
}

function confirmStatusRollback(current, target) {
  if (!isStatusRollback(current, target)) return true;
  const currentLabel = META.sample_statuses[current] || current;
  const targetLabel = META.sample_statuses[target] || target;
  return confirm(`确定将样品从“${currentLabel}”退回到“${targetLabel}”吗？\n\n本次退回会写入审计历史；现有样品和检测记录不会自动删除。`);
}

function statusActorHtml(sample) {
  const history = Array.isArray(sample?.status_history) && sample.status_history.length
    ? sample.status_history
    : (sample?.status_operator ? [{ action: sample.status_action, operator: sample.status_operator, at: sample.status_changed_at }] : []);
  if (!history.length) return "";
  const compactLabels = {
    received: "登记", queued: "制样", measuring: "开始测量", completed: "测量完成",
    reviewed: "审核", cancelled: "作废",
  };
  return `<span class="status-history">${history.map((item) => {
    const action = compactLabels[item.action] || STATUS_ACTION_LABELS[item.action] || item.action || "状态";
    const label = item.rollback
      ? (item.action === "completed" ? "撤回审核" : `退回${META?.sample_statuses?.[item.action] || action}`)
      : action;
    const reviewRollback = item.rollback && item.action === "completed";
    const title = [item.at || "时间未知", item.reason].filter(Boolean).join(" · ");
    return `<span class="status-history-item ${item.rollback ? "rollback" : ""} ${reviewRollback ? "review-rollback" : ""}" title="${esc(title)}"><b>${esc(label)}</b><em>${esc(item.operator || "系统")}</em></span>`;
  }).join("")}</span>`;
}

function sampleStageTrackHtml(status) {
  if (status === "cancelled") return "";
  const stage = STATUS_STAGE[status] ?? 0;
  return `<span class="sample-stage-track stage-${stage}" style="--stage:${stage}" title="${esc(STATUS_STAGE_LABELS[stage])}" aria-label="${esc(STATUS_STAGE_LABELS[stage])}">
    ${STATUS_STAGE_LABELS.map((_, index) => `<i class="${index <= stage ? "passed" : ""}"></i>`).join("")}</span>`;
}

const AUDIT_ACTION_LABELS = {
  setup: "初始化系统", login: "终端登录", logout: "终端退出",
  heartbeat: "仪器状态心跳", instrument_login: "标准客户端用户登录",
  create: "新建", update: "修改", delete: "删除", disable: "停用", restore: "恢复",
  reorder: "调整顺序", capabilities: "修改仪器能力", status_change: "修改状态",
  cancel: "作废", result_update: "修改结果", report_use: "修改结果参与计算",
  report_meta: "修改报告信息", report_order: "修改报告顺序", report_print: "修改报告打印项",
  report_override: "旧版手工修改报告",
  result_override: "特权补录结果",
  instrument_import: "导入仪器结果", instrument_reading: "仪器录入读数",
  instrument_submit: "仪器批量提交",
  xrf_assign: "关联 XRF 扫描",
  xrf_unassign: "解绑 XRF 扫描",
  xrf_report_use: "修改 XRF 结果参与计算", special_result: "修改专项检测数据",
  excel_plan_create: "从 Excel 新建样品", excel_plan_overwrite: "从 Excel 覆盖样品方案",
  excel_data_overwrite: "从 Excel 覆盖检测数据",
};

const AUDIT_ENTITY_LABELS = {
  sample: "样品", sample_analyte: "检测任务", reading: "读数", result: "结果",
  session: "登录会话", instrument_client: "仪器客户端", standard_submission: "标准客户端提交",
  xrf_analysis: "XRF 扫描", xrf_value: "XRF 结果", uq_analysis: "UniQuant 分析", analyte: "分析项目",
  instrument: "仪器", dilution: "稀释方式", method: "分析方法", template: "样品模板",
  volume_preset: "定容容量", preparation_combination: "溶样组合",
  report_profile: "报告版式", result_order_template: "结果顺序模板", user: "用户", terminal: "终端",
};

function renderServerClock() {
  if (!SERVER_TIME_AT_SYNC) return;
  const now = new Date(SERVER_TIME_AT_SYNC.getTime() + Date.now() - CLIENT_TIME_AT_SYNC);
  const date = now.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" })
    .replaceAll("/", "-");
  const time = now.toLocaleTimeString("zh-CN", { hour12: false });
  const clock = $("#server-clock");
  clock.dateTime = now.toISOString();
  clock.textContent = `服务器 ${date} ${time}`;
}

function renderLatestChange() {
  const box = $("#ctx-last-change");
  const separator = $("#ctx-change-separator");
  if (!box || !separator) return;
  const visible = Boolean(CONTEXT_ENTITY);
  box.hidden = !visible;
  separator.hidden = !visible;
  if (!visible) return;
  const change = SITE_STATUS?.latest_change;
  const title = `${CONTEXT_ENTITY.label || "所选对象"} · 上一次修改`;
  if (change === undefined) {
    box.innerHTML = `<b>${esc(title)}</b><small>正在读取……</small>`;
    return;
  }
  if (!change) {
    box.innerHTML = `<b>${esc(title)}</b><small>尚无修改记录</small>`;
    return;
  }
  const user = change.display_name || change.username || "system";
  const action = AUDIT_ACTION_LABELS[change.action] || change.action || "修改";
  const changes = change.changes || [];
  const details = changes.length
    ? `<div class="context-change-list">${changes.slice(0, 6).map((item) =>
        `<div><span>${esc(item.label || item.field)}</span><del>${esc(item.before)}</del><i>→</i><ins>${esc(item.after)}</ins></div>`
      ).join("")}${changes.length > 6 ? `<small>另有 ${changes.length - 6} 项变化</small>` : ""}</div>`
    : "";
  box.innerHTML = `<b>${esc(title)}</b><small>${esc(change.created_at || "时间未知")} · ${esc(user)}</small>` +
    `<small>${esc(action)}</small>${details}`;
}

async function refreshSiteStatus(entity = null) {
  try {
    const query = entity
      ? `?entity_type=${encodeURIComponent(entity.type)}&entity_id=${encodeURIComponent(entity.id)}` : "";
    const response = await fetch("/api/site-status" + query, { cache: "no-store" });
    if (response.status === 401) { location.href = "/login"; return; }
    if (!response.ok) return;
    const status = await response.json();
    if (!status.server_time) return;
    SITE_STATUS = { ...SITE_STATUS, server_time: status.server_time, revision: +(status.revision || 0) };
    SERVER_TIME_AT_SYNC = new Date(status.server_time);
    CLIENT_TIME_AT_SYNC = Date.now();
    renderServerClock();
    if (entity && CONTEXT_ENTITY && entity.type === CONTEXT_ENTITY.type && String(entity.id) === String(CONTEXT_ENTITY.id)) {
      SITE_STATUS.latest_change = status.latest_change;
      renderLatestChange();
    }
    return status;
  } catch (_) {
    // 时钟同步失败不打断业务操作；下一次定时同步会自动重试。
  }
  return null;
}

function activePageName() {
  return $(".tab.active")?.dataset.page || "intake";
}

function collaborationRefreshCanRun() {
  if (document.hidden || !$("#authorization-dialog")?.hidden || !$("#error-dialog-backdrop")?.hidden) return false;
  const page = $(".page.active");
  const focused = document.activeElement;
  return !(page && focused && page.contains(focused) &&
    focused.matches("input, textarea, select, [contenteditable='true']"));
}

async function refreshActiveCollaborationPage() {
  const page = activePageName();
  if (page === "intake") {
    await loadSamples();
  } else if (page === "data") {
    await loadSamples();
    if ($("#d-sample").value) await loadDataEntry();
  } else if (page === "results") {
    await loadResultsPage();
  } else if (page === "report") {
    await loadReportPrintPage();
  } else if (page === "instrument") {
    await autoRefreshInstrumentPage();
  } else if (page === "audit") {
    await loadAudit();
  } else if (page === "users") {
    await loadUsers();
    await loadTerminals();
  } else if (page === "settings") {
    await loadMeta();
  }
}

async function pollCollaborationChanges() {
  if (COLLAB_POLLING || document.hidden) return;
  COLLAB_POLLING = true;
  try {
    const status = await refreshSiteStatus();
    if (!status) return;
    const revision = +(status.revision || 0);
    if (APPLIED_COLLAB_REVISION === null || revision < APPLIED_COLLAB_REVISION) {
      APPLIED_COLLAB_REVISION = revision;
      return;
    }
    if (revision === APPLIED_COLLAB_REVISION || COLLAB_REFRESHING || !collaborationRefreshCanRun()) return;
    COLLAB_REFRESHING = true;
    try {
      await refreshActiveCollaborationPage();
      APPLIED_COLLAB_REVISION = revision;
    } finally {
      COLLAB_REFRESHING = false;
    }
  } finally {
    COLLAB_POLLING = false;
  }
}

async function autoRefreshInstrumentPage() {
  if (INSTRUMENT_AUTO_REFRESHING || document.hidden || !$("#page-instrument").classList.contains("active")) return;
  if (document.activeElement?.closest?.(".xrf-monitor-controls")) return;
  if (!$("#xrf-assign-dialog").hidden) return;
  INSTRUMENT_AUTO_REFRESHING = true;
  try { await loadInstrumentPage(); }
  finally { INSTRUMENT_AUTO_REFRESHING = false; }
}

setInterval(renderServerClock, 1000);
setInterval(pollCollaborationChanges, 600);
setInterval(autoRefreshInstrumentPage, 2000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    pollCollaborationChanges();
    autoRefreshInstrumentPage();
  }
});

/* ---------------- 初始化 ---------------- */
async function loadMeta() {
  META = await api("/api/meta");
  if (!META || META.ok === false) return false;
  renderAccessIdentity();
  renderIntakeForm();
  renderSettings();
  loadUsers(); loadTerminals();
  return true;
}

$("#authorization-form").addEventListener("submit", submitAuthorization);
$("#authorization-cancel").onclick = () => closeAuthorizationDialog(false);
$("#clear-authorization").onclick = async () => {
  const result = await api("/api/authorization/clear", "POST", {});
  if (result?.ok === false) return;
  await loadMeta();
};
window.addEventListener("keydown", (event) => {
  const dialog = $("#authorization-dialog");
  if (dialog.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopImmediatePropagation();
    closeAuthorizationDialog(false);
  }
  if (event.key === "Tab") {
    const controls = [...dialog.querySelectorAll("input, button:not(:disabled)")];
    const edge = event.shiftKey ? controls[0] : controls.at(-1);
    if (document.activeElement === edge) {
      event.preventDefault();
      (event.shiftKey ? controls.at(-1) : controls[0]).focus();
    }
  }
}, true);
async function loadSamples(query = SAMPLE_QUERY, page = SAMPLE_PAGE) {
  SAMPLE_QUERY = query;
  SAMPLE_PAGE = Math.max(0, page);
  const result = await api(`/api/samples?paged=1&limit=${SAMPLE_PAGE_SIZE}&offset=${SAMPLE_PAGE * SAMPLE_PAGE_SIZE}&type=${SAMPLE_TYPE}&include_cancelled=${SHOW_CANCELLED ? 1 : 0}&q=${encodeURIComponent(query)}`);
  if (!result || result.ok === false) return;
  SAMPLES = result.rows;
  SAMPLE_TOTAL = result.total;
  const lastPage = Math.max(0, Math.ceil(SAMPLE_TOTAL / SAMPLE_PAGE_SIZE) - 1);
  if (SAMPLE_PAGE > lastPage) return loadSamples(query, lastPage);
  renderSampleList();
  renderSamplePager();
  renderSampleSelects();
}

/* ---------------- 页签 ---------------- */
const URL_PAGES = ["intake", "data", "instrument", "results", "report", "audit", "users", "settings", "about"];

function syncPageUrl(page, sampleId = null) {
  try {
    const url = new URL(window.location.href);
    if (page) url.searchParams.set("page", page);
    if (sampleId) url.searchParams.set("sample", sampleId);
    history.replaceState(null, "", url);
  } catch (_) { /* URL 同步失败不影响页面 */ }
}

async function activatePage(page) {
  $$(".tab").forEach((x) => x.classList.toggle("active", x.dataset.page === page));
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + page));
  syncPageUrl(page);
  if (page === "intake") {
    await loadSamples();
  } else if (page === "data") {
    await loadSamples();
    await loadDataEntry();
  } else if (page === "results") {
    await loadResultsPage();
  } else if (page === "report") {
    await loadReportPrintPage();
  } else if (page === "instrument") {
    await loadInstrumentPage();
  } else if (page === "audit") {
    await loadAudit();
  } else if (page === "users") {
    await loadUsers();
    await loadTerminals();
  }
}

$$(".tab").forEach((button) => button.onclick = () => activatePage(button.dataset.page));

function setCurrentSample(sample) {
  if (!sample?.id) return;
  CURRENT_SAMPLE = {
    id: +sample.id, name: sample.name,
    is_liquid: sample.is_liquid === undefined ? CURRENT_SAMPLE?.is_liquid : +sample.is_liquid,
    workflow_type: sample.workflow_type ?? CURRENT_SAMPLE?.workflow_type ?? "regular",
    lims_no: sample.lims_no ?? CURRENT_SAMPLE?.lims_no,
    status: sample.status ?? CURRENT_SAMPLE?.status,
  };
  for (const prefix of ["d", "r"]) {
    $("#" + prefix + "-sample").value = CURRENT_SAMPLE.id;
    $("#" + prefix + "-sample-search").value = `#${CURRENT_SAMPLE.id} ${CURRENT_SAMPLE.name}`;
  }
  $("#current-sample").hidden = false;
  $("#current-sample").textContent = `${CURRENT_SAMPLE.lims_no || "#" + CURRENT_SAMPLE.id} ${CURRENT_SAMPLE.name}`;
  $$(".sample-card").forEach((card) =>
    card.classList.toggle("current", +card.dataset.sid === CURRENT_SAMPLE.id));
}

function clearCurrentSample() {
  CURRENT_SAMPLE = null;
  $("#current-sample").hidden = true;
  for (const prefix of ["d", "r"]) {
    $("#" + prefix + "-sample").value = "";
    $("#" + prefix + "-sample-search").value = "";
  }
  $("#d-info").textContent = "";
  $("#d-status-actions").innerHTML = "";
  $("#d-table tbody").innerHTML = "";
  $("#d-msg").textContent = "";
  $("#d-grid-status").textContent = "";
  $$(".sample-card").forEach((card) => card.classList.remove("current"));
}

async function openSamplePage(sid, page) {
  let sample = SAMPLES.find((item) => item.id === +sid);
  if (!sample) {
    const detail = await api(`/api/samples/${sid}`);
    sample = detail.sample;
  }
  if (!sample) return;
  setCurrentSample(sample);
  if (page === "results") RESULT_EXPANDED.add(+sid);
  if (page === "report" && sample.status === "reviewed") {
    REPORT_SELECTED.add(+sid);
    REPORT_FOCUS_ID = +sid;
  }
  syncPageUrl(page, sample.id);
  await activatePage(page);
  if (page === "intake") await editSample(sample.id);
}

/* ---------------- 项目文本自动识别 ---------------- */
// 输入 "Ag, cu, ph, TOC" 之类，大小写不敏感地匹配已登记的分析项目
function parseAnalyteText(text) {
  const byName = new Map(META.analytes.map((a) => [a.name.toLowerCase(), a]));
  const tokens = text.split(/[,，、;；\s]+/).filter(Boolean);
  const matched = [], unmatched = [];
  const seen = new Set();
  for (const t of tokens) {
    const a = byName.get(t.toLowerCase());
    if (a) {
      if (!seen.has(a.id)) { seen.add(a.id); matched.push(a); }
    } else unmatched.push(t);
  }
  return { matched, unmatched };
}

function renderChips() {
  const { matched, unmatched } = parseAnalyteText($("#s-analyte-text").value);
  $("#s-chips").innerHTML =
    matched.map((a) => `<span class="tag ok">${a.name}</span>`).join("") +
    unmatched.map((t) => `<span class="tag bad">${t}?</span>`).join("");
}

function renderXrfChips() {
  const { matched, unmatched } = parseAnalyteText($("#s-xrf-text").value);
  $("#s-xrf-chips").innerHTML =
    matched.map((item) => `<span class="tag ok">${esc(item.name)}</span>`).join("") +
    unmatched.map((name) => `<span class="tag">${esc(name)}</span>`).join("");
}

function dilutionOptions(sel) {
  sel.innerHTML = META.dilutions.filter((d) => d.active).map((d) =>
    `<option value="${d.id}">${d.label}</option>`).join("");
}

function dilutionChoices(currentId = null) {
  return META.dilutions.filter((d) => d.active || d.id === currentId);
}

function prepDilutionIds(prep = {}) {
  if (Array.isArray(prep.dilution_ids)) return prep.dilution_ids.map(Number).filter(Boolean);
  if (Array.isArray(prep.dilution_steps)) return prep.dilution_steps.map(Number).filter(Boolean);
  if (typeof prep.dilution_steps === "string") {
    const parsed = templateJson(prep.dilution_steps, []);
    if (Array.isArray(parsed) && parsed.length) return parsed.map(Number).filter(Boolean);
  }
  return prep.dilution_id ? [+prep.dilution_id] : [];
}

function dilutionStepHtml(currentId, selectClass) {
  const choices = dilutionChoices(+currentId || null);
  return `<span class="dilution-step"><select class="${selectClass}">${choices.map((d) =>
    `<option value="${d.id}" ${d.id === +currentId ? "selected" : ""}>${esc(d.label)}${d.active ? "" : "（停用）"}</option>`).join("")}</select>` +
    `<button class="dilution-remove" type="button" title="删除这一级">×</button></span>`;
}

function dilutionChainHtml(prep, selectClass) {
  const fallback = META.dilutions.find((item) => item.active)?.id;
  const ids = prepDilutionIds(prep);
  if (!ids.length && fallback) ids.push(fallback);
  return `<div class="dilution-chain" data-select-class="${selectClass}">${ids.map((id) =>
    dilutionStepHtml(id, selectClass)).join("")}<button class="dilution-add" type="button" title="追加一级稀释">+</button></div>`;
}

function wireDilutionChain(chain, onChange = () => {}) {
  const selectClass = chain.dataset.selectClass;
  const wire = () => {
    chain.querySelectorAll("select").forEach((select) => select.onchange = onChange);
    chain.querySelectorAll(".dilution-remove").forEach((button) => {
      button.disabled = chain.querySelectorAll(".dilution-step").length <= 1;
      button.onclick = () => {
        if (chain.querySelectorAll(".dilution-step").length <= 1) return;
        button.closest(".dilution-step").remove(); wire(); onChange();
      };
    });
  };
  chain.querySelector(".dilution-add").onclick = () => {
    const current = chain.querySelector("select:last-of-type")?.value || META.dilutions.find((item) => item.active)?.id;
    if (!current || chain.querySelectorAll(".dilution-step").length >= 8) return;
    chain.querySelector(".dilution-add").insertAdjacentHTML("beforebegin", dilutionStepHtml(current, selectClass));
    wire(); onChange();
  };
  wire();
}

function dilutionIdsFrom(root, selectClass) {
  return [...root.querySelectorAll(`.${selectClass}`)].map((select) => +select.value).filter(Boolean);
}

function volumePresetChoices(currentValue = null) {
  const parsed = Number(currentValue);
  const target = Number.isFinite(parsed) && parsed > 0 ? parsed : +(META.default_volume_ml || 250);
  const choices = (META.volume_presets || []).filter((item) => item.active || +item.volume_ml === target);
  if (!choices.some((item) => +item.volume_ml === target))
    choices.push({ id: null, volume_ml: target, active: 0 });
  return { choices, target };
}

function volumePresetOptions(currentValue = null) {
  const { choices, target } = volumePresetChoices(currentValue);
  return choices.map((item) => `<option value="${item.volume_ml}" ${+item.volume_ml === target ? "selected" : ""}>${+item.volume_ml} mL${item.active ? "" : "（历史值）"}</option>`).join("");
}

function methodsFor(itype) {
  return META.methods.filter((method) => {
    const methodType = method.itype === "titration" ? "function" : (method.itype || "function");
    return methodType === itype;
  });
}

function renderXrfMethodSelect(select, currentId = null) {
  select.innerHTML = '<option value="">— 选择 XRF 方法 —</option>' + methodsFor("xrf").map((method) =>
    `<option value="${method.id}" ${method.id === +currentId ? "selected" : ""}>${esc(method.name)}</option>`).join("");
}

/* ---------------- 来样: 溶样方案 ---------------- */
function prepRowHtml(prep = {}) {
  return `<tr data-pid="${prep.id || ""}">
    <td class="grid-cell p-name-cell"><input class="p-name" value="${esc(prep.name || "")}" placeholder="留空自动生成"><small class="p-preview"></small></td>
    <td class="solid-only grid-cell"><input class="p-mass" type="number" step="0.0001" value="${prep.mass_g ?? ""}"></td>
    <td class="solid-only grid-cell"><select class="p-vol">${volumePresetOptions(prep.volume_ml)}</select></td>
    <td class="grid-cell">${dilutionChainHtml(prep, "p-dil")}</td>
    <td class="grid-cell p-routing-cell"><input class="p-analytes" type="hidden"><div class="p-routing"></div></td>
    <td class="grid-cell readonly prep-row-actions"><button class="copy-row" type="button" title="复制整行">⧉</button><button class="del" type="button" title="删除">×</button></td>
  </tr>`;
}

function isLiquid() {
  return $('input[name=s-liquid]:checked').value === "1";
}

function isSpecial() {
  return $('input[name=s-liquid]:checked').value === "special";
}

function syncSampleWorkflowForm() {
  const special = isSpecial();
  $("#s-special-config").hidden = !special;
  $("#s-regular-config").hidden = special;
  $("#s-xrf").closest("label").hidden = special;
  $("#s-template").closest("label").hidden = special;
}

function prepAnalyteIds(tr) {
  const overallIds = parseAnalyteText($("#s-analyte-text").value).matched.map((a) => a.id);
  const overallSet = new Set(overallIds);
  tr._includedAnalytes ||= new Set(overallIds);
  if (tr._usesAllAnalytes) overallIds.forEach((id) => tr._includedAnalytes.add(id));
  [...tr._includedAnalytes].forEach((id) => { if (!overallSet.has(id)) tr._includedAnalytes.delete(id); });
  return overallIds.filter((id) => tr._includedAnalytes.has(id));
}

function syncPrepAnalytes(tr) {
  tr.querySelector(".p-analytes").value = prepAnalyteIds(tr).map((id) =>
    META.analytes.find((item) => item.id === id)?.name).filter(Boolean).join(", ");
}

function routingChipHtml(tr, aid) {
  const analyte = META.analytes.find((item) => item.id === aid);
  const setting = tr._instrumentMap?.[String(aid)] || {};
  const instrument = META.instruments.find((item) => item.id === +setting.instrument_id);
  const selected = tr._selectedAnalytes?.has(aid) ? " selected" : "";
  const method = instrument?.itype === "function" ? `<select class="route-method" data-aid="${aid}" title="公式方法">
    <option value="">选择方法</option>${methodsFor("function").map((item) =>
      `<option value="${item.id}" ${item.id === +setting.method_id ? "selected" : ""}>${esc(item.name)}</option>`).join("")}</select>` : "";
  return `<span class="route-chip-wrap"><span class="route-chip${selected}" role="button" tabindex="0" draggable="true" data-aid="${aid}">${esc(analyte?.name || aid)}</span>${method}</span>`;
}

function renderPrepRouting(tr) {
  const overallIds = parseAnalyteText($("#s-analyte-text").value).matched.map((a) => a.id);
  const ids = prepAnalyteIds(tr);
  tr._instrumentMap ||= {};
  tr._selectedAnalytes ||= new Set();
  const instruments = META.instruments.filter((item) => item.itype !== "xrf" &&
    overallIds.some((aid) => item.analytes.includes(aid)));
  const validInstrumentIds = new Set(instruments.map((item) => item.id));
  const grouped = new Map(instruments.map((item) => [item.id, []]));
  const assigned = new Set();
  ids.forEach((aid) => {
    const iid = +tr._instrumentMap[String(aid)]?.instrument_id || 0;
    const instrument = META.instruments.find((item) => item.id === iid);
    if (validInstrumentIds.has(iid) && instrument?.analytes.includes(aid)) {
      grouped.get(iid).push(aid);
      assigned.add(aid);
    } else {
      delete tr._instrumentMap[String(aid)];
    }
  });
  tr._usesAllAnalytes = false;
  tr._includedAnalytes = assigned;
  const excluded = overallIds.filter((id) => !assigned.has(id));
  syncPrepAnalytes(tr);
  const zone = (kind, iid, label, aids) => `<div class="route-zone ${kind}" data-kind="${kind}" data-iid="${iid || 0}">
    <b>${esc(label)}</b><div class="route-items">${aids.map((aid) => routingChipHtml(tr, aid)).join("") || '<i>拖到这里</i>'}</div></div>`;
  tr.querySelector(".p-routing").innerHTML = `<div class="route-tools"><button type="button" class="route-select-all">全选标签</button><button type="button" class="route-clear-select">取消选择</button></div><div class="route-zones">` +
    zone("excluded", 0, "不测", excluded) +
    instruments.map((instrument) => zone("instrument", instrument.id, instrument.name, grouped.get(instrument.id))).join("") + "</div>";

  tr.querySelector(".route-select-all").onclick = () => {
    tr._selectedAnalytes = new Set(overallIds); renderPrepRouting(tr);
  };
  tr.querySelector(".route-clear-select").onclick = () => {
    tr._selectedAnalytes.clear(); renderPrepRouting(tr);
  };
  tr.querySelectorAll(".route-chip").forEach((chip) => {
    chip.onmousedown = (event) => event.stopPropagation();
    chip.onclick = (event) => {
      event.stopPropagation();
      const aid = +chip.dataset.aid;
      if (tr._selectedAnalytes.has(aid)) tr._selectedAnalytes.delete(aid);
      else tr._selectedAnalytes.add(aid);
      chip.classList.toggle("selected", tr._selectedAnalytes.has(aid));
    };
    chip.ondragstart = (event) => {
      event.stopPropagation();
      const aid = +chip.dataset.aid;
      if (!tr._selectedAnalytes.has(aid)) tr._selectedAnalytes = new Set([aid]);
      event.dataTransfer.setData("text/plain", String(aid));
      event.dataTransfer.effectAllowed = "move";
      chip.classList.add("dragging");
    };
    chip.ondragend = () => chip.classList.remove("dragging");
  });
  const moveToZone = (dropZone, dragged = 0) => {
    const moving = tr._selectedAnalytes.size ? [...tr._selectedAnalytes] : (dragged ? [dragged] : []);
    if (!moving.length) return;
    const iid = +dropZone.dataset.iid;
    const kind = dropZone.dataset.kind;
    const instrument = META.instruments.find((item) => item.id === iid);
    const rejected = [];
    moving.forEach((aid) => {
      if (kind === "excluded") {
        tr._usesAllAnalytes = false;
        tr._includedAnalytes.delete(aid);
        delete tr._instrumentMap[String(aid)];
      } else if (instrument.analytes.includes(aid)) {
        tr._includedAnalytes.add(aid);
        const old = tr._instrumentMap[String(aid)] || {};
        tr._instrumentMap[String(aid)] = {
          instrument_id: iid,
          method_id: old.instrument_id === iid ? (old.method_id || null) : null,
        };
      } else rejected.push(META.analytes.find((item) => item.id === aid)?.name || aid);
    });
    if (rejected.length) showError(`${instrument.name} 未配置测定：${rejected.join("、")}`, "无法分配仪器");
    tr._selectedAnalytes.clear();
    syncPrepAnalytes(tr);
    renderPrepRouting(tr);
    renderPrepPreviews();
  };
  tr.querySelectorAll(".route-zone").forEach((dropZone) => {
    dropZone.onmousedown = (event) => event.stopPropagation();
    dropZone.onclick = () => moveToZone(dropZone);
    dropZone.ondragover = (event) => {
      event.preventDefault(); event.dataTransfer.dropEffect = "move"; dropZone.classList.add("drag-over");
    };
    dropZone.ondragleave = () => dropZone.classList.remove("drag-over");
    dropZone.ondrop = (event) => {
      event.preventDefault(); dropZone.classList.remove("drag-over");
      const dragged = +event.dataTransfer.getData("text/plain");
      moveToZone(dropZone, dragged);
    };
  });
  tr.querySelectorAll(".route-method").forEach((select) => {
    select.onclick = (event) => event.stopPropagation();
    select.onchange = () => {
      const aid = select.dataset.aid;
      if (tr._instrumentMap[aid]) tr._instrumentMap[aid].method_id = +select.value || null;
    };
  });
}

function automaticPrepName(tr) {
  const base = $("#s-name").value.trim() || "?";
  const dilutionIds = dilutionIdsFrom(tr, "p-dil");
  const factor = dilutionIds.reduce((product, id) =>
    product * (META.dilutions.find((d) => d.id === id)?.factor ?? 1), 1);
  const factorMark = Number.isInteger(+factor) ? String(+factor) : String(+factor.toFixed(6)).replace(/0+$/, "");
  const ids = prepAnalyteIds(tr);
  const firstAnalyte = META.analytes.find((item) => item.id === ids[0])?.name || "";
  const automaticBase = firstAnalyte ? `${firstAnalyte}.${base}` : base;
  return `${automaticBase}${tr._legacyParallelIndex ? `-${tr._legacyParallelIndex}` : ""}*${factorMark}`;
}

// 自动名称随多级稀释总倍数变化；手工名称可完全覆盖默认值。
function rowPreps(tr) {
  const dilutionIds = dilutionIdsFrom(tr, "p-dil");
  const customName = tr._autoName ? "" : tr.querySelector(".p-name").value.trim();
  const ids = prepAnalyteIds(tr);
  return [{
    id: tr.dataset.pid ? +tr.dataset.pid : undefined,
    name: customName || automaticPrepName(tr),
    mass_g: isLiquid() ? null : parseFloat(tr.querySelector(".p-mass").value) || null,
    volume_ml: isLiquid() ? null : parseFloat(tr.querySelector(".p-vol").value) || null,
    dilution_id: dilutionIds[0] || null,
    dilution_ids: dilutionIds,
    analyte_ids: ids,
    instrument_map: structuredClone(tr._instrumentMap || {}),
  }];
}

function renderPrepPreviews() {
  $$("#p-table tbody tr").forEach((tr) => {
    const preps = rowPreps(tr);
    if (tr._autoName) tr.querySelector(".p-name").value = preps[0].name;
    tr.querySelector(".p-preview").innerHTML = "结果：" + preps.map((p) => esc(p.name)).join(" / ");
  });
}

function addPrepRow(prep = {}, afterRow = null) {
  if (afterRow) afterRow.insertAdjacentHTML("afterend", prepRowHtml(prep));
  else $("#p-table tbody").insertAdjacentHTML("beforeend", prepRowHtml(prep));
  const tr = afterRow ? afterRow.nextElementSibling : $("#p-table tbody tr:last-child");
  tr._instrumentMap = structuredClone(prep.instrument_map || FORM_INSTRUMENT_MAP || {});
  tr._legacyParallelIndex = prep._legacy_parallel_index || null;
  tr._selectedAnalytes = new Set();
  const overallIds = parseAnalyteText($("#s-analyte-text").value).matched.map((a) => a.id);
  const configuredIds = Array.isArray(prep.analyte_ids) ? prep.analyte_ids : [];
  tr._usesAllAnalytes = configuredIds.length === 0;
  tr._includedAnalytes = new Set(tr._usesAllAnalytes ? overallIds : configuredIds);
  syncPrepAnalytes(tr);
  tr._autoName = prep._auto_name ?? (!prep.name || prep.name === automaticPrepName(tr));
  wireDilutionChain(tr.querySelector(".dilution-chain"), renderPrepPreviews);
  tr.querySelector(".copy-row").onclick = () => {
    const copied = rowPreps(tr)[0];
    copied.name = tr.querySelector(".p-name").value;
    copied._auto_name = tr._autoName;
    delete copied.id;
    addPrepRow(copied, tr);
  };
  tr.querySelector(".del").onclick = () => { tr.remove(); renderPrepPreviews(); PREP_GRID.refresh(); };
  tr.querySelector(".p-name").addEventListener("input", (event) => {
    tr._autoName = !event.target.value.trim();
    renderPrepPreviews();
  });
  tr.querySelectorAll("input:not(.p-name),select").forEach((el) => el.addEventListener("input", () => {
    renderPrepPreviews();
  }));
  if (isLiquid()) tr.querySelectorAll(".solid-only").forEach((el) => el.style.display = "none");
  renderPrepPreviews();
  renderPrepRouting(tr);
  PREP_GRID.refresh();
}

function renderIntakeForm() {
  $("#s-template").innerHTML = '<option value="">— 不使用 —</option>' +
    META.templates.map((t) => `<option value="${t.id}">${t.name}</option>`).join("");
  const selectedCombination = +$("#p-combination").value || null;
  $("#p-combination").innerHTML = '<option value="">— 选择组合 —</option>' +
    (META.preparation_combinations || []).map((item) =>
      `<option value="${item.id}" ${item.id === selectedCombination ? "selected" : ""}>${esc(item.name)}（${item.rows.length}路）</option>`).join("");
  $("#p-combination-add").disabled = !(META.preparation_combinations || []).length;
  $("#s-categories").innerHTML = (META.categories || [])
    .map((c) => `<option value="${esc(c)}">`).join("");
  if (!$("#p-table tbody tr")) addPrepRow();
  const currentXrfMethod = +$("#s-xrf-method").value || null;
  renderXrfMethodSelect($("#s-xrf-method"), currentXrfMethod);
  $("#s-special-method").innerHTML = '<option value="">— 选择专项方法 —</option>' +
    (META.special_methods || []).map((method) => `<option value="${method.id}">${esc(method.name)} · ${esc(method.instrument)}</option>`).join("");
  syncSampleWorkflowForm();
  renderChips();
}

$("#p-add").onclick = () => addPrepRow();
$("#p-combination-add").onclick = () => {
  const combination = (META.preparation_combinations || []).find((item) => item.id === +$("#p-combination").value);
  if (!combination) return;
  combination.rows.forEach((prep) => addPrepRow({
    ...structuredClone(prep), analyte_ids: [], instrument_map: structuredClone(FORM_INSTRUMENT_MAP),
  }));
};
$("#s-analyte-text").addEventListener("input", () => {
  renderChips(); renderXrfChips(); renderPrepPreviews();
  $$("#p-table tbody tr").forEach(renderPrepRouting);
});
$("#s-name").addEventListener("input", renderPrepPreviews);
$("#s-xrf").addEventListener("change", (event) => {
  $("#s-xrf-config").hidden = !event.target.checked;
  if (event.target.checked && !$("#s-xrf-method").value && methodsFor("xrf").length === 1) {
    $("#s-xrf-method").value = methodsFor("xrf")[0].id;
  }
  renderXrfChips();
});
$("#s-xrf-text").addEventListener("input", renderXrfChips);

$$("input[name=s-liquid]").forEach((r) => r.onchange = () => {
  $$(".solid-only").forEach((el) => el.style.display = isLiquid() ? "none" : "");
  syncSampleWorkflowForm();
});

function templateJson(value, fallback) {
  try { return JSON.parse(value || "") || fallback; } catch (_) { return fallback; }
}

function getTemplatePreps(template) {
  const configured = templateJson(template.prep_config, []);
  if (configured.length) return configured.flatMap((prep) => {
    const count = Math.max(1, parseInt(prep.count) || 1);
    return Array.from({ length: count }, (_, index) => {
      const expanded = structuredClone(prep);
      delete expanded.count;
      if (count > 1) expanded._legacy_parallel_index = index + 1;
      return expanded;
    });
  });
  return [{ dilution_id: template.dilution_id, analyte_ids: [] }];
}

function collectTemplatePreps() {
  return $$("#p-table tbody tr").map((tr) => {
    return {
      mass_g: isLiquid() ? null : (parseFloat(tr.querySelector(".p-mass").value) || null),
      volume_ml: isLiquid() ? null : (parseFloat(tr.querySelector(".p-vol").value) || null),
      dilution_id: dilutionIdsFrom(tr, "p-dil")[0] || null,
      dilution_ids: dilutionIdsFrom(tr, "p-dil"),
      analyte_ids: tr._usesAllAnalytes ? [] : prepAnalyteIds(tr),
      instrument_map: structuredClone(tr._instrumentMap || {}),
    };
  });
}

function currentTemplatePayload(name) {
  const analyte_ids = parseAnalyteText($("#s-analyte-text").value).matched.map((a) => a.id);
  const preps = collectTemplatePreps();
  return {
    name,
    is_liquid: isLiquid() ? 1 : 0,
    xrf: $("#s-xrf").checked ? 1 : 0,
    dilution_id: preps[0]?.dilution_id || null,
    analyte_ids,
    preps,
    instrument_map: { ...CAPTURED_INSTRUMENT_MAP, ...FORM_INSTRUMENT_MAP,
      __xrf_report_items: $("#s-xrf-text").value.trim(),
      __xrf_method_id: +$("#s-xrf-method").value || null,
      __report_order: FORM_REPORT_ORDER.length ? FORM_REPORT_ORDER : analyte_ids },
  };
}

$("#s-apply-tpl").onclick = () => {
  const t = META.templates.find((x) => x.id === +$("#s-template").value);
  if (!t) return;
  const ids = JSON.parse(t.analyte_ids);
  $("#s-analyte-text").value = META.analytes
    .filter((a) => ids.includes(a.id)).map((a) => a.name).join(", ");
  renderChips();
  $('input[name=s-liquid][value="' + (t.is_liquid ? 1 : 0) + '"]').click();
  $("#s-xrf").checked = !!t.xrf;
  $("#s-xrf-config").hidden = !t.xrf;
  const templateInstrumentMap = templateJson(t.instrument_config, {});
  const templateXrfIds = templateInstrumentMap.__xrf_analyte_ids || ids;
  const templateXrfMethodId = templateInstrumentMap.__xrf_method_id || null;
  FORM_REPORT_ORDER = [...(templateInstrumentMap.__report_order || ids)];
  $("#s-xrf-text").value = t.xrf ? (templateInstrumentMap.__xrf_report_items ||
    META.analytes.filter((a) => templateXrfIds.includes(a.id)).map((a) => a.name).join(", ")) : "";
  renderXrfChips();
  delete templateInstrumentMap.__xrf_analyte_ids;
  delete templateInstrumentMap.__xrf_report_items;
  delete templateInstrumentMap.__xrf_method_id;
  delete templateInstrumentMap.__report_order;
  renderXrfMethodSelect($("#s-xrf-method"), templateXrfMethodId);
  FORM_INSTRUMENT_MAP = templateInstrumentMap;
  CAPTURED_INSTRUMENT_MAP = structuredClone(FORM_INSTRUMENT_MAP);
  $("#p-table tbody").innerHTML = "";
  getTemplatePreps(t).forEach((prep) => addPrepRow({
    ...prep, instrument_map: prep.instrument_map || FORM_INSTRUMENT_MAP,
  }));
  renderPrepPreviews();
};

$("#s-save-template").onclick = async () => {
  const suggested = $("#s-name").value.trim() || "新模板";
  const name = prompt("模板名称", suggested);
  if (!name?.trim()) return;
  const result = await api("/api/templates", "POST", currentTemplatePayload(name.trim()));
  await loadMeta();
  $("#s-template").value = result.id;
  $("#s-msg").textContent = "方案已保存为模板";
};

$("#s-submit").onclick = async () => {
  const name = $("#s-name").value.trim();
  if (!name) { showError("请填写来样序号。"); $("#s-name").focus(); return; }
  if (isSpecial()) {
    const specialMethodId = +$("#s-special-method").value || null;
    if (!specialMethodId) { showError("请选择专项检测方法。"); $("#s-special-method").focus(); return; }
    const payload = { name, category: $("#s-category").value.trim(), workflow_type: "special",
      special_method_id: specialMethodId };
    const result = await api(EDITING_SAMPLE_ID ? `/api/samples/${EDITING_SAMPLE_ID}` : "/api/samples",
      EDITING_SAMPLE_ID ? "PUT" : "POST", payload);
    if (result.ok) {
      setCurrentSample({ id: result.id, name, workflow_type: "special", is_liquid: 0,
        lims_no: result.lims_no, status: result.status });
      closeSampleEditor(); await loadSamples(); await loadMeta();
      await refreshSampleConsumers(result.id, name);
    }
    return;
  }
  const { matched } = parseAnalyteText($("#s-analyte-text").value);
  const preps = $$("#p-table tbody tr").flatMap((tr) => rowPreps(tr));
  const unassigned = [];
  const missingMethod = [];
  preps.forEach((prep) => prep.analyte_ids.forEach((aid) => {
    const setting = prep.instrument_map?.[String(aid)];
    const analyte = META.analytes.find((item) => item.id === aid)?.name || aid;
    const instrument = META.instruments.find((item) => item.id === +setting?.instrument_id);
    if (!instrument || !instrument.analytes.includes(aid)) unassigned.push(`${prep.name}：${analyte}`);
    else if (instrument.itype === "function" && !setting.method_id) missingMethod.push(`${prep.name}：${analyte}`);
  }));
  if (unassigned.length) {
    showError(`请先分配仪器：${unassigned.slice(0, 5).join("；")}${unassigned.length > 5 ? "…" : ""}`);
    return;
  }
  if (missingMethod.length) {
    showError(`请选择公式方法：${missingMethod.slice(0, 5).join("；")}`);
    return;
  }
  const xrf = $("#s-xrf").checked;
  const xrfMethodId = xrf ? (+$("#s-xrf-method").value || null) : null;
  if (!preps.some((p) => p.analyte_ids.length) && !xrf) {
    showError("溶样方案和分析项目至少需要有一项。"); return;
  }
  if (xrf && !xrfMethodId) {
    showError("请选择 XRF 方法。");
    $("#s-xrf-method").focus();
    return;
  }
  const payload = {
    name, category: $("#s-category").value.trim(),
    is_liquid: isLiquid() ? 1 : 0, xrf: xrf ? 1 : 0,
    preps, xrf_report_items: $("#s-xrf-text").value.trim(), xrf_method_id: xrfMethodId,
    instrument_map: FORM_INSTRUMENT_MAP,
    report_order: FORM_REPORT_ORDER,
  };
  const r = await api(EDITING_SAMPLE_ID ? `/api/samples/${EDITING_SAMPLE_ID}` : "/api/samples",
    EDITING_SAMPLE_ID ? "PUT" : "POST", payload);
  if (r.ok) {
    const message = EDITING_SAMPLE_ID ? `已保存 #${r.id}` : `已创建 #${r.id}`;
    setCurrentSample({ id: r.id, name, is_liquid: payload.is_liquid,
      lims_no: r.lims_no, status: r.status });
    closeSampleEditor();
    $("#s-workspace-msg").textContent = message;
    await loadSamples();
    await loadMeta();   // 刷新类型联想
    await refreshSampleConsumers(r.id, name);
  }
};

function resetSampleForm() {
  EDITING_SAMPLE_ID = null;
  FORM_INSTRUMENT_MAP = {};
  CAPTURED_INSTRUMENT_MAP = {};
  FORM_REPORT_ORDER = [];
  $("#s-form-title").textContent = "新建样品";
  $("#s-submit").textContent = "创建样品";
  $("#s-name").value = "";
  $("#s-category").value = "";
  $("#s-analyte-text").value = "";
  $("#s-xrf").checked = false;
  $("#s-xrf-config").hidden = true;
  $("#s-xrf-text").value = "";
  renderXrfMethodSelect($("#s-xrf-method"));
  const defaultType = SAMPLE_TYPE === "liquid" ? "1" : (SAMPLE_TYPE === "special" ? "special" : "0");
  $(`input[name=s-liquid][value="${defaultType}"]`).checked = true;
  $("#s-special-method").value = "";
  $("#p-table tbody").innerHTML = "";
  addPrepRow();
  renderChips();
  $$(".solid-only").forEach((el) => el.style.display = isLiquid() ? "none" : "");
  syncSampleWorkflowForm();
  $("#s-msg").textContent = "";
  $("#s-excel-plan-export").hidden = true;
  $("#s-excel-plan-import").hidden = true;
}

function showSampleEditor(card = null) {
  const panel = $("#sample-editor-panel");
  $$(".sample-card.expanded").forEach((item) => item.classList.remove("expanded"));
  if (card) card.classList.add("expanded");
  $("#s-card-list").before(panel);
  panel.closest(".sample-workspace").classList.add("editing");
  panel.hidden = false;
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function closeSampleEditor() {
  const panel = $("#sample-editor-panel");
  panel.hidden = true;
  panel.closest(".sample-workspace").classList.remove("editing");
  $$(".sample-card.expanded").forEach((item) => item.classList.remove("expanded"));
  $("#s-card-list").before(panel);
  EDITING_SAMPLE_ID = null;
}

function populateSampleForm(sample, preps, items, copy = false) {
  EDITING_SAMPLE_ID = copy ? null : sample.id;
  $("#s-form-title").textContent = copy ? `复制 #${sample.id} 为新样品` : `编辑 #${sample.id} ${sample.name}`;
  $("#s-submit").textContent = copy ? "创建副本" : "保存修改";
  $("#s-msg").textContent = "";
  $("#s-excel-plan-export").hidden = copy;
  $("#s-excel-plan-import").hidden = copy;
  $("#s-name").value = copy ? `${sample.name}-副本` : sample.name;
  $("#s-category").value = sample.category || "";
  if (sample.workflow_type === "special") {
    $('input[name=s-liquid][value="special"]').checked = true;
    $("#s-special-method").value = sample.special_method_id || "";
    $("#s-xrf").checked = false;
    $("#s-analyte-text").value = "";
    $("#p-table tbody").innerHTML = "";
    syncSampleWorkflowForm();
    return;
  }
  $("#s-xrf").checked = !!sample.xrf;
  $("#s-xrf-config").hidden = !sample.xrf;
  $(`input[name=s-liquid][value="${sample.is_liquid ? 1 : 0}"]`).checked = true;
  syncSampleWorkflowForm();
  const solutionIds = [...new Set(items.filter((item) => item.preparation_id).map((item) => item.analyte_id))];
  const xrfIds = [];
  const xrfMethodId = sample.xrf_method_id || null;
  CAPTURED_INSTRUMENT_MAP = {};
  items.filter((item) => item.preparation_id && item.instrument_id).forEach((item) => {
    const key = String(item.analyte_id);
    if (!CAPTURED_INSTRUMENT_MAP[key]) {
      CAPTURED_INSTRUMENT_MAP[key] = {
        instrument_id: item.instrument_id,
        method_id: item.method_id || null,
      };
    }
  });
  FORM_INSTRUMENT_MAP = copy ? structuredClone(CAPTURED_INSTRUMENT_MAP) : {};
  FORM_REPORT_ORDER = templateJson(sample.report_order, []);
  $("#s-analyte-text").value = solutionIds.map((id) => META.analytes.find((a) => a.id === id)?.name)
    .filter(Boolean).join(", ");
  $("#s-xrf-text").value = sample.xrf_report_items || "";
  renderXrfMethodSelect($("#s-xrf-method"), xrfMethodId);
  $("#p-table tbody").innerHTML = "";
  const solutionSet = new Set(solutionIds);
  preps.forEach((prep) => {
    const prepItems = items.filter((item) => item.preparation_id === prep.id);
    const prepIds = prepItems.map((item) => item.analyte_id);
    const usesAll = prepIds.length === solutionIds.length && prepIds.every((id) => solutionSet.has(id));
    const prepInstrumentMap = Object.fromEntries(prepItems.filter((item) => item.instrument_id).map((item) => [
      String(item.analyte_id), { instrument_id: item.instrument_id, method_id: item.method_id || null },
    ]));
    addPrepRow({
      ...prep,
      id: copy ? undefined : prep.id,
      name: copy ? "" : prep.name,
      analyte_ids: usesAll ? [] : prepIds,
      instrument_map: prepInstrumentMap,
    });
  });
  if (!preps.length) addPrepRow();
  renderChips();
  renderXrfChips();
  renderPrepPreviews();
  $$(".solid-only").forEach((el) => el.style.display = sample.is_liquid ? "none" : "");
}

async function editSample(sid) {
  const { sample, preps, items } = await api(`/api/samples/${sid}`);
  setCurrentSample(sample);
  populateSampleForm(sample, preps, items);
  showSampleEditor($(`.sample-card[data-sid="${sid}"]`));
}

async function duplicateSample(sid) {
  const { sample, preps, items } = await api(`/api/samples/${sid}`);
  populateSampleForm(sample, preps, items, true);
  showSampleEditor();
  $("#s-name").select();
}

$("#s-new").onclick = () => { resetSampleForm(); showSampleEditor(); $("#s-name").focus(); };
$("#s-excel-create").onclick = () => $("#s-excel-create-file").click();
$("#s-excel-create-file").onchange = async (event) => {
  const input = event.currentTarget;
  const file = selectedExcelFile(input);
  if (!file) return;
  if (!confirm(`确定根据“${file.name}”新建样品？系统会生成新的 LIMS 编号。`)) { input.value = ""; return; }
  const button = $("#s-excel-create");
  button.disabled = true;
  button.textContent = "正在创建…";
  try {
    const result = await uploadExcel("/api/excel/samples/create", file);
    if (!result.ok) return;
    await loadMeta();
    await loadSamples();
    $("#s-workspace-msg").textContent = result.message || `已创建 ${result.lims_no}`;
    await editSample(result.id);
    $("#s-msg").textContent = result.message || `已创建 ${result.lims_no}`;
  } finally {
    input.value = "";
    button.disabled = false;
    button.textContent = "从 Excel 新建";
  }
};
$("#s-excel-plan-export").onclick = () => {
  if (EDITING_SAMPLE_ID) downloadApi(`/api/excel/samples/${EDITING_SAMPLE_ID}/detail`);
};
$("#s-excel-plan-import").onclick = () => {
  if (EDITING_SAMPLE_ID) $("#s-excel-plan-file").click();
};
$("#s-excel-plan-file").onchange = async (event) => {
  const input = event.currentTarget;
  const file = selectedExcelFile(input);
  const sid = EDITING_SAMPLE_ID;
  if (!file || !sid) { input.value = ""; return; }
  if (!confirm(`确定用“${file.name}”覆盖当前样品方案？删除或改变的检测任务可能清除对应结果。`)) { input.value = ""; return; }
  const button = $("#s-excel-plan-import");
  button.disabled = true;
  button.textContent = "正在覆盖…";
  try {
    const result = await uploadExcel(`/api/excel/samples/${sid}/detail`, file);
    if (!result.ok) return;
    await loadMeta();
    await loadSamples();
    await editSample(sid);
    $("#s-msg").textContent = result.message || "样品方案已覆盖";
    await refreshSampleConsumers(sid, $("#s-name").value);
  } finally {
    input.value = "";
    button.disabled = false;
    button.textContent = "Excel 覆盖方案";
  }
};
$("#s-cancel-edit").onclick = closeSampleEditor;
document.addEventListener("keydown", (event) => {
  const panel = $("#sample-editor-panel");
  if (event.key !== "Escape" || panel.hidden) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  closeSampleEditor();
  $("#s-card-list").scrollIntoView({ behavior: "smooth", block: "start" });
}, true);

function renderSampleList() {
  const editor = $("#sample-editor-panel");
  const canEdit = true;
  const canData = true;
  if ($("#s-card-list").contains(editor)) $("#s-card-list").before(editor);
  $("#s-card-list").innerHTML = SAMPLES.map((s) => {
    const special = s.workflow_type === "special";
    const analytes = special ? [s.special_method_name].filter(Boolean) : (s.analyte_names || "").split(", ").filter(Boolean);
    const statusLabel = META.sample_statuses?.[s.status] || s.status || "未制样";
    const nextStatuses = (META.sample_transitions?.[s.status] || []).filter((status) =>
      !["cancelled", "reviewed"].includes(status) && META.allowed_status_targets.includes(status));
    const canCancel = (META.sample_transitions?.[s.status] || []).includes("cancelled") &&
      META.allowed_status_targets.includes("cancelled");
    return `<article class="sample-card status-${esc(s.status)} ${CURRENT_SAMPLE?.id === s.id ? "current" : ""} ${s.status === "cancelled" ? "cancelled" : ""}" data-sid="${s.id}">
      <div class="sample-card-summary" role="button" tabindex="0">
        <div class="sample-identity"><span class="sample-lims-no">${esc(s.lims_no || "#" + s.id)}</span><b>${esc(s.name)}</b>
          <span class="sample-category ${s.category ? "" : "empty"}" ${s.category ? "" : 'aria-hidden="true"'}>${esc(s.category || "占位")}</span>
          <span class="sample-kind ${special ? "special" : (s.is_liquid ? "liquid" : "solid")}">${special ? "其他" : (s.is_liquid ? "液体" : "固体")}</span>
          ${sampleStageTrackHtml(s.status)}
          <span class="sample-status ${esc(s.status)}">${esc(statusLabel)}</span></div>
        <div class="sample-analytes">${analytes.length
          ? analytes.map((name) => `<span>${esc(name)}</span>`).join("")
          : '<i>尚无待测项目</i>'}</div>
        <div class="sample-card-meta"><span>${special ? esc(s.special_instrument || "专项检测") : `${s.prep_count} 路溶样`}</span>${s.xrf ? "<span>XRF</span>" : ""}<time>${esc(s.created_at)}</time>${statusActorHtml(s)}</div>
        <div class="sample-card-actions">${s.status !== "cancelled" ? `${canData ? '<button class="enter-data" type="button">录数据</button>' : ""}${nextStatuses.map((status) => `<button class="status-next" data-status="${status}" type="button">${esc(statusTransitionLabel(s.status, status))}</button>`).join("")}${canEdit ? '<button class="duplicate" type="button" title="复制为新样品">复制新建</button>' : ""}${canCancel ? '<button class="del" type="button" title="作废样品">作废</button>' : ""}${canEdit ? '<button class="expand" type="button" title="展开全部内容">⌄</button>' : ""}` : ""}</div>
      </div>
    </article>`;
  }).join("");
  $$(".sample-card-summary").forEach((summary) => {
    summary.onclick = (event) => {
      if (canEdit && !event.target.closest("button")) editSample(+summary.closest(".sample-card").dataset.sid);
    };
    summary.onkeydown = (event) => {
      if (event.target.closest("button")) return;
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); summary.click(); }
    };
    const expand = summary.querySelector(".expand");
    if (expand) expand.onclick = () => editSample(+summary.closest(".sample-card").dataset.sid);
  });
  $$("#s-card-list .enter-data").forEach((b) => b.onclick = () =>
    openSamplePage(+b.closest(".sample-card").dataset.sid, "data"));
  $$("#s-card-list .duplicate").forEach((b) => b.onclick = () => duplicateSample(+b.closest(".sample-card").dataset.sid));
  $$("#s-card-list .status-next").forEach((b) => b.onclick = async () => {
    const sid = +b.closest(".sample-card").dataset.sid;
    const sample = SAMPLES.find((item) => item.id === sid);
    if (sample && !confirmStatusRollback(sample.status, b.dataset.status)) return;
    const result = await api(`/api/samples/${sid}/status`, "PUT", { status: b.dataset.status });
    if (!result.ok) return;
    await loadSamples();
  });
  $$("#s-card-list .del").forEach((b) => b.onclick = async () => {
    const reason = prompt("请输入作废原因。样品和历史结果将保留，但不能继续录入。", "登记错误");
    if (!reason?.trim()) return;
    const sid = b.closest(".sample-card").dataset.sid;
    const result = await api("/api/samples/" + sid, "DELETE", { reason: reason.trim() });
    if (!result.ok) return;
    if (EDITING_SAMPLE_ID === +sid) closeSampleEditor();
    if (CURRENT_SAMPLE?.id === +sid) {
      clearCurrentSample();
    }
    for (const prefix of ["d", "r"]) {
      if ($("#" + prefix + "-sample").value === sid) {
        $("#" + prefix + "-sample").value = "";
        $("#" + prefix + "-sample-search").value = "";
      }
    }
    loadSamples();
  });
  if (!editor.hidden) $("#s-card-list").before(editor);
}

function renderSamplePager() {
  const pages = Math.max(1, Math.ceil(SAMPLE_TOTAL / SAMPLE_PAGE_SIZE));
  const start = SAMPLE_TOTAL ? SAMPLE_PAGE * SAMPLE_PAGE_SIZE + 1 : 0;
  const end = Math.min((SAMPLE_PAGE + 1) * SAMPLE_PAGE_SIZE, SAMPLE_TOTAL);
  $("#s-list-count").textContent = `共 ${SAMPLE_TOTAL} 个，当前 ${start}-${end}`;
  $("#s-page-label").textContent = `${SAMPLE_PAGE + 1} / ${pages}`;
  $("#s-page-prev").disabled = SAMPLE_PAGE === 0;
  $("#s-page-next").disabled = SAMPLE_PAGE + 1 >= pages;
}

$("#s-page-prev").onclick = () => loadSamples(SAMPLE_QUERY, SAMPLE_PAGE - 1);
$("#s-page-next").onclick = () => loadSamples(SAMPLE_QUERY, SAMPLE_PAGE + 1);
$("#s-page-size").onchange = (event) => {
  SAMPLE_PAGE_SIZE = +event.currentTarget.value || 50;
  loadSamples(SAMPLE_QUERY, 0);
};

function renderSampleSelects() {
  if (CURRENT_SAMPLE) setCurrentSample(CURRENT_SAMPLE);
}

async function refreshSampleConsumers(sid, name) {
  const jobs = [];
  for (const prefix of ["d", "r"]) {
    if (+$("#" + prefix + "-sample").value !== +sid) continue;
    $("#" + prefix + "-sample-search").value = "#" + sid + " " + name;
    jobs.push(prefix === "d" ? loadDataEntry() : loadReport());
  }
  await Promise.all(jobs);
}

function selectSample(prefix, sample) {
  setCurrentSample(sample);
  $("#" + prefix + "-sample-search").closest(".sample-picker").querySelector(".sample-options").classList.remove("open");
  if (prefix === "d") loadDataEntry(); else loadReport();
}

function setupSamplePicker(prefix) {
  const input = $("#" + prefix + "-sample-search");
  const options = input.closest(".sample-picker").querySelector(".sample-options");
  let timer;
  const search = async (showAll = false) => {
    const q = showAll ? "" : input.value.replace(/^#\d+\s*/, "").trim();
    const found = await api(`/api/samples?limit=30&q=${encodeURIComponent(q)}`);
    options.innerHTML = found.length ? found.map((s) =>
      `<button type="button" data-id="${s.id}"><b>#${s.id}</b><span>${esc(s.name)}</span><small>${s.is_liquid ? "液体" : "固体"} · ${esc(s.created_at)}</small></button>`
    ).join("") : '<span class="empty">没有匹配的样品</span>';
    options.classList.add("open");
    options.querySelectorAll("button").forEach((button) => button.onmousedown = (event) => {
      event.preventDefault();
      selectSample(prefix, found.find((s) => s.id === +button.dataset.id));
    });
  };
  input.onfocus = () => { input.select(); search(true); };
  input.oninput = () => {
    const query = input.value;
    if ($("#" + prefix + "-sample").value || CURRENT_SAMPLE) {
      clearCurrentSample();
      input.value = query;
    }
    if (prefix === "d") loadDataEntry();
    clearTimeout(timer);
    timer = setTimeout(search, 180);
  };
  input.onkeydown = (event) => {
    const buttons = [...options.querySelectorAll("button")];
    let at = buttons.findIndex((b) => b.classList.contains("active"));
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (buttons.length) {
        buttons.forEach((b) => b.classList.remove("active"));
        at = event.key === "ArrowDown" ? Math.min(at + 1, buttons.length - 1) : Math.max(at - 1, 0);
        buttons[at].classList.add("active");
      }
    } else if (event.key === "Enter" && at >= 0) buttons[at].dispatchEvent(new MouseEvent("mousedown"));
    else if (event.key === "Escape") options.classList.remove("open");
  };
}

let sampleListTimer;
$("#s-list-search").oninput = (event) => {
  clearTimeout(sampleListTimer);
  sampleListTimer = setTimeout(() => loadSamples(event.target.value.trim(), 0), 180);
};
$("#s-show-cancelled").onchange = (event) => {
  SHOW_CANCELLED = event.target.checked;
  loadSamples(SAMPLE_QUERY, 0);
};

$("#s-excel-overview").onclick = () => {
  const dateFrom = $("#s-excel-date-from").value;
  const dateTo = $("#s-excel-date-to").value;
  if (!dateFrom || !dateTo) { showError("请选择总览的开始和结束日期。"); return; }
  if (dateFrom > dateTo) { showError("开始日期不能晚于结束日期。"); return; }
  const params = new URLSearchParams({
    date_from: dateFrom, date_to: dateTo, type: SAMPLE_TYPE, q: SAMPLE_QUERY,
    include_cancelled: SHOW_CANCELLED ? "1" : "0",
  });
  downloadApi(`/api/excel/samples-overview?${params}`);
};

$$("#s-type-filter button").forEach((button) => button.onclick = () => {
  $$("#s-type-filter button").forEach((item) => item.classList.toggle("active", item === button));
  SAMPLE_TYPE = button.dataset.type;
  if (CURRENT_SAMPLE && SAMPLE_TYPE !== "all" &&
      ((SAMPLE_TYPE === "special") !== (CURRENT_SAMPLE.workflow_type === "special") ||
       (SAMPLE_TYPE !== "special" && Boolean(CURRENT_SAMPLE.is_liquid) !== (SAMPLE_TYPE === "liquid")))) {
    clearCurrentSample();
  }
  loadSamples(SAMPLE_QUERY, 0);
});

async function editCurrentSample(prefix) {
  const sid = +$("#" + prefix + "-sample").value;
  if (!sid) return;
  await activatePage("intake");
  await editSample(sid);
}

$("#d-edit-sample").onclick = () => editCurrentSample("d");
$("#r-edit-sample").onclick = () => editCurrentSample("r");
$("#d-view-report").textContent = "查看结果";
$("#d-view-report").onclick = () => openSamplePage(+$("#d-sample").value, "results");
$("#d-manual-result").onclick = async () => {
  const sid = +$("#d-sample").value;
  if (!sid) return;
  await openSamplePage(sid, "results");
  const button = $("#r-manual-edit");
  if (button && !button.disabled) button.click();
};
$("#d-excel-export").onclick = () => {
  const sid = +$("#d-sample").value;
  if (sid) downloadApi(`/api/excel/samples/${sid}/data`);
};
$("#d-excel-import").onclick = () => {
  if ($("#d-sample").value) $("#d-excel-file").click();
};
$("#d-excel-file").onchange = async (event) => {
  const input = event.currentTarget;
  const file = selectedExcelFile(input);
  const sid = +$("#d-sample").value;
  if (!file || !sid) { input.value = ""; return; }
  if (!confirm(`确定用“${file.name}”覆盖工作簿中列出的检测任务数据？此操作会替换这些任务的现有读数。`)) { input.value = ""; return; }
  const button = $("#d-excel-import");
  button.disabled = true;
  button.textContent = "正在覆盖…";
  try {
    const result = await uploadExcel(`/api/excel/samples/${sid}/data`, file);
    if (!result.ok) return;
    await loadSamples();
    await loadDataEntry();
    if (+$("#r-sample").value === sid) await loadReport();
    $("#d-msg").textContent = result.message || "检测数据已覆盖";
  } finally {
    input.value = "";
    button.disabled = false;
    button.textContent = "Excel 覆盖数据";
  }
};
$("#instrument-refresh").onclick = loadInstrumentPage;
$("#xrf-scan-search").oninput = (event) => {
  clearTimeout(XRF_SCAN_SEARCH_TIMER);
  const query = event.currentTarget.value.trim();
  XRF_SCAN_SEARCH_TIMER = setTimeout(() => {
    XRF_SCAN_QUERY = query;
    XRF_SCAN_PAGE = 1;
    loadInstrumentPage();
  }, 250);
};
$("#xrf-scan-kind").onchange = (event) => {
  XRF_SCAN_KIND = event.currentTarget.value;
  XRF_SCAN_PAGE = 1;
  loadInstrumentPage();
};
$("#xrf-scan-match").onchange = (event) => {
  XRF_SCAN_MATCH = event.currentTarget.value;
  XRF_SCAN_PAGE = 1;
  loadInstrumentPage();
};
$("#xrf-scan-page-size").onchange = (event) => {
  XRF_SCAN_PAGE_SIZE = Math.max(10, Math.min(100, +event.currentTarget.value || 25));
  XRF_SCAN_PAGE = 1;
  loadInstrumentPage();
};
$("#xrf-page-prev").onclick = () => {
  if (XRF_SCAN_PAGE > 1) { XRF_SCAN_PAGE--; loadInstrumentPage(); }
};
$("#xrf-page-next").onclick = () => { XRF_SCAN_PAGE++; loadInstrumentPage(); };
$("#d-xrf-scan-search").onfocus = (event) => loadDataXrfCandidates(event.currentTarget.value.trim());
$("#d-xrf-scan-search").oninput = (event) => {
  clearTimeout(XRF_DATA_SEARCH_TIMER);
  const query = event.currentTarget.value.trim();
  XRF_DATA_SEARCH_TIMER = setTimeout(() => loadDataXrfCandidates(query), 220);
};
$("#xrf-assign-close").onclick = closeXrfAssignDialog;
$("#xrf-assign-dialog").onclick = (event) => {
  if (event.target === event.currentTarget) closeXrfAssignDialog();
};
$("#xrf-assign-sample-search").oninput = (event) => {
  clearTimeout(XRF_ASSIGN_SEARCH_TIMER);
  const query = event.currentTarget.value.trim();
  XRF_ASSIGN_SEARCH_TIMER = setTimeout(() => loadXrfAssignableSamples(query), 180);
};
$("#r-enter-data").onclick = () => openSamplePage(+$("#r-sample").value, "data");
$("#current-sample").onclick = async () => {
  if (!CURRENT_SAMPLE) return;
  await activatePage("intake");
  await editSample(CURRENT_SAMPLE.id);
};

/* ---------------- 数据录入（自动保存） ---------------- */
let reportRefreshTimer;
let dataLoadSequence = 0;
let reportLoadSequence = 0;
let REPORT_DATA = null;
let REPORT_BATCH_DATA = [];
function rowSaved(tr) {
  const st = tr.querySelector(".st");
  st.textContent = "✓ 已存 " + new Date().toLocaleTimeString();
  let hasValue = false;
  tr.querySelectorAll(".reading").forEach((reading) => {
    const readingHasValue = [...reading.querySelectorAll(".rd-raw, .rd-var")]
      .some((input) => input.value !== "");
    reading.classList.toggle("has-value", readingHasValue);
    hasValue ||= readingHasValue;
  });
  tr.classList.toggle("task-completed", hasValue);
  if ($("#r-sample").value === $("#d-sample").value) {
    clearTimeout(reportRefreshTimer);
    reportRefreshTimer = setTimeout(loadReport, 250);
  }
}

function readingHasStoredValue(reading) {
  if (!reading) return false;
  if (reading.raw !== null && reading.raw !== undefined && reading.raw !== "") return true;
  let extra = reading.extra;
  if (typeof extra === "string") {
    try { extra = JSON.parse(extra || "{}"); } catch (_) { extra = {}; }
  }
  return Boolean(extra && typeof extra === "object" && Object.keys(extra).length);
}

function methodFormulaVariables(formula) {
  const found = String(formula || "").match(/\b[A-Za-z_][A-Za-z0-9_]*\b/g) || [];
  return [...new Set(found)];
}

function titrationInputs(sa) {
  const constants = templateJson(sa.method_constants, {});
  const variables = methodFormulaVariables(sa.formula);
  const fixedValues = { ...constants };
  if (variables.includes("m") && sa.prep_mass != null) fixedValues.m = sa.prep_mass;
  if (variables.includes("v") && sa.prep_vol != null) fixedValues.v = sa.prep_vol;
  const fixed = Object.entries(fixedValues).map(([key, value]) => `${key}=${value}`).join(" ");
  return `<span class="method-label">${esc(sa.method_name || "未设置公式方法")}</span>
    ${fixed ? `<span class="hint">${esc(fixed)}</span>` : ""}
    ${sa.method_id ? `<button class="method-detail" type="button" data-method-id="${sa.method_id}">详情</button>` : ""}`;
}

function closeMethodDetail() {
  $("#method-detail-backdrop").hidden = true;
}

function openMethodDetail(methodId) {
  const method = META.methods.find((item) => item.id === +methodId);
  if (!method) return;
  const constants = templateJson(method.constants, {});
  $("#method-detail-title").textContent = method.name;
  $("#method-detail-formula").textContent = method.formula || "未设置";
  $("#method-detail-constants").textContent = Object.entries(constants)
    .map(([key, value]) => `${key}=${value}`).join("，") || "无";
  $("#method-detail-note").textContent = method.note?.trim() || "尚未填写滴定说明。";
  $("#method-detail-backdrop").hidden = false;
}

$("#method-detail-x").onclick = closeMethodDetail;
$("#method-detail-close").onclick = closeMethodDetail;
$("#method-detail-backdrop").onclick = (event) => {
  if (event.target === event.currentTarget) closeMethodDetail();
};

// 一遍读数(平行测试)的输入行; rd 为空表示尚未落库的新读数
// multiple=false(只有一遍)时无需显示“参与”勾框
function readingLineHtml(sa, rd, multiple, hasFinal = false) {
  const unitMap = { xrf: "%", ppm: "ppm", ppb: "ppb", percent: "%", ph: "pH" };
  const rawUnit = unitMap[sa.itype] || "";
  const rdExtra = rd && rd.extra
    ? (typeof rd.extra === "string" ? JSON.parse(rd.extra || "{}") : rd.extra) : {};
  let valueCell;
  if (sa.itype === "function") {
    const constants = templateJson(sa.method_constants, {});
    let inputs = "";
    if (sa.formula) {
      for (const variable of methodFormulaVariables(sa.formula)) {
        const supplied = Object.hasOwn(constants, variable) ||
          (variable === "m" && sa.prep_mass != null) || (variable === "v" && sa.prep_vol != null);
        if (!supplied) {
          inputs += `${esc(variable)}=<input type="number" step="any" class="rd-var" data-var="${esc(variable)}" value="${rdExtra[variable] ?? ""}">`;
        }
      }
    }
    valueCell = `<span class="tit-inputs">${inputs}</span>`;
  } else {
    valueCell = `<span class="input-unit"><input type="number" step="any" class="rd-raw" value="${rd?.raw ?? ""}"> <span>${rawUnit}</span></span>`;
  }
  const included = hasFinal ? !!rd?.is_final : rd?.use_avg !== false;
  const toggles = multiple
    ? `<label class="inline rd-use-label" title="勾选后参与结果计算"><input type="checkbox" class="rd-use" ${included ? "checked" : ""}>参与</label>`
    : "";
  return `<div class="reading ${readingHasStoredValue(rd) ? "has-value" : ""}" data-rid="${rd?.id ?? ""}">
    ${valueCell}${toggles}
    ${rd && multiple ? '<button class="del rd-del" type="button" title="删除这遍">删</button>' : ""}
  </div>`;
}

function entryRowHtml(sa, analyteCount = 1) {
  const aux = sa.aux ? JSON.parse(sa.aux) : {};
  const rdCount = (sa.readings && sa.readings.length) || 0;
  const hasFinal = !!sa.readings?.some((rd) => rd.is_final);
  const readingsHtml = rdCount
    ? sa.readings.map((rd) => readingLineHtml(sa, rd, rdCount > 1, hasFinal)).join("")
    : readingLineHtml(sa, null, false);
  let cell;
  if (!sa.itype) cell = '<i style="color:#999">先选仪器</i>';
  else if (sa.itype === "function") cell = `${titrationInputs(sa)}
    <div class="readings">${readingsHtml}</div>
    <button class="rd-add" type="button">+ 再测一遍</button>`;
  else cell = `<div class="readings">${readingsHtml}</div>
    <button class="rd-add" type="button">+ 再测一遍</button>`;
  let coeffText = "";
  if (aux.use) {
    if (aux.expected && aux.measured) coeffText = "×" + (aux.measured / aux.expected).toFixed(4);
    else if (aux.coefficient) coeffText = "×" + aux.coefficient;
  }
  const hasStoredValue = sa.readings?.some(readingHasStoredValue) || readingHasStoredValue(sa);
  return `<tr class="${sa.status === "completed" || hasStoredValue ? "task-completed" : ""}" data-said="${sa.id}" data-itype="${sa.itype || ""}" data-analyte="${esc(sa.analyte)}" data-prep="${esc(sa.prep_name || '原样')}">
    <td class="grid-cell readonly">${esc(sa.analyte)}</td>
    <td class="grid-cell readonly">${esc(sa.prep_name || "原样")}</td>
    <td class="grid-cell readonly">${sa.instrument ? esc(sa.instrument) : '<i class="bad-text">未分配（请到来样页设置）</i>'}${sa.method_name ? `<small>${esc(sa.method_name)}</small>` : ""}</td>
    <td class="grid-cell">${cell}</td>
    <td class="grid-cell"><span class="aux-box">标称<input type="number" step="any" class="aux-std" value="${aux.expected ?? ""}" style="width:55px">
      回读<input type="number" step="any" class="aux-read" value="${aux.measured ?? ""}" style="width:55px">
      <label class="inline" title="带标计算"><input type="checkbox" class="aux-use" ${aux.use ? "checked" : ""}>带标</label>
      <span class="aux-show">${coeffText}</span></span></td>
    <td class="grid-cell readonly st"></td></tr>`;
}

function specialFieldHtml(field, raw, calculated, locked) {
  const calculatedField = !!field.formula;
  const value = calculatedField ? calculated[field.key] : raw[field.key];
  const type = field.type || (field.unit ? "number" : "text");
  return `<label class="special-field ${calculatedField ? "calculated" : ""}">
    <span>${esc(field.label)}${field.required ? " *" : ""}</span>
    <span class="special-input-wrap"><input data-key="${esc(field.key)}" type="${esc(type)}" ${type === "number" ? 'step="any"' : ""}
      value="${esc(value ?? "")}" ${calculatedField || locked ? "disabled" : ""}>${field.unit ? `<em>${esc(field.unit)}</em>` : ""}</span>
  </label>`;
}

function renderSpecialData(sample, special) {
  const panel = $("#d-special-panel");
  const locked = ["registered", "received", "queued", "reviewed", "reported", "cancelled"].includes(sample.status);
  const raw = special?.raw_data || {};
  const calculated = special?.calculated_data || {};
  panel.innerHTML = `<div class="special-form-head"><div><h3>${esc(special.schema.title)}</h3>
    <p>${esc(special.method_name)} · ${esc(special.instrument)}</p></div><span class="sample-status ${esc(special.status)}">${special.status === "completed" ? "数据完整" : "待录完整"}</span></div>` +
    special.schema.groups.map((group) => `<fieldset class="special-fieldset"><legend>${esc(group.name)}</legend><div class="special-fields">${
      group.fields.map((field) => specialFieldHtml(field, raw, calculated, locked)).join("")}</div></fieldset>`).join("") +
    `<label class="special-note">备注<textarea data-key="note" ${locked ? "disabled" : ""}>${esc(raw.note || "")}</textarea></label>
     <p class="hint">带 * 的原始字段填齐后可标记检测完成；灰色字段由专项方法公式自动计算。</p>`;
  panel.querySelectorAll("input:not([disabled]),textarea:not([disabled])").forEach((input) => {
    input.onchange = async () => {
        const rawData = {};
        panel.querySelectorAll("input[data-key]:not(:disabled),textarea[data-key]:not(:disabled)").forEach((control) => {
          if (control.value === "") return;
          rawData[control.dataset.key] = control.type === "number" ? +control.value : control.value;
        });
        const result = await api(`/api/special-results/${sample.id}`, "PUT", { raw_data: rawData });
        if (result.ok) await loadDataEntry();
    };
  });
}

function preparationMethodHtml(sample, preps, items, special) {
  if (sample.workflow_type === "special") {
    return `<div class="prep-method-card"><b>${esc(special?.method_name || "专项检测")}</b>
      <span>${esc(special?.instrument || "按专项方法完成前处理")}</span></div>`;
  }
  if (!preps.length) return '<div class="prep-method-card"><b>原样测量</b><span>无需溶样，请确认样品与仪器已就绪</span></div>';
  return preps.map((prep) => {
    const tasks = items.filter((item) => item.preparation_id === prep.id);
    const analytes = [...new Set(tasks.map((item) => item.analyte).filter(Boolean))].join("、") || "待测项目";
    const instruments = [...new Set(tasks.map((item) => item.instrument).filter(Boolean))].join("、");
    const steps = sample.is_liquid
      ? [prep.dilution_label]
      : [prep.mass_g != null ? `称样 ${prep.mass_g} g` : "按方案称样",
         prep.volume_ml != null ? `定容 ${prep.volume_ml} mL` : null, prep.dilution_label];
    return `<div class="prep-method-card"><b>${esc(prep.name)}</b>
      <span>${esc(steps.filter(Boolean).join(" · "))}</span>
      <small>${esc(analytes)}${instruments ? ` · ${esc(instruments)}` : ""}</small></div>`;
  }).join("");
}

function ensureDataStageWorkspace() {
  let workspace = $("#d-stage-workspace");
  if (workspace) return workspace;
  const regular = $("#d-regular-panel");
  const special = $("#d-special-panel");
  if (!regular || !special) return null;
  workspace = document.createElement("div");
  workspace.id = "d-stage-workspace";
  workspace.className = "data-stage-workspace";
  workspace.innerHTML = '<div id="d-stage-overlay" class="data-stage-overlay" hidden></div><div id="d-stage-content" class="data-stage-content"></div>';
  regular.before(workspace);
  const content = workspace.querySelector("#d-stage-content");
  content.append(regular, special);
  return workspace;
}

function renderDataStage(sample, preps, items, special) {
  const workspace = ensureDataStageWorkspace();
  const overlay = workspace?.querySelector("#d-stage-overlay");
  if (!workspace || !overlay) return;
  const locked = ["received", "queued"].includes(sample.status);
  workspace.classList.toggle("stage-locked", locked);
  workspace.classList.toggle("stage-unprepared", sample.status === "received");
  workspace.classList.toggle("stage-prepared", sample.status === "queued");
  overlay.hidden = !locked;
  if (!locked) { overlay.innerHTML = ""; return; }
  const unprepared = sample.status === "received";
  overlay.innerHTML = `<div class="data-stage-dialog">
    <span class="data-stage-kicker">${unprepared ? "步骤 1 / 2" : "步骤 2 / 2"}</span>
    <h3>${unprepared ? "请先按方案完成制样" : "制样已完成，是否开始测量？"}</h3>
    <p>${unprepared ? "完成下列前处理后再进入待测阶段。XRF 数据仍会正常显示和同步。" : "请确认样品、仪器和方法均已就绪。开始测量后开放数据录入。"}</p>
    <div class="prep-method-list">${preparationMethodHtml(sample, preps, items, special)}</div>
    <button type="button" class="data-stage-action primary" data-target="${unprepared ? "queued" : "measuring"}">${unprepared ? "制样完成" : "开始测量"}</button>
    ${statusActorHtml(sample)}</div>`;
  overlay.querySelector(".data-stage-action").onclick = async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    const result = await api(`/api/samples/${sample.id}/status`, "PUT", { status: button.dataset.target });
    if (!result.ok) { button.disabled = false; return; }
    await loadSamples();
    await loadDataEntry();
    if (+$("#r-sample").value === sample.id) await loadReport();
  };
}

async function loadDataEntry() {
  const sid = $("#d-sample").value;
  $("#d-excel-export").disabled = !sid;
  $("#d-excel-import").disabled = !sid;
  $("#d-manual-result").disabled = !sid;
  if (!sid) {
    $("#d-info").textContent = "";
    $("#d-status-actions").innerHTML = "";
    $("#d-table tbody").innerHTML = "";
    $("#d-xrf-panel").hidden = true;
    const workspace = ensureDataStageWorkspace();
    workspace?.classList.remove("stage-locked", "stage-unprepared", "stage-prepared");
    const overlay = workspace?.querySelector("#d-stage-overlay");
    if (overlay) overlay.hidden = true;
    return;
  }
  const sequence = ++dataLoadSequence;
  const { sample, preps, items, special } = await api("/api/samples/" + sid);
  if (sequence !== dataLoadSequence || $("#d-sample").value !== sid) return;
  setCurrentSample(sample);
  const excelDataLocked = ["registered", "received", "queued", "reviewed", "reported", "cancelled"].includes(sample.status);
  $("#d-excel-import").disabled = excelDataLocked;
  $("#d-excel-import").title = excelDataLocked ? "当前样品状态不能通过 Excel 覆盖检测数据" : "";
  $("#d-manual-result").disabled = !["completed", "reviewed"].includes(sample.status);
  $("#d-manual-result").title = $("#d-manual-result").disabled ? "样品测量完成后才能手工补录结果" : "需要特权权限、操作原因和再次密码确认";
  const statusLabel = META.sample_statuses[sample.status] || sample.status;
  $("#d-info").innerHTML = `${sample.workflow_type === "special" ? "其他样" : (sample.is_liquid ? "液体样" : "固体")} <span class="sample-status ${esc(sample.status)}">${esc(statusLabel)}</span>${statusActorHtml(sample)}`;
  const nextStatuses = (META.sample_transitions?.[sample.status] || []).filter((status) =>
    !["cancelled", "reviewed"].includes(status) && META.allowed_status_targets.includes(status));
  const statusActions = $("#d-status-actions");
  statusActions.innerHTML = (["received", "queued"].includes(sample.status) ? [] : nextStatuses).map((status) =>
    `<button type="button" data-status="${status}">${esc(statusTransitionLabel(sample.status, status))}</button>`).join("");
  statusActions.querySelectorAll("button").forEach((button) => button.onclick = async () => {
    if (!confirmStatusRollback(sample.status, button.dataset.status)) return;
    const result = await api(`/api/samples/${sid}/status`, "PUT", { status: button.dataset.status });
    if (!result.ok) return;
    await loadSamples();
    await loadDataEntry();
    if ($("#r-sample").value === sid) await loadReport();
  });
  const isSpecialSample = sample.workflow_type === "special";
  renderDataStage(sample, preps, items, special);
  $("#d-regular-panel").hidden = isSpecialSample;
  $("#d-special-panel").hidden = !isSpecialSample;
  if (isSpecialSample) {
    $("#d-xrf-panel").hidden = true;
    renderSpecialData(sample, special);
    $("#d-msg").textContent = ["received", "queued"].includes(sample.status) ? "开始测量后开放专项数据录入" : "原始字段失焦后自动保存并重新计算";
    return;
  }
  const xrfResult = await api(`/api/xrf/samples/${sid}`);
  if (sequence !== dataLoadSequence || $("#d-sample").value !== sid) return;
  renderDataXrfPanel(sample, xrfResult);
  // 按仪器分组, 未选仪器的归入"未选仪器"
  const groups = new Map();
  const analyteCounts = {};
  for (const sa of items.filter((item) => item.itype !== "xrf")) {
    const key = sa.instrument_id ?? 0;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(sa);
    analyteCounts[sa.analyte_id] = (analyteCounts[sa.analyte_id] || 0) + 1;
  }
  const instrumentOrder = new Map(META.instruments.map((item, index) => [item.id, index]));
  const analyteOrder = new Map(META.analytes.map((item, index) => [item.id, index]));
  const orderedGroups = [...groups.entries()].sort(([left], [right]) =>
    (instrumentOrder.get(+left) ?? Number.MAX_SAFE_INTEGER) -
    (instrumentOrder.get(+right) ?? Number.MAX_SAFE_INTEGER));
  let html = "";
  for (const [iid, rows] of orderedGroups) {
    rows.sort((left, right) =>
      String(left.prep_name || "原样").localeCompare(String(right.prep_name || "原样"), "zh-CN") ||
      (analyteOrder.get(left.analyte_id) ?? Number.MAX_SAFE_INTEGER) -
      (analyteOrder.get(right.analyte_id) ?? Number.MAX_SAFE_INTEGER) || left.id - right.id);
    const label = iid ? rows[0].instrument : "未选仪器";
    html += `<tr class="group"><td colspan="6"><b>${esc(label)}</b></td></tr>`;
    html += rows.map((sa) => entryRowHtml(sa, analyteCounts[sa.analyte_id])).join("");
  }
  $("#d-table tbody").innerHTML = html;
  DATA_GRID.refresh();
  $$("#d-table .method-detail").forEach((button) =>
    button.onclick = () => openMethodDetail(button.dataset.methodId));
  if (sample.status === "cancelled") {
    $$("#d-table input, #d-table select, #d-table button:not(.method-detail)").forEach((control) => control.disabled = true);
    $("#d-msg").textContent = "样品已作废，数据只读";
    return;
  }
  if (["registered", "received", "queued"].includes(sample.status)) {
    $$("#d-table tr[data-said]:not([data-itype='xrf'])").forEach((row) =>
      row.querySelectorAll("input,select,button:not(.method-detail)").forEach((control) => control.disabled = true));
    $("#d-msg").textContent = "XRF 正常显示；其余项目在开始测量后开放录入";
  } else $("#d-msg").textContent = "";

  // 选仪器 → 保存并刷新该行（不同仪器输入形式不同）
  $$("#d-table .i-sel").forEach((sel) => sel.onchange = async () => {
    const result = await api("/api/results", "POST", {
      sample_analyte_id: +sel.closest("tr").dataset.said,
      instrument_id: sel.value ? +sel.value : null,
    });
    if (!result.ok) return;
    await loadDataEntry();
    if ($("#r-sample").value === $("#d-sample").value) await loadReport();
  });
  // 滴定: 选方法 → 保存并刷新（公式决定变量输入框）
  $$("#d-table .m-sel").forEach((sel) => sel.onchange = async () => {
    const result = await api("/api/results", "POST", {
      sample_analyte_id: +sel.closest("tr").dataset.said,
      method_id: +sel.value || null,
    });
    if (!result.ok) return;
    await loadDataEntry();
  });
  // 原始值(平行读数) / 是否参与 / 辅助数据(回标): 失焦即自动保存
  $$("#d-table tr[data-said]").forEach((tr) => {
    const said = +tr.dataset.said;
    // --- 平行读数 ---
    const saveReading = async (div) => {
      let rid = div.dataset.rid ? +div.dataset.rid : null;
      if (!rid) {
        const r = await api("/api/readings", "POST", { sample_analyte_id: said });
        if (!r.ok) return false;
        rid = r.id;
        div.dataset.rid = rid;
      }
      const use = div.querySelector(".rd-use");
      const body = {
        use_avg: use ? use.checked : true,
        is_final: false,
      };
      const rawInp = div.querySelector(".rd-raw");
      if (rawInp) body.raw = rawInp.value === "" ? null : parseFloat(rawInp.value);
      const vars = div.querySelectorAll(".rd-var");
      if (vars.length) {
        const extra = {};
        vars.forEach((i) => { if (i.value !== "") extra[i.dataset.var] = parseFloat(i.value); });
        body.extra = extra;
      }
      const result = await api("/api/readings/" + rid, "PUT", body);
      if (!result.ok) return false;
      rowSaved(tr);
      return true;
    };
    tr.querySelectorAll(".reading").forEach((div) => {
      div.querySelectorAll(".rd-raw, .rd-var").forEach((inp) =>
        inp.onchange = () => saveReading(div));
      const use = div.querySelector(".rd-use");
      if (use) use.onchange = async () => {
        // 一次保存整组，把旧数据中的“终值”状态统一迁移为简单的“是否参与”。
        for (const reading of tr.querySelectorAll(".reading")) {
          if (!await saveReading(reading)) break;
        }
      };
      const del = div.querySelector(".rd-del");
      if (del) del.onclick = async () => {
        const result = await api("/api/readings/" + div.dataset.rid, "DELETE");
        if (!result.ok) return;
        await loadDataEntry();
      };
    });
    const addBtn = tr.querySelector(".rd-add");
    if (addBtn) addBtn.onclick = async () => {
      const result = await api("/api/readings", "POST", { sample_analyte_id: said });
      if (!result.ok) return;
      await loadDataEntry();
    };
    const auxStd = tr.querySelector(".aux-std");
    const auxRead = tr.querySelector(".aux-read");
    const auxUse = tr.querySelector(".aux-use");
    const saveAux = async () => {
      const aux = { use: auxUse.checked };
      if (auxStd.value !== "") aux.expected = parseFloat(auxStd.value);
      if (auxRead.value !== "") aux.measured = parseFloat(auxRead.value);
      const result = await api("/api/results", "POST", { sample_analyte_id: said, aux });
      if (!result.ok) return;
      const show = tr.querySelector(".aux-show");
      show.textContent = auxUse.checked && aux.expected && aux.measured
        ? "×" + (aux.measured / aux.expected).toFixed(4) : "";
      rowSaved(tr);
    };
    if (auxUse) auxUse.onchange = saveAux;
    if (auxStd) auxStd.onchange = saveAux;
    if (auxRead) auxRead.onchange = saveAux;
  });
}

async function loadInstrumentPage() {
  const sequence = ++INSTRUMENT_LOAD_SEQUENCE;
  const standardBox = $("#standard-client-status");
  const box = $("#instrument-status");
  const historyBody = $("#xrf-scan-history tbody");
  const query = new URLSearchParams({
    page: XRF_SCAN_PAGE, limit: XRF_SCAN_PAGE_SIZE, q: XRF_SCAN_QUERY,
    kind: XRF_SCAN_KIND, match: XRF_SCAN_MATCH,
  });
  const result = await api(`/api/xrf/monitor?${query}`);
  if (sequence !== INSTRUMENT_LOAD_SEQUENCE) return;
  if (!result.ok) { standardBox.innerHTML = ""; box.innerHTML = ""; historyBody.innerHTML = ""; return; }
  const standardClients = result.standard_clients || [];
  standardBox.innerHTML = standardClients.length ? standardClients.map((standardClient) => {
    const recent = standardClient.recent_entry;
    const recentItems = recent?.items || [];
    const recentText = recent
      ? `${esc(recent.at || "")} · ${esc(recentItems.join("，") || `${recent.count || 0} 条读数`)}${recent.count > recentItems.length ? ` 等 ${recent.count} 条` : ""}`
      : "尚无录入";
    return `<article class="standard-client-card">
      <div class="standard-client-head">
        <span class="instrument-state connected">已连接</span>
        <strong>${esc(standardClient.instrument_name || "标准仪器")}</strong>
        <small>${esc(standardClient.machine_name || standardClient.client_id || "标准客户端")}</small>
      </div>
      <div class="standard-client-fields">
        <div><b>网络位置</b><span>${esc(standardClient.network_position || "—")}</span></div>
        <div><b>当前用户</b><span>${esc(standardClient.display_name || standardClient.username || "未登录")}</span></div>
        <div class="standard-client-recent"><b>最近录入</b><span>${recentText}</span></div>
        <div><b>最近心跳</b><span>${esc(standardClient.seen_at || "—")}</span></div>
      </div>
    </article>`;
  }).join("") : '<p class="hint">标准客户端尚未连接；客户端连接 LIMS 后自动显示。</p>';
  const client = result.client;
  const stateLabels = { idle: "待机", reading: "测量中", uploading: "上传结果", error: "错误" };
  const state = client?.online === false ? "offline" : (client?.state || "idle");
  box.innerHTML = client ? `
    <div class="instrument-state ${esc(state)}">${esc(state === "offline" ? "离线" : (stateLabels[state] || state))}</div>
    <div><b>终端</b><span>${esc(client.machine_name || client.client_id || "XRF终端")}</span></div>
    <div><b>当前样品</b><span>${esc(client.current_sample || "—")}</span></div>
    <div><b>当前方法</b><span>${esc(client.current_method || "—")}</span></div>
    <div><b>当前批次</b><span>${esc(client.current_batch || "—")}</span></div>
    <div><b>运行编号</b><span>${esc(client.current_run_id || "—")}</span></div>
    <div><b>位置</b><span>${esc(client.current_position || "—")}</span></div>
    <div><b>开始时间</b><span>${esc(client.current_started_at || "—")}</span></div>
    <div><b>最近心跳</b><span>${esc(client.seen_at || "—")}</span></div>
    ${client.message ? `<div class="instrument-message"><b>说明</b><span>${esc(client.message)}</span></div>` : ""}`
    : '<p class="hint">XRF 终端尚未上报状态；启动客户端并连接 LIMS 后自动显示。</p>';
  XRF_SCAN_PAGE = result.page || 1;
  const scans = result.scans || [];
  historyBody.innerHTML = scans.length ? scans.map((scan) => {
    const expanded = XRF_EXPANDED.has(String(scan.id));
    const type = scan.kind === "uq" ? "UniQuant" : "普通定量";
    const options = (scan.option_details || []).map((option) => `<div><b>${esc(option.label)}</b><span>${esc(Array.isArray(option.value) ? option.value.join(", ") : option.value)}</span></div>`).join("");
    const values = (scan.values || []).map((value) => `<div><b>${esc(value.name)}</b><span>${esc(xrfValueText(value.value))}%</span></div>`).join("");
    const keyOption = scan.kind === "uq"
      ? `<span class="xrf-option-badge ${scan.oxide ? "oxide" : "element"}">${scan.oxide ? "氧化物" : "元素"}</span>`
      : (scan.batch ? `<small>批次 ${esc(scan.batch)}</small>` : "");
    return `<tr class="xrf-scan-row" data-scan-id="${scan.id}" tabindex="0" aria-expanded="${expanded}">
      <td>${esc(scan.analyzed_at || scan.created_at || "")}</td>
      <td><span class="xrf-type ${scan.kind === "uq" ? "uq" : "quant"}">${type}</span></td>
      <td><strong>${esc(scan.sample_name || "—")}</strong><small>扫描 ${esc(scan.external_id || "—")}</small></td>
      <td>${scan.matched ? `<strong>${esc(scan.lims_sample_name || "")}</strong><small>${esc(scan.lims_no || "")}</small>${!["reviewed", "reported", "cancelled"].includes(scan.sample_status) ? `<button type="button" class="xrf-unassign-open" data-analysis-id="${scan.id}">解绑</button>` : ""}` : `<span class="xrf-unmatched">未关联 LIMS</span><button type="button" class="xrf-assign-open" data-analysis-id="${scan.id}" data-scan-label="${esc(scan.sample_name || scan.external_id || "XRF 扫描")}">关联样品</button>`}</td>
      <td><strong>${esc(scan.method || "—")}</strong>${keyOption}</td>
      <td><div class="xrf-result-preview">${(scan.top_values || []).map((value) => `<span>${esc(value)}</span>`).join("") || '<span class="hint">无终值</span>'}</div>${scan.value_count > (scan.top_values || []).length ? `<small>另有 ${scan.value_count - scan.top_values.length} 项</small>` : ""}</td>
      <td><button type="button" class="xrf-expand" aria-label="展开最终结果">${expanded ? "收起" : "展开"}</button></td></tr>
      <tr class="xrf-scan-detail" data-detail-id="${scan.id}" ${expanded ? "" : "hidden"}><td colspan="7"><div class="xrf-expanded-grid">
        <section><h4>最终组成 <small>${scan.value_count || 0} 项 · Wt%</small></h4><div class="xrf-result-list">${values || '<span class="hint">无最终组成</span>'}</div></section>
        <section><h4>${scan.kind === "uq" ? "UniQuant 关键选项" : "扫描信息"}</h4><div class="xrf-option-list">${options || ""}<div><b>方法</b><span>${esc(scan.method || "—")}</span></div>${scan.batch ? `<div><b>批次</b><span>${esc(scan.batch)}</span></div>` : ""}<div><b>扫描编号</b><span>${esc(scan.external_id || "—")}</span></div></div></section>
      </div></td></tr>`;
  }).join("") : '<tr><td colspan="7" class="xrf-empty">没有符合条件的 XRF 扫描。</td></tr>';
  $("#xrf-scan-count").textContent = `共 ${result.total || 0} 条扫描`;
  $("#xrf-page-summary").textContent = scans.length ? `本页 ${scans.length} 条` : "";
  $("#xrf-page-label").textContent = `${result.page || 1} / ${result.pages || 1}`;
  $("#xrf-page-prev").disabled = (result.page || 1) <= 1;
  $("#xrf-page-next").disabled = (result.page || 1) >= (result.pages || 1);
  historyBody.querySelectorAll(".xrf-scan-row").forEach((row) => {
    const toggle = () => {
      const id = row.dataset.scanId;
      const open = !XRF_EXPANDED.has(id);
      if (open) XRF_EXPANDED.add(id); else XRF_EXPANDED.delete(id);
      row.setAttribute("aria-expanded", String(open));
      row.querySelector(".xrf-expand").textContent = open ? "收起" : "展开";
      historyBody.querySelector(`[data-detail-id="${id}"]`).hidden = !open;
    };
    row.onclick = toggle;
    row.querySelector(".xrf-expand").onclick = (event) => { event.stopPropagation(); toggle(); };
    const assign = row.querySelector(".xrf-assign-open");
    if (assign) assign.onclick = (event) => {
      event.stopPropagation();
      openXrfAssignDialog(+assign.dataset.analysisId, assign.dataset.scanLabel);
    };
    const unassign = row.querySelector(".xrf-unassign-open");
    if (unassign) unassign.onclick = async (event) => {
      event.stopPropagation();
      if (!confirm("确定解除该 XRF 扫描与 LIMS 样品的关联？")) return;
      const result = await unassignXrfAnalysis(+unassign.dataset.analysisId);
      if (!result.ok) return;
      await loadSamples();
      await loadInstrumentPage();
    };
    row.onkeydown = (event) => { if (event.key === "Enter") { event.preventDefault(); toggle(); } };
  });
}

async function assignXrfAnalysis(analysisId, sampleId) {
  return api(`/api/xrf/analyses/${analysisId}/sample`, "PUT", { sample_id: sampleId });
}

async function unassignXrfAnalysis(analysisId) {
  return api(`/api/xrf/analyses/${analysisId}/sample`, "DELETE", {});
}

async function loadDataXrfCandidates(query = "") {
  const sid = +$("#d-sample").value;
  const options = $("#d-xrf-scan-options");
  if (!sid || $("#d-xrf-panel").hidden) { options.innerHTML = ""; return; }
  const result = await api(`/api/xrf/monitor?match=unmatched&limit=10&q=${encodeURIComponent(query)}`);
  if (!result?.ok || sid !== +$("#d-sample").value || query !== $("#d-xrf-scan-search").value.trim()) return;
  const scans = result.scans || [];
  options.innerHTML = scans.length ? scans.map((scan) => `<article>
    <div><strong>${esc(scan.sample_name || "未命名扫描")}</strong><span>${esc(scan.kind === "uq" ? "UniQuant" : "普通定量")} · ${esc(scan.analyzed_at || scan.created_at || "时间未知")}</span><small>${esc(scan.method || "方法未知")} · 扫描 ${esc(scan.external_id || "—")} · ${(scan.top_values || []).map(esc).join("，")}</small></div>
    <button type="button" data-analysis-id="${scan.id}">关联当前样品</button>
  </article>`).join("") : `<p class="hint">${query ? "没有匹配的未关联 XRF 扫描。" : "当前没有未关联 XRF 扫描。"}</p>`;
  options.querySelectorAll("button").forEach((button) => button.onclick = async () => {
    button.disabled = true;
    const assigned = await assignXrfAnalysis(+button.dataset.analysisId, sid);
    if (!assigned.ok) { button.disabled = false; return; }
    $("#d-xrf-scan-search").value = "";
    await loadSamples();
    await loadDataEntry();
    if (+$("#r-sample").value === sid) await loadReport();
  });
}

function closeXrfAssignDialog() {
  clearTimeout(XRF_ASSIGN_SEARCH_TIMER);
  XRF_ASSIGN_ANALYSIS_ID = null;
  $("#xrf-assign-dialog").hidden = true;
}

function openXrfAssignDialog(analysisId, scanLabel) {
  XRF_ASSIGN_ANALYSIS_ID = analysisId;
  $("#xrf-assign-scan").textContent = `XRF 扫描：${scanLabel}`;
  $("#xrf-assign-sample-search").value = "";
  $("#xrf-assign-sample-options").innerHTML = '<p class="hint">正在加载可关联样品…</p>';
  $("#xrf-assign-dialog").hidden = false;
  $("#xrf-assign-sample-search").focus();
  loadXrfAssignableSamples();
}

async function loadXrfAssignableSamples(query = "") {
  const analysisId = XRF_ASSIGN_ANALYSIS_ID;
  const options = $("#xrf-assign-sample-options");
  const statuses = "received,queued,measuring,partially_done,completed";
  const found = await api(`/api/samples?xrf=1&xrf_available=1&status=${statuses}&limit=30&q=${encodeURIComponent(query)}`);
  if (analysisId !== XRF_ASSIGN_ANALYSIS_ID || query !== $("#xrf-assign-sample-search").value.trim() || !Array.isArray(found)) return;
  options.innerHTML = found.length ? found.map((sample) => `<button type="button" data-sample-id="${sample.id}">
    <b>${esc(sample.name || "未命名样品")}</b><span>${esc(sample.category || "未填写样品名称")}</span><small>${esc(sample.lims_no || `#${sample.id}`)} · ${esc(META.sample_statuses[sample.status] || sample.status)}</small>
  </button>`).join("") : '<p class="hint">没有可关联的 XRF 样品。</p>';
  options.querySelectorAll("button").forEach((button) => button.onclick = async () => {
    button.disabled = true;
    const assigned = await assignXrfAnalysis(analysisId, +button.dataset.sampleId);
    if (!assigned.ok) { button.disabled = false; return; }
    closeXrfAssignDialog();
    await loadSamples();
    await loadInstrumentPage();
  });
}

function renderDataXrfPanel(sample, result) {
  const panel = $("#d-xrf-panel");
  const valuesBox = $("#d-xrf-values");
  const assignment = panel.querySelector(".xrf-data-assign");
  const unassign = $("#d-xrf-unassign");
  const analyses = result?.analyses || [];
  if ((!sample?.xrf && !analyses.length) || sample.workflow_type === "special") {
    panel.hidden = true;
    valuesBox.innerHTML = "";
    $("#d-xrf-scan-options").innerHTML = "";
    unassign.hidden = true;
    return;
  }
  const latest = analyses[0];
  const values = latest?.values || [];
  const editable = !["reviewed", "reported", "cancelled"].includes(sample.status);
  assignment.hidden = !sample.xrf || !editable || analyses.length > 0;
  if (assignment.hidden) $("#d-xrf-scan-options").innerHTML = "";
  unassign.hidden = !latest || !editable;
  unassign.disabled = false;
  unassign.onclick = latest && editable ? async () => {
    if (!confirm(`确定解除当前样品与 XRF 扫描 ${latest.external_id || latest.id} 的关联？`)) return;
    unassign.disabled = true;
    const unlinked = await unassignXrfAnalysis(latest.id);
    if (!unlinked.ok) { unassign.disabled = false; return; }
    await loadSamples();
    await loadDataEntry();
    if (+$("#r-sample").value === sample.id) await loadReport();
  } : null;
  $("#d-xrf-meta").textContent = latest
    ? `${latest.kind === "uq" ? "UniQuant" : "常规 XRF"} · ${latest.analyzed_at || latest.created_at || ""} · ${latest.method || sample.method_name || "XRF"}${latest.batch ? ` · 批次 ${latest.batch}` : ""}${latest.remark ? ` · ${latest.remark}` : ""} · 共 ${analyses.length} 次分析`
    : "尚未收到扫描结果";
  valuesBox.innerHTML = values.length ? values.map((value) => `<div class="xrf-value ${value.use_report ? "used" : ""}" title="${value.use_report ? "参与最终结果计算" : "不参与最终结果计算"}">
    <b>${esc(value.name)}</b><span>${xrfValueText(value.value)}%</span></div>`).join("")
    : '<p class="hint">待 XRF 终端上传结果。</p>';
  panel.hidden = false;
}
$("#d-sample").onchange = loadDataEntry;

/* ---------------- 类 Excel 表格交互 ---------------- */
function createSpreadsheet(table, status, options = {}) {
  let anchor = null;
  let focus = null;
  let dragging = false;
  let fillTarget = null;
  const rowSelector = options.rowSelector || "tr[data-said]";
  const editableSelector = options.editableSelector || "input.raw, .rd-raw, .rd-var, .tit-inputs input";

  const cells = () => [...table.querySelectorAll(`${rowSelector} .grid-cell`)];
  const locate = (cell) => ({ row: +cell.dataset.row, col: +cell.dataset.col });
  const at = (row, col) => table.querySelector(`.grid-cell[data-row="${row}"][data-col="${col}"]`);
  const selected = () => cells().filter((cell) => cell.classList.contains("selected"));
  const valueOf = (cell) => {
    const control = cell.querySelector("input,select");
    if (control?.tagName === "SELECT") return control.selectedOptions[0]?.textContent || "";
    if (control) return control.value;
    return cell.textContent.trim();
  };
  const editableInput = (cell) => cell?.querySelector(editableSelector);

  function paintRange(from, to) {
    const a = locate(from), b = locate(to);
    const r0 = Math.min(a.row, b.row), r1 = Math.max(a.row, b.row);
    const c0 = Math.min(a.col, b.col), c1 = Math.max(a.col, b.col);
    cells().forEach((cell) => {
      const p = locate(cell);
      cell.classList.toggle("selected", p.row >= r0 && p.row <= r1 && p.col >= c0 && p.col <= c1);
      cell.classList.remove("active");
      cell.querySelector(".fill-handle")?.remove();
    });
    focus = to;
    focus.classList.add("active");
    if (editableInput(focus)) {
      const handle = document.createElement("span");
      handle.className = "fill-handle";
      handle.title = "拖动填充";
      focus.append(handle);
      handle.onmousedown = (event) => {
        event.preventDefault();
        event.stopPropagation();
        fillTarget = focus;
        document.body.classList.add("grid-filling");
      };
    }
    status.textContent = `${r1 - r0 + 1} 行 × ${c1 - c0 + 1} 列`;
  }

  function refresh() {
    [...table.querySelectorAll(rowSelector)].forEach((row, rowIndex) => {
      [...row.querySelectorAll(".grid-cell")].forEach((cell, colIndex) => {
        cell.dataset.row = rowIndex;
        cell.dataset.col = colIndex;
      });
    });
    anchor = focus = null;
    status.textContent = "";
  }

  function matrix() {
    const list = selected();
    if (!list.length) return [];
    const points = list.map(locate);
    const r0 = Math.min(...points.map((p) => p.row)), r1 = Math.max(...points.map((p) => p.row));
    const c0 = Math.min(...points.map((p) => p.col)), c1 = Math.max(...points.map((p) => p.col));
    return Array.from({ length: r1 - r0 + 1 }, (_, r) =>
      Array.from({ length: c1 - c0 + 1 }, (_, c) => valueOf(at(r0 + r, c0 + c))));
  }

  async function copy() {
    const text = matrix().map((row) => row.join("\t")).join("\n");
    if (text) await navigator.clipboard.writeText(text);
  }

  function write(cell, value) {
    const control = editableInput(cell);
    if (!control) return false;
    if (control.tagName === "SELECT") {
      const text = String(value).trim();
      const option = [...control.options].find((item) =>
        item.value === text || item.textContent.trim() === text);
      if (!option) return false;
      control.value = option.value;
    } else control.value = value;
    control.dispatchEvent(new Event("input", { bubbles: true }));
    control.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  function paste(text) {
    if (!focus) return;
    const data = text.replace(/\r/g, "").split("\n").filter((row, i, all) => row || i < all.length - 1)
      .map((row) => row.split("\t"));
    const start = locate(focus);
    let changed = 0;
    data.forEach((row, ri) => {
      if (options.appendRow) {
        while (!at(start.row + ri, start.col)) options.appendRow();
      }
      row.forEach((value, ci) => {
        if (write(at(start.row + ri, start.col + ci), value)) changed++;
      });
    });
    status.textContent = changed ? `已粘贴 ${changed} 个单元格` : "选区没有可写入的数值格";
  }

  function fillDown(targetRow = null) {
    const list = selected().filter(editableInput).sort((a, b) => locate(a).row - locate(b).row);
    if (!list.length) return;
    const col = locate(list[0]).col;
    const source = list.filter((cell) => locate(cell).col === col);
    if (targetRow === null) {
      const value = valueOf(source[0]);
      let changed = 0;
      source.slice(1).forEach((cell) => { if (write(cell, value)) changed++; });
      status.textContent = changed ? `已向下填充 ${changed} 个单元格` : status.textContent;
      return;
    }
    const lastRow = targetRow ?? locate(source[source.length - 1]).row;
    const values = source.map(valueOf);
    const numbers = values.map(Number);
    const numericSeries = values.length >= 2 && numbers.every(Number.isFinite);
    const step = numericSeries ? numbers[numbers.length - 1] - numbers[numbers.length - 2] : 0;
    let changed = 0;
    for (let row = locate(source[source.length - 1]).row + 1; row <= lastRow; row++) {
      const offset = row - locate(source[source.length - 1]).row;
      const value = numericSeries ? numbers[numbers.length - 1] + step * offset
        : values[(row - locate(source[0]).row) % values.length];
      if (write(at(row, col), value)) changed++;
    }
    status.textContent = changed ? `已填充 ${changed} 个单元格` : status.textContent;
  }

  table.addEventListener("mousedown", (event) => {
    if (event.target.closest(".p-routing-cell, .route-chip, .route-zone, .route-tools, .route-method")) return;
    const cell = event.target.closest(".grid-cell");
    if (!cell || event.target.closest(".fill-handle")) return;
    if (!event.shiftKey || !anchor) anchor = cell;
    paintRange(anchor, cell);
    dragging = true;
  });
  table.addEventListener("mouseover", (event) => {
    if (event.target.closest(".p-routing-cell, .route-chip, .route-zone, .route-tools, .route-method")) return;
    const cell = event.target.closest(".grid-cell");
    if (dragging && cell) paintRange(anchor, cell);
  });
  document.addEventListener("mousemove", (event) => {
    if (!fillTarget) return;
    const cell = document.elementFromPoint(event.clientX, event.clientY)?.closest(".grid-cell");
    if (cell && locate(cell).col === locate(fillTarget).col) {
      cells().forEach((item) => item.classList.remove("fill-preview"));
      const from = locate(fillTarget).row, to = locate(cell).row;
      for (let row = Math.min(from, to); row <= Math.max(from, to); row++) at(row, locate(cell).col)?.classList.add("fill-preview");
      fillTarget.dataset.targetRow = to;
    }
  });
  document.addEventListener("mouseup", () => {
    dragging = false;
    if (fillTarget) {
      const target = +fillTarget.dataset.targetRow;
      cells().forEach((cell) => cell.classList.remove("fill-preview"));
      if (Number.isFinite(target) && target > locate(fillTarget).row) fillDown(target);
      delete fillTarget.dataset.targetRow;
      fillTarget = null;
      document.body.classList.remove("grid-filling");
    }
  });
  table.addEventListener("copy", (event) => {
    const text = matrix().map((row) => row.join("\t")).join("\n");
    if (text) { event.preventDefault(); event.clipboardData.setData("text/plain", text); }
  });
  table.addEventListener("paste", (event) => {
    if (!focus) return;
    event.preventDefault();
    paste(event.clipboardData.getData("text/plain"));
  });
  table.addEventListener("keydown", (event) => {
    if (event.target.closest(".p-routing-cell, .route-method")) return;
    const keyMoves = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    const currentCell = event.target.closest(".grid-cell") || focus;
    if (event.key === "Escape" && currentCell) {
      event.preventDefault();
      event.target.blur?.();
      table.focus({ preventScroll: true });
      paintRange(currentCell, currentCell);
      return;
    }
    if (keyMoves[event.key] && currentCell) {
      event.preventDefault();
      const controls = [...currentCell.querySelectorAll(editableSelector)].filter((item) => !item.disabled);
      const controlIndex = controls.indexOf(event.target);
      const horizontalStep = keyMoves[event.key][1];
      if (horizontalStep && controlIndex >= 0 && controls[controlIndex + horizontalStep]) {
        const control = controls[controlIndex + horizontalStep];
        control.focus(); control.select?.();
        return;
      }
      const point = locate(currentCell);
      const targetCell = at(point.row + keyMoves[event.key][0], point.col + keyMoves[event.key][1]);
      if (!targetCell) return;
      anchor = targetCell;
      paintRange(targetCell, targetCell);
      const control = editableInput(targetCell);
      if (control && !control.disabled) { control.focus(); control.select?.(); }
      else table.focus({ preventScroll: true });
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "d") {
      event.preventDefault(); fillDown();
    }
  });
  return { refresh, copy, fillDown };
}

const DATA_GRID = createSpreadsheet($("#d-table"), $("#d-grid-status"));
const PREP_GRID = createSpreadsheet($("#p-table"), $("#p-grid-status"), {
  rowSelector: "tbody tr",
  editableSelector: "input:not(.p-analytes),select:not(.route-method)",
  appendRow: () => addPrepRow(),
});
$(".grid-copy").onclick = () => DATA_GRID.copy();
$(".grid-fill").onclick = () => DATA_GRID.fillDown();
$(".prep-grid-copy").onclick = () => PREP_GRID.copy();
$(".prep-grid-fill").onclick = () => PREP_GRID.fillDown();

/* ---------------- 报告 ---------------- */
function reportDate(sample) {
  return sample.analysis_date || String(sample.created_at || "").slice(0, 10) ||
    new Date().toLocaleDateString("sv-SE");
}

function reportMetaPayload() {
  return {
    report_profile_id: +$("#r-report-profile").value || null,
    customer: $("#r-customer").value.trim(),
    report_no: $("#r-report-no").value.trim(),
    analysis_date: $("#r-analysis-date").value,
    analyst: $("#r-analyst").value.trim(),
  };
}

async function saveReportMeta(silent = false) {
  const ids = [...REPORT_SELECTED];
  if (!ids.length) return false;
  const payload = reportMetaPayload();
  const results = await Promise.all(ids.map((sid) => api(`/api/samples/${sid}/report-meta`, "PUT", payload)));
  if (results.some((result) => !result.ok)) return false;
  const profile = META.report_profiles.find((item) => item.id === payload.report_profile_id);
  for (const reportData of REPORT_BATCH_DATA) {
    Object.assign(reportData.sample, payload);
    if (profile) reportData.report_profile = profile;
  }
  if (!silent) $("#r-meta-msg").textContent = `✓ 已保存到 ${ids.length} 个样品`;
  renderPrintTickets();
  await updateFinalTicket();
  return true;
}

function displayNumber(value) {
  if (value === null || value === undefined || value === "") return "—";
  return Number.isFinite(+value) ? String(+value) : String(value);
}

function xrfValueText(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = +value;
  if (!Number.isFinite(number)) return String(value);
  return Number(number.toPrecision(5)).toString();
}

function rawReadingText(row, reading) {
  if (row.method) {
    const text = Object.entries(reading.extra || {}).map(([key, value]) => `${key}=${value}`).join(" ");
    return text || "—";
  }
  return displayNumber(reading.raw);
}

function combinedRawTicketHtml(payloads) {
  if (!payloads.length) return '<div class="report-empty-preview">选择已审核样品后生成原始分析记录预览</div>';
  const profile = payloads[0].report_profile || {};
  const rawRows = [];
  for (const payload of payloads) {
    const { sample, groups, special } = payload;
    const sampleRows = [];
    if (sample.workflow_type === "special") {
      for (const group of special?.schema?.groups || []) {
        for (const field of group.fields || []) {
          const raw = special.raw_data?.[field.key];
          const calculated = special.calculated_data?.[field.key];
          if ([raw, calculated].every((value) => value === undefined || value === "")) continue;
          sampleRows.push({
            analyte: field.label, mass: null, volume: null, dilution: "—",
            raw: raw ?? calculated, result: calculated ?? raw, unit: field.unit || "",
            remark: [special.method_name, special.instrument].filter(Boolean).join(" / "),
          });
        }
      }
    } else for (const group of groups || []) {
      for (const row of group.rows) {
        const readings = row.readings?.length ? row.readings : [{ raw: null, extra: {}, corrected_value: null }];
        readings.forEach((reading, index) => {
          const result = reading.corrected_value ?? (index === 0 ? row.value : null);
          const aux = row.aux?.use
            ? (row.aux.expected && row.aux.measured
                ? `回标 ${row.aux.expected}→${row.aux.measured}` : "带标校正") : "";
          sampleRows.push({
            analyte: group.analyte, mass: row.mass_g, volume: row.volume_ml,
            dilution: row.dilution, raw: rawReadingText(row, reading), result, unit: row.unit,
            remark: [row.instrument, row.method, aux].filter(Boolean).join(" / "),
          });
        });
      }
    }
    if (!sampleRows.length) sampleRows.push({ analyte: "—", raw: "—", result: null, remark: "暂无检测明细" });
    sampleRows.forEach((row, index) => rawRows.push({
      ...row, sample, date: reportDate(sample), firstForSample: index === 0,
    }));
  }
  const rawBody = rawRows.map((row) => {
    const [year = "", month = "", day = ""] = row.date.split("-");
    return `<tr>
      <td>${row.firstForSample ? esc(year.slice(-2)) : ""}</td><td>${row.firstForSample ? esc(month) : ""}</td><td>${row.firstForSample ? esc(day) : ""}</td>
      <td>${row.firstForSample ? esc(row.sample.name || "—") : ""}</td><td>${row.firstForSample ? esc(row.sample.category || "—") : ""}</td>
      <td>${esc(row.analyte)}</td><td>${displayNumber(row.mass)}</td><td>${displayNumber(row.volume)}</td>
      <td>${esc(row.dilution || "—")}</td><td>${esc(row.raw)}</td>
      <td>${row.result === null || row.result === undefined ? "—" : `${displayNumber(row.result)} ${esc(row.unit || "")}`}</td>
      <td>${row.firstForSample ? esc(row.sample.analyst || "") : ""}</td><td>${esc(row.remark)}</td></tr>`;
  }).join("");
  const rawBlankRows = Array.from({ length: Math.max(0, 12 - rawRows.length) }, () =>
    `<tr class="blank-row">${"<td></td>".repeat(13)}</tr>`).join("");
  const rowHeight = Math.max(3.2, Math.min(8, 96 / Math.max(12, rawRows.length)));
  const names = (key) => [...new Set(payloads.map((payload) => payload.sample[key]).filter(Boolean))].join("、");
  return `<section class="print-document raw-ticket raw-ticket-page" style="--raw-row-height:${rowHeight}mm;--raw-font-size:${rawRows.length > 18 ? 9 : 11}px">
    <div class="ticket-code">${esc(profile.raw_code || "")}</div>
    <header class="ticket-brand"><h1>${esc(profile.company_name_cn || "")}</h1>
      ${profile.company_name_en ? `<p>${esc(profile.company_name_en)}</p>` : ""}</header>
    <h2>原 始 分 析 记 录</h2>
    <table class="raw-record-table"><thead><tr>
      <th colspan="3">分析日期</th><th rowspan="2">来样序号</th><th rowspan="2">样品名称</th>
      <th rowspan="2">分析项目</th><th rowspan="2">样品净重<br>(g)</th><th rowspan="2">定容<br>(mL)</th>
      <th rowspan="2">检测体积<br>(mL)</th><th rowspan="2">读数</th><th rowspan="2">分析结果</th>
      <th rowspan="2">分析者</th><th rowspan="2">备注</th></tr>
      <tr><th>年</th><th>月</th><th>日</th></tr></thead>
      <tbody>${rawBody}${rawBlankRows}<tr class="remark-row"><td colspan="3">备注</td><td colspan="10"></td></tr></tbody></table>
    <div class="ticket-signatures"><span>分析：${esc(names("analyst"))}</span><span>审核：${esc(names("reviewer"))}</span></div></section>`;
}

function renderPrintTickets() {
  $("#raw-ticket").innerHTML = combinedRawTicketHtml(REPORT_BATCH_DATA);
}

function manualReportEditRow(row = {}) {
  return `<tr class="${row._blank ? "manual-empty-row" : ""}">
    <td><input class="mr-item" value="${esc(row.item || "")}" placeholder="如 Cu"></td>
    <td><input class="mr-result" value="${esc(row.result || "")}" placeholder="数值或报告文本"></td>
    <td><input class="mr-unit" value="${esc(row.unit || "")}" placeholder="如 %"></td>
    <td><input class="mr-note" value="${esc(row.note || "")}" placeholder="可留空"></td>
    <td><button class="del mr-delete" type="button" title="删除该行">×</button></td></tr>`;
}

function bindManualReportRows(scope) {
  const tbody = scope.querySelector(".r-manual-table tbody");
  const appendBlankWhenNeeded = (event) => {
    const row = event.target.closest("tr");
    if (row !== tbody.lastElementChild) return;
    if (![...row.querySelectorAll("input:not([type=checkbox])")].some((input) => input.value.trim())) return;
    row.classList.remove("manual-empty-row");
    tbody.insertAdjacentHTML("beforeend", manualReportEditRow({ _blank: true }));
    bindManualReportRows(scope);
  };
  tbody.querySelectorAll("input").forEach((input) => input.oninput = appendBlankWhenNeeded);
  tbody.querySelectorAll(".mr-delete").forEach((button) => button.onclick = () => {
    button.closest("tr").remove();
    if (!tbody.lastElementChild || !tbody.lastElementChild.classList.contains("manual-empty-row")) {
      tbody.insertAdjacentHTML("beforeend", manualReportEditRow({ _blank: true }));
    }
    bindManualReportRows(scope);
  });
}

function collectManualReportRows(scope) {
  return [...scope.querySelectorAll(".r-manual-table tbody tr")].map((row) => ({
    item: row.querySelector(".mr-item").value.trim(),
    result: row.querySelector(".mr-result").value.trim(),
    unit: row.querySelector(".mr-unit").value.trim(),
    note: row.querySelector(".mr-note").value.trim(),
    include: true,
  })).filter((row) => row.item || row.result || row.unit || row.note);
}

function manualCardsHtml(data) {
  const rows = data.report_rows || [];
  const originals = new Map((data.default_report_rows || []).map((row) => [String(row.item).toLowerCase(), row]));
  const cards = rows.map((row) => {
    const original = originals.get(String(row.item).toLowerCase());
    const source = original
      ? `原值 ${esc(original.result)}${original.unit ? ` ${esc(original.unit)}` : ""}`
      : "手工新增";
    const noteRow = row.note
      ? `<div class="result-measurement-row"><div class="result-measurement-main"><b>说明</b><span>${esc(row.note)}</span></div></div>`
      : "";
    return `<article class="result-element-card result-manual-card">
      <header><span class="result-element-name">${esc(row.item)}</span><span class="result-element-final"><strong>${esc(row.result)} <small>${esc(row.unit || "")}</small></strong><em>${source}</em></span></header>
      <div class="result-measurements">${noteRow || '<div class="result-measurement-row"><div class="result-measurement-main"><b>手工补录</b><span>—</span></div></div>'}</div>
    </article>`;
  }).join("");
  return `<div class="result-element-grid" style="--result-grid-columns:5">${cards || '<p class="xrf-empty">暂无手工补录结果</p>'}</div>`;
}

function renderManualReportSection(scope, sid) {
  const editButton = scope.querySelector(".r-manual-edit");
  if (!editButton) { RESULT_MANUAL_EDITING.delete(sid); return; }
  const data = RESULT_DETAILS.get(sid);
  const manual = data?.manual_report;
  const editing = RESULT_MANUAL_EDITING.has(sid);
  const showManual = editing || Boolean(manual);
  const simpleDetails = scope.querySelector(".results-simple-details");
  if (simpleDetails) simpleDetails.hidden = editing;
  if (simpleDetails && manual && !editing) simpleDetails.innerHTML = manualCardsHtml(data);
  scope.querySelector(".r-manual-details").hidden = !showManual;
  scope.querySelector(".r-manual-table").closest(".table-shell").hidden = !editing;
  editButton.textContent = manual ? "修改手工补录" : "手工补录结果";
  if (!showManual) return;
  const rows = data.report_rows || [];
  scope.querySelector(".r-manual-audit").innerHTML = manual
    ? `<b>当前结果包含特权手工补录</b>　${esc(manual.updated_by)} · ${esc(manual.updated_at)}<br><small>卡片中同时显示系统原值与补录值；系统计算和仪器原始记录未被改写。</small>`
    : "<b>正在建立手工补录结果</b>　保存后作为最终结果内容，系统计算和仪器原始记录保持不变。";
  scope.querySelector(".r-manual-actions").hidden = !editing;
  const tbody = scope.querySelector(".r-manual-table tbody");
  if (editing) {
    tbody.innerHTML = rows.map(manualReportEditRow).join("") + manualReportEditRow({ _blank: true });
    bindManualReportRows(scope);
  }
}

function renderSpecialRecord(sample, special) {
  const values = { ...(special.raw_data || {}), ...(special.calculated_data || {}) };
  const groups = special.schema.groups.map((group) => `<table><tbody><tr class="special-record-group"><th colspan="${group.fields.length}">${esc(group.name)}</th></tr>
    <tr>${group.fields.map((field) => `<th>${esc(field.label)}${field.unit ? ` (${esc(field.unit)})` : ""}</th>`).join("")}</tr>
    <tr>${group.fields.map((field) => `<td>${esc(values[field.key] ?? "")}</td>`).join("")}</tr></tbody></table>`).join("");
  return `<div class="special-record">
    <h1>${esc(special.schema.title)}</h1>
    <div class="special-record-meta"><span>检测日期：${esc(reportDate(sample))}</span><span>来样序号：${esc(sample.name)}</span><span>样品名称：${esc(sample.category || "—")}</span></div>
    ${groups}<table><tbody><tr><th style="width:15%">备注</th><td class="special-record-note">${esc(special.raw_data?.note || "")}</td></tr></tbody></table>
    <div class="ticket-signatures"><span>检测人：${esc(sample.analyst || "")}</span><span>校核人：</span><span>审核人：${esc(sample.reviewer || "")}</span></div>
  </div>`;
}

function updateResultsExportState() {
  $("#results-excel").disabled = RESULT_SELECTED.size === 0;
  $("#results-clear-selection").disabled = RESULT_SELECTED.size === 0;
  renderResultsPager();
}

function collapseResultSample(sid) {
  if (!RESULT_EXPANDED.has(sid)) return false;
  RESULT_EXPANDED.delete(sid);
  RESULT_DETAILS.delete(sid);
  RESULT_MANUAL_EDITING.delete(sid);
  const index = RESULT_EXPANDED_ORDER.indexOf(sid);
  if (index >= 0) RESULT_EXPANDED_ORDER.splice(index, 1);
  return true;
}

async function expandResultSample(sample) {
  if (!sample) return;
  if (collapseResultSample(sample.id)) {
    renderResultsList();
    return;
  }
  RESULT_EXPANDED.add(sample.id);
  RESULT_EXPANDED_ORDER.push(sample.id);
  RESULT_MANUAL_EDITING.delete(sample.id);
  renderResultsList();
  await loadResultDetail(sample.id);
  $(`#results-list .result-detail-row[data-sid="${sample.id}"]`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function loadResultDetail(sid, rerender = true) {
  if (!RESULT_EXPANDED.has(sid)) return;
  const sequence = ++resultDetailSequence;
  RESULT_DETAIL_REQUESTS.set(sid, sequence);
  const data = await api("/api/report/" + sid);
  if (RESULT_DETAIL_REQUESTS.get(sid) !== sequence || !RESULT_EXPANDED.has(sid)) return;
  if (!data || data.ok === false) return;
  RESULT_DETAILS.set(sid, data);
  RESULT_MANUAL_EDITING.delete(sid);
  if (rerender) renderResultsList();
}

function resultDetailGroupsHtml(data) {
  const { sample, groups } = data;
  const reviewed = sample.status === "reviewed";
  const items = groups || [];
  const columns = 5;
  const xrfRows = items.flatMap((group) => group.rows
    .filter((row) => row.xrf_value_id)
    .map((row) => ({ ...row, analyte: group.analyte })))
    .sort((left, right) => (+right.value || 0) - (+left.value || 0));
  const xrf = xrfRows.length ? `<section class="result-xrf-composition">
    <h4>XRF 最终组成 <small>${xrfRows.length} 项 · Wt%</small></h4>
    <div class="xrf-result-list result-xrf-list">${xrfRows.map((row) => `<div>
      <input class="xrf-report-use" type="checkbox" data-xrf-value="${row.xrf_value_id}" aria-label="${esc(row.analyte)}参与最终结果" title="参与最终结果" ${row.selection === "exclude" ? "" : "checked"} ${reviewed ? "disabled" : ""}>
      <b>${esc(row.analyte)}</b><span>${esc(xrfValueText(row.value))}%</span>
    </div>`).join("")}</div>
  </section>` : "";
  const cards = items.map((group) => ({ ...group, rows: group.rows.filter((row) => !row.xrf_value_id) }))
    .filter((group) => group.rows.length)
    .map((g) => {
    const final = g.final
      ? `<strong>${esc(g.final.value)} <small>${esc(g.final.unit || "")}</small></strong><em>${esc(g.final.mode)}${g.final.based_on > 1 ? ` × ${g.final.based_on}` : ""}</em>`
      : "<strong>—</strong><em>暂无最终值</em>";
    const rows = g.rows.map((r) => {
      const canChoose = g.rows.length > 1;
      const use = canChoose
        ? `<label class="report-use-label"><input class="report-use" type="checkbox" data-said="${r.sample_analyte_id || ""}" ${r.selection === "exclude" ? "" : "checked"} ${reviewed ? 'disabled title="已审核样品需先特权退回才能改参与"' : ""}>参与</label>`
        : "—";
      const result = r.value === null || r.value === undefined ? `<i>${esc(r.unit || "")}</i>` : `${esc(r.value)} ${esc(r.unit || "")}`;
      const instrument = [r.instrument, r.method].filter(Boolean).join(" / ") || "—";
      return `<div class="result-measurement-row">
        <div class="result-measurement-main"><b title="${esc(r.prep || "—")}">${esc(r.prep || "—")}</b><span>${result}</span></div>
        <div class="result-measurement-meta"><span title="${esc(instrument)}">${esc(instrument)}</span><span>${use}</span></div>
      </div>`;
    }).join("");
    return `<article class="result-element-card">
      <header><span class="result-element-name">${esc(g.analyte)}</span><span class="result-element-final">${final}</span></header>
      <div class="result-measurements">${rows || '<span class="hint">暂无测量结果</span>'}</div>
    </article>`;
  }).join("");
  const regular = cards ? `<div class="result-element-grid" style="--result-grid-columns:${columns}">${cards}</div>` : "";
  return xrf + regular || '<p class="xrf-empty">暂无结果</p>';
}

function resultDetailSpecialHtml(data) {
  const { special } = data;
  const values = { ...(special?.raw_data || {}), ...(special?.calculated_data || {}) };
  const rows = (special?.schema?.groups || []).map((group) =>
    `<tr class="analyte-group"><td colspan="3"><b>${esc(group.name)}</b></td></tr>` +
    (group.fields || []).map((field) => `<tr class="sub-row"><td>${esc(field.label)}</td>
      <td>${esc(values[field.key] ?? "—")}</td><td>${esc(field.unit || "")}</td></tr>`).join("")
  ).join("");
  return `<p class="hint">${esc(special?.schema?.title || "专项检测")}${special?.method_name ? ` · ${esc(special.method_name)}` : ""}${special?.instrument ? ` · ${esc(special.instrument)}` : ""}</p>
    <table class="data-grid results-simple-table">
    <thead><tr><th>项目</th><th>结果值</th><th>单位</th></tr></thead>
    <tbody>${rows || '<tr><td colspan="3" class="xrf-empty">暂无专项数据</td></tr>'}</tbody></table>`;
}

function resultDetailHtml(sid) {
  const data = RESULT_DETAILS.get(sid);
  if (!data || data.sample?.id !== sid) return '<p class="hint">正在读取结果明细…</p>';
  const { sample } = data;
  const statusLabel = META.sample_statuses[sample.status] || sample.status;
  const reviewable = ["completed", "reviewed"].includes(sample.status);
  const isSpecial = sample.workflow_type === "special";
  const manualAllowed = reviewable && !isSpecial;
  const reviewButton = reviewable
    ? `<button type="button" class="results-review ${sample.status === "reviewed" ? "danger-soft" : "primary"}">${sample.status === "reviewed" ? "特权退回审核" : "审核确认"}</button>` : "";
  const manualTitle = isSpecial
    ? "专项检测不支持手工补录"
    : (manualAllowed ? "需要特权权限、操作原因和再次密码确认" : "样品测量完成后才能手工补录结果");
  return `<div class="result-detail">
    <div class="result-detail-head">
      <b>${esc(sample.lims_no || "#" + sample.id)}</b><span>${esc(sample.name)}</span>
      <span class="sample-status ${esc(sample.status)}">${esc(statusLabel)}</span>
      ${statusActorHtml(sample)}
      <span class="footer-spacer"></span>
       <button type="button" class="r-manual-edit primary" ${manualAllowed ? "" : "disabled"} title="${esc(manualTitle)}">手工补录结果</button>
      ${reviewButton}
    </div>
    <div class="results-simple-details">${isSpecial ? resultDetailSpecialHtml(data) : resultDetailGroupsHtml(data)}</div>
    <div class="r-manual-details" hidden>
      <div class="r-manual-audit manual-report-audit"></div>
       <div class="table-shell"><table class="r-manual-table data-grid spreadsheet"><thead><tr><th>结果项目</th><th>结果</th><th>单位</th><th>说明</th><th></th></tr></thead><tbody></tbody></table></div>
      <div class="r-manual-actions editor-footer"><button class="r-manual-cancel" type="button">取消</button>
        <button class="r-manual-restore" type="button">恢复系统计算</button><span class="footer-spacer"></span>
        <span class="r-manual-msg"></span><button class="r-manual-save primary" type="button">填写原因、验证密码并保存</button></div>
    </div>
  </div>`;
}

function bindResultDetail(scope, sid) {
  const data = RESULT_DETAILS.get(sid);
  if (!scope || !data) return;
  const reviewButton = scope.querySelector(".results-review");
  if (reviewButton) reviewButton.onclick = () => reviewResultSample(sid);
  scope.querySelectorAll(".report-use").forEach((checkbox) => checkbox.onchange = async () => {
    const result = await api(`/api/sample-analytes/${checkbox.dataset.said}/report-use`, "PUT", {
      use: checkbox.checked,
    });
    if (!result.ok) { checkbox.checked = !checkbox.checked; return; }
    await loadResultDetail(sid);
  });
  scope.querySelectorAll(".xrf-report-use").forEach((checkbox) => checkbox.onchange = async () => {
    const result = await api(`/api/xrf/values/${checkbox.dataset.xrfValue}/report-use`, "PUT", { use: checkbox.checked });
    if (!result.ok) { checkbox.checked = !checkbox.checked; return; }
    await loadResultDetail(sid);
  });
  const editButton = scope.querySelector(".r-manual-edit");
  editButton.onclick = () => {
    if (!RESULT_DETAILS.has(sid) || editButton.disabled) return;
    RESULT_MANUAL_EDITING.add(sid);
    renderManualReportSection(scope, sid);
    scope.querySelector(".r-manual-table input")?.focus();
  };
  scope.querySelector(".r-manual-cancel").onclick = () => {
    RESULT_MANUAL_EDITING.delete(sid);
    renderManualReportSection(scope, sid);
  };
  scope.querySelector(".r-manual-save").onclick = async () => {
    const rows = collectManualReportRows(scope);
    if (!rows.length) { showError("请至少填写一条结果；如需取消手工补录，请使用“恢复系统计算”。"); return; }
    const reason = prompt("请输入手工补录原因。该原因会写入审计记录。", "补录检测结果");
    if (!reason?.trim()) return;
    if (!await requestAuthorization("保存手工补录必须重新输入具备“审核退回与手工结果补录”权限的用户密码。本次确认仅用于这一次保存。", "result_override")) return;
    const result = await api(`/api/reports/${sid}/manual`, "PUT", { rows, reason: reason.trim() }, false);
    if (!result.ok) return;
    await loadResultDetail(sid);
  };
  scope.querySelector(".r-manual-restore").onclick = async () => {
    if (!RESULT_DETAILS.get(sid)?.manual_report) { RESULT_MANUAL_EDITING.delete(sid); renderManualReportSection(scope, sid); return; }
    if (!confirm("确认删除手工补录内容并恢复系统计算结果？此操作会记录审计。")) return;
    const reason = prompt("请输入恢复系统计算的原因。", "撤销手工补录");
    if (!reason?.trim()) return;
    if (!await requestAuthorization("恢复系统计算会改变最终结果，必须重新输入具备“审核退回与手工结果补录”权限的用户密码。", "result_override")) return;
    const result = await api(`/api/reports/${sid}/manual`, "DELETE", { reason: reason.trim() }, false);
    if (!result.ok) return;
    await loadResultDetail(sid);
  };
}

function renderResultsList() {
  const body = $("#results-list tbody");
  $("#results-collapse-all").disabled = RESULT_EXPANDED.size === 0;
  body.innerHTML = RESULT_SAMPLES.map((sample) => {
    const expanded = RESULT_EXPANDED.has(sample.id);
    const analytes = String(sample.analyte_names || "").split(", ").filter(Boolean);
    const summary = analytes.length
      ? analytes.slice(0, 8).map((name) => `<span>${esc(name)}</span>`).join("") + (analytes.length > 8 ? `<small>+${analytes.length - 8}</small>` : "")
      : "<i>展开查看结果</i>";
    return `<tr class="result-row ${expanded ? "expanded" : ""}" data-sid="${sample.id}" aria-expanded="${expanded}">
      <td><input class="result-select" type="checkbox" ${RESULT_SELECTED.has(sample.id) ? "checked" : ""} aria-label="选择 ${esc(sample.name)}"></td>
      <td><b>${esc(sample.lims_no || "#" + sample.id)}</b></td><td>${esc(sample.name)}</td><td>${esc(sample.category || "—")}</td>
      <td><span class="sample-status ${esc(sample.status)}">${esc(META.sample_statuses[sample.status] || sample.status)}</span></td>
      <td><div class="result-summary">${summary}</div></td><td>${esc(sample.reviewer || (sample.status === "completed" ? "待审核" : "—"))}</td>
      <td><button class="result-expand" type="button">${expanded ? "收起" : "展开"}</button></td></tr>
      ${expanded ? `<tr class="result-detail-row" data-sid="${sample.id}"><td colspan="8">${resultDetailHtml(sample.id)}</td></tr>` : ""}`;
  }).join("") || '<tr><td colspan="8" class="xrf-empty">没有已制样或后续阶段的样品</td></tr>';
  body.querySelectorAll(".result-detail-row").forEach((detailRow) => {
    const sid = +detailRow.dataset.sid;
    renderManualReportSection(detailRow, sid);
    bindResultDetail(detailRow, sid);
  });
  body.querySelectorAll(".result-select").forEach((checkbox) => checkbox.onchange = (event) => {
    const id = +event.currentTarget.closest("tr[data-sid]")?.dataset.sid;
    if (!id) return;
    if (event.currentTarget.checked) RESULT_SELECTED.add(id); else RESULT_SELECTED.delete(id);
    updateResultsExportState();
  });
  body.querySelectorAll(".result-row").forEach((row) => row.onclick = (event) => {
    if (event.target.closest("input")) return;
    const id = +row.dataset.sid;
    if (event.ctrlKey || event.metaKey) {
      if (RESULT_SELECTED.has(id)) RESULT_SELECTED.delete(id); else RESULT_SELECTED.add(id);
      renderResultsList();
      return;
    }
    expandResultSample(RESULT_SAMPLES.find((sample) => sample.id === id));
  });
  const visibleIds = RESULT_SAMPLES.map((sample) => sample.id);
  $("#results-check-all").checked = Boolean(visibleIds.length) && visibleIds.every((id) => RESULT_SELECTED.has(id));
  updateResultsExportState();
}

function renderResultsPager() {
  const pages = Math.max(1, Math.ceil(RESULT_TOTAL / RESULT_PAGE_SIZE));
  const start = RESULT_TOTAL ? RESULT_PAGE * RESULT_PAGE_SIZE + 1 : 0;
  const end = Math.min((RESULT_PAGE + 1) * RESULT_PAGE_SIZE, RESULT_TOTAL);
  $("#results-page-label").textContent = `${RESULT_PAGE + 1} / ${pages}`;
  $("#results-page-prev").disabled = RESULT_PAGE === 0;
  $("#results-page-next").disabled = RESULT_PAGE + 1 >= pages;
  $("#results-count").textContent = `共 ${RESULT_TOTAL} 个，当前 ${start}-${end} · 已选 ${RESULT_SELECTED.size} 个`;
}

async function loadResultsPage() {
  const query = $("#results-search").value.trim();
  const result = await api(`/api/samples?paged=1&limit=${RESULT_PAGE_SIZE}&offset=${RESULT_PAGE * RESULT_PAGE_SIZE}&type=all&status=queued,measuring,partially_done,completed,reviewed&q=${encodeURIComponent(query)}`);
  if (!result || result.ok === false) return;
  RESULT_TOTAL = result.total || result.rows.length;
  const lastPage = Math.max(0, Math.ceil(RESULT_TOTAL / RESULT_PAGE_SIZE) - 1);
  if (RESULT_PAGE > lastPage) {
    RESULT_PAGE = lastPage;
    return loadResultsPage();
  }
  RESULT_SAMPLES = result.rows;
  $("#results-template").innerHTML = '<option value="">全局默认</option>' +
    (META.result_order_templates || []).map((template) => `<option value="${template.id}">${esc(template.name)}</option>`).join("");
  const visibleIds = new Set(RESULT_SAMPLES.map((sample) => sample.id));
  for (const sid of [...RESULT_EXPANDED]) {
    if (!visibleIds.has(sid)) collapseResultSample(sid);
  }
  renderResultsList();
  await Promise.all([...RESULT_EXPANDED].map((sid) => loadResultDetail(sid, false)));
  renderResultsList();
}

async function reviewResultSample(sid) {
  const sample = RESULT_DETAILS.get(sid)?.sample;
  if (!sample) return;
  if (sample.status === "completed") {
    const result = await api(`/api/samples/${sample.id}/status`, "PUT", { status: "reviewed" });
    if (!result.ok) return;
  } else if (sample.status === "reviewed") {
    const reason = prompt("请输入审核退回原因。该原因会写入审计历史。", "结果需复核");
    if (!reason?.trim()) return;
    if (!await requestAuthorization("审核退回是特权操作。请输入具备“审核退回与手工结果补录”权限的用户密码。", "result_override")) return;
    const result = await api(`/api/samples/${sample.id}/status`, "PUT", {
      status: "completed", reason: reason.trim(),
    }, false);
    if (!result.ok) return;
  }
  await loadResultsPage();
}

function combinedFinalTicketHtml(payloads) {
  if (!payloads.length) return '<div class="report-empty-preview">选择已审核样品后生成组合报告预览</div>';
  const first = payloads[0];
  const profile = first.report_profile || {};
  const rows = [];
  for (const payload of payloads) {
    let selected = (payload.report_rows || []).filter((row) => row.include !== false);
    if (payload.sample.workflow_type === "special") {
      const special = payload.special || {};
      const values = { ...(special.raw_data || {}), ...(special.calculated_data || {}) };
      selected = (special.schema?.groups || []).flatMap((group) => group.fields || []).filter((field) =>
        values[field.key] !== undefined && values[field.key] !== "").map((field) => ({
          item: field.label, result: values[field.key], unit: field.unit || "",
        }));
    }
    if (!selected.length) selected.push({ item: "—", result: "—", unit: "" });
    selected.forEach((row, index) => rows.push({ payload, row, first: index === 0, count: selected.length }));
  }
  const body = rows.map(({ payload, row, first: firstRow, count }) => `<tr>
    ${firstRow ? `<td rowspan="${count}">${esc(payload.sample.name || "—")}</td><td rowspan="${count}">${esc(payload.sample.category || "—")}</td>` : ""}
    <td>${esc(row.item)}</td><td>${esc(displayNumber(row.result))} ${esc(row.unit || "")}</td></tr>`).join("");
  const blankRows = Array.from({ length: Math.max(0, 12 - rows.length) }, () =>
    '<tr class="blank-row"><td></td><td></td><td></td><td></td></tr>').join("");
  const values = (key) => [...new Set(payloads.map((payload) => payload.sample[key]).filter(Boolean))].join("、");
  return `<div class="final-serial">${esc(values("report_no"))}</div><div class="ticket-code">${esc(profile.final_code || "")}</div>
    <header class="ticket-brand"><h1>${esc(profile.company_name_cn || "")}</h1></header><h2>分 析 报 告 票</h2>
    <div class="final-meta"><span>来样单位：${esc(values("customer"))}</span><span>分析时间：${esc(values("analysis_date") || reportDate(first.sample))}</span></div>
    <table class="final-report-table"><thead><tr><th>来样序号</th><th>样品名称</th><th>分析项目</th><th>分析结果</th></tr></thead><tbody>${body}${blankRows}</tbody></table>
    <div class="ticket-signatures"><span>分析：${esc(values("analyst"))}</span><span>审核：${esc(values("reviewer"))}</span></div>
    <div class="report-notes"><b>说明：</b><ol><li>本结果只对来样负责。</li><li>若对本结果有异议，可在15个工作日内提出复查申请。</li><li>本检测报告需部门领导审核签字方能生效。</li></ol></div>`;
}

function renderReportBatch(payloads) {
  REPORT_BATCH_DATA = payloads;
  REPORT_DATA = payloads[0] || null;
  const first = REPORT_DATA;
  $(".report-compose").hidden = !first;
  $("#r-excel-export").disabled = payloads.length !== 1;
  $("#r-excel-export").title = payloads.length > 1 ? "单样品 Excel 请只保留一个勾选样品" : "";
  $("#r-edit-sample").hidden = true;
  $("#r-enter-data").hidden = true;
  $("#r-order-default").hidden = true;
  $("#r-special-details").hidden = true;
  $("#r-regular-details").hidden = false;
  if (!first) {
    $("#r-status-info").textContent = "";
    $("#r-head").textContent = "";
    $("#r-table tbody").innerHTML = "";
    return;
  }
  $("#r-status-info").innerHTML = `<span class="sample-status reviewed">已选 ${payloads.length} 个已审核样品</span>`;
  $("#r-calculation-title").textContent = "所选样品结果编排";
  $("#r-head").innerHTML = `以下内容按样品顺序完整展示。可调整样品顺序、各样品内的元素顺序及是否打印。`;
  $("#r-report-profile").innerHTML = (META.report_profiles || []).map((profile) =>
    `<option value="${profile.id}">${esc(profile.name)} · ${esc(profile.company_name_cn)}</option>`).join("");
  $("#r-report-profile").value = first.report_profile?.id || "";
  $("#r-customer").value = first.sample.customer || "";
  $("#r-report-no").value = first.sample.report_no || "";
  $("#r-analysis-date").value = reportDate(first.sample);
  const editorCounts = new Map();
  for (const payload of payloads) {
    for (const editor of payload.data_editors || []) {
      const name = String(editor.name || "").trim();
      if (!name) continue;
      editorCounts.set(name, (editorCounts.get(name) || 0) + (editor.count || 0));
    }
  }
  const analystDefault = [...editorCounts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh"))
    .map(([name]) => name).join(" ");
  $("#r-analyst").value = analystDefault || first.sample.analyst || "";
  $("#r-reviewer").value = [...new Set(payloads.map((data) => data.sample.reviewer).filter(Boolean))].join("、");
  $$("#r-customer, #r-report-no, #r-analysis-date, #r-analyst, #r-report-profile")
    .forEach((control) => control.disabled = false);
  $("#r-reviewer").disabled = true;
  $("#r-save-meta").disabled = false;
  $("#r-save-meta").textContent = "保存整组票面信息";
  $("#r-save-meta").title = `保存到全部 ${payloads.length} 个样品`;
  $("#r-meta-msg").textContent = `票面信息将统一应用到全部 ${payloads.length} 个样品`;

  let html = "";
  payloads.forEach((reportData, sampleIndex) => {
    const { sample, groups, special } = reportData;
    const prepText = (reportData.preps || []).map((prep) => prep.name).filter(Boolean).join("、") || "—";
    html += `<tr class="report-sample-group" data-sid="${sample.id}"><td colspan="6">
      <span class="report-sample-order-actions noprint"><button type="button" class="batch-sample-up" ${sampleIndex === 0 ? "disabled" : ""} title="样品前移">↑</button><button type="button" class="batch-sample-down" ${sampleIndex === payloads.length - 1 ? "disabled" : ""} title="样品后移">↓</button></span>
      <strong>${sampleIndex + 1}. 来样序号：${esc(sample.name || "—")}</strong>
      <span>样品名称：${esc(sample.category || "—")}</span>
      <small>LIMS ${esc(sample.lims_no || "#" + sample.id)} · 溶样 ${esc(prepText)}</small>
      ${reportData.manual_report ? `<span class="manual-result-source" title="系统计算结果被历史手工结果覆盖；请在结果页查看或恢复系统计算">历史手工结果 · ${esc(reportData.manual_report.updated_by)} · ${esc(reportData.manual_report.updated_at)}</span>` : ""}
      ${sample.workflow_type === "regular" && !reportData.manual_report ? '<button type="button" class="sample-order-default noprint">恢复该样品默认元素顺序</button>' : ""}
    </td></tr>`;
    if (sample.workflow_type === "special") {
      const values = { ...(special?.raw_data || {}), ...(special?.calculated_data || {}) };
      for (const group of special?.schema?.groups || []) for (const field of group.fields || []) {
        if (values[field.key] === undefined || values[field.key] === "") continue;
        html += `<tr class="analyte-group special-report-row" data-sid="${sample.id}"><td><b>${esc(field.label)}</b></td><td>专项检测</td>
          <td>${esc(special.method_name || "—")}${special.instrument ? ` / ${esc(special.instrument)}` : ""}</td><td>${esc(values[field.key])}</td>
          <td><b>${esc(values[field.key])}</b> ${esc(field.unit || "")}</td><td>打印</td></tr>`;
      }
    } else if (reportData.manual_report) {
      for (const row of reportData.report_rows || []) {
        const key = `m:${String(row.item).toLowerCase()}`;
        html += `<tr class="analyte-group manual-print-row" data-sid="${sample.id}" data-key="${esc(key)}">
          <td><b>${esc(row.item)}</b>${row.note ? `<small>${esc(row.note)}</small>` : ""}</td><td>历史手工结果覆盖</td><td>—</td><td>—</td>
          <td><b>${esc(row.result)}</b> ${esc(row.unit || "")}</td><td><label class="print-use-label"><input class="print-use" type="checkbox" data-sid="${sample.id}" data-key="${esc(key)}" ${row.include === false ? "" : "checked"}>打印</label></td></tr>`;
      }
    } else for (const group of groups || []) {
      const final = group.final
        ? `<b>${esc(group.final.value)}</b> ${esc(group.final.unit || "")} <small>(${esc(group.final.mode)}${group.final.based_on > 1 ? ` × ${group.final.based_on}` : ""})</small>`
        : "<i>—</i>";
      html += `<tr class="analyte-group" data-sid="${sample.id}" data-aid="${group.analyte_id || ""}" data-key="${esc(group.key || "")}">
        <td colspan="5"><span class="report-order-actions noprint"><button class="r-order-up" type="button" title="元素上移" ${group.analyte_id ? "" : "disabled"}>↑</button><button class="r-order-down" type="button" title="元素下移" ${group.analyte_id ? "" : "disabled"}>↓</button></span>
        <b>${esc(group.analyte)}</b>　最终: ${final}</td><td><label class="print-use-label"><input class="print-use" type="checkbox" data-sid="${sample.id}" data-key="${esc(group.key || "")}" ${group.print === false ? "" : "checked"}>打印</label></td></tr>`;
      for (const row of group.rows || []) {
        const raw = row.readings?.length ? row.readings.map((reading) => {
          const label = row.method ? Object.entries(reading.extra || {}).map(([key, value]) => `${key}=${value}`).join(" ") || "—" : (reading.raw ?? "—");
          return reading.used ? `<b>${esc(label)}</b>` : `<span class="rd-unused">${esc(label)}</span>`;
        }).join(" / ") : "—";
        const result = row.value === null || row.value === undefined ? `<i>${esc(row.unit || "")}</i>` : `${esc(row.value)} ${esc(row.unit || "")}`;
        html += `<tr class="sub-row" data-sid="${sample.id}"><td></td><td>${esc(row.prep || "—")}</td><td>${row.instrument ? esc(row.instrument) : "—"}${row.method ? " / " + esc(row.method) : ""}</td><td>${raw}</td><td>${result}</td><td>—</td></tr>`;
      }
    }
  });
  $("#r-table tbody").innerHTML = html;
  $("#r-table").classList.remove("manual-report-table");

  $$("#r-table .report-sample-group").forEach((row) => {
    const sid = +row.dataset.sid;
    row.querySelector(".batch-sample-up").onclick = () => moveReportSample(sid, -1);
    row.querySelector(".batch-sample-down").onclick = () => moveReportSample(sid, 1);
    const reset = row.querySelector(".sample-order-default");
    if (reset) reset.onclick = async () => {
      const result = await api(`/api/samples/${sid}/report-order`, "PUT", { analyte_ids: [] });
      if (result.ok) await loadReport();
    };
  });
  payloads.forEach((reportData) => {
    const sid = reportData.sample.id;
    const rows = $$(`#r-table tr.analyte-group[data-sid="${sid}"][data-aid]`).filter((row) => row.dataset.aid);
    rows.forEach((row, index) => {
      const save = async (step) => {
        const ids = rows.map((item) => +item.dataset.aid);
        [ids[index], ids[index + step]] = [ids[index + step], ids[index]];
        const result = await api(`/api/samples/${sid}/report-order`, "PUT", { analyte_ids: ids });
        if (result.ok) await loadReport();
      };
      row.querySelector(".r-order-up").onclick = () => { if (index) save(-1); };
      row.querySelector(".r-order-down").onclick = () => { if (index < rows.length - 1) save(1); };
    });
  });
  $$("#r-table .print-use").forEach((checkbox) => checkbox.onchange = async () => {
    const sid = +checkbox.dataset.sid;
    const excludes = $$(`#r-table .print-use[data-sid="${sid}"]:not(:checked)`).map((item) => item.dataset.key).filter(Boolean);
    const result = await api(`/api/samples/${sid}/report-print`, "PUT", { excludes });
    if (!result.ok) checkbox.checked = !checkbox.checked;
    else await loadReport();
  });
}

async function updateFinalTicket() {
  const sequence = ++REPORT_QUEUE_SEQUENCE;
  const ids = [...REPORT_SELECTED];
  renderReportPager();
  $("#r-print-raw").disabled = !ids.length;
  $("#r-print-raw").textContent = ids.length
    ? `打印合并原始分析记录（${ids.length}个样品 / A4横向）` : "打印合并原始分析记录（A4横向）";
  $("#r-print-raw").title = ids.length ? "所选样品合并到同一张原始分析记录" : "请先勾选需要打印原始记录的已审核样品";
  $("#r-print-final").disabled = !ids.length;
  $("#r-print-final").title = ids.length ? "" : "请先勾选需要组合打印的已审核样品";
  if (!ids.length) {
    renderReportBatch([]);
    $("#raw-ticket").innerHTML = '<div class="report-empty-preview">选择已审核样品后生成原始分析记录预览</div>';
    $("#final-ticket").innerHTML = combinedFinalTicketHtml([]);
    return;
  }
  const payloads = await Promise.all(ids.map((id) => api(`/api/report/${id}`)));
  if (sequence !== REPORT_QUEUE_SEQUENCE) return;
  const valid = payloads.filter((payload) => payload?.sample?.status === "reviewed");
  renderReportBatch(valid);
  $("#raw-ticket").innerHTML = combinedRawTicketHtml(valid);
  $("#final-ticket").innerHTML = combinedFinalTicketHtml(valid);
}

function syncReportFocus() {
  REPORT_FOCUS_ID = [...REPORT_SELECTED][0] ?? null;
  $("#r-sample").value = REPORT_FOCUS_ID || "";
  const first = REPORT_KNOWN.get(REPORT_FOCUS_ID) || REPORT_SAMPLES.find((sample) => sample.id === REPORT_FOCUS_ID);
  $("#r-sample-search").value = first ? `#${first.id} ${first.name}` : "";
}

async function moveReportSample(id, step) {
  const ids = [...REPORT_SELECTED];
  const index = ids.indexOf(id);
  const target = index + step;
  if (index < 0 || target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target], ids[index]];
  REPORT_SELECTED.clear();
  ids.forEach((sampleId) => REPORT_SELECTED.add(sampleId));
  syncReportFocus();
  renderReportSamples();
  await loadReport();
}

function renderReportPager() {
  const pages = Math.max(1, Math.ceil(REPORT_TOTAL / REPORT_PAGE_SIZE));
  const start = REPORT_TOTAL ? REPORT_PAGE * REPORT_PAGE_SIZE + 1 : 0;
  const end = Math.min((REPORT_PAGE + 1) * REPORT_PAGE_SIZE, REPORT_TOTAL);
  $("#report-page-label").textContent = `${REPORT_PAGE + 1} / ${pages}`;
  $("#report-page-prev").disabled = REPORT_PAGE === 0;
  $("#report-page-next").disabled = REPORT_PAGE + 1 >= pages;
  $("#report-count").textContent = `已审核 ${REPORT_TOTAL} 个，当前 ${start}-${end} · 已选 ${REPORT_SELECTED.size} 个`;
}

function renderReportSamples() {
  const selectedIds = [...REPORT_SELECTED];
  const byId = (id) => REPORT_KNOWN.get(id) || REPORT_SAMPLES.find((sample) => sample.id === id);
  const displayed = [
    ...selectedIds.map((id) => byId(id)).filter(Boolean),
    ...REPORT_SAMPLES.filter((sample) => !REPORT_SELECTED.has(sample.id)),
  ];
  $("#report-samples").innerHTML = displayed.map((sample) => {
    const order = selectedIds.indexOf(sample.id);
    return `<div class="report-sample-option" data-sid="${sample.id}">
    <input type="checkbox" value="${sample.id}" ${REPORT_SELECTED.has(sample.id) ? "checked" : ""} aria-label="选择 ${esc(sample.name)}">
    <span class="report-selection-order">${order >= 0 ? order + 1 : ""}</span>
    <span class="report-sample-identity"><b>${esc(sample.name || "未填来样序号")}</b><em>${esc(sample.category || "未填样品名称")}</em></span>
    <small>${esc(sample.lims_no || "#" + sample.id)} · ${esc(sample.reviewer || "已审核")}</small>
    <span class="report-sample-move">${order >= 0 ? `<button type="button" data-step="-1" ${order === 0 ? "disabled" : ""} title="前移">↑</button><button type="button" data-step="1" ${order === selectedIds.length - 1 ? "disabled" : ""} title="后移">↓</button>` : ""}</span></div>`;
  }).join("") ||
    '<p class="hint">没有匹配的已审核样品</p>';
  $$("#report-samples .report-sample-option").forEach((option) => {
    const id = +option.dataset.sid;
    const checkbox = option.querySelector("input");
    checkbox.onchange = async () => {
      if (checkbox.checked) {
        REPORT_SELECTED.add(id);
      } else {
        REPORT_SELECTED.delete(id);
      }
      syncReportFocus();
      renderReportSamples();
      await loadReport();
    };
    option.onclick = async (event) => {
      if (event.target.closest("input, button")) return;
      if (!REPORT_SELECTED.has(id)) {
        REPORT_SELECTED.add(id);
      }
      syncReportFocus();
      renderReportSamples();
      await loadReport();
    };
    option.querySelectorAll(".report-sample-move button").forEach((button) => button.onclick = () =>
      moveReportSample(id, +button.dataset.step));
  });
}

async function loadReportPrintPage() {
  const query = $("#report-search").value.trim();
  const result = await api(`/api/samples?paged=1&limit=${REPORT_PAGE_SIZE}&offset=${REPORT_PAGE * REPORT_PAGE_SIZE}&type=all&status=reviewed&q=${encodeURIComponent(query)}`);
  if (!result || result.ok === false) return;
  REPORT_TOTAL = result.total || result.rows.length;
  const lastPage = Math.max(0, Math.ceil(REPORT_TOTAL / REPORT_PAGE_SIZE) - 1);
  if (REPORT_PAGE > lastPage) {
    REPORT_PAGE = lastPage;
    return loadReportPrintPage();
  }
  REPORT_SAMPLES = result.rows;
  result.rows.forEach((sample) => REPORT_KNOWN.set(sample.id, sample));
  const available = new Set(REPORT_SAMPLES.map((sample) => sample.id));
  if (!REPORT_SELECTED.size && CURRENT_SAMPLE?.status === "reviewed" && available.has(CURRENT_SAMPLE.id)) {
    REPORT_SELECTED.add(CURRENT_SAMPLE.id);
  }
  renderReportSamples();
  renderReportPager();
  syncReportFocus();
  await loadReport();
}

async function loadReport() {
  await updateFinalTicket();
  return;
  const sid = $("#r-sample").value;
  $("#r-excel-export").disabled = !sid;
  $(".report-compose").hidden = !sid;
  if (!sid) {
    REPORT_DATA = null;
    $("#r-status-info").innerHTML = "";
    $("#raw-ticket").innerHTML = '<div class="report-empty-preview">选择已审核样品后生成原始分析记录预览</div>';
    return;
  }
  const sequence = ++reportLoadSequence;
  const reportData = await api("/api/report/" + sid);
  if (!reportData || reportData.ok === false) return;
  const { sample, preps, groups, special } = reportData;
  if (sequence !== reportLoadSequence || $("#r-sample").value !== sid) return;
  const statusLabel = META.sample_statuses[sample.status] || sample.status;
  $("#r-status-info").innerHTML = `<span class="sample-status ${esc(sample.status)}">${esc(statusLabel)}</span>${statusActorHtml(sample)}`;
  REPORT_DATA = reportData;
  const reportLocked = ["reported", "cancelled"].includes(sample.status);
  $("#r-customer").value = sample.customer || "";
  $("#r-report-profile").innerHTML = (META.report_profiles || []).map((profile) =>
    `<option value="${profile.id}">${esc(profile.name)} · ${esc(profile.company_name_cn)}</option>`).join("");
  $("#r-report-profile").value = reportData.report_profile?.id || "";
  $("#r-report-no").value = sample.report_no || "";
  $("#r-analysis-date").value = reportDate(sample);
  $("#r-analyst").value = sample.analyst || "";
  $("#r-reviewer").value = sample.reviewer || "";
  $$("#r-customer, #r-report-no, #r-analysis-date, #r-analyst, #r-report-profile")
    .forEach((control) => control.disabled = reportLocked);
  $("#r-reviewer").disabled = true;
  $("#r-save-meta").disabled = reportLocked;
  $("#r-save-meta").title = reportLocked ? "已作废样品的票面信息只读" : "";
  $("#r-meta-msg").textContent = "";
  const isSpecialSample = sample.workflow_type === "special";
  $("#r-regular-details").hidden = isSpecialSample;
  $("#r-special-details").hidden = !isSpecialSample;
  $("#raw-ticket").closest(".ticket-preview-shell").hidden = false;
  $("#final-ticket").closest(".ticket-preview-shell").hidden = false;
  if (isSpecialSample) {
    $("#r-special-details").innerHTML = `<h3>${esc(special?.method_name || "专项检测")} · ${esc(special?.instrument || "")}</h3><p class="hint">专项检测结果随当前勾选样品加入组合报告；原始分析记录按专项表样式打印。</p>`;
    renderPrintTickets();
    await updateFinalTicket();
    return;
  }
  const prepStr = preps.map((p) =>
    `${p.name}(${sample.is_liquid ? "" : `${p.mass_g ?? "?"}g/${p.volume_ml ?? "?"}mL/`}${p.dilution_label || "—"})`
  ).join("　");
  $("#r-head").innerHTML = `<b>${esc(sample.name)}</b> (#${sample.id}) ·
    ${sample.is_liquid ? "液体样" : "固体"}${sample.category ? ` · ${esc(sample.category)}` : ""}${sample.xrf ? " · 含XRF粗扫" : ""} ·
    ${esc(sample.created_at)}<br>溶样: ${esc(prepStr) || "—"}`;
  let html = "";
  if (reportData.manual_report) {
    for (const row of reportData.report_rows || []) {
      html += `<tr class="analyte-group manual-print-row" data-key="${esc(row.key || `m:${String(row.item).toLowerCase()}`)}">
        <td><b>${esc(row.item)}</b>${row.note ? `<small>${esc(row.note)}</small>` : ""}</td>
        <td>手工补录</td><td>—</td><td>—</td><td><b>${esc(row.result)}</b> ${esc(row.unit || "")}</td>
        <td><label class="print-use-label"><input class="print-use" type="checkbox" data-key="${esc(row.key || `m:${String(row.item).toLowerCase()}`)}" ${row.include === false ? "" : "checked"}>打印</label></td></tr>`;
    }
  } else for (const g of groups) {
    const final = g.final
      ? `<b>${esc(g.final.value)}</b> ${esc(g.final.unit || "")} <small>(${esc(g.final.mode)}${g.final.based_on > 1 ? ` × ${g.final.based_on}` : ""})</small>`
      : '<i>—</i>';
    html += `<tr class="analyte-group" data-aid="${g.analyte_id || ""}" data-key="${esc(g.key || "")}">
      <td colspan="5"><span class="report-order-actions noprint"><button class="r-order-up" type="button" title="上移" ${reportLocked || !g.analyte_id ? "disabled" : ""}>↑</button><button class="r-order-down" type="button" title="下移" ${reportLocked || !g.analyte_id ? "disabled" : ""}>↓</button></span>
      <b>${esc(g.analyte)}</b>　最终: ${final}</td>
      <td><label class="print-use-label"><input class="print-use" type="checkbox" data-key="${esc(g.key || "")}" ${g.print === false ? "" : "checked"} ${reportLocked ? "disabled" : ""}>打印</label></td></tr>`;
    for (const r of g.rows) {
      let raw;
      if (r.readings && r.readings.length) {
        raw = r.readings.map((d) => {
          const label = r.method
            ? Object.entries(d.extra).map(([k, v]) => `${k}=${v}`).join(" ") || "—"
            : (d.raw ?? "—");
          return d.used
            ? `<b>${esc(label)}</b>${d.value !== null && d.value !== undefined ? `<small>=${d.value}</small>` : ""}`
            : `<span class="rd-unused">${esc(label)}</span>`;
        }).join(" / ");
      } else raw = "—";
      const auxBadge = r.aux && r.aux.use
        ? (r.aux.expected && r.aux.measured
            ? ` <span class="tag" title="回标 ${r.aux.expected}→${r.aux.measured}">×${(r.aux.measured / r.aux.expected).toFixed(4)}</span>`
            : (r.aux.coefficient ? ` <span class="tag">×${r.aux.coefficient}</span>` : ""))
        : "";
      const res = r.value === null || r.value === undefined
        ? `<i>${esc(r.unit || "")}</i>` : `${esc(r.value)} ${esc(r.unit || "")}${auxBadge}`;
      html += `<tr class="sub-row">
        <td></td><td>${esc(r.prep)}</td>
        <td>${r.instrument ? esc(r.instrument) : "—"}${r.method ? " / " + esc(r.method) : ""}</td>
        <td>${raw}</td><td>${res}</td><td>—</td></tr>`;
    }
  }
  $("#r-table tbody").innerHTML = html;
  $("#r-table").classList.toggle("manual-report-table", Boolean(reportData.manual_report));
  $("#r-calculation-title").textContent = reportData.manual_report ? "手工补录结果编排" : "系统计算明细";
  $("#r-order-default").hidden = Boolean(reportData.manual_report);
  $("#r-order-default").disabled = reportLocked;
  $("#r-order-default").title = reportLocked ? "当前样品的报告顺序只读" : "清除本样品自定义顺序，重新使用设置中的默认顺序";
  const saveReportOrder = async (analyteIds) => {
    const result = await api(`/api/samples/${sid}/report-order`, "PUT", { analyte_ids: analyteIds });
    if (!result.ok) return;
    await loadReport();
  };
  $$("#r-table tr.analyte-group").filter((row) => row.dataset.aid).forEach((row, index, rows) => {
    row.querySelector(".r-order-up").onclick = () => {
      if (!index) return;
      const ids = rows.map((item) => +item.dataset.aid);
      [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]];
      saveReportOrder(ids);
    };
    row.querySelector(".r-order-down").onclick = () => {
      if (index >= rows.length - 1) return;
      const ids = rows.map((item) => +item.dataset.aid);
      [ids[index], ids[index + 1]] = [ids[index + 1], ids[index]];
      saveReportOrder(ids);
    };
  });
  $("#r-order-default").onclick = () => saveReportOrder([]);
  $$("#r-table .print-use").forEach((checkbox) => checkbox.onchange = async () => {
    const excludes = $$("#r-table .print-use:not(:checked)").map((item) => item.dataset.key).filter(Boolean);
    const result = await api(`/api/samples/${sid}/report-print`, "PUT", { excludes });
    if (!result.ok) { checkbox.checked = !checkbox.checked; return; }
    await loadReport();
  });
  renderPrintTickets();
  await updateFinalTicket();
}
$("#r-sample").onchange = loadReport;
$("#r-save-meta").onclick = () => saveReportMeta();
$("#r-report-profile").onchange = () => {
  if (!REPORT_BATCH_DATA.length) return;
  const profile = META.report_profiles.find((item) => item.id === +$("#r-report-profile").value);
  if (profile) REPORT_BATCH_DATA.forEach((reportData) => { reportData.report_profile = profile; });
  renderPrintTickets();
  $("#final-ticket").innerHTML = combinedFinalTicketHtml(REPORT_BATCH_DATA);
};
["r-customer", "r-report-no", "r-analysis-date", "r-analyst"].forEach((id) => {
  $("#" + id).addEventListener("input", () => {
    if (!REPORT_BATCH_DATA.length) return;
    const payload = reportMetaPayload();
    REPORT_BATCH_DATA.forEach((reportData) => Object.assign(reportData.sample, payload));
    renderPrintTickets();
    $("#final-ticket").innerHTML = combinedFinalTicketHtml(REPORT_BATCH_DATA);
  });
});
$("#r-excel-export").onclick = () => {
  const sid = +$("#r-sample").value;
  if (sid) downloadApi(`/api/excel/reports/${sid}`);
};

async function printTicket(kind) {
  if (!REPORT_DATA) return;
  if (!await saveReportMeta(true)) return;
  activatePrintMode(kind);
  window.print();
}
function activatePrintMode(kind) {
  document.body.classList.remove("print-raw", "print-final");
  document.body.classList.add(kind === "raw" ? "print-raw" : "print-final");
  $("#ticket-page-style")?.remove();
  const pageStyle = document.createElement("style");
  pageStyle.id = "ticket-page-style";
  pageStyle.textContent = kind === "raw"
    ? "@page { size: A4 landscape; margin: 8mm; }"
    : "@page { size: A5 portrait; margin: 7mm; }";
  document.head.appendChild(pageStyle);
}
function clearPrintMode() {
  document.body.classList.remove("print-raw", "print-final");
  $("#ticket-page-style")?.remove();
}
window.addEventListener("afterprint", clearPrintMode);
$("#r-print-raw").onclick = () => printTicket("raw");
$("#r-print-final").onclick = () => printTicket("final");
$("#results-search").oninput = () => loadResultsPage();
window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || event.defaultPrevented || activePageName() !== "results" || !RESULT_EXPANDED_ORDER.length) return;
  if (shortcutEditable(event.target)) return;
  event.preventDefault();
  const sid = RESULT_EXPANDED_ORDER.pop();
  collapseResultSample(sid);
  renderResultsList();
});
$("#results-collapse-all").onclick = () => {
  RESULT_EXPANDED.clear();
  RESULT_EXPANDED_ORDER.length = 0;
  RESULT_DETAILS.clear();
  RESULT_MANUAL_EDITING.clear();
  renderResultsList();
};
$("#results-clear-selection").onclick = () => {
  RESULT_SELECTED.clear();
  renderResultsList();
};
$("#results-page-prev").onclick = () => {
  RESULT_PAGE = Math.max(0, RESULT_PAGE - 1);
  loadResultsPage();
};
$("#results-page-next").onclick = () => {
  RESULT_PAGE += 1;
  loadResultsPage();
};
$("#results-page-size").onchange = (event) => {
  RESULT_PAGE_SIZE = +event.currentTarget.value || 50;
  RESULT_PAGE = 0;
  loadResultsPage();
};
$("#results-check-all").onchange = (event) => {
  RESULT_SAMPLES.forEach((sample) => event.currentTarget.checked
    ? RESULT_SELECTED.add(sample.id) : RESULT_SELECTED.delete(sample.id));
  renderResultsList();
};
$("#results-excel").onclick = () => {
  if (!RESULT_SELECTED.size) return;
  const params = new URLSearchParams({
    sample_ids: [...RESULT_SELECTED].join(","),
  });
  if ($("#results-template").value) params.set("template_id", $("#results-template").value);
  downloadApi(`/api/excel/results-report?${params}`);
};
$("#report-search").oninput = () => loadReportPrintPage();
$("#report-page-prev").onclick = () => {
  REPORT_PAGE = Math.max(0, REPORT_PAGE - 1);
  loadReportPrintPage();
};
$("#report-page-next").onclick = () => {
  REPORT_PAGE += 1;
  loadReportPrintPage();
};
$("#report-page-size").onchange = (event) => {
  REPORT_PAGE_SIZE = +event.currentTarget.value || 20;
  REPORT_PAGE = 0;
  loadReportPrintPage();
};

/* ---------------- 设置 ---------------- */
function permissionPickerHtml(selected = [], prefix = "permission") {
  const enabled = new Set(selected || []);
  return Object.entries(META.capabilities || {}).map(([value, label]) =>
    `<label><input type="checkbox" class="${prefix}" value="${esc(value)}" ${enabled.has(value) ? "checked" : ""}> ${esc(label)}</label>`
  ).join("");
}

function selectedPermissions(container, selector) {
  return [...container.querySelectorAll(`${selector}:checked`)].map((input) => input.value);
}

async function loadUsers() {
  const users = await api("/api/users");
  if (!Array.isArray(users)) return;
  $("#u-new-permissions").innerHTML = permissionPickerHtml([], "u-new-permission");
  $("#u-table tbody").innerHTML = users.map((user) => `<tr data-uid="${user.id}">
    <td><input class="u-username" value="${esc(user.username)}"></td><td><input class="u-display" value="${esc(user.display_name)}"></td>
    <td><div class="permission-picker compact">${permissionPickerHtml(user.permissions, "u-permission")}</div></td>
    <td>${user.active ? "启用" : "停用"}</td><td><button class="u-save" type="button">保存</button>
      <button class="u-toggle" type="button">${user.active ? "停用" : "启用"}</button>
      <button class="u-password" type="button">重置密码</button></td></tr>`).join("");
  $$("#u-table .u-save").forEach((button) => button.onclick = async () => {
    const row = button.closest("tr");
    const result = await api(`/api/users/${row.dataset.uid}`, "PUT", {
      username: row.querySelector(".u-username").value.trim(),
      display_name: row.querySelector(".u-display").value.trim(),
      permissions: selectedPermissions(row, ".u-permission"),
    });
    if (!result.ok) return; else loadUsers();
  });
  $$("#u-table .u-toggle").forEach((button) => button.onclick = async () => {
    const row = button.closest("tr");
    const active = button.textContent === "启用";
    const result = await api(`/api/users/${row.dataset.uid}`, "PUT", { active });
    if (!result.ok) return; else loadUsers();
  });
  $$("#u-table .u-password").forEach((button) => button.onclick = async () => {
    const password = prompt("输入新密码");
    if (!password) return;
    const result = await api(`/api/users/${button.closest("tr").dataset.uid}`, "PUT", { password });
    if (!result.ok) return; else alert("密码已更新");
  });
}

async function loadTerminals() {
  const terminals = await api("/api/terminals");
  if (!Array.isArray(terminals)) return;
  const currentTerminalId = META.terminal?.id;
  $("#terminal-table tbody").innerHTML = terminals.map((terminal, index) => `<tr data-terminal-id="${terminal.id}">
    <td><input class="terminal-row-name" value="${esc(terminal.name)}"></td>
    <td><select class="terminal-row-kind"><option value="standard" ${terminal.kind === "standard" ? "selected" : ""}>普通终端</option><option value="admin" ${terminal.kind === "admin" ? "selected" : ""}>管理终端</option></select></td>
    <td><button class="terminal-move" data-direction="up" type="button" ${index === 0 ? "disabled" : ""}>上移</button>
      <button class="terminal-move" data-direction="down" type="button" ${index === terminals.length - 1 ? "disabled" : ""}>下移</button></td>
    <td>${terminal.active ? "启用" : "停用"}${terminal.id === currentTerminalId ? " · 当前" : ""}</td>
    <td><button class="terminal-save" type="button">保存</button>
      <button class="terminal-toggle" type="button">${terminal.active ? "停用" : "启用"}</button>
      <button class="terminal-reset" type="button">重置密码</button></td></tr>`).join("");
  $$("#terminal-table .terminal-save").forEach((button) => button.onclick = async () => {
    const row = button.closest("tr");
    const kind = row.querySelector(".terminal-row-kind").value;
    const payload = {
      name: row.querySelector(".terminal-row-name").value.trim(),
      kind,
    };
    const result = await api(`/api/terminals/${row.dataset.terminalId}`, "PUT", payload);
    if (!result.ok) return;
    await loadMeta();
  });
  $$("#terminal-table .terminal-toggle").forEach((button) => button.onclick = async () => {
    const row = button.closest("tr");
    const result = await api(`/api/terminals/${row.dataset.terminalId}`, "PUT", {
      active: button.textContent === "启用",
    });
    if (result.ok) loadTerminals();
  });
  $$("#terminal-table .terminal-reset").forEach((button) => button.onclick = async () => {
    const password = prompt("输入新的终端密码");
    if (!password) return;
    const result = await api(`/api/terminals/${button.closest("tr").dataset.terminalId}`, "PUT", { password });
    if (result.ok) alert("终端密码已更新");
  });
  $$("#terminal-table .terminal-move").forEach((button) => button.onclick = async () => {
    const terminalId = button.closest("tr").dataset.terminalId;
    const result = await api(`/api/terminals/${terminalId}/order`, "PUT", {
      direction: button.dataset.direction,
    });
    if (result.ok) loadTerminals();
  });
}

$("#terminal-add").onclick = async () => {
  const result = await api("/api/terminals", "POST", {
    name: $("#terminal-name").value.trim(),
    password: $("#terminal-password").value,
    kind: $("#terminal-kind").value,
  });
  if (!result.ok) return;
  $("#terminal-name").value = $("#terminal-password").value = "";
  loadTerminals();
};

function auditActionLabel(action) {
  return AUDIT_ACTION_LABELS[action] || action || "未知动作";
}

function auditEntityLabel(entity) {
  return AUDIT_ENTITY_LABELS[entity] || entity || "未知对象";
}

function auditSearchText(item) {
  const changes = (item.changes || []).flatMap((change) =>
    [change.label, change.field, change.before, change.after]);
  return [item.created_at, item.username, item.terminal_name, auditActionLabel(item.action), item.action,
    auditEntityLabel(item.entity_type), item.entity_type, item.entity_id, item.reason, item.ip_address,
    ...changes].filter((value) => value !== null && value !== undefined).join(" ").toLocaleLowerCase("zh-CN");
}

function renderAudit() {
  const query = $("#audit-search").value.trim().toLocaleLowerCase("zh-CN");
  const action = $("#audit-action-filter").value;
  const entity = $("#audit-entity-filter").value;
  const records = AUDIT_RECORDS.filter((item) =>
    (!action || item.action === action) && (!entity || item.entity_type === entity) &&
    (!query || auditSearchText(item).includes(query)));
  $("#audit-count").textContent = `显示 ${records.length} / ${AUDIT_RECORDS.length} 条`;
  $("#audit-table tbody").innerHTML = records.length ? records.map((item) => `<tr data-audit-id="${item.id}">
    <td>${esc(item.created_at)}</td>
    <td>${esc(item.username)}${item.terminal_name ? `<small class="audit-terminal">@ ${esc(item.terminal_name)}</small>` : ""}</td>
    <td>${esc(auditActionLabel(item.action))}</td>
    <td>${esc(auditEntityLabel(item.entity_type))} ${esc(item.entity_id || "")}</td>
    <td>${esc(item.reason || "—")}</td><td>${esc(item.ip_address || "—")}</td>
    <td><button class="audit-detail" type="button">详情</button></td></tr>`).join("")
    : '<tr><td colspan="7" class="audit-empty">没有符合当前过滤条件的审计记录。</td></tr>';
  $$("#audit-table .audit-detail").forEach((button) => button.onclick = () => {
    const item = AUDIT_RECORDS.find((record) => record.id === +button.closest("tr").dataset.auditId);
    if (!item) return;
    const changes = (item.changes || []).length
      ? item.changes.map((change) => `${change.label || change.field}：${change.before} → ${change.after}`).join("\n")
      : "未找到有效字段变化";
    showError(`时间：${item.created_at}\n操作者：${item.username}${item.terminal_name ? ` @ ${item.terminal_name}` : ""}\n动作：${auditActionLabel(item.action)}\n对象：${auditEntityLabel(item.entity_type)} ${item.entity_id || ""}\n原因：${item.reason || "—"}\nIP：${item.ip_address || "—"}\n\n真正变化：\n${changes}`, "审计详情");
  });
}

function populateAuditFilters() {
  const actionSelect = $("#audit-action-filter");
  const entitySelect = $("#audit-entity-filter");
  const selectedAction = actionSelect.value;
  const selectedEntity = entitySelect.value;
  const actions = [...new Set(AUDIT_RECORDS.map((item) => item.action).filter(Boolean))]
    .sort((left, right) => auditActionLabel(left).localeCompare(auditActionLabel(right), "zh-CN"));
  const entities = [...new Set(AUDIT_RECORDS.map((item) => item.entity_type).filter(Boolean))]
    .sort((left, right) => auditEntityLabel(left).localeCompare(auditEntityLabel(right), "zh-CN"));
  actionSelect.innerHTML = '<option value="">全部动作</option>' + actions.map((value) =>
    `<option value="${esc(value)}">${esc(auditActionLabel(value))}</option>`).join("");
  entitySelect.innerHTML = '<option value="">全部对象</option>' + entities.map((value) =>
    `<option value="${esc(value)}">${esc(auditEntityLabel(value))}</option>`).join("");
  if (actions.includes(selectedAction)) actionSelect.value = selectedAction;
  if (entities.includes(selectedEntity)) entitySelect.value = selectedEntity;
}

async function loadAudit() {
  const records = await api("/api/audit?limit=500");
  if (!Array.isArray(records)) return;
  AUDIT_RECORDS = records;
  populateAuditFilters();
  renderAudit();
}

$("#u-add").onclick = async () => {
  const result = await api("/api/users", "POST", {
    username: $("#u-username").value.trim(), display_name: $("#u-display-name").value.trim(),
    password: $("#u-password").value,
    permissions: selectedPermissions($("#u-new-permissions"), ".u-new-permission"),
  });
  if (!result.ok) return;
  $("#u-username").value = $("#u-display-name").value = $("#u-password").value = "";
  loadUsers();
};
$("#audit-refresh").onclick = loadAudit;
$("#audit-search").oninput = renderAudit;
$("#audit-action-filter").onchange = renderAudit;
$("#audit-entity-filter").onchange = renderAudit;
$("#audit-clear").onclick = () => {
  $("#audit-search").value = "";
  $("#audit-action-filter").value = "";
  $("#audit-entity-filter").value = "";
  renderAudit();
};

$("#rp-add").onclick = async () => {
  const result = await api("/api/report-profiles", "POST", {
    name: $("#rp-name").value.trim(),
    company_name_cn: $("#rp-company-cn").value.trim(),
    company_name_en: $("#rp-company-en").value.trim(),
    raw_code: $("#rp-raw-code").value.trim(),
    final_code: $("#rp-final-code").value.trim(),
  });
  if (!result.ok) return;
  $$("#rp-name, #rp-company-cn, #rp-company-en, #rp-raw-code, #rp-final-code")
    .forEach((input) => { input.value = ""; });
  await loadMeta();
};

function templatePrepRowHtml(prep = {}) {
  const names = (prep.analyte_ids || []).map((id) => META.analytes.find((a) => a.id === id)?.name)
    .filter(Boolean).join(", ");
  return `<tr>
    <td class="t-solid-only"><input class="tp-mass" type="number" step="0.0001" value="${prep.mass_g ?? ""}"></td>
    <td class="t-solid-only"><select class="tp-vol">${volumePresetOptions(prep.volume_ml)}</select></td>
    <td>${dilutionChainHtml(prep, "tp-dil")}</td>
    <td><input class="tp-analytes" value="${esc(names)}" placeholder="留空=全部项目"></td>
    <td class="prep-row-actions"><button class="copy-row" type="button" title="复制整行">⧉</button><button class="del" type="button">×</button></td></tr>`;
}

function templatePrepData(row) {
  const text = row.querySelector(".tp-analytes").value.trim();
  const dilution_ids = dilutionIdsFrom(row, "tp-dil");
  return {
    mass_g: parseFloat(row.querySelector(".tp-mass").value) || null,
    volume_ml: parseFloat(row.querySelector(".tp-vol").value) || null,
    dilution_id: dilution_ids[0] || null,
    dilution_ids,
    analyte_ids: text ? parseAnalyteText(text).matched.map((a) => a.id) : [],
  };
}

function addTemplatePrepRow(prep = {}, afterRow = null) {
  if (afterRow) afterRow.insertAdjacentHTML("afterend", templatePrepRowHtml(prep));
  else $("#t-prep-table tbody").insertAdjacentHTML("beforeend", templatePrepRowHtml(prep));
  const row = afterRow ? afterRow.nextElementSibling : $("#t-prep-table tbody tr:last-child");
  wireDilutionChain(row.querySelector(".dilution-chain"));
  row.querySelector(".copy-row").onclick = () => addTemplatePrepRow(templatePrepData(row), row);
  row.querySelector(".del").onclick = () => row.remove();
  row.querySelectorAll(".t-solid-only").forEach((cell) => cell.style.display = $("#t-liquid").checked ? "none" : "");
}

function syncTemplateAnalyteRow(row) {
  const instrument = row.querySelector(".ta-instrument");
  const method = row.querySelector(".ta-method");
  const selected = META.instruments.find((item) => item.id === +instrument.value);
  method.disabled = selected?.itype !== "function";
  method.style.visibility = selected?.itype === "function" ? "visible" : "hidden";
  row.classList.add("enabled");
  const instrument_id = +instrument.value || null;
  if (instrument_id) {
    TEMPLATE_INSTRUMENT_MAP[row.dataset.aid] = {
      instrument_id,
      method_id: selected?.itype === "function" ? (+method.value || null) : null,
    };
  } else delete TEMPLATE_INSTRUMENT_MAP[row.dataset.aid];
}

function renderTemplateAnalyteRows() {
  const parsed = parseAnalyteText($("#t-analyte-text").value);
  $("#t-analyte-chips").innerHTML =
    parsed.matched.map((item) => `<span class="tag ok">${esc(item.name)}</span>`).join("") +
    parsed.unmatched.map((name) => `<span class="tag bad">${esc(name)}?</span>`).join("");
  $("#t-analytes").innerHTML = parsed.matched.map((a) => {
    const setting = TEMPLATE_INSTRUMENT_MAP[String(a.id)] || {};
    const instruments = META.instruments.filter((item) => item.itype !== "xrf" && item.analytes.includes(a.id));
    return `<div class="template-analyte-row enabled" data-aid="${a.id}">
      <b>${esc(a.name)}</b>
      <span class="template-order-actions"><button class="ta-up" type="button" title="上移">↑</button><button class="ta-down" type="button" title="下移">↓</button></span>
      <select class="ta-instrument"><option value="">— 默认仪器 —</option>${instruments.map((item) =>
        `<option value="${item.id}" ${item.id === +setting.instrument_id ? "selected" : ""}>${esc(item.name)}</option>`).join("")}</select>
      <select class="ta-method"><option value="">— 公式方法 —</option>${methodsFor("function").map((method) =>
        `<option value="${method.id}" ${method.id === +setting.method_id ? "selected" : ""}>${esc(method.name)}</option>`).join("")}</select>
      <button class="del ta-remove" type="button" title="移除项目">×</button>
    </div>`;
  }).join("");
  $$("#t-analytes .template-analyte-row").forEach((row) => {
    row.querySelector(".ta-instrument").onchange = () => syncTemplateAnalyteRow(row);
    row.querySelector(".ta-method").onchange = () => syncTemplateAnalyteRow(row);
    const syncOrder = () => {
      $("#t-analyte-text").value = $$("#t-analytes .template-analyte-row")
        .map((item) => META.analytes.find((a) => a.id === +item.dataset.aid)?.name)
        .filter(Boolean).join(", ");
      renderTemplateAnalyteRows();
    };
    row.querySelector(".ta-up").onclick = () => {
      const previous = row.previousElementSibling;
      if (previous) { row.parentElement.insertBefore(row, previous); syncOrder(); }
    };
    row.querySelector(".ta-down").onclick = () => {
      const next = row.nextElementSibling;
      if (next) { row.parentElement.insertBefore(next, row); syncOrder(); }
    };
    row.querySelector(".ta-remove").onclick = () => {
      delete TEMPLATE_INSTRUMENT_MAP[row.dataset.aid];
      row.remove();
      syncOrder();
    };
    syncTemplateAnalyteRow(row);
  });
}

function renderTemplateXrfChips() {
  const { matched, unmatched } = parseAnalyteText($("#t-xrf-text").value);
  $("#t-xrf-chips").innerHTML =
    matched.map((item) => `<span class="tag ok">${esc(item.name)}</span>`).join("") +
    unmatched.map((name) => `<span class="tag">${esc(name)}</span>`).join("");
}

function renderTemplateEditor(template = null) {
  const selectedIds = template ? templateJson(template.analyte_ids, []).map(Number) : [];
  TEMPLATE_INSTRUMENT_MAP = template ? templateJson(template.instrument_config, {}) : {};
  const xrfMethodId = TEMPLATE_INSTRUMENT_MAP.__xrf_method_id || null;
  const xrfIds = TEMPLATE_INSTRUMENT_MAP.__xrf_analyte_ids || selectedIds;
  const xrfReportItems = TEMPLATE_INSTRUMENT_MAP.__xrf_report_items ||
    xrfIds.map((id) => META.analytes.find((item) => item.id === +id)?.name).filter(Boolean).join(", ");
  const reportOrder = (TEMPLATE_INSTRUMENT_MAP.__report_order || []).map(Number);
  const orderedIds = [...reportOrder.filter((id) => selectedIds.includes(id)),
    ...selectedIds.filter((id) => !reportOrder.includes(id))];
  $("#t-editor-title").textContent = template ? `编辑模板 #${template.id}` : "新建样品模板";
  $("#t-name").value = template?.name || "";
  $("#t-liquid").checked = !!template?.is_liquid;
  $("#t-xrf").checked = !!template?.xrf;
  $("#t-xrf-config").hidden = !template?.xrf;
  $("#t-xrf-text").value = template?.xrf ? xrfReportItems : "";
  renderXrfMethodSelect($("#t-xrf-method"), xrfMethodId);
  renderTemplateXrfChips();
  $("#t-add").textContent = template ? "保存修改" : "保存模板";
  $("#t-cancel").hidden = !template;
  $("#t-analyte-text").value = orderedIds.map((id) =>
    META.analytes.find((item) => item.id === id)?.name).filter(Boolean).join(", ");
  renderTemplateAnalyteRows();
  $("#t-prep-table tbody").innerHTML = "";
  const preps = template ? getTemplatePreps(template) : [{}];
  preps.forEach(addTemplatePrepRow);
  $$(".t-solid-only").forEach((cell) => cell.style.display = $("#t-liquid").checked ? "none" : "");
}

function collectSettingsTemplate() {
  const analyte_ids = $$("#t-analytes .template-analyte-row")
    .map((row) => +row.dataset.aid);
  const allowed = new Set(analyte_ids);
  const instrument_map = {};
  $$("#t-analytes .template-analyte-row").forEach((row) => {
    const instrument_id = +row.querySelector(".ta-instrument").value;
    if (!instrument_id) return;
    const instrument = META.instruments.find((item) => item.id === instrument_id);
    instrument_map[row.dataset.aid] = {
      instrument_id,
      method_id: instrument?.itype === "function" ? (+row.querySelector(".ta-method").value || null) : null,
    };
  });
  instrument_map.__xrf_method_id = $("#t-xrf").checked
    ? (+$("#t-xrf-method").value || null) : null;
  const xrfReportItems = $("#t-xrf-text").value.trim();
  instrument_map.__xrf_report_items = $("#t-xrf").checked ? xrfReportItems : "";
  instrument_map.__xrf_analyte_ids = $("#t-xrf").checked
    ? parseAnalyteText(xrfReportItems).matched.map((item) => item.id) : [];
  instrument_map.__report_order = analyte_ids;
  const isLiquidTemplate = $("#t-liquid").checked;
  const preps = $$("#t-prep-table tbody tr").map((row) => {
    const text = row.querySelector(".tp-analytes").value.trim();
    return {
      mass_g: isLiquidTemplate ? null : (parseFloat(row.querySelector(".tp-mass").value) || null),
      volume_ml: isLiquidTemplate ? null : (parseFloat(row.querySelector(".tp-vol").value) || null),
      dilution_id: dilutionIdsFrom(row, "tp-dil")[0] || null,
      dilution_ids: dilutionIdsFrom(row, "tp-dil"),
      analyte_ids: text ? parseAnalyteText(text).matched.map((a) => a.id).filter((id) => allowed.has(id)) : [],
    };
  });
  return {
    name: $("#t-name").value.trim(),
    is_liquid: isLiquidTemplate ? 1 : 0,
    xrf: $("#t-xrf").checked ? 1 : 0,
    dilution_id: preps[0]?.dilution_id || null,
    analyte_ids, preps, instrument_map,
  };
}

async function moveMetaOrder(kind, itemId, delta) {
  const key = kind === "instruments" ? "instruments" : "analytes";
  const ids = META[key].map((item) => item.id);
  const index = ids.indexOf(+itemId);
  const target = index + delta;
  if (index < 0 || target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target], ids[index]];
  const result = await api(`/api/${key}/order`, "PUT", { ids });
  if (!result.ok) return;
  await loadMeta();
}

function combinationPrepRowHtml(prep = {}) {
  return `<tr><td><input class="pc-row-name" value="${esc(prep.name || "")}" placeholder="留空自动生成"></td>
    <td><input class="pc-mass" type="number" step="0.0001" value="${prep.mass_g ?? ""}"></td>
    <td><select class="pc-vol">${volumePresetOptions(prep.volume_ml)}</select></td>
    <td>${dilutionChainHtml(prep, "pc-dil")}</td>
    <td class="prep-row-actions"><button class="copy-row" type="button" title="复制整行">⧉</button><button class="del" type="button">×</button></td></tr>`;
}

function combinationPrepData(row) {
  const dilution_ids = dilutionIdsFrom(row, "pc-dil");
  return {
    name: row.querySelector(".pc-row-name").value.trim(),
    mass_g: parseFloat(row.querySelector(".pc-mass").value) || null,
    volume_ml: parseFloat(row.querySelector(".pc-vol").value) || null,
    dilution_id: dilution_ids[0] || null,
    dilution_ids,
  };
}

function addCombinationPrepRow(prep = {}, afterRow = null) {
  if (afterRow) afterRow.insertAdjacentHTML("afterend", combinationPrepRowHtml(prep));
  else $("#pc-prep-table tbody").insertAdjacentHTML("beforeend", combinationPrepRowHtml(prep));
  const row = afterRow ? afterRow.nextElementSibling : $("#pc-prep-table tbody tr:last-child");
  wireDilutionChain(row.querySelector(".dilution-chain"));
  row.querySelector(".copy-row").onclick = () => addCombinationPrepRow(combinationPrepData(row), row);
  row.querySelector(".del").onclick = () => row.remove();
}

function renderPreparationCombinationEditor(combination = null) {
  $("#pc-editor-title").textContent = combination ? `编辑溶样组合 #${combination.id}` : "溶样组合";
  $("#pc-name").value = combination?.name || "";
  $("#pc-save").textContent = combination ? "保存修改" : "保存组合";
  $("#pc-cancel").hidden = !combination;
  $("#pc-prep-table tbody").innerHTML = "";
  (combination?.rows?.length ? combination.rows : [{}]).forEach((prep) => addCombinationPrepRow(prep));
}

function preparationCombinationSummary(combination) {
  return combination.rows.map((prep) => {
    const chain = prepDilutionIds(prep).map((id) =>
      META.dilutions.find((item) => item.id === id)?.label || `#${id}`).join(" × ");
    const amount = [prep.mass_g ? `${prep.mass_g}g` : "", prep.volume_ml ? `${prep.volume_ml}mL` : ""]
      .filter(Boolean).join("/");
    return [prep.name, amount, chain].filter(Boolean).join(" · ");
  }).join("；");
}

function renderSettings() {
  $("#rp-table tbody").innerHTML = (META.report_profiles || []).map((profile) => `<tr data-rpid="${profile.id}">
    <td><input class="rp-row-name" value="${esc(profile.name)}"></td>
    <td><input class="rp-row-company-cn" value="${esc(profile.company_name_cn)}"></td>
    <td><input class="rp-row-company-en" value="${esc(profile.company_name_en || "")}"></td>
    <td><input class="rp-row-raw-code" value="${esc(profile.raw_code || "")}"></td>
    <td><input class="rp-row-final-code" value="${esc(profile.final_code || "")}"></td>
    <td><button class="rp-save" type="button">保存</button><button class="del rp-delete" type="button">删除</button></td></tr>`).join("");
  $$("#rp-table .rp-save").forEach((button) => button.onclick = async () => {
    const row = button.closest("tr");
    const result = await api(`/api/report-profiles/${row.dataset.rpid}`, "PUT", {
      name: row.querySelector(".rp-row-name").value.trim(),
      company_name_cn: row.querySelector(".rp-row-company-cn").value.trim(),
      company_name_en: row.querySelector(".rp-row-company-en").value.trim(),
      raw_code: row.querySelector(".rp-row-raw-code").value.trim(),
      final_code: row.querySelector(".rp-row-final-code").value.trim(),
    });
    if (result.ok) await loadMeta();
  });
  $$("#rp-table .rp-delete").forEach((button) => button.onclick = async () => {
    if (!confirm("确定删除这套报告版式？使用它的样品将改用现存第一套版式。")) return;
    const result = await api(`/api/report-profiles/${button.closest("tr").dataset.rpid}`, "DELETE");
    if (result.ok) await loadMeta();
  });
  $("#rot-table tbody").innerHTML = (META.result_order_templates || []).map((template) =>
    `<tr data-rotid="${template.id}"><td><input class="rot-row-name" value="${esc(template.name)}"></td>` +
    `<td><input class="rot-row-items" value="${esc((template.items || []).join(", "))}"></td>` +
    '<td class="actions"><button class="rot-save" type="button">保存</button><button class="del rot-delete" type="button">删除</button></td></tr>').join("");
  $$("#rot-table .rot-save").forEach((button) => button.onclick = async () => {
    const row = button.closest("tr");
    const result = await api(`/api/result-order-templates/${row.dataset.rotid}`, "PUT", {
      name: row.querySelector(".rot-row-name").value.trim(),
      items: resultOrderItems(row.querySelector(".rot-row-items").value),
    });
    if (result.ok) await loadMeta();
  });
  $$("#rot-table .rot-delete").forEach((button) => button.onclick = async () => {
    if (!confirm("确定删除这个结果元素顺序模板？历史导出文件不受影响。")) return;
    const result = await api(`/api/result-order-templates/${button.closest("tr").dataset.rotid}`, "DELETE");
    if (result.ok) await loadMeta();
  });
  // 项目
  $("#a-list").innerHTML = META.analytes.map((a) =>
    `<span class="tag order-tag"><button class="order-up" type="button" data-aid="${a.id}" title="上移">↑</button><button class="order-down" type="button" data-aid="${a.id}" title="下移">↓</button>${esc(a.name)}<button class="del" data-aid="${a.id}">×</button></span>`).join("");
  $$("#a-list .order-up").forEach((b) => b.onclick = () => moveMetaOrder("analytes", b.dataset.aid, -1));
  $$("#a-list .order-down").forEach((b) => b.onclick = () => moveMetaOrder("analytes", b.dataset.aid, 1));
  $$("#a-list .del").forEach((b) => b.onclick = async () => {
    await api("/api/analytes/" + b.dataset.aid, "DELETE"); loadMeta();
  });
  // 定容容量
  $("#vp-list").innerHTML = (META.volume_presets || []).filter((item) => item.active).map((item) =>
    `<span class="tag">${+item.volume_ml} mL${+item.volume_ml === +(META.default_volume_ml || 250)
      ? "（默认）" : `<button class="del" data-vpid="${item.id}">×</button>`}</span>`).join("");
  $$("#vp-list .del").forEach((button) => button.onclick = async () => {
    if (!confirm("从设置中移除这个定容容量？历史样品仍会保留原容量。")) return;
    const result = await api(`/api/volume-presets/${button.dataset.vpid}`, "DELETE");
    if (result.ok) loadMeta();
  });
  // 稀释倍数
  $("#dl-list").innerHTML = META.dilutions.filter((d) => d.active).map((d) =>
    `<span class="tag">${esc(d.label)}（${d.factor}倍）<button class="del" data-did="${d.id}">×</button></span>`).join("");
  $$("#dl-list .del").forEach((b) => b.onclick = async () => {
    if (!confirm("从设置中移除这个稀释方式？历史样品仍会保留原稀释参数和计算结果。")) return;
    const result = await api("/api/dilutions/" + b.dataset.did, "DELETE");
    if (!result.ok) return;
    loadMeta();
  });
  // 溶样组合
  renderPreparationCombinationEditor(PREP_COMBINATION_EDIT_ID
    ? (META.preparation_combinations || []).find((item) => item.id === PREP_COMBINATION_EDIT_ID) : null);
  $("#pc-table tbody").innerHTML = (META.preparation_combinations || []).map((item) =>
    `<tr data-pcid="${item.id}"><td>${esc(item.name)}</td><td>${esc(preparationCombinationSummary(item))}</td>` +
    `<td class="actions"><button class="pc-edit" type="button">编辑</button><button class="del" type="button">删除</button></td></tr>`).join("");
  $$("#pc-table .pc-edit").forEach((button) => button.onclick = () => {
    PREP_COMBINATION_EDIT_ID = +button.closest("tr").dataset.pcid;
    renderPreparationCombinationEditor((META.preparation_combinations || []).find((item) => item.id === PREP_COMBINATION_EDIT_ID));
    $("#pc-name").focus();
  });
  $$("#pc-table .del").forEach((button) => button.onclick = async () => {
    if (!confirm("确定删除这个溶样组合？已创建样品不会受影响。")) return;
    const id = +button.closest("tr").dataset.pcid;
    const result = await api(`/api/preparation-combinations/${id}`, "DELETE");
    if (!result.ok) return;
    if (PREP_COMBINATION_EDIT_ID === id) PREP_COMBINATION_EDIT_ID = null;
    await loadMeta();
  });
  // 仪器 + 能力
  $("#i-list").innerHTML = META.instruments.map((i) => `<div class="caprow">
    <button class="order-up" type="button" data-iid="${i.id}" title="上移">↑</button><button class="order-down" type="button" data-iid="${i.id}" title="下移">↓</button>
    <b>${esc(i.name)}</b> <i>(${esc(i.itype)})</i>
    <button class="del" data-iid="${i.id}">删除</button>
    <button class="cap-edit" data-iid="${i.id}">可测项目</button>
    <div class="cap-body" id="cap-${i.id}" style="display:none"></div></div>`).join("");
  $$("#i-list .order-up").forEach((b) => b.onclick = () => moveMetaOrder("instruments", b.dataset.iid, -1));
  $$("#i-list .order-down").forEach((b) => b.onclick = () => moveMetaOrder("instruments", b.dataset.iid, 1));
  $$("#i-list .del").forEach((b) => b.onclick = async () => {
    await api("/api/instruments/" + b.dataset.iid, "DELETE"); loadMeta();
  });
  $$("#i-list .cap-edit").forEach((b) => b.onclick = () => {
    const iid = +b.dataset.iid;
    const ins = META.instruments.find((x) => x.id === iid);
    const body = $("#cap-" + iid);
    if (body.style.display !== "none") { body.style.display = "none"; return; }
    body.innerHTML = META.analytes.map((a) =>
      `<label class="inline" style="margin-right:8px">
        <input type="checkbox" value="${a.id}" ${ins.analytes.includes(a.id) ? "checked" : ""}> ${a.name}</label>`
    ).join("") + `<button class="cap-save" data-iid="${iid}">保存</button>`;
    body.style.display = "";
    body.querySelector(".cap-save").onclick = async (e) => {
      const ids = [...body.querySelectorAll("input:checked")].map((c) => +c.value);
      await api(`/api/instruments/${e.target.dataset.iid}/capabilities`, "PUT", { analyte_ids: ids });
      loadMeta();
    };
  });
  // 分析方法
  $("#m-table tbody").innerHTML = META.methods.map((m) =>
    `<tr><td>${m.itype === "xrf" ? "XRF" : "公式"}</td><td>${esc(m.name)}</td><td><code>${esc(m.formula || "—")}</code></td>
     <td>${esc(Object.entries(templateJson(m.constants, {})).map(([k, v]) => `${k}=${v}`).join(", ") || "—")}</td>
     <td><textarea class="m-row-note" rows="2" maxlength="2000">${esc(m.note || "")}</textarea></td>
     <td><button class="m-note-save" data-mid="${m.id}" type="button">保存说明</button><button class="del" data-mid="${m.id}">删</button></td></tr>`).join("");
  $$("#m-table .m-note-save").forEach((button) => button.onclick = async () => {
    const note = button.closest("tr").querySelector(".m-row-note").value;
    const result = await api(`/api/methods/${button.dataset.mid}/note`, "PUT", { note });
    if (result.ok) await loadMeta();
  });
  $$("#m-table .del").forEach((b) => b.onclick = async () => {
    await api("/api/methods/" + b.dataset.mid, "DELETE"); loadMeta();
  });
  // 模板
  renderTemplateEditor(TEMPLATE_EDIT_ID
    ? META.templates.find((template) => template.id === TEMPLATE_EDIT_ID) : null);
  $("#t-table tbody").innerHTML = META.templates.map((t) => {
    const preps = getTemplatePreps(t);
    const instruments = templateJson(t.instrument_config, {});
    const xrfMethod = META.methods.find((method) => method.id === +instruments.__xrf_method_id);
    const regularCount = templateJson(t.analyte_ids, []).length;
    const xrfCount = String(instruments.__xrf_report_items || "")
      .split(/[,，、;；\s]+/).filter(Boolean).length;
    return `<tr><td>${esc(t.name)}</td><td>${t.is_liquid ? "液体" : "固体"}${t.xrf ? ` / XRF${xrfMethod ? `：${esc(xrfMethod.name)}` : "（未选方法）"}` : ""}</td>
      <td>${t.xrf ? `常规 ${regularCount} / XRF ${xrfCount}` : regularCount}</td><td>${preps.length} 路</td>
      <td>${Object.keys(instruments).filter((key) => !key.startsWith("__")).length}</td>
      <td class="actions"><button class="t-edit" data-tid="${t.id}">编辑</button><button class="del" data-tid="${t.id}">删除</button></td></tr>`;
  }).join("");
  $$("#t-table .t-edit").forEach((b) => b.onclick = () => {
    TEMPLATE_EDIT_ID = +b.dataset.tid;
    renderTemplateEditor(META.templates.find((template) => template.id === TEMPLATE_EDIT_ID));
    $("#t-name").focus();
  });
  $$("#t-table .del").forEach((b) => b.onclick = async () => {
    if (!confirm("确定删除这个模板？")) return;
    await api("/api/templates/" + b.dataset.tid, "DELETE");
    if (TEMPLATE_EDIT_ID === +b.dataset.tid) TEMPLATE_EDIT_ID = null;
    loadMeta();
  });
}

$("#a-add").onclick = async () => {
  const name = $("#a-name").value.trim();
  if (name) { await api("/api/analytes", "POST", { name }); $("#a-name").value = ""; loadMeta(); }
};
function resultOrderItems(text) {
  return [...new Set(String(text || "").split(/[,，、;；\s]+/).map((item) => item.trim()).filter(Boolean))];
}
$("#rot-add").onclick = async () => {
  const payload = { name: $("#rot-name").value.trim(), items: resultOrderItems($("#rot-items").value) };
  if (!payload.name) { $("#rot-name").focus(); return; }
  const result = await api("/api/result-order-templates", "POST", payload);
  if (!result.ok) return;
  $("#rot-name").value = "";
  $("#rot-items").value = "";
  await loadMeta();
};
$("#vp-add").onclick = async () => {
  const volume_ml = parseFloat($("#vp-volume").value);
  if (!Number.isFinite(volume_ml) || volume_ml <= 0) return;
  const result = await api("/api/volume-presets", "POST", { volume_ml });
  if (!result.ok) return;
  $("#vp-volume").value = "250";
  loadMeta();
};
$("#dl-add").onclick = async () => {
  const aliquot_ml = parseFloat($("#dl-aliquot").value);
  const final_volume_ml = parseFloat($("#dl-final-volume").value);
  if (!Number.isFinite(aliquot_ml) || !Number.isFinite(final_volume_ml)) return;
  const result = await api("/api/dilutions", "POST", { aliquot_ml, final_volume_ml });
  if (!result.ok) return;
  $("#dl-aliquot").value = "";
  $("#dl-final-volume").value = "";
  loadMeta();
};
$("#pc-row-add").onclick = () => addCombinationPrepRow();
$("#pc-save").onclick = async () => {
  const payload = {
    name: $("#pc-name").value.trim(),
    rows: $$("#pc-prep-table tbody tr").map(combinationPrepData),
  };
  if (!payload.name) { $("#pc-name").focus(); return; }
  const result = await api(PREP_COMBINATION_EDIT_ID
    ? `/api/preparation-combinations/${PREP_COMBINATION_EDIT_ID}` : "/api/preparation-combinations",
  PREP_COMBINATION_EDIT_ID ? "PUT" : "POST", payload);
  if (!result.ok) return;
  PREP_COMBINATION_EDIT_ID = null;
  await loadMeta();
};
$("#pc-cancel").onclick = () => {
  PREP_COMBINATION_EDIT_ID = null;
  renderPreparationCombinationEditor();
};
$("#i-add").onclick = async () => {
  const name = $("#i-name").value.trim();
  if (name) {
    await api("/api/instruments", "POST", { name, itype: $("#i-type").value });
    $("#i-name").value = ""; loadMeta();
  }
};
$("#m-add").onclick = async () => {
  const name = $("#m-name").value.trim(), formula = $("#m-formula").value.trim();
  const itype = $("#m-type").value;
  if (name && (itype === "xrf" || formula)) {
    const constants = {};
    const constantText = $("#m-constants").value.trim();
    for (const part of constantText.split(/[,，;；\s]+/).filter(Boolean)) {
      const [key, value, ...rest] = part.split("=");
      if (!key || value === undefined || rest.length || value.trim() === "" || !Number.isFinite(Number(value))) {
        showError(`固定常数格式不正确：${part}`);
        return;
      }
      constants[key.trim()] = Number(value);
    }
    const r = await api("/api/methods", "POST", {
      name, itype, formula, constants, note: $("#m-note").value.trim(),
    });
    if (!r.ok) return;
    $("#m-name").value = ""; $("#m-formula").value = "";
    $("#m-constants").value = ""; $("#m-note").value = ""; loadMeta();
  }
};
$("#t-add").onclick = async () => {
  const payload = collectSettingsTemplate();
  if (!payload.name) { $("#t-name").focus(); return; }
  if (!payload.analyte_ids.length && !payload.xrf) {
    showError("模板的溶样方案和 XRF 至少需要有一项。"); return;
  }
  if (payload.xrf && !payload.instrument_map.__xrf_method_id) {
    showError("请选择模板的 XRF 方法。"); $("#t-xrf-method").focus(); return;
  }
  await api(TEMPLATE_EDIT_ID ? `/api/templates/${TEMPLATE_EDIT_ID}` : "/api/templates",
    TEMPLATE_EDIT_ID ? "PUT" : "POST", payload);
  TEMPLATE_EDIT_ID = null;
  await loadMeta();
};
$("#t-prep-add").onclick = () => addTemplatePrepRow();
$("#t-analyte-text").oninput = renderTemplateAnalyteRows;
$("#t-xrf-text").oninput = renderTemplateXrfChips;
$("#t-liquid").onchange = () => {
  $$(".t-solid-only").forEach((cell) => cell.style.display = $("#t-liquid").checked ? "none" : "");
};
$("#t-xrf").onchange = () => {
  $("#t-xrf-config").hidden = !$("#t-xrf").checked;
  if ($("#t-xrf").checked && !$("#t-xrf-method").value && methodsFor("xrf").length === 1) {
    $("#t-xrf-method").value = methodsFor("xrf")[0].id;
  }
  renderTemplateXrfChips();
};
$("#m-type").onchange = () => {
  const xrf = $("#m-type").value === "xrf";
  $("#m-formula").disabled = xrf;
  $("#m-constants").disabled = xrf;
};
$("#t-cancel").onclick = () => { TEMPLATE_EDIT_ID = null; renderTemplateEditor(); };

/* ---------------- 启动 ---------------- */
setupSamplePicker("d");
document.addEventListener("mousedown", (event) => {
  if (!event.target.closest(".sample-picker")) {
    $$(".sample-options.open").forEach((options) => options.classList.remove("open"));
  }
});

/* ---------------- 全站右键菜单 ---------------- */
const SITE_CONTEXT_MENU = $("#site-context-menu");
let CONTEXT_TARGET = null;

function closeSiteContextMenu() {
  SITE_CONTEXT_MENU.hidden = true;
  CONTEXT_TARGET = null;
  CONTEXT_ENTITY = null;
}

function contextSelectedText() {
  const target = CONTEXT_TARGET;
  if (target && (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) {
    const start = target.selectionStart ?? 0;
    const end = target.selectionEnd ?? 0;
    if (end > start) return target.value.slice(start, end);
  }
  return String(window.getSelection()?.toString() || "");
}

async function copyFromContext() {
  try {
    const text = contextSelectedText();
    if (text) {
      await navigator.clipboard.writeText(text);
    } else if (CONTEXT_TARGET?.closest("#d-table")) {
      await DATA_GRID.copy();
    } else if (CONTEXT_TARGET?.closest("#p-table")) {
      await PREP_GRID.copy();
    }
  } finally {
    closeSiteContextMenu();
  }
}

function contextEntityFromTarget(target) {
  if (!(target instanceof Element)) return null;
  const activePage = $(".tab.active")?.dataset.page;
  if (activePage === "instrument") return null;
  const make = (type, id, label) => id ? { type, id: String(id), label } : null;
  let reading = target.closest(".reading[data-rid]");
  if (!reading) {
    const rawCell = target.closest("#d-table td:nth-child(4)");
    if (rawCell) {
      const activeReading = document.activeElement?.closest?.(".reading[data-rid]");
      if (activeReading && rawCell.contains(activeReading)) reading = activeReading;
      else if (LAST_READING_TARGET?.dataset.rid && rawCell.contains(LAST_READING_TARGET)) {
        reading = LAST_READING_TARGET;
      }
      else {
        const persisted = [...rawCell.querySelectorAll(".reading[data-rid]")]
          .filter((item) => item.dataset.rid);
        if (persisted.length === 1) reading = persisted[0];
      }
    }
  }
  if (reading?.dataset.rid) {
    const row = reading.closest("tr[data-said]");
    const label = [row?.dataset.prep, row?.dataset.analyte, "原始值"].filter(Boolean).join(" · ");
    return make("reading", reading.dataset.rid, label);
  }
  const task = target.closest("tr[data-said]");
  if (task?.dataset.said) {
    const label = [task.dataset.prep, task.dataset.analyte].filter(Boolean).join(" · ") || "检测项目";
    return make("sample_analyte", task.dataset.said, label);
  }
  const reportControl = target.closest("[data-xrf-value]") || target.closest("tr")?.querySelector("[data-xrf-value]");
  if (reportControl?.dataset.xrfValue) return make("xrf_value", reportControl.dataset.xrfValue, "XRF 结果");
  const card = target.closest(".sample-card[data-sid]");
  if (card?.dataset.sid) {
    const sample = SAMPLES.find((item) => item.id === +card.dataset.sid);
    return make("sample", card.dataset.sid,
      sample ? `${sample.lims_no || "#" + sample.id} ${sample.name}` : `样品 #${card.dataset.sid}`);
  }
  if (activePage === "users") {
    const row = target.closest("tr");
    if (row?.dataset.uid) return make("user", row.dataset.uid, "用户");
    if (row?.dataset.terminalId) return make("terminal", row.dataset.terminalId, "终端");
    return null;
  }
  if (activePage === "settings") {
    const container = target.closest("tr, .caprow, .tag, .template-analyte-row") || target;
    const findValue = (attribute, datasetKey) => {
      const element = target.closest(`[data-${attribute}]`) || container.querySelector?.(`[data-${attribute}]`);
      return element?.dataset?.[datasetKey];
    };
    const tid = findValue("tid", "tid");
    if (tid) return make("template", tid, META.templates.find((item) => item.id === +tid)?.name || "模板");
    const mid = findValue("mid", "mid");
    if (mid) return make("method", mid, META.methods.find((item) => item.id === +mid)?.name || "分析方法");
    const iid = findValue("iid", "iid");
    if (iid && +iid) return make("instrument", iid, META.instruments.find((item) => item.id === +iid)?.name || "仪器");
    const did = findValue("did", "did");
    if (did) return make("dilution", did, META.dilutions.find((item) => item.id === +did)?.label || "稀释方式");
    const aid = findValue("aid", "aid");
    if (aid) return make("analyte", aid, META.analytes.find((item) => item.id === +aid)?.name || "测定项目");
    return null;
  }
  if (CURRENT_SAMPLE) {
    return make("sample", CURRENT_SAMPLE.id,
      `${CURRENT_SAMPLE.lims_no || "#" + CURRENT_SAMPLE.id} ${CURRENT_SAMPLE.name}`);
  }
  return null;
}

document.addEventListener("pointerdown", (event) => {
  const reading = event.target.closest?.(".reading");
  if (reading) LAST_READING_TARGET = reading;
}, true);
document.addEventListener("focusin", (event) => {
  const reading = event.target.closest?.(".reading");
  if (reading) LAST_READING_TARGET = reading;
}, true);

document.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  CONTEXT_TARGET = event.target;
  const card = event.target.closest(".sample-card[data-sid]");
  if (card) {
    const cardSample = SAMPLES.find((sample) => sample.id === +card.dataset.sid);
    if (cardSample) setCurrentSample(cardSample);
  }
  const selectedText = contextSelectedText();
  $("#ctx-copy").disabled = !selectedText &&
    !CONTEXT_TARGET.closest("#d-table, #p-table");
  if (CURRENT_SAMPLE) {
    const status = META?.sample_statuses?.[CURRENT_SAMPLE.status] || CURRENT_SAMPLE.status || "状态未知";
    $("#ctx-sample-status").innerHTML = `<b>${esc(CURRENT_SAMPLE.lims_no || "#" + CURRENT_SAMPLE.id)}　${esc(CURRENT_SAMPLE.name)}</b><small>当前状态：${esc(status)}</small>`;
  } else {
    $("#ctx-sample-status").innerHTML = "<b>尚未选择样品</b><small>请先在来样页选择样品</small>";
  }
  CONTEXT_ENTITY = contextEntityFromTarget(CONTEXT_TARGET);
  SITE_STATUS = { ...SITE_STATUS, latest_change: undefined };
  renderLatestChange();
  const activePage = $(".tab.active")?.dataset.page;
  $$("[data-context-page]").forEach((button) =>
    button.classList.toggle("active", button.dataset.contextPage === activePage));
  SITE_CONTEXT_MENU.hidden = false;
  SITE_CONTEXT_MENU.style.left = "0px";
  SITE_CONTEXT_MENU.style.top = "0px";
  const rect = SITE_CONTEXT_MENU.getBoundingClientRect();
  SITE_CONTEXT_MENU.style.left = `${Math.max(6, Math.min(event.clientX, window.innerWidth - rect.width - 6))}px`;
  SITE_CONTEXT_MENU.style.top = `${Math.max(6, Math.min(event.clientY, window.innerHeight - rect.height - 6))}px`;
  if (CONTEXT_ENTITY) refreshSiteStatus({ ...CONTEXT_ENTITY });
});

$("#ctx-copy").onclick = copyFromContext;
$$("[data-context-page]").forEach((button) => button.onclick = async () => {
  const page = button.dataset.contextPage;
  closeSiteContextMenu();
  await activatePage(page);
});
document.addEventListener("mousedown", (event) => {
  if (!SITE_CONTEXT_MENU.hidden && !event.target.closest("#site-context-menu")) closeSiteContextMenu();
});
window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || SITE_CONTEXT_MENU.hidden) return;
  event.preventDefault();
  event.stopPropagation();
  closeSiteContextMenu();
}, true);
window.addEventListener("scroll", closeSiteContextMenu, true);
window.addEventListener("resize", closeSiteContextMenu);
window.addEventListener("blur", closeSiteContextMenu);

/* ---------------- 全局快捷键 ---------------- */
const PAGE_SEARCH_INPUTS = {
  intake: "s-list-search",
  data: "d-sample-search",
  instrument: "xrf-scan-search",
  results: "results-search",
  report: "report-search",
  audit: "audit-search",
};
const PAGE_EXPORT_BUTTONS = {
  intake: "s-excel-overview",
  data: "d-excel-export",
  results: "results-excel",
  report: "r-excel-export",
};
const PAGE_PAGER_BUTTONS = {
  intake: ["s-page-prev", "s-page-next"],
  results: ["results-page-prev", "results-page-next"],
  report: ["report-page-prev", "report-page-next"],
};

function shortcutEditable(target) {
  return Boolean(target?.closest?.("input, textarea, select, [contenteditable='true']"));
}

window.addEventListener("keydown", (event) => {
  if (event.defaultPrevented) return;
  if (event.ctrlKey || event.altKey || event.metaKey) return;
  if (!$("#error-dialog-backdrop")?.hidden || !$("#authorization-dialog")?.hidden) return;
  if (!$("#xrf-assign-dialog").hidden) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeXrfAssignDialog();
    }
    return;
  }
  if (event.key === "Escape") {
    const active = document.activeElement;
    if (active?.closest?.("input, textarea, select, [contenteditable='true']")) {
      event.preventDefault();
      active.blur();
    }
    return;
  }
  if (shortcutEditable(event.target)) return;
  const page = activePageName();
  if (event.key === "/") {
    const input = PAGE_SEARCH_INPUTS[page] ? $("#" + PAGE_SEARCH_INPUTS[page]) : null;
    if (input) {
      event.preventDefault();
      input.focus();
      input.select();
    }
    return;
  }
  if (/^[1-9]$/.test(event.key)) {
    const tabs = $$(".tab");
    const index = +event.key - 1;
    if (index < tabs.length) {
      event.preventDefault();
      activatePage(tabs[index].dataset.page);
    }
    return;
  }
  const lower = event.key.toLowerCase();
  if (lower === "n" && page === "intake") {
    event.preventDefault();
    $("#s-new")?.click();
    return;
  }
  if (lower === "e") {
    const id = PAGE_EXPORT_BUTTONS[page];
    const button = id ? $("#" + id) : null;
    if (button && !button.disabled && button.offsetParent !== null) {
      event.preventDefault();
      button.click();
    }
    return;
  }
  if (event.key === "[" || event.key === "]") {
    const pager = PAGE_PAGER_BUTTONS[page];
    if (!pager) return;
    const button = $("#" + pager[event.key === "[" ? 0 : 1]);
    if (button && !button.disabled) {
      event.preventDefault();
      button.click();
    }
  }
});

(async () => {
  const today = new Date().toLocaleDateString("sv-SE");
  $("#s-excel-date-to").value = today;
  $("#s-excel-date-from").value = `${today.slice(0, 8)}01`;
  const initialStatus = await refreshSiteStatus();
  APPLIED_COLLAB_REVISION = +(initialStatus?.revision || 0);
  if (!await loadMeta()) return;
  await loadSamples();
  const params = new URLSearchParams(window.location.search);
  const linkedSample = +params.get("sample");
  const linkedPage = params.get("page");
  if (linkedSample && ["intake", "data", "results", "report"].includes(linkedPage)) {
    await openSamplePage(linkedSample, linkedPage);
    const linkedPrint = params.get("print");
    if (linkedPage === "report" && ["raw", "final"].includes(linkedPrint)) {
      activatePrintMode(linkedPrint);
    }
  } else if (linkedPage && URL_PAGES.includes(linkedPage) && linkedPage !== "intake") {
    await activatePage(linkedPage);
  }
})();
