const TIMEZONES = [
  "UTC",
  "US/Eastern",
  "US/Pacific",
  "Europe/London",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Australia/Sydney",
];

const UI_SCALE_MIN = 0.72;
const UI_SCALE_MAX = 1.0;
const TOAST_LIMIT = 4;
const TOAST_DEFAULT_MS = 3200;
const TOAST_ERROR_MS = 4600;
const HIGHLIGHT_MS = 2400;
const SELECTION_HINT_MS = 260;
const PANEL_STAGGER_MS = 90;
const GROUP_STAGGER_MS = 44;
const MAX_BOOT_GROUPS = 6;
const MAX_SELECTION_PULSES = 12;

const TASK_COPY = {
  IMPORT: {
    pillLabel: "Import",
    start() {
      return "Starting import...";
    },
    success(result) {
      const count = Number(result && result.processed_count);
      return count > 0 ? `Import complete: ${countLabel(count, "file")} moved.` : "Import complete.";
    },
    failure: "Import failed",
  },
  CONVERT: {
    pillLabel: "Convert",
    start(meta) {
      return meta.count ? `Starting conversion for ${countLabel(meta.count, "file")}...` : "Starting conversion...";
    },
    success(result) {
      const count = Number(result && result.processed_count);
      return count > 0 ? `Converted ${countLabel(count, "video file")}.` : "Conversion complete.";
    },
    failure: "Conversion failed",
  },
  MERGE: {
    pillLabel: "Merge",
    start(meta) {
      return meta.count ? `Starting merge for ${countLabel(meta.count, "file")}...` : "Starting merge...";
    },
    success() {
      return "Merge complete.";
    },
    failure: "Merge failed",
  },
  MERGE_BY_DATE: {
    pillLabel: "Merge",
    start(meta) {
      return meta.dateKey ? `Starting merge for ${meta.dateKey}...` : "Starting merge...";
    },
    success() {
      return "Merge complete.";
    },
    failure: "Merge failed",
  },
  ANNOTATE_TIME_RANGE: {
    pillLabel: "Notes",
    start(meta) {
      return meta.count ? `Adding time notes to ${countLabel(meta.count, "file")}...` : "Adding time notes...";
    },
    success(result) {
      const count = Number(result && result.processed_count);
      return count > 0 ? `Added time notes to ${countLabel(count, "file")}.` : "Time notes added.";
    },
    failure: "Time notes failed",
  },
  REMOVE_SILENCE: {
    pillLabel: "Silence",
    start(meta) {
      return meta.count ? `Starting silence removal for ${countLabel(meta.count, "file")}...` : "Starting silence removal...";
    },
    success(result) {
      const count = Number(result && result.processed_count);
      return count > 0 ? `Silence removal complete for ${countLabel(count, "file")}.` : "Silence removal complete.";
    },
    failure: "Silence removal failed",
  },
  ORGANIZE: {
    pillLabel: "Organize",
    start() {
      return "Starting organize...";
    },
    success() {
      return "Organize complete.";
    },
    failure: "Organize failed",
  },
  DEFAULT: {
    pillLabel: "Task",
    start() {
      return "Starting task...";
    },
    success() {
      return "Task complete.";
    },
    failure: "Task failed",
  },
};

const state = {
  cwd: "",
  busy: false,
  settings: { timezone: "Asia/Shanghai", max_workers: 4, cutoff_hour: 4 },
  groups: [],
  fileSnapshot: new Map(),
  selected: new Set(),
  lastSelectionCount: 0,
  settingsSaveInFlight: false,
  currentTaskId: null,
  lastHandledFinishedTaskId: null,
  activeTask: null,
  observedTaskRunning: false,
  highlightedPaths: new Set(),
  highlightedGroups: new Set(),
  highlightTimer: null,
  selectionHintTimer: null,
  toastCounter: 0,
  bootAnimationPlayed: false,
  pollTimer: null,
  fitUiRaf: null,
};

function qs(id) { return document.getElementById(id); }

function countLabel(count, noun) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function motionAllowed() {
  return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function animateElement(el, keyframes, options) {
  if (!el || !motionAllowed() || typeof el.animate !== "function") return null;
  return el.animate(keyframes, options);
}

function captureToastPositions(region) {
  const positions = new Map();
  if (!region) return positions;

  for (const toast of region.children) {
    if (!toast.dataset.toastId) continue;
    positions.set(toast.dataset.toastId, toast.getBoundingClientRect());
  }
  return positions;
}

function animateToastLayout(previousPositions) {
  if (!motionAllowed()) return;
  const region = qs("toastRegion");
  if (!region) return;

  for (const toast of region.children) {
    const previous = previousPositions.get(toast.dataset.toastId);
    if (!previous) continue;
    const next = toast.getBoundingClientRect();
    const deltaY = previous.top - next.top;
    if (Math.abs(deltaY) < 1) continue;
    toast.animate(
      [
        { transform: `translateY(${deltaY}px)` },
        { transform: "translateY(0)" },
      ],
      {
        duration: 220,
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
      }
    );
  }
}

function getTaskCopy(type) {
  return TASK_COPY[type] || TASK_COPY.DEFAULT;
}

function createTaskMeta(payload) {
  const params = payload && typeof payload.params === "object" ? payload.params : {};
  const paths = Array.isArray(payload && payload.paths) ? payload.paths : [];
  const type = String((payload && payload.type) || "").toUpperCase() || "DEFAULT";
  const copy = getTaskCopy(type);
  return {
    type,
    count: paths.length,
    dateKey: typeof params.date_key === "string" ? params.date_key : "",
    pillLabel: copy.pillLabel,
    triggerSelector: "",
  };
}

function buildTriggerSelector(sourceEl, taskMeta) {
  if (sourceEl && sourceEl.id) return `#${CSS.escape(sourceEl.id)}`;
  if (taskMeta && taskMeta.type === "MERGE_BY_DATE" && taskMeta.dateKey) {
    return `[data-merge-by-date="${CSS.escape(taskMeta.dateKey)}"]`;
  }
  return "";
}

function formatTaskStart(meta) {
  const copy = getTaskCopy(meta && meta.type);
  return copy.start(meta || {});
}

function formatTaskSuccess(meta, result) {
  const copy = getTaskCopy(meta && meta.type);
  return copy.success(result || {});
}

function formatTaskError(meta, result) {
  const copy = getTaskCopy(meta && meta.type);
  const detail = result && result.error ? String(result.error).trim() : "";
  return detail ? `${copy.failure}: ${detail}` : `${copy.failure}.`;
}

function buildFileSnapshot(groups) {
  const snapshot = new Map();
  for (const group of groups || []) {
    for (const file of group.files || []) {
      snapshot.set(file.path, {
        dateKey: group.date_key,
        state: String(file.state || ""),
        style: String(file.style || ""),
        display: String(file.display || ""),
        time: String(file.time || ""),
        size: String(file.size || ""),
      });
    }
  }
  return snapshot;
}

function diffSnapshots(previousSnapshot, nextSnapshot, taskMeta) {
  const paths = new Set();
  const groups = new Set();

  for (const [path, nextFile] of nextSnapshot.entries()) {
    const previousFile = previousSnapshot.get(path);
    const hasChanged = !previousFile
      || previousFile.state !== nextFile.state
      || previousFile.style !== nextFile.style
      || previousFile.display !== nextFile.display
      || previousFile.time !== nextFile.time
      || previousFile.size !== nextFile.size;

    if (!hasChanged) continue;
    paths.add(path);
    if (nextFile.dateKey) groups.add(nextFile.dateKey);
  }

  if (taskMeta && taskMeta.type === "MERGE_BY_DATE" && taskMeta.dateKey) {
    groups.add(taskMeta.dateKey);
  }

  return { paths, groups };
}

function dismissToast(toast) {
  if (!toast || toast.dataset.leaving === "true") return;
  toast.dataset.leaving = "true";
  toast.classList.add("is-leaving");
  const region = qs("toastRegion");
  const previousPositions = captureToastPositions(region);
  window.setTimeout(() => {
    toast.remove();
    animateToastLayout(previousPositions);
  }, 200);
}

function showToast({ tone = "info", title = "", message = "", duration } = {}) {
  const region = qs("toastRegion");
  if (!region || !message) return;
  const previousPositions = captureToastPositions(region);

  while (region.children.length >= TOAST_LIMIT) {
    const oldest = region.firstElementChild;
    if (!oldest) break;
    oldest.remove();
  }

  const toast = document.createElement("div");
  toast.className = `toast toast-${tone}`;
  toast.dataset.toastId = String(++state.toastCounter);
  toast.setAttribute("role", tone === "error" ? "alert" : "status");

  if (title) {
    const titleEl = document.createElement("div");
    titleEl.className = "toastTitle";
    titleEl.textContent = title;
    toast.appendChild(titleEl);
  }

  const messageEl = document.createElement("div");
  messageEl.className = "toastMessage";
  messageEl.textContent = message;
  toast.appendChild(messageEl);
  region.appendChild(toast);
  animateToastLayout(previousPositions);

  const timeoutMs = Number.isFinite(duration) ? duration : (tone === "error" ? TOAST_ERROR_MS : TOAST_DEFAULT_MS);
  window.setTimeout(() => dismissToast(toast), timeoutMs);
}

function syncTransientHighlights() {
  const root = qs("filesRoot");
  if (!root) return;

  for (const row of root.querySelectorAll("[data-row-path]")) {
    const path = row.getAttribute("data-row-path");
    row.classList.toggle("fresh", !!path && state.highlightedPaths.has(path));
  }

  for (const group of root.querySelectorAll("[data-date-key]")) {
    const dateKey = group.getAttribute("data-date-key");
    group.classList.toggle("group-fresh", !!dateKey && state.highlightedGroups.has(dateKey));
  }
}

function clearTransientHighlights() {
  if (state.highlightTimer) {
    clearTimeout(state.highlightTimer);
    state.highlightTimer = null;
  }
  state.highlightedPaths.clear();
  state.highlightedGroups.clear();
  syncTransientHighlights();
}

function animateHighlightTargets(paths, groups) {
  if (!motionAllowed()) return;

  const root = qs("filesRoot");
  if (!root) return;

  let groupIndex = 0;
  for (const dateKey of groups || []) {
    const group = root.querySelector(`[data-date-key="${CSS.escape(dateKey)}"]`);
    if (!group) continue;
    animateElement(
      group,
      [
        { transform: "translateY(6px)", opacity: 0.98 },
        { transform: "translateY(0)", opacity: 1 },
      ],
      {
        duration: 280,
        delay: Math.min(groupIndex * 28, 120),
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
      }
    );
    groupIndex += 1;
  }

  let rowIndex = 0;
  for (const path of paths || []) {
    const row = root.querySelector(`[data-row-path="${CSS.escape(path)}"]`);
    if (!row) continue;
    animateElement(
      row,
      [
        { transform: "translateX(6px)", opacity: 0.92 },
        { transform: "translateX(0)", opacity: 1 },
      ],
      {
        duration: 260,
        delay: Math.min(rowIndex * 24, 180),
        easing: "cubic-bezier(0.16, 1, 0.3, 1)",
      }
    );
    rowIndex += 1;
  }
}

function setTransientHighlights(paths, groups) {
  if (state.highlightTimer) {
    clearTimeout(state.highlightTimer);
    state.highlightTimer = null;
  }

  state.highlightedPaths = new Set(paths || []);
  state.highlightedGroups = new Set(groups || []);
  syncTransientHighlights();
  animateHighlightTargets(state.highlightedPaths, state.highlightedGroups);

  if (!state.highlightedPaths.size && !state.highlightedGroups.size) return;
  state.highlightTimer = window.setTimeout(() => {
    state.highlightTimer = null;
    state.highlightedPaths.clear();
    state.highlightedGroups.clear();
    syncTransientHighlights();
  }, HIGHLIGHT_MS);
}

function syncSelectionState() {
  const root = qs("filesRoot");
  if (!root) return;

  for (const row of root.querySelectorAll("[data-row-path]")) {
    const path = row.getAttribute("data-row-path");
    const selected = !!path && state.selected.has(path);
    row.classList.toggle("selected", selected);
    row.setAttribute("aria-selected", selected ? "true" : "false");
  }
}

function animateSelectionChange(paths, checked) {
  if (!motionAllowed()) return;

  const limitedPaths = Array.from(paths || []).slice(0, MAX_SELECTION_PULSES);
  for (const path of limitedPaths) {
    const row = document.querySelector(`[data-row-path="${CSS.escape(path)}"]`);
    if (!row) continue;
    animateElement(
      row,
      checked
        ? [
            { transform: "scale(0.995)", boxShadow: "inset 0 0 0 1px rgba(220,136,98,0.1)" },
            { transform: "scale(1)", boxShadow: "inset 0 0 0 1px rgba(220,136,98,0.32)" },
          ]
        : [
            { transform: "scale(1)", opacity: 1 },
            { transform: "scale(0.998)", opacity: 0.92 },
            { transform: "scale(1)", opacity: 1 },
          ],
      {
        duration: checked ? 220 : 180,
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
      }
    );
  }
}

function syncBusyDecorations() {
  const logBox = qs("logBox");
  if (logBox) logBox.classList.toggle("is-busy", state.busy);

  for (const btn of document.querySelectorAll(".btn.is-origin")) {
    btn.classList.remove("is-origin");
  }
  if (!state.busy || !state.activeTask || !state.activeTask.triggerSelector) return;
  const origin = document.querySelector(state.activeTask.triggerSelector);
  if (origin) origin.classList.add("is-origin");
}

function setBusy(busy) {
  state.busy = !!busy;
  document.body.dataset.busy = state.busy ? "true" : "false";
  const pill = qs("busyPill");
  if (state.busy) {
    const label = state.activeTask && state.activeTask.pillLabel ? `Busy: ${state.activeTask.pillLabel}` : "Busy";
    pill.textContent = label;
    pill.title = state.activeTask ? formatTaskStart(state.activeTask) : "Task running";
    pill.classList.add("busy");
  } else {
    pill.textContent = "Idle";
    pill.removeAttribute("title");
    pill.classList.remove("busy");
  }

  for (const id of ["importBtn","convertBtn","mergeBtn","annotateBtn","silenceBtn","organizeBtn","refreshBtn"]) {
    const el = qs(id);
    if (el) el.disabled = state.busy;
  }
  const saveBtn = qs("saveSettingsBtn");
  if (saveBtn) saveBtn.disabled = state.busy || state.settingsSaveInFlight;
  for (const id of ["timezoneSelect", "threadsInput", "cutoffHourInput"]) {
    const el = qs(id);
    if (el) el.disabled = state.busy || state.settingsSaveInFlight;
  }
  for (const btn of document.querySelectorAll("[data-merge-by-date]")) {
    btn.disabled = state.busy;
  }
  syncBusyDecorations();
}

function updateSelectionHint() {
  const hint = qs("selectionHint");
  const nextCount = state.selected.size;
  hint.textContent = `${nextCount} selected`;

  if (nextCount !== state.lastSelectionCount) {
    hint.classList.remove("is-updating");
    void hint.offsetWidth;
    hint.classList.add("is-updating");
    if (state.selectionHintTimer) clearTimeout(state.selectionHintTimer);
    state.selectionHintTimer = window.setTimeout(() => {
      state.selectionHintTimer = null;
      hint.classList.remove("is-updating");
    }, SELECTION_HINT_MS);
  }

  state.lastSelectionCount = nextCount;
  syncSelectionState();
}

function setSettingsStatus(statusClass, text) {
  const el = qs("settingsStatus");
  if (!el) return;
  el.classList.remove("status-pending", "status-saving", "status-ok", "status-error");
  if (statusClass) el.classList.add(`status-${statusClass}`);
  el.textContent = text;
  scheduleFitControlsUi();
}

function markSettingsDirty() {
  if (state.busy || state.settingsSaveInFlight) return;
  setSettingsStatus("pending", "Settings changed. Saving soon...");
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll("\"","&quot;")
    .replaceAll("'","&#039;");
}

function controlsFitInViewport() {
  const body = document.querySelector(".controls > .panelBody");
  if (!body) return true;
  return body.scrollHeight <= body.clientHeight + 1;
}

function fitControlsUiScale() {
  const root = document.documentElement;
  if (window.matchMedia("(max-width: 980px)").matches) {
    root.style.setProperty("--ui-scale", "1");
    return;
  }

  root.style.setProperty("--ui-scale", String(UI_SCALE_MAX));
  if (controlsFitInViewport()) return;

  root.style.setProperty("--ui-scale", String(UI_SCALE_MIN));
  if (!controlsFitInViewport()) {
    return;
  }

  let low = UI_SCALE_MIN;
  let high = UI_SCALE_MAX;
  let best = UI_SCALE_MIN;

  for (let i = 0; i < 10; i += 1) {
    const mid = (low + high) / 2;
    root.style.setProperty("--ui-scale", mid.toFixed(4));
    if (controlsFitInViewport()) {
      best = mid;
      low = mid;
    } else {
      high = mid;
    }
  }

  root.style.setProperty("--ui-scale", best.toFixed(3));
}

function scheduleFitControlsUi() {
  if (state.fitUiRaf) cancelAnimationFrame(state.fitUiRaf);
  state.fitUiRaf = requestAnimationFrame(() => {
    state.fitUiRaf = null;
    fitControlsUiScale();
  });
}

async function apiGet(path) {
  const res = await fetch(path, { cache: "no-store" });
  const data = await res.json();
  if (!res.ok) {
    const msg = data && (data.message || data.error) ? `${data.error || "Error"}: ${data.message || ""}` : "Request failed";
    throw new Error(msg);
  }
  return data;
}

async function apiPost(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    const msg = data && (data.message || data.error) ? `${data.error || "Error"}: ${data.message || ""}` : "Request failed";
    throw new Error(msg);
  }
  return data;
}

function fileRowHtml(file) {
  const disabled = !!file.disabled;
  const styleClass = file.style ? String(file.style) : "normal";
  const format = file.format ? String(file.format).toUpperCase() : "";
  const selected = state.selected.has(file.path);
  const fresh = state.highlightedPaths.has(file.path);
  const mediaBadge = file.is_video && format
    ? `<span class="mediaBadge mediaBadge-video">${escapeHtml(format)}</span>`
    : "";

  const checked = selected ? "checked" : "";
  const cb = file.checkable
    ? `<input type="checkbox" data-path="${escapeHtml(file.path)}" ${checked} ${disabled ? "disabled" : ""} />`
    : `<span></span>`;

  return `
    <div class="fileRow ${disabled ? "disabled" : ""} ${selected ? "selected" : ""} ${fresh ? "fresh" : ""} style-${escapeHtml(styleClass)}" data-row-path="${escapeHtml(file.path)}" title="${escapeHtml(file.display || "")}">
      ${cb}
      <div class="fileName">
        <span class="fileLabel">${escapeHtml(file.display || "")}</span>
        ${mediaBadge}
      </div>
      <div class="fileMeta">${escapeHtml(file.time || "")}</div>
      <div class="stateTag ${escapeHtml(styleClass)}" title="${escapeHtml(file.state || "")}">${escapeHtml(file.state || "")}</div>
      <div class="fileMeta">${escapeHtml(file.size || "")}</div>
    </div>
  `;
}

function renderFiles() {
  const root = qs("filesRoot");
  root.innerHTML = "";

  for (const group of state.groups) {
    const swatch = group.color ? `<div class="swatch" style="background:${escapeHtml(group.color)}"></div>` : `<div class="swatch"></div>`;
    const filesHtml = (group.files || []).map(fileRowHtml).join("");
    const groupEl = document.createElement("div");
    groupEl.className = `dateGroup ${state.highlightedGroups.has(group.date_key) ? "group-fresh" : ""}`;
    groupEl.dataset.dateKey = group.date_key;
    groupEl.innerHTML = `
      <div class="dateHeader">
        <div class="dateTitle">${swatch}<span>📅 ${escapeHtml(group.date_key)}</span></div>
        <div class="dateActions">
          <button class="btn secondary" data-merge-by-date="${escapeHtml(group.date_key)}">Merge by Date</button>
        </div>
      </div>
      <div>${filesHtml}</div>
    `;
    root.appendChild(groupEl);
  }

  syncSelectionState();
  syncTransientHighlights();
  setBusy(state.busy);
}

function playBootChoreography() {
  if (state.bootAnimationPlayed) return;
  state.bootAnimationPlayed = true;
  if (!motionAllowed()) return;

  animateElement(
    document.querySelector(".topbar"),
    [
      { opacity: 0, transform: "translateY(-10px)" },
      { opacity: 1, transform: "translateY(0)" },
    ],
    {
      duration: 420,
      easing: "cubic-bezier(0.16, 1, 0.3, 1)",
    }
  );

  const panels = Array.from(document.querySelectorAll(".layout > .panel"));
  panels.forEach((panel, index) => {
    animateElement(
      panel,
      [
        { opacity: 0, transform: "translateY(14px)" },
        { opacity: 1, transform: "translateY(0)" },
      ],
      {
        duration: 420,
        delay: 80 + index * PANEL_STAGGER_MS,
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
        fill: "both",
      }
    );
  });

  const groups = Array.from(document.querySelectorAll(".dateGroup")).slice(0, MAX_BOOT_GROUPS);
  groups.forEach((group, index) => {
    animateElement(
      group,
      [
        { opacity: 0, transform: "translateY(10px)" },
        { opacity: 1, transform: "translateY(0)" },
      ],
      {
        duration: 340,
        delay: 140 + index * GROUP_STAGGER_MS,
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
        fill: "both",
      }
    );
  });
}

function applySettingsToUI() {
  const tzSel = qs("timezoneSelect");
  const currentTz = state.settings.timezone || "Asia/Shanghai";
  const zones = Array.from(new Set([...TIMEZONES, currentTz]));
  tzSel.innerHTML = zones.map(tz => `<option value="${escapeHtml(tz)}">${escapeHtml(tz)}</option>`).join("");
  tzSel.value = currentTz;
  qs("threadsInput").value = String(state.settings.max_workers || 4);
  const cutoff = Number(state.settings.cutoff_hour);
  qs("cutoffHourInput").value = String(Number.isFinite(cutoff) ? Math.max(0, Math.min(23, cutoff)) : 4);
}

async function refreshAll({ highlightChanges = false, taskMeta = null } = {}) {
  const previousSnapshot = state.fileSnapshot;
  const st = await apiGet("/api/state");
  state.cwd = st.cwd || "";
  state.settings = st.settings || state.settings;
  qs("cwd").textContent = state.cwd;
  setBusy(!!st.busy);
  applySettingsToUI();

  const files = await apiGet("/api/files");
  state.groups = files.groups || [];
  state.fileSnapshot = buildFileSnapshot(state.groups);

  state.selected = new Set();
  updateSelectionHint();
  renderFiles();
  if (highlightChanges) {
    const diff = diffSnapshots(previousSnapshot, state.fileSnapshot, taskMeta);
    setTransientHighlights(diff.paths, diff.groups);
  } else {
    clearTransientHighlights();
  }
  scheduleFitControlsUi();
}

function setLog(lines) {
  const box = qs("logBox");
  const nextText = (lines || []).join("\n");
  if (box.textContent === nextText) return;
  box.textContent = nextText;
  box.scrollTop = box.scrollHeight;
  scheduleFitControlsUi();
}

async function pollTask() {
  try {
    const t = await apiGet("/api/task/current");
    if (!t || !t.task_id) {
      state.currentTaskId = null;
      state.activeTask = null;
      state.observedTaskRunning = false;
      setLog([]);
      setBusy(false);
      return;
    }

    state.currentTaskId = t.task_id;
    const isRunning = t.status === "running";
    if (isRunning) state.observedTaskRunning = true;
    setBusy(isRunning);
    setLog(t.log || []);

    if ((t.status === "done" || t.status === "error") && state.lastHandledFinishedTaskId !== t.task_id) {
      const taskMeta = state.activeTask;
      const shouldAnnounce = !!taskMeta || state.observedTaskRunning;
      state.lastHandledFinishedTaskId = t.task_id;
      state.observedTaskRunning = false;

      if (shouldAnnounce) {
        showToast({
          tone: t.status === "done" ? "success" : "error",
          title: t.status === "done" ? "Completed" : "Attention",
          message: t.status === "done"
            ? formatTaskSuccess(taskMeta, t.result || {})
            : formatTaskError(taskMeta, t.result || {}),
        });
        await refreshAll({ highlightChanges: t.status === "done", taskMeta });
      }

      state.activeTask = null;
      return;
    }

    if (!isRunning && state.lastHandledFinishedTaskId === t.task_id) {
      state.activeTask = null;
    }
  } catch (e) {
    // ignore transient errors
  }
}

function ensurePolling() {
  if (state.pollTimer) return;
  state.pollTimer = setInterval(pollTask, 800);
}

async function startTask(payload, sourceEl = null) {
  const taskMeta = createTaskMeta(payload);
  taskMeta.triggerSelector = buildTriggerSelector(sourceEl, taskMeta);
  try {
    const res = await apiPost("/api/task", payload);
    state.activeTask = taskMeta;
    state.currentTaskId = res.task_id || null;
    state.lastHandledFinishedTaskId = null;
    state.observedTaskRunning = true;
    setLog([]);
    setBusy(true);
    showToast({
      tone: "info",
      title: "Working",
      message: formatTaskStart(taskMeta),
    });
    ensurePolling();
    await pollTask();
  } catch (e) {
    state.activeTask = null;
    state.observedTaskRunning = false;
    setBusy(false);
    showToast({
      tone: "error",
      title: "Attention",
      message: e.message || String(e),
    });
  }
}

async function startMergeByDate(dateKey) {
  await startTask({ type: "MERGE_BY_DATE", params: { date_key: dateKey } });
}

function selectedPaths() {
  return Array.from(state.selected);
}

async function onImport(sourceEl = null) {
  try {
    const hint = await apiGet("/api/obs_location");
    const dialog = qs("importDialog");
    const input = qs("importPathInput");
    input.value = (hint && hint.path) ? hint.path : "";
    dialog.showModal();
    requestAnimationFrame(() => {
      input.focus();
      input.select();
    });

    const confirmed = await new Promise((resolve) => {
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    });
    if (!confirmed) return;
    const sourceDir = input.value.trim();
    if (!sourceDir) {
      showToast({
        tone: "warning",
        title: "Attention",
        message: "Please provide a source directory path.",
      });
      return;
    }
    await startTask({ type: "IMPORT", params: { source_dir: sourceDir } }, sourceEl);
  } catch (e) {
    showToast({
      tone: "error",
      title: "Attention",
      message: e.message || String(e),
    });
  }
}

async function onConvert(sourceEl = null) {
  const paths = selectedPaths();
  if (!paths.length) {
    showToast({
      tone: "warning",
      title: "Selection",
      message: "Select some files first.",
    });
    return;
  }
  await startTask({ type: "CONVERT", paths }, sourceEl);
}

async function onMergeSelected(sourceEl = null) {
  const paths = selectedPaths();
  if (!paths.length) {
    showToast({
      tone: "warning",
      title: "Selection",
      message: "Select some files first.",
    });
    return;
  }
  await startTask({ type: "MERGE", paths }, sourceEl);
}

async function onAnnotateTimeRange(sourceEl = null) {
  const paths = selectedPaths();
  if (!paths.length) {
    showToast({
      tone: "warning",
      title: "Selection",
      message: "Select some files first.",
    });
    return;
  }
  await startTask({ type: "ANNOTATE_TIME_RANGE", paths }, sourceEl);
}

async function onSilence(sourceEl = null) {
  const paths = selectedPaths();
  if (!paths.length) {
    showToast({
      tone: "warning",
      title: "Selection",
      message: "Select some files first.",
    });
    return;
  }
  await startTask({ type: "REMOVE_SILENCE", paths }, sourceEl);
}

async function onOrganize(sourceEl = null) {
  const ok = confirm("Organize all files by date and create an archive for each folder?");
  if (!ok) return;
  await startTask({ type: "ORGANIZE", params: { create_archive: true } }, sourceEl);
}

async function onSaveSettings(trigger = "manual") {
  if (state.settingsSaveInFlight) return;
  const tz = qs("timezoneSelect").value;
  const mw = Number(qs("threadsInput").value || "4");
  const maxWorkers = Math.max(1, Math.min(16, isFinite(mw) ? mw : 4));
  const ch = Number(qs("cutoffHourInput").value || "4");
  const cutoffHour = Math.max(0, Math.min(23, isFinite(ch) ? ch : 4));
  const saveBtn = qs("saveSettingsBtn");
  const originalLabel = saveBtn ? saveBtn.textContent : "Save Settings";
  state.settingsSaveInFlight = true;
  if (saveBtn) saveBtn.textContent = "Saving...";
  setBusy(state.busy);
  setSettingsStatus("saving", "Applying settings...");
  try {
    const resp = await apiPost("/api/settings", { timezone: tz, max_workers: maxWorkers, cutoff_hour: cutoffHour });
    if (resp && resp.settings) state.settings = resp.settings;
    await refreshAll();
    const applied = state.settings || {};
    const ts = new Date().toLocaleTimeString();
    setSettingsStatus(
      "ok",
      `Applied at ${ts}: ${applied.timezone}, threads ${applied.max_workers}, cutoff ${applied.cutoff_hour}.`
    );
    if (trigger === "manual") {
      showToast({
        tone: "success",
        title: "Settings",
        message: "Settings applied.",
      });
    }
  } catch (e) {
    const msg = e.message || String(e);
    setSettingsStatus("error", `Save failed: ${msg}`);
    showToast({
      tone: "error",
      title: "Settings",
      message: `Save failed: ${msg}`,
    });
  } finally {
    state.settingsSaveInFlight = false;
    if (saveBtn) saveBtn.textContent = originalLabel;
    setBusy(state.busy);
  }
}

function debounce(fn, delayMs) {
  let t = null;
  return (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), delayMs);
  };
}

function setAll(checked) {
  const root = qs("filesRoot");
  let changed = 0;
  const changedPaths = [];
  for (const cb of root.querySelectorAll("input[type='checkbox'][data-path]")) {
    if (cb.disabled) continue;
    if (cb.checked === checked) continue;
    cb.checked = checked;
    const p = cb.getAttribute("data-path");
    if (!p) continue;
    if (checked) state.selected.add(p);
    else state.selected.delete(p);
    changed += 1;
    changedPaths.push(p);
  }
  updateSelectionHint();
  animateSelectionChange(changedPaths, checked);

  if (checked) {
    if (state.selected.size) {
      showToast({
        tone: "info",
        title: "Selection",
        message: `Selected ${countLabel(state.selected.size, "file")}.`,
      });
    } else {
      showToast({
        tone: "warning",
        title: "Selection",
        message: "No selectable files available.",
      });
    }
    return;
  }

  if (changed > 0) {
    showToast({
      tone: "info",
      title: "Selection",
      message: "Selection cleared.",
    });
  }
}

async function init() {
  const filesRoot = qs("filesRoot");
  filesRoot.addEventListener("change", (e) => {
    const cb = e.target;
    if (!cb || cb.tagName !== "INPUT" || cb.type !== "checkbox") return;
    const p = cb.getAttribute("data-path");
    if (!p) return;
    if (cb.checked) state.selected.add(p);
    else state.selected.delete(p);
    updateSelectionHint();
    animateSelectionChange([p], cb.checked);
  });

  filesRoot.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-merge-by-date]");
    if (btn) {
      const dk = btn.getAttribute("data-merge-by-date");
      if (dk) startTask({ type: "MERGE_BY_DATE", params: { date_key: dk } }, btn);
      return;
    }

    if (e.target.closest("input[type='checkbox']")) return;

    const row = e.target.closest("[data-row-path]");
    if (!row) return;
    const p = row.getAttribute("data-row-path");
    if (!p) return;
    const cb = row.querySelector(`input[type="checkbox"][data-path="${CSS.escape(p)}"]`);
    if (cb && !cb.disabled) cb.click();
  });

  qs("refreshBtn").addEventListener("click", () => {
    refreshAll().catch((e) => {
      showToast({
        tone: "error",
        title: "Attention",
        message: e.message || String(e),
      });
    });
  });
  qs("importBtn").addEventListener("click", (e) => onImport(e.currentTarget));
  qs("convertBtn").addEventListener("click", (e) => onConvert(e.currentTarget));
  qs("mergeBtn").addEventListener("click", (e) => onMergeSelected(e.currentTarget));
  qs("annotateBtn").addEventListener("click", (e) => onAnnotateTimeRange(e.currentTarget));
  qs("silenceBtn").addEventListener("click", (e) => onSilence(e.currentTarget));
  qs("organizeBtn").addEventListener("click", (e) => onOrganize(e.currentTarget));
  qs("saveSettingsBtn").addEventListener("click", () => onSaveSettings("manual"));
  qs("selectAllBtn").addEventListener("click", () => setAll(true));
  qs("deselectAllBtn").addEventListener("click", () => setAll(false));

  const autoSave = debounce(() => {
    if (state.busy) return;
    onSaveSettings("auto");
  }, 350);
  qs("timezoneSelect").addEventListener("change", () => {
    markSettingsDirty();
    autoSave();
  });
  qs("threadsInput").addEventListener("change", () => {
    markSettingsDirty();
    autoSave();
  });
  qs("threadsInput").addEventListener("blur", autoSave);
  qs("cutoffHourInput").addEventListener("change", () => {
    markSettingsDirty();
    autoSave();
  });
  qs("cutoffHourInput").addEventListener("blur", autoSave);
  window.addEventListener("resize", debounce(scheduleFitControlsUi, 80));

  applySettingsToUI();
  setSettingsStatus("ok", "Settings loaded.");
  await refreshAll();
  playBootChoreography();
  scheduleFitControlsUi();
  ensurePolling();
}

init().catch((e) => {
  alert(e.message || String(e));
});
