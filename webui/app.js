
const TIMEZONES = [
  "UTC",
  "US/Eastern",
  "US/Pacific",
  "Europe/London",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Australia/Sydney",
];

const PANEL_STORAGE_KEY = "audio-toolbox-panel-collapsed";
const TAB_STORAGE_KEY = "audio-toolbox-panel-tab";
const THEME_STORAGE_KEY = "audio-toolbox-theme-mode";
const FILE_FILTER_STORAGE_KEY = "audio-toolbox-file-filter";
const FEEDBACK_MS = 3600;
const BUTTON_FLASH_MS = 1400;
const HIGHLIGHT_MS = 2200;

const TASK_COPY = {
  IMPORT: {
    pillLabel: "Import",
    runningLabel: "Importing…",
    start: () => "Starting OBS import.",
    success: (result) => {
      const count = Number(result && result.processed_count);
      return count > 0 ? `Import complete. Moved ${count} files.` : "Import complete.";
    },
    failure: "Import failed",
  },
  CONVERT: {
    pillLabel: "Convert",
    runningLabel: "Converting…",
    start: (meta) => `Starting MP3 conversion for ${meta.count || 0} videos.`,
    success: (result) => {
      const count = Number(result && result.processed_count);
      return count > 0 ? `Conversion complete. Processed ${count} videos.` : "Conversion complete.";
    },
    failure: "Conversion failed",
  },
  MERGE: {
    pillLabel: "Merge",
    runningLabel: "Merging…",
    start: (meta) => `Starting merge for ${meta.count || 0} audio files.`,
    success: () => "Merge complete.",
    failure: "Merge failed",
  },
  MERGE_BY_DATE: {
    pillLabel: "Date Merge",
    runningLabel: "Merging…",
    start: (meta) => `Starting merge for ${meta.dateKey || "this date"}.`,
    success: () => "Date merge complete.",
    failure: "Date merge failed",
  },
  ANNOTATE_TIME_RANGE: {
    pillLabel: "Annotate",
    runningLabel: "Writing…",
    start: (meta) => `Starting time annotation for ${meta.count || 0} files.`,
    success: (result) => {
      const count = Number(result && result.processed_count);
      return count > 0 ? `Time annotations written to ${count} files.` : "Time annotation complete.";
    },
    failure: "Time annotation failed",
  },
  REMOVE_SILENCE: {
    pillLabel: "Silence",
    runningLabel: "Processing…",
    start: (meta) => `Starting silence removal for ${meta.count || 0} audio files.`,
    success: (result) => {
      const count = Number(result && result.processed_count);
      return count > 0 ? `Silence removal complete for ${count} files.` : "Silence removal complete.";
    },
    failure: "Silence removal failed",
  },
  ORGANIZE: {
    pillLabel: "Organize",
    runningLabel: "Organizing…",
    start: () => "Starting library organization by date.",
    success: () => "Organization complete.",
    failure: "Organization failed",
  },
  DEFAULT: {
    pillLabel: "Task",
    runningLabel: "Working…",
    start: () => "Starting task.",
    success: () => "Task complete.",
    failure: "Task failed",
  },
};

function qs(id) {
  return document.getElementById(id);
}

function readStorage(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : value;
  } catch {
    return fallback;
  }
}

function writeStorage(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    return;
  }
}

function normalizeThemeMode(value) {
  return ["system", "light", "dark"].includes(value) ? value : "system";
}

function normalizeFileFilter(value) {
  return ["all", "actionable", "audio", "video", "selected"].includes(value) ? value : "all";
}

const state = {
  cwd: "",
  busy: false,
  settings: { timezone: "Asia/Shanghai", max_workers: 4, cutoff_hour: 4 },
  groups: [],
  fileSnapshot: new Map(),
  selected: new Set(),
  currentTaskId: null,
  lastHandledFinishedTaskId: null,
  activeTask: null,
  observedTaskRunning: false,
  settingsSaveInFlight: false,
  pollTimer: null,
  feedbackTimer: null,
  workspaceNoticeTimer: null,
  buttonTimers: new Map(),
  highlightTimer: null,
  highlightedPaths: new Set(),
  highlightedGroups: new Set(),
  lastSyncAt: null,
  query: "",
  fileFilter: normalizeFileFilter(readStorage(FILE_FILTER_STORAGE_KEY, "all")),
  themeMode: normalizeThemeMode(readStorage(THEME_STORAGE_KEY, "system")),
  resolvedTheme: "dark",
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatRelativeTime(ts) {
  if (!ts) return "Just now";
  const delta = Math.max(0, Date.now() - ts);
  if (delta < 1000) return "Just now";
  const seconds = Math.floor(delta / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function getTaskCopy(type) {
  return TASK_COPY[type] || TASK_COPY.DEFAULT;
}

function buildTriggerSelector(sourceEl, taskMeta) {
  if (sourceEl && sourceEl.id) return `#${CSS.escape(sourceEl.id)}`;
  if (taskMeta && taskMeta.type === "MERGE_BY_DATE" && taskMeta.dateKey) {
    return `[data-merge-by-date="${CSS.escape(taskMeta.dateKey)}"]`;
  }
  return "";
}

function createTaskMeta(payload, sourceEl) {
  const params = payload && typeof payload.params === "object" ? payload.params : {};
  const paths = Array.isArray(payload && payload.paths) ? payload.paths : [];
  const type = String((payload && payload.type) || "").toUpperCase() || "DEFAULT";
  const dateKey = typeof params.date_key === "string" ? params.date_key : "";
  const copy = getTaskCopy(type);
  return {
    type,
    count: paths.length,
    dateKey,
    triggerSelector: buildTriggerSelector(sourceEl, { type, dateKey }),
    pillLabel: copy.pillLabel,
    runningLabel: copy.runningLabel,
  };
}

function formatTaskStart(meta) {
  return getTaskCopy(meta && meta.type).start(meta || {});
}

function formatTaskSuccess(meta, result) {
  return getTaskCopy(meta && meta.type).success(result || {});
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
      snapshot.set(file.path, { ...file, dateKey: group.date_key });
    }
  }
  return snapshot;
}

function diffSnapshots(previousSnapshot, nextSnapshot, taskMeta) {
  const paths = new Set();
  const groups = new Set();

  for (const [path, nextFile] of nextSnapshot.entries()) {
    const previousFile = previousSnapshot.get(path);
    if (!previousFile) {
      paths.add(path);
      if (nextFile.dateKey) groups.add(nextFile.dateKey);
      continue;
    }
    if (
      previousFile.display !== nextFile.display ||
      previousFile.state !== nextFile.state ||
      previousFile.style !== nextFile.style ||
      previousFile.size !== nextFile.size ||
      previousFile.time !== nextFile.time
    ) {
      paths.add(path);
      if (nextFile.dateKey) groups.add(nextFile.dateKey);
    }
  }

  if (taskMeta && taskMeta.dateKey) {
    groups.add(taskMeta.dateKey);
  }

  return { paths, groups };
}

function clearHighlights() {
  if (state.highlightTimer) {
    clearTimeout(state.highlightTimer);
    state.highlightTimer = null;
  }
  state.highlightedPaths.clear();
  state.highlightedGroups.clear();
}

function setHighlights(paths, groups) {
  clearHighlights();
  state.highlightedPaths = new Set(paths || []);
  state.highlightedGroups = new Set(groups || []);
  if (!state.highlightedPaths.size && !state.highlightedGroups.size) return;
  state.highlightTimer = window.setTimeout(() => {
    clearHighlights();
    renderFiles();
  }, HIGHLIGHT_MS);
}

function setFeedback(tone, message) {
  const strip = qs("feedbackStrip");
  if (!strip) return;
  if (!message) {
    strip.hidden = true;
    strip.textContent = "";
    strip.removeAttribute("data-tone");
    return;
  }

  strip.hidden = false;
  strip.dataset.tone = tone || "info";
  strip.textContent = message;

  if (state.feedbackTimer) clearTimeout(state.feedbackTimer);
  state.feedbackTimer = window.setTimeout(() => {
    strip.hidden = true;
    strip.textContent = "";
    strip.removeAttribute("data-tone");
    state.feedbackTimer = null;
  }, FEEDBACK_MS);
}

function setWorkspaceNotice(tone, message, persist = false) {
  const box = qs("workspaceNotice");
  if (!box) return;
  if (!message) {
    box.hidden = true;
    box.textContent = "";
    box.removeAttribute("data-tone");
    return;
  }

  box.hidden = false;
  box.dataset.tone = tone || "info";
  box.textContent = message;

  if (state.workspaceNoticeTimer) clearTimeout(state.workspaceNoticeTimer);
  if (!persist) {
    state.workspaceNoticeTimer = window.setTimeout(() => {
      box.hidden = true;
      box.textContent = "";
      box.removeAttribute("data-tone");
      state.workspaceNoticeTimer = null;
    }, FEEDBACK_MS);
  }
}

function flashButton(button, label, className = "is-success", duration = BUTTON_FLASH_MS) {
  if (!button) return;
  const timer = state.buttonTimers.get(button);
  if (timer) clearTimeout(timer);
  if (!button.dataset.defaultLabel) {
    button.dataset.defaultLabel = button.textContent || "";
  }
  button.textContent = label;
  button.classList.add(className);
  const nextTimer = window.setTimeout(() => {
    button.textContent = button.dataset.defaultLabel || button.textContent;
    button.classList.remove(className);
    state.buttonTimers.delete(button);
  }, duration);
  state.buttonTimers.set(button, nextTimer);
}

function setButtonWorking(button, isWorking, label) {
  if (!button) return;
  if (!button.dataset.defaultLabel) {
    button.dataset.defaultLabel = button.textContent || "";
  }
  button.classList.toggle("is-working", !!isWorking);
  button.textContent = isWorking ? label : (button.dataset.defaultLabel || button.textContent);
}

async function apiGet(path) {
  const response = await fetch(path, { cache: "no-store" });
  const data = await response.json();
  if (!response.ok) {
    const message = data && (data.message || data.error)
      ? `${data.error || "Error"}: ${data.message || ""}`.trim()
      : "Request failed";
    throw new Error(message);
  }
  return data;
}

async function apiPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    const message = data && (data.message || data.error)
      ? `${data.error || "Error"}: ${data.message || ""}`.trim()
      : "Request failed";
    throw new Error(message);
  }
  return data;
}

function selectedFiles() {
  return Array.from(state.selected)
    .map((path) => state.fileSnapshot.get(path))
    .filter(Boolean);
}

function selectionSummary() {
  const files = selectedFiles();
  return {
    total: files.length,
    audio: files.filter((file) => file.is_audio).length,
    video: files.filter((file) => file.is_video).length,
    ready: files.filter((file) => file.checkable && !file.disabled).length,
  };
}

function librarySummary() {
  const groups = state.groups.length;
  let files = 0;
  for (const group of state.groups) {
    files += (group.files || []).length;
  }
  return { groups, files };
}

function resolveSystemTheme() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(mode, { persist = true } = {}) {
  state.themeMode = normalizeThemeMode(mode);
  state.resolvedTheme = state.themeMode === "system" ? resolveSystemTheme() : state.themeMode;

  document.documentElement.dataset.themeMode = state.themeMode;
  document.documentElement.dataset.theme = state.resolvedTheme;
  document.documentElement.style.colorScheme = state.resolvedTheme;

  if (persist) {
    writeStorage(THEME_STORAGE_KEY, state.themeMode);
  }

  for (const button of document.querySelectorAll("[data-theme-mode]")) {
    button.classList.toggle("is-active", button.getAttribute("data-theme-mode") === state.themeMode);
    button.setAttribute("aria-pressed", button.classList.contains("is-active") ? "true" : "false");
  }

  const textMap = {
    system: `Follow system (currently ${state.resolvedTheme === "dark" ? "dark" : "light"})`,
    light: "Light theme enabled",
    dark: "Dark theme enabled",
  };
  const statusText = textMap[state.themeMode] || textMap.system;

  if (qs("themeStatusText")) qs("themeStatusText").textContent = statusText;
  if (qs("themeModeExplain")) qs("themeModeExplain").textContent = `Current theme: ${statusText}`;
}

function fileMatchesFilter(file) {
  switch (state.fileFilter) {
    case "actionable":
      return !!file.checkable && !file.disabled;
    case "audio":
      return !!file.is_audio;
    case "video":
      return !!file.is_video;
    case "selected":
      return state.selected.has(file.path);
    case "all":
    default:
      return true;
  }
}

function fileMatchesQuery(file) {
  const query = state.query.trim().toLowerCase();
  if (!query) return true;
  const haystack = [
    file.display,
    file.path,
    file.state,
    file.format,
    file.time,
    file.size,
    file.dateKey,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  return haystack.includes(query);
}

function getVisibleGroups() {
  const visible = [];
  for (const group of state.groups || []) {
    const files = (group.files || []).filter((file) => fileMatchesFilter(file) && fileMatchesQuery(file));
    if (files.length) {
      visible.push({ ...group, files });
    }
  }
  return visible;
}

function visibleSummary() {
  const visibleGroups = getVisibleGroups();
  let files = 0;
  for (const group of visibleGroups) {
    files += (group.files || []).length;
  }
  return { groups: visibleGroups.length, files };
}

function updateTelemetry() {
  const summary = selectionSummary();
  const library = librarySummary();
  const visible = visibleSummary();
  const currentTask = state.activeTask ? (state.activeTask.pillLabel || state.activeTask.type) : "Idle";

  qs("selectionHeadline").textContent = `${summary.total} files selected`;
  qs("selectedAudioCount").textContent = String(summary.audio);
  qs("selectedVideoCount").textContent = String(summary.video);
  qs("selectedReadyCount").textContent = String(summary.ready);

  qs("selectionCountCard").textContent = String(summary.total);
  qs("libraryCountCard").textContent = `${library.groups} groups / ${library.files} files`;
  qs("resultSummary").textContent = `${visible.groups} groups / ${visible.files} files visible`;
  qs("timelineSummary").textContent = `${library.groups} groups · ${library.files} files`;

  const filterLabelMap = {
    all: "All",
    actionable: "Actionable",
    audio: "Audio",
    video: "Video",
    selected: "Selected",
  };
  const query = state.query.trim();
  const queryPieces = [];
  if (state.fileFilter !== "all") queryPieces.push(`Filter: ${filterLabelMap[state.fileFilter]}`);
  if (query) queryPieces.push(`Search: "${query}"`);
  qs("queryMeta").textContent = queryPieces.length
    ? `View: ${queryPieces.join(" · ")} · ${visible.files} results`
    : "Showing all files";

  qs("statusCurrentTask").textContent = currentTask;
  qs("statusSelection").textContent = `${summary.total} files`;
  qs("statusLibrary").textContent = `${library.groups} groups`;
  qs("statusLastSync").textContent = formatRelativeTime(state.lastSyncAt);

  const statusWord = state.busy
    ? (state.activeTask && state.activeTask.pillLabel ? state.activeTask.pillLabel : "Running")
    : "Idle";
  qs("headerSummary").textContent = `${statusWord} | ${summary.total} selected | ${library.files} files`;
}

function updateSettingsInputs() {
  const tzSelect = qs("timezoneSelect");
  const activeTimezone = state.settings.timezone || "Asia/Shanghai";
  const zones = Array.from(new Set([...TIMEZONES, activeTimezone]));
  tzSelect.innerHTML = zones.map((zone) => `<option value="${escapeHtml(zone)}">${escapeHtml(zone)}</option>`).join("");
  tzSelect.value = activeTimezone;
  qs("threadsInput").value = String(state.settings.max_workers || 4);
  const cutoff = Number(state.settings.cutoff_hour);
  qs("cutoffHourInput").value = String(Number.isFinite(cutoff) ? Math.max(0, Math.min(23, cutoff)) : 4);
}

function updateStatusDecorations(taskState) {
  const dot = qs("stateDot");
  const panelProgress = qs("panelProgress");
  const logBox = qs("logBox");
  const taskBadge = qs("taskBadge");

  document.body.dataset.busy = state.busy ? "true" : "false";
  dot.classList.remove("busy", "error");
  panelProgress.classList.toggle("is-busy", state.busy);
  logBox.classList.toggle("is-busy", state.busy);

  taskBadge.removeAttribute("data-status");
  if (taskState === "error") {
    dot.classList.add("error");
    taskBadge.dataset.status = "error";
    return;
  }
  if (taskState === "done") {
    taskBadge.dataset.status = "done";
    return;
  }
  if (state.busy || taskState === "running") {
    dot.classList.add("busy");
    taskBadge.dataset.status = "running";
  }
}

function syncFilterButtons() {
  for (const button of document.querySelectorAll("[data-file-filter]")) {
    const active = button.getAttribute("data-file-filter") === state.fileFilter;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }
}

function updateActionAvailability() {
  const summary = selectionSummary();
  const library = librarySummary();
  const importPath = qs("importPathInput").value.trim();

  qs("mergeBtn").disabled = state.busy || summary.audio < 1;
  qs("convertBtn").disabled = state.busy || summary.video < 1;
  qs("annotateBtn").disabled = state.busy || summary.ready < 1;
  qs("silenceBtn").disabled = state.busy || summary.audio < 1;
  qs("refreshBtn").disabled = state.busy;
  qs("runRefreshBtn").disabled = state.busy;
  qs("importBtn").disabled = state.busy || !importPath;
  qs("saveSettingsBtn").disabled = state.busy || state.settingsSaveInFlight;
  qs("timezoneSelect").disabled = state.busy || state.settingsSaveInFlight;
  qs("threadsInput").disabled = state.busy || state.settingsSaveInFlight;
  qs("cutoffHourInput").disabled = state.busy || state.settingsSaveInFlight;
  qs("organizeArmBtn").disabled = state.busy || library.files < 1;
  qs("organizeConfirmBtn").disabled = state.busy || library.files < 1;

  for (const button of document.querySelectorAll("[data-merge-by-date]")) {
    button.disabled = state.busy || button.dataset.mergeEnabled !== "true";
  }

  const origin = state.activeTask ? document.querySelector(state.activeTask.triggerSelector) : null;
  for (const button of document.querySelectorAll(".btn")) {
    if (button === origin) continue;
    if (button.classList.contains("is-working")) {
      setButtonWorking(button, false);
    }
  }
  if (origin && state.activeTask) {
    setButtonWorking(origin, state.busy, state.activeTask.runningLabel);
  }

  syncFilterButtons();
  updateTelemetry();
}

function highlightMatch(text, query) {
  const safeText = String(text || "");
  const q = String(query || "").trim();
  if (!q) return escapeHtml(safeText);
  const lowerText = safeText.toLowerCase();
  const lowerQuery = q.toLowerCase();
  const idx = lowerText.indexOf(lowerQuery);
  if (idx < 0) return escapeHtml(safeText);
  const end = idx + q.length;
  return `${escapeHtml(safeText.slice(0, idx))}<mark>${escapeHtml(safeText.slice(idx, end))}</mark>${escapeHtml(safeText.slice(end))}`;
}

function fileRowHtml(file) {
  const disabled = !!file.disabled;
  const selected = state.selected.has(file.path);
  const fresh = state.highlightedPaths.has(file.path);
  const styleClass = file.style ? `style-${escapeHtml(file.style)}` : "";
  const formatBadge = file.is_video && file.format
    ? `<span class="mediaBadge">${escapeHtml(String(file.format).toUpperCase())}</span>`
    : "";
  const checkbox = file.checkable
    ? `<label class="fileCheck"><input type="checkbox" data-path="${escapeHtml(file.path)}" ${selected ? "checked" : ""} ${disabled ? "disabled" : ""} /></label>`
    : `<div class="fileCheck"></div>`;

  return `
    <div
      class="fileRow ${disabled ? "disabled" : ""} ${selected ? "selected" : ""} ${fresh ? "fresh" : ""} ${styleClass}"
      data-row-path="${escapeHtml(file.path)}"
      aria-selected="${selected ? "true" : "false"}"
      ${disabled ? "" : 'tabindex="0"'}
    >
      ${checkbox}
      <div class="fileMain" title="${escapeHtml(file.display || file.path)}">
        <span class="fileName">${highlightMatch(file.display || file.path, state.query)}</span>
        ${formatBadge}
      </div>
      <div class="fileMeta">${escapeHtml(file.time || "")}</div>
      <div class="stateTag ${escapeHtml(file.style || "normal")}">${escapeHtml(file.state || "")}</div>
      <div class="fileMeta">${escapeHtml(file.size || "")}</div>
    </div>
  `;
}

function groupMetaSummary(group) {
  const files = group.files || [];
  const audioCount = files.filter((file) => file.is_audio).length;
  const videoCount = files.filter((file) => file.is_video).length;
  const actionableCount = files.filter((file) => file.checkable && !file.disabled && file.is_audio).length;
  const mergeable = actionableCount > 0;
  return {
    audioCount,
    videoCount,
    actionableCount,
    totalCount: files.length,
    mergeable,
  };
}

function renderFiles() {
  const root = qs("filesRoot");
  const visibleGroups = getVisibleGroups();

  if (!state.groups.length) {
    root.innerHTML = `<div class="emptyState">No media files are available in the current directory.</div>`;
    updateActionAvailability();
    return;
  }

  if (!visibleGroups.length) {
    root.innerHTML = `<div class="emptyState">No matches for the current filter. Try changing filters or clearing the search.</div>`;
    updateActionAvailability();
    return;
  }

  root.innerHTML = visibleGroups.map((group) => {
    const meta = groupMetaSummary(group);
    const rows = (group.files || []).map((file) => fileRowHtml(file)).join("");
    const accentStyle = group.color ? ` style="--group-accent:${escapeHtml(group.color)}"` : "";
    return `
      <section class="dateGroup ${state.highlightedGroups.has(group.date_key) ? "group-fresh" : ""}" data-date-key="${escapeHtml(group.date_key)}"${accentStyle}>
        <div class="groupHeader">
          <div class="groupTitle">
            <span class="groupDate">${escapeHtml(group.date_key)}</span>
            <span class="groupMeta">${meta.totalCount} files · ${meta.audioCount} audio · ${meta.videoCount} video · ${meta.actionableCount} ready</span>
          </div>
          <div class="groupActions">
            <button
              class="btn btn-ghost"
              type="button"
              data-merge-by-date="${escapeHtml(group.date_key)}"
              data-merge-enabled="${meta.mergeable ? "true" : "false"}"
            >Merge Day</button>
          </div>
        </div>
        <div class="fileRows">${rows}</div>
      </section>
    `;
  }).join("");

  updateActionAvailability();
}

function replaySelectionFlash(row) {
  if (!row) return;
  row.classList.remove("selection-flash");
  void row.offsetWidth;
  row.classList.add("selection-flash");
  row.addEventListener("animationend", () => {
    row.classList.remove("selection-flash");
  }, { once: true });
}

function syncVisibleSelectionState({ animatePaths = [] } = {}) {
  const animateSet = new Set(animatePaths);
  for (const row of document.querySelectorAll("[data-row-path]")) {
    const path = row.getAttribute("data-row-path");
    if (!path) continue;
    const selected = state.selected.has(path);
    row.classList.toggle("selected", selected);
    row.setAttribute("aria-selected", selected ? "true" : "false");

    const checkbox = row.querySelector("input[type='checkbox'][data-path]");
    if (checkbox) checkbox.checked = selected;

    if (selected && animateSet.has(path)) {
      replaySelectionFlash(row);
    } else {
      row.classList.remove("selection-flash");
    }
  }
}

function refreshSelectionUi({ animatePaths = [] } = {}) {
  if (state.fileFilter === "selected") {
    renderFiles();
    return;
  }
  syncVisibleSelectionState({ animatePaths });
  updateActionAvailability();
}

function setActiveTab(tabName) {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("is-active", tab.dataset.tab === tabName);
  }
  for (const pane of document.querySelectorAll(".pane")) {
    pane.classList.toggle("is-active", pane.dataset.pane === tabName);
  }
  writeStorage(TAB_STORAGE_KEY, tabName);
}

function setCollapsed(collapsed) {
  const panel = qs("commandPanel");
  const toggle = qs("panelToggle");
  const fold = qs("headerFold");
  panel.dataset.collapsed = collapsed ? "true" : "false";
  document.body.dataset.panelCollapsed = collapsed ? "true" : "false";
  toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  fold.textContent = collapsed ? "Expand" : "Collapse";
  writeStorage(PANEL_STORAGE_KEY, collapsed ? "true" : "false");
}

function setTaskPanel(record, metaOverride = null) {
  if (!record || !record.task_id) {
    qs("taskHeadline").textContent = "Idle";
    qs("taskMeta").textContent = "No active task";
    qs("taskSubline").textContent = "Waiting for action.";
    qs("taskBadge").textContent = "Idle";
    qs("logBox").textContent = "";
    updateStatusDecorations(null);
    return;
  }

  const taskMeta = metaOverride || state.activeTask;
  const taskLabel = taskMeta && taskMeta.pillLabel ? taskMeta.pillLabel : "Task";
  const stateLabel = record.status === "running"
    ? "Running"
    : (record.status === "done" ? "Done" : "Failed");
  const lastLog = Array.isArray(record.log) && record.log.length ? record.log[record.log.length - 1] : "";

  qs("taskHeadline").textContent = taskLabel;
  qs("taskMeta").textContent = stateLabel;
  qs("taskSubline").textContent = lastLog || (record.status === "running" ? "Working…" : "Waiting for action.");
  qs("taskBadge").textContent = stateLabel;
  qs("logBox").textContent = Array.isArray(record.log) ? record.log.join("\n") : "";
  updateStatusDecorations(record.status);
}

async function fetchObsLocation({ overwriteInput = false } = {}) {
  try {
    const response = await apiGet("/api/obs_location");
    const input = qs("importPathInput");
    const hint = qs("importPathHint");
    if (response && response.path) {
      if (overwriteInput || !input.value.trim()) input.value = response.path;
      hint.textContent = `Detected OBS directory: ${response.path}`;
      updateActionAvailability();
      return response.path;
    }
    hint.textContent = "OBS directory was not detected automatically. Paste a path manually.";
    updateActionAvailability();
    return "";
  } catch {
    return "";
  }
}

async function refreshAll({ highlightChanges = false, taskMeta = null } = {}) {
  const previousSnapshot = state.fileSnapshot;
  const previousSelection = new Set(state.selected);

  clearHighlights();

  const appState = await apiGet("/api/state");
  state.cwd = appState.cwd || "";
  state.settings = appState.settings || state.settings;
  state.busy = !!appState.busy;
  state.currentTaskId = appState.current_task ? appState.current_task.task_id : null;

  const files = await apiGet("/api/files");
  state.groups = files.groups || [];
  state.fileSnapshot = buildFileSnapshot(state.groups);
  state.lastSyncAt = Date.now();

  const nextSelection = new Set();
  for (const path of previousSelection) {
    const file = state.fileSnapshot.get(path);
    if (file && file.checkable && !file.disabled) {
      nextSelection.add(path);
    }
  }
  state.selected = nextSelection;

  updateSettingsInputs();
  renderFiles();
  updateTelemetry();
  setTaskPanel(appState.current_task || null, state.activeTask);

  const cwdCard = qs("cwdCard");
  cwdCard.textContent = state.cwd;
  cwdCard.title = state.cwd;

  if (highlightChanges) {
    const diff = diffSnapshots(previousSnapshot, state.fileSnapshot, taskMeta);
    setHighlights(diff.paths, diff.groups);
    renderFiles();
  }
}

async function pollTask() {
  try {
    const record = await apiGet("/api/task/current");
    if (!record || !record.task_id) {
      state.currentTaskId = null;
      state.observedTaskRunning = false;
      state.busy = false;
      state.activeTask = null;
      setTaskPanel(null);
      updateActionAvailability();
      return;
    }

    state.currentTaskId = record.task_id;
    const isRunning = record.status === "running";
    if (isRunning) state.observedTaskRunning = true;
    state.busy = isRunning;
    setTaskPanel(record);
    updateActionAvailability();

    if ((record.status === "done" || record.status === "error") && state.lastHandledFinishedTaskId !== record.task_id) {
      const taskMeta = state.activeTask;
      state.lastHandledFinishedTaskId = record.task_id;
      state.observedTaskRunning = false;

      if (record.status === "done") {
        const successMessage = formatTaskSuccess(taskMeta, record.result || {});
        setFeedback("success", successMessage);
        setWorkspaceNotice("success", successMessage);
        const origin = taskMeta ? document.querySelector(taskMeta.triggerSelector) : null;
        flashButton(origin, "✓ Done");
        await refreshAll({ highlightChanges: true, taskMeta });
      } else {
        const errorMessage = formatTaskError(taskMeta, record.result || {});
        setFeedback("error", errorMessage);
        setWorkspaceNotice("error", errorMessage);
        await refreshAll();
      }

      state.busy = false;
      setTaskPanel(record, taskMeta);
      state.activeTask = null;
      updateActionAvailability();
    }
  } catch {
    return;
  }
}

function ensurePolling() {
  if (state.pollTimer) return;
  state.pollTimer = window.setInterval(pollTask, 900);
}

async function startTask(payload, sourceEl = null) {
  const taskMeta = createTaskMeta(payload, sourceEl);
  try {
    const response = await apiPost("/api/task", payload);
    state.activeTask = taskMeta;
    state.currentTaskId = response.task_id || null;
    state.lastHandledFinishedTaskId = null;
    state.observedTaskRunning = true;
    state.busy = true;
    setFeedback("info", formatTaskStart(taskMeta));
    setWorkspaceNotice("info", formatTaskStart(taskMeta));
    setTaskPanel({
      task_id: response.task_id,
      status: "running",
      log: [],
    });
    updateActionAvailability();
    ensurePolling();
    await pollTask();
  } catch (error) {
    state.activeTask = null;
    state.observedTaskRunning = false;
    state.busy = false;
    setFeedback("error", error.message || String(error));
    setWorkspaceNotice("error", error.message || String(error));
    updateActionAvailability();
  }
}

function selectedPaths() {
  return Array.from(state.selected);
}

async function onImport(sourceEl) {
  const sourceDir = qs("importPathInput").value.trim();
  if (!sourceDir) return;
  await startTask({ type: "IMPORT", params: { source_dir: sourceDir } }, sourceEl);
}

async function onConvert(sourceEl) {
  await startTask({ type: "CONVERT", paths: selectedPaths() }, sourceEl);
}

async function onMerge(sourceEl) {
  await startTask({ type: "MERGE", paths: selectedPaths() }, sourceEl);
}

async function onAnnotate(sourceEl) {
  await startTask({ type: "ANNOTATE_TIME_RANGE", paths: selectedPaths() }, sourceEl);
}

async function onSilence(sourceEl) {
  await startTask({ type: "REMOVE_SILENCE", paths: selectedPaths() }, sourceEl);
}

async function onOrganize(sourceEl) {
  qs("organizeConfirmBlock").hidden = true;
  await startTask({ type: "ORGANIZE", params: { create_archive: true } }, sourceEl);
}

function setSettingsStatus(text, tone = "") {
  const node = qs("settingsStatus");
  node.textContent = text;
  node.dataset.tone = tone;
}

function markSettingsDirty() {
  if (state.busy || state.settingsSaveInFlight) return;
  setSettingsStatus("Settings changed, applying soon…", "pending");
}

async function saveSettings(trigger = "manual") {
  if (state.settingsSaveInFlight) return;
  state.settingsSaveInFlight = true;
  updateActionAvailability();
  const button = qs("saveSettingsBtn");
  setButtonWorking(button, true, "Applying…");
  setSettingsStatus("Applying settings…", "pending");

  const timezone = qs("timezoneSelect").value;
  const maxWorkers = Math.max(1, Math.min(16, Number(qs("threadsInput").value || "4") || 4));
  const cutoffHour = Math.max(0, Math.min(23, Number(qs("cutoffHourInput").value || "4") || 4));

  try {
    const response = await apiPost("/api/settings", {
      timezone,
      max_workers: maxWorkers,
      cutoff_hour: cutoffHour,
    });
    if (response && response.settings) {
      state.settings = response.settings;
    }
    await refreshAll();
    setSettingsStatus(`Applied: ${state.settings.timezone} · threads ${state.settings.max_workers} · cutoff ${state.settings.cutoff_hour}`, "ok");
    if (trigger === "manual") {
      flashButton(button, "✓ Applied");
    }
  } catch (error) {
    setSettingsStatus(`Save failed: ${error.message || String(error)}`, "error");
    setFeedback("error", error.message || String(error));
    setWorkspaceNotice("error", error.message || String(error));
  } finally {
    state.settingsSaveInFlight = false;
    setButtonWorking(button, false);
    updateActionAvailability();
  }
}

function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    if (timer) clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

function setAllSelection(checked) {
  for (const [path, file] of state.fileSnapshot.entries()) {
    if (!file.checkable || file.disabled) continue;
    if (checked) state.selected.add(path);
    else state.selected.delete(path);
  }
  refreshSelectionUi();
  if (checked) {
    flashButton(qs("selectAllBtn"), "✓ Selected");
  } else {
    flashButton(qs("deselectAllBtn"), "✓ Cleared");
  }
}

function handleFileRowToggle(path, checked) {
  if (!path) return;
  if (checked) state.selected.add(path);
  else state.selected.delete(path);
  refreshSelectionUi({ animatePaths: checked ? [path] : [] });
}

function toggleRowSelection(path) {
  if (!path) return;
  const checkbox = document.querySelector(`input[type="checkbox"][data-path="${CSS.escape(path)}"]`);
  if (!checkbox || checkbox.disabled) return;
  checkbox.checked = !checkbox.checked;
  handleFileRowToggle(path, checkbox.checked);
}

function wireFileEvents() {
  const root = qs("filesRoot");
  root.addEventListener("change", (event) => {
    const checkbox = event.target;
    if (!checkbox || checkbox.tagName !== "INPUT" || checkbox.type !== "checkbox") return;
    handleFileRowToggle(checkbox.getAttribute("data-path"), checkbox.checked);
  });

  root.addEventListener("click", (event) => {
    const mergeButton = event.target.closest("[data-merge-by-date]");
    if (mergeButton) {
      const dateKey = mergeButton.getAttribute("data-merge-by-date");
      if (dateKey) {
        startTask({ type: "MERGE_BY_DATE", params: { date_key: dateKey } }, mergeButton);
      }
      return;
    }

    if (event.target.closest("input[type='checkbox']")) return;

    const row = event.target.closest("[data-row-path]");
    if (!row || row.classList.contains("disabled")) return;
    const path = row.getAttribute("data-row-path");
    toggleRowSelection(path);
  });

  root.addEventListener("keydown", (event) => {
    const row = event.target.closest("[data-row-path]");
    if (!row || row.classList.contains("disabled")) return;
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      const path = row.getAttribute("data-row-path");
      toggleRowSelection(path);
    }
  });
}

function initPanelControls() {
  const initialCollapsed = readStorage(PANEL_STORAGE_KEY, "false") === "true";
  const initialTab = readStorage(TAB_STORAGE_KEY, "run");
  setCollapsed(initialCollapsed);
  setActiveTab(["run", "load", "status"].includes(initialTab) ? initialTab : "run");

  qs("panelToggle").addEventListener("click", () => {
    const collapsed = qs("commandPanel").dataset.collapsed === "true";
    setCollapsed(!collapsed);
  });

  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => setActiveTab(tab.dataset.tab));
  }
}

function initThemeControls() {
  applyTheme(state.themeMode, { persist: false });

  for (const button of document.querySelectorAll("[data-theme-mode]")) {
    button.addEventListener("click", () => applyTheme(button.getAttribute("data-theme-mode")));
  }

  if (window.matchMedia) {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = () => {
      if (state.themeMode === "system") applyTheme("system", { persist: false });
    };
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", listener);
    } else if (typeof media.addListener === "function") {
      media.addListener(listener);
    }
  }
}

function initFilterControls() {
  for (const button of document.querySelectorAll("[data-file-filter]")) {
    button.addEventListener("click", () => {
      state.fileFilter = normalizeFileFilter(button.getAttribute("data-file-filter"));
      writeStorage(FILE_FILTER_STORAGE_KEY, state.fileFilter);
      renderFiles();
    });
  }

  const searchInput = qs("searchInput");
  const searchClear = qs("searchClearBtn");
  const syncSearchClear = () => {
    const hasValue = !!searchInput.value.trim();
    searchClear.style.visibility = hasValue ? "visible" : "hidden";
  };

  searchInput.addEventListener("input", () => {
    state.query = searchInput.value;
    syncSearchClear();
    renderFiles();
  });

  searchClear.addEventListener("click", () => {
    searchInput.value = "";
    state.query = "";
    syncSearchClear();
    renderFiles();
    searchInput.focus();
  });

  syncSearchClear();
}

function isTypingTarget(target) {
  if (!target) return false;
  const tag = target.tagName;
  return target.isContentEditable || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

function initKeyboardShortcuts() {
  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented) return;

    const typing = isTypingTarget(event.target);
    const searchInput = qs("searchInput");

    if ((event.key === "/" && !typing) || ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k")) {
      event.preventDefault();
      searchInput.focus();
      searchInput.select();
      return;
    }

    if (event.key === "Escape") {
      if (document.activeElement === searchInput && searchInput.value) {
        searchInput.value = "";
        state.query = "";
        renderFiles();
      }
      qs("organizeConfirmBlock").hidden = true;
    }
  });
}

async function init() {
  initPanelControls();
  initThemeControls();
  initFilterControls();
  initKeyboardShortcuts();
  wireFileEvents();

  qs("refreshBtn").addEventListener("click", async (event) => {
    try {
      await refreshAll();
      flashButton(event.currentTarget, "✓ Synced");
      setWorkspaceNotice("success", "File list refreshed.");
    } catch (error) {
      setFeedback("error", error.message || String(error));
      setWorkspaceNotice("error", error.message || String(error));
    }
  });

  qs("runRefreshBtn").addEventListener("click", async (event) => {
    try {
      await refreshAll();
      flashButton(event.currentTarget, "✓ Synced");
    } catch (error) {
      setFeedback("error", error.message || String(error));
      setWorkspaceNotice("error", error.message || String(error));
    }
  });

  qs("selectAllBtn").addEventListener("click", () => setAllSelection(true));
  qs("deselectAllBtn").addEventListener("click", () => setAllSelection(false));

  qs("mergeBtn").addEventListener("click", (event) => onMerge(event.currentTarget));
  qs("convertBtn").addEventListener("click", (event) => onConvert(event.currentTarget));
  qs("annotateBtn").addEventListener("click", (event) => onAnnotate(event.currentTarget));
  qs("silenceBtn").addEventListener("click", (event) => onSilence(event.currentTarget));

  qs("detectObsBtn").addEventListener("click", async (event) => {
    const path = await fetchObsLocation({ overwriteInput: true });
    if (path) {
      flashButton(event.currentTarget, "✓ Filled");
      setFeedback("success", "Detected OBS directory inserted.");
    } else {
      setFeedback("warning", "OBS path not detected. Enter it manually.");
    }
  });

  qs("importBtn").addEventListener("click", (event) => onImport(event.currentTarget));
  qs("importPathInput").addEventListener("input", () => updateActionAvailability());

  qs("saveSettingsBtn").addEventListener("click", () => saveSettings("manual"));
  const autoSave = debounce(() => {
    if (!state.busy) saveSettings("auto");
  }, 360);

  for (const id of ["timezoneSelect", "threadsInput", "cutoffHourInput"]) {
    qs(id).addEventListener("change", () => {
      markSettingsDirty();
      autoSave();
    });
    qs(id).addEventListener("blur", autoSave);
  }

  qs("organizeArmBtn").addEventListener("click", (event) => {
    qs("organizeConfirmBlock").hidden = false;
    flashButton(event.currentTarget, "Confirm below", "is-working", 1200);
  });
  qs("organizeCancelBtn").addEventListener("click", () => {
    qs("organizeConfirmBlock").hidden = true;
  });
  qs("organizeConfirmBtn").addEventListener("click", (event) => onOrganize(event.currentTarget));

  updateSettingsInputs();
  setSettingsStatus("Settings loaded.");
  syncFilterButtons();

  try {
    await refreshAll();
    await fetchObsLocation();
    ensurePolling();
    await pollTask();
  } catch (error) {
    setFeedback("error", error.message || String(error));
    setWorkspaceNotice("error", error.message || String(error), true);
  }
}

init();
