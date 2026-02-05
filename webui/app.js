const TIMEZONES = [
  "UTC",
  "US/Eastern",
  "US/Pacific",
  "Europe/London",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Australia/Sydney",
];

const state = {
  cwd: "",
  busy: false,
  settings: { timezone: "Asia/Shanghai", max_workers: 4 },
  groups: [],
  selected: new Set(),
  currentTaskId: null,
  lastHandledFinishedTaskId: null,
  pollTimer: null,
};

function qs(id) { return document.getElementById(id); }

function setBusy(busy) {
  state.busy = !!busy;
  const pill = qs("busyPill");
  if (state.busy) {
    pill.textContent = "Busy";
    pill.classList.add("busy");
  } else {
    pill.textContent = "Idle";
    pill.classList.remove("busy");
  }

  for (const id of ["importBtn","convertBtn","mergeBtn","silenceBtn","organizeBtn","refreshBtn","saveSettingsBtn"]) {
    const el = qs(id);
    if (el) el.disabled = state.busy;
  }
  for (const id of ["timezoneSelect", "threadsInput"]) {
    const el = qs(id);
    if (el) el.disabled = state.busy;
  }
  for (const btn of document.querySelectorAll("[data-merge-by-date]")) {
    btn.disabled = state.busy;
  }
}

function updateSelectionHint() {
  qs("selectionHint").textContent = `${state.selected.size} selected`;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll("\"","&quot;")
    .replaceAll("'","&#039;");
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

  const checked = state.selected.has(file.path) ? "checked" : "";
  const cb = file.checkable
    ? `<input type="checkbox" data-path="${escapeHtml(file.path)}" ${checked} ${disabled ? "disabled" : ""} />`
    : `<span></span>`;

  return `
    <div class="fileRow ${disabled ? "disabled" : ""} style-${escapeHtml(styleClass)}" data-row-path="${escapeHtml(file.path)}" title="${escapeHtml(file.display || "")}">
      ${cb}
      <div class="fileName">${escapeHtml(file.display || "")}</div>
      <div class="fileMeta">${escapeHtml(file.time || "")}</div>
      <div class="stateTag ${escapeHtml(styleClass)}" title="${escapeHtml(file.state || "")}">${escapeHtml(file.state || "")}</div>
      <div class="fileMeta">${escapeHtml(file.size || "")}</div>
    </div>
  `;
}

function renderFiles() {
  const root = qs("filesRoot");
  root.innerHTML = "";
  root.classList.add("filesRoot");

  for (const group of state.groups) {
    const swatch = group.color ? `<div class="swatch" style="background:${escapeHtml(group.color)}"></div>` : `<div class="swatch"></div>`;
    const filesHtml = (group.files || []).map(fileRowHtml).join("");
    const groupEl = document.createElement("div");
    groupEl.className = "dateGroup";
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
}

function applySettingsToUI() {
  const tzSel = qs("timezoneSelect");
  const currentTz = state.settings.timezone || "Asia/Shanghai";
  const zones = Array.from(new Set([...TIMEZONES, currentTz]));
  tzSel.innerHTML = zones.map(tz => `<option value="${escapeHtml(tz)}">${escapeHtml(tz)}</option>`).join("");
  tzSel.value = currentTz;
  qs("threadsInput").value = String(state.settings.max_workers || 4);
}

async function refreshAll() {
  const st = await apiGet("/api/state");
  state.cwd = st.cwd || "";
  state.settings = st.settings || state.settings;
  qs("cwd").textContent = state.cwd;
  setBusy(!!st.busy);
  applySettingsToUI();

  const files = await apiGet("/api/files");
  state.groups = files.groups || [];

  // Match desktop UI: refresh rebuilds the tree, so all checkboxes reset to Unchecked.
  state.selected = new Set();
  updateSelectionHint();
  renderFiles();
}

function setLog(lines) {
  const box = qs("logBox");
  box.textContent = (lines || []).join("\n");
  box.scrollTop = box.scrollHeight;
}

async function pollTask() {
  try {
    const t = await apiGet("/api/task/current");
    if (!t || !t.task_id) {
      state.currentTaskId = null;
      setLog([]);
      setBusy(false);
      return;
    }
    state.currentTaskId = t.task_id;
    setBusy(t.status === "running");
    setLog(t.log || []);
    if (t.status === "done" || t.status === "error") {
      if (state.lastHandledFinishedTaskId !== t.task_id) {
        state.lastHandledFinishedTaskId = t.task_id;
        await refreshAll();
      }
    }
  } catch (e) {
    // ignore transient errors
  }
}

function ensurePolling() {
  if (state.pollTimer) return;
  state.pollTimer = setInterval(pollTask, 800);
}

async function startTask(payload) {
  try {
    const res = await apiPost("/api/task", payload);
    state.currentTaskId = res.task_id || null;
    state.lastHandledFinishedTaskId = null;
    ensurePolling();
    await pollTask();
  } catch (e) {
    alert(e.message || String(e));
  }
}

async function startMergeByDate(dateKey) {
  await startTask({ type: "MERGE_BY_DATE", params: { date_key: dateKey } });
}

function selectedPaths() {
  return Array.from(state.selected);
}

async function onImport() {
  try {
    const hint = await apiGet("/api/obs_location");
    const dialog = qs("importDialog");
    const input = qs("importPathInput");
    input.value = (hint && hint.path) ? hint.path : "";
    dialog.showModal();

    const confirmed = await new Promise((resolve) => {
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    });
    if (!confirmed) return;
    const sourceDir = input.value.trim();
    if (!sourceDir) {
      alert("Please provide a source directory path.");
      return;
    }
    await startTask({ type: "IMPORT", params: { source_dir: sourceDir } });
  } catch (e) {
    alert(e.message || String(e));
  }
}

async function onConvert() {
  const paths = selectedPaths();
  if (!paths.length) return alert("Select some files first.");
  await startTask({ type: "CONVERT", paths });
}

async function onMergeSelected() {
  const paths = selectedPaths();
  await startTask({ type: "MERGE", paths });
}

async function onSilence() {
  const paths = selectedPaths();
  if (!paths.length) return alert("Select some files first.");
  await startTask({ type: "REMOVE_SILENCE", paths });
}

async function onOrganize() {
  const ok = confirm("Organize all files by date and create an archive for each folder?");
  if (!ok) return;
  await startTask({ type: "ORGANIZE", params: { create_archive: true } });
}

async function onSaveSettings() {
  const tz = qs("timezoneSelect").value;
  const mw = Number(qs("threadsInput").value || "4");
  const maxWorkers = Math.max(1, Math.min(16, isFinite(mw) ? mw : 4));
  try {
    await apiPost("/api/settings", { timezone: tz, max_workers: maxWorkers });
    await refreshAll();
  } catch (e) {
    alert(e.message || String(e));
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
  for (const cb of root.querySelectorAll("input[type='checkbox'][data-path]")) {
    if (cb.disabled) continue;
    cb.checked = checked;
    const p = cb.getAttribute("data-path");
    if (!p) continue;
    if (checked) state.selected.add(p);
    else state.selected.delete(p);
  }
  updateSelectionHint();
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
  });

  filesRoot.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-merge-by-date]");
    if (btn) {
      const dk = btn.getAttribute("data-merge-by-date");
      if (dk) startMergeByDate(dk);
      return;
    }

    const row = e.target.closest("[data-row-path]");
    if (!row) return;
    const p = row.getAttribute("data-row-path");
    if (!p) return;
    const cb = row.querySelector(`input[type="checkbox"][data-path="${CSS.escape(p)}"]`);
    if (cb && !cb.disabled) cb.click();
  });

  qs("refreshBtn").addEventListener("click", () => refreshAll().catch(e => alert(e.message || String(e))));
  qs("importBtn").addEventListener("click", onImport);
  qs("convertBtn").addEventListener("click", onConvert);
  qs("mergeBtn").addEventListener("click", onMergeSelected);
  qs("silenceBtn").addEventListener("click", onSilence);
  qs("organizeBtn").addEventListener("click", onOrganize);
  qs("saveSettingsBtn").addEventListener("click", onSaveSettings);
  qs("selectAllBtn").addEventListener("click", () => setAll(true));
  qs("deselectAllBtn").addEventListener("click", () => setAll(false));

  // Auto-save settings on change (prevents "reverting" when user forgets to click Save)
  const autoSave = debounce(() => {
    if (state.busy) return;
    onSaveSettings();
  }, 350);
  qs("timezoneSelect").addEventListener("change", autoSave);
  qs("threadsInput").addEventListener("change", autoSave);
  qs("threadsInput").addEventListener("blur", autoSave);

  applySettingsToUI();
  await refreshAll();
  ensurePolling();
}

init().catch((e) => {
  alert(e.message || String(e));
});
