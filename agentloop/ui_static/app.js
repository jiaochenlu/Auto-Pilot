const state = {
  tasks: [],
  selectedTaskId: null,
  detail: null,
  filter: "all",
  runtimeIndex: 0,
  iterationIndex: null,
  busy: false,
  settings: null,
  pollTimer: null,
};

const REFRESH_INTERVAL_MS = 3000;

const $ = (id) => document.getElementById(id);

async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error?.message || `HTTP ${response.status}`);
  }
  return data;
}

function showBanner(message) {
  const banner = $("banner");
  if (!message) {
    banner.classList.add("hidden");
    banner.textContent = "";
    return;
  }
  banner.textContent = message;
  banner.classList.remove("hidden");
}

function statusClass(status) {
  return `badge status-${String(status || "UNKNOWN").replaceAll(" ", "_")}`;
}

function matchesFilter(task) {
  const status = String(task.status || "");
  if (state.filter === "all") return true;
  if (state.filter === "active") return !["DONE", "CANCELLED", "CREATED"].includes(status);
  if (state.filter === "waiting") return status.includes("WAITING") || status === "READY_TO_START";
  if (state.filter === "running") return ["DESIGNING", "IMPLEMENTING_AND_TESTING", "REVIEWING"].includes(status);
  if (state.filter === "done") return ["DONE", "CANCELLED"].includes(status);
  return true;
}

function renderTaskList() {
  const search = $("searchInput").value.toLowerCase().trim();
  const list = $("taskList");
  list.innerHTML = "";
  const filtered = state.tasks.filter((task) => {
    const text = `${task.task_id} ${task.title}`.toLowerCase();
    return matchesFilter(task) && (!search || text.includes(search));
  });
  if (!filtered.length) {
    list.innerHTML = '<div class="task-sub">No tasks match this view.</div>';
    return;
  }
  for (const task of filtered) {
    const button = document.createElement("button");
    button.className = `task-row ${task.task_id === state.selectedTaskId ? "active" : ""}`;
    button.innerHTML = `
      <div class="task-row-top">
        <span class="task-title">${escapeHtml(task.current ? "* " : "")}${escapeHtml(task.title || task.task_id)}</span>
        <span class="${statusClass(task.status)}">${escapeHtml(task.status || "UNKNOWN")}</span>
      </div>
      <div class="task-sub">
        <span class="task-id">${escapeHtml(task.task_id)}</span>
      </div>
      <div class="task-sub">
        <span>${escapeHtml(task.current_phase || "-")}</span>
        <span>${task.iteration ?? "-"}/${task.max_iterations ?? "-"}</span>
        <span>${escapeHtml(task.updated_at || "-")}</span>
        ${task.locked ? "<span>locked</span>" : ""}
      </div>`;
    button.addEventListener("click", () => selectTask(task.task_id));
    list.appendChild(button);
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[ch]));
}

async function loadTasks(keepSelection = true) {
  const data = await apiFetch("/api/tasks");
  state.tasks = data.tasks || [];
  if (!keepSelection || !state.selectedTaskId || !state.tasks.some((task) => task.task_id === state.selectedTaskId)) {
    state.selectedTaskId = data.current_task_id || state.tasks[0]?.task_id || null;
  }
  renderTaskList();
  if (state.selectedTaskId) {
    await loadDetail(state.selectedTaskId);
  } else {
    renderEmptyDetail();
  }
}

async function refreshSelectedTask() {
  if (state.busy) return;
  try {
    await loadTasks(true);
    showBanner(null);
  } catch (error) {
    showBanner(error.message);
  }
}

function startAutoRefresh() {
  if (state.pollTimer) window.clearInterval(state.pollTimer);
  state.pollTimer = window.setInterval(refreshSelectedTask, REFRESH_INTERVAL_MS);
}

async function loadSettings() {
  state.settings = await apiFetch("/api/settings");
  return state.settings;
}

async function selectTask(taskId) {
  state.selectedTaskId = taskId;
  renderTaskList();
  await loadDetail(taskId);
}

async function loadDetail(taskId) {
  try {
    state.detail = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}`);
    state.runtimeIndex = 0;
    state.iterationIndex = state.detail.runtime?.latest_iteration ?? null;
    renderDetail();
    showBanner((state.detail.errors || []).join("; "));
  } catch (error) {
    showBanner(error.message);
  }
}

function renderEmptyDetail() {
  state.detail = null;
  $("taskIdLabel").textContent = "No task selected";
  $("taskTitle").textContent = "Create or select a task";
  $("taskMeta").textContent = "";
  ["approveBtn", "cancelBtn", "deleteBtn"].forEach((id) => ($(id).disabled = true));
}

function renderDetail() {
  const detail = state.detail;
  const task = detail.state;
  $("taskIdLabel").textContent = task.task_id;
  $("taskTitle").textContent = task.title || task.task_id;
  $("taskMeta").innerHTML = `<span class="${statusClass(task.status)}">${escapeHtml(task.status)}</span> ${escapeHtml(task.current_phase || "-")} · ${task.iteration ?? "-"}/${task.max_iterations ?? "-"} · updated ${escapeHtml(task.updated_at || "-")}`;
  setAction("approveBtn", detail.actions.approve, () => mutate("approve"));
  $("approveBtn").textContent = "Approve and run";
  setAction("cancelBtn", detail.actions.cancel, () => mutate("cancel"));
  setAction("deleteBtn", detail.actions.delete, openDeleteDialog);
  renderOverview(detail);
  renderArtifacts(detail);
  renderConfig(detail);
  renderRuntime(detail);
}

function setAction(id, action, handler) {
  const button = $(id);
  button.disabled = !action?.enabled || state.busy;
  button.title = action?.reason || "";
  button.onclick = handler;
}

function renderOverview(detail) {
  const task = detail.state;
  renderAnalysisReview(detail);
  renderExecutionApproval(detail);
  renderHumanReview(detail);
  $("goalText").textContent = task.goal?.raw_request || task.title || "";
  const phaseList = $("phaseList");
  phaseList.innerHTML = "";
  Object.entries(task.phases || {}).forEach(([name, phase]) => {
    const item = document.createElement("div");
    item.className = "phase-item";
    item.innerHTML = `<strong>${escapeHtml(name)}</strong><span class="badge">${escapeHtml(phase?.status || "pending")}</span>`;
    phaseList.appendChild(item);
  });
  const list = $("acceptanceList");
  list.innerHTML = "";
  const items = task.acceptance_criteria || [];
  const passed = items.filter((ac) => String(ac.status || "").toLowerCase() === "passed").length;
  const failed = items.filter((ac) => String(ac.status || "").toLowerCase() === "failed").length;
  const countEl = $("acceptanceCount");
  if (countEl) {
    countEl.innerHTML = items.length
      ? `<span class="count-chip">${passed}/${items.length} passed</span>${failed ? `<span class="count-chip count-chip-fail">${failed} failed</span>` : ""}`
      : "";
  }
  if (!items.length) {
    list.innerHTML = '<div class="task-sub">No acceptance criteria.</div>';
    return;
  }
  for (const ac of items) {
    const item = document.createElement("details");
    item.className = "ac-item";
    const status = String(ac.status || "pending").toLowerCase();
    const required = ac.required ? "required" : "optional";
    item.innerHTML = `
      <summary class="ac-summary">
        <span class="ac-id">${escapeHtml(ac.id)}</span>
        <span class="ac-req ${ac.required ? "is-required" : "is-optional"}">${required}</span>
        <span class="ac-criterion">${escapeHtml(ac.description)}</span>
        <span class="ac-status ac-status-${escapeHtml(status)}">${escapeHtml(ac.status || "pending")}</span>
        <span class="ac-caret" aria-hidden="true">›</span>
      </summary>
      <div class="ac-body">
        <div class="ac-field"><span class="ac-label">Verification</span><span class="ac-value">${escapeHtml(ac.verification || "-")}</span></div>
        <div class="ac-field"><span class="ac-label">Evidence</span><span class="ac-value">${escapeHtml(ac.evidence || "-")}</span></div>
      </div>`;
    list.appendChild(item);
  }
}

function renderAnalysisReview(detail) {
  const panel = $("analysisReviewPanel");
  const review = detail.analysis_review;
  if (!review?.required) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  const questions = Array.isArray(review.questions) ? review.questions : [];
  panel.classList.remove("hidden");
  panel.innerHTML = `
    <div class="analysis-review-head">
      <div>
        <h3>Analysis review</h3>
        <p>${escapeHtml(review.meaning || "Review the initial analysis before approval.")}</p>
      </div>
      <span class="badge status-WAITING_FOR_ANALYSIS_REVIEW">NEEDS ANSWERS</span>
    </div>
    <div class="question-list">
      ${questions.length ? questions.map(renderAnalysisQuestion).join("") : '<div class="task-sub">No open questions. Continue analysis to prepare the approval package.</div>'}
    </div>
    <div class="analysis-review-actions">
      <button id="submitAnalysisReviewBtn" class="primary" type="button">Continue analysis</button>
    </div>`;
  $("submitAnalysisReviewBtn").addEventListener("click", submitAnalysisReview);
}

function renderAnalysisQuestion(question) {
  const required = question.blocking ? "required" : "optional";
  return `<label class="question-item">
    <span class="question-top"><strong>${escapeHtml(question.id || "Q")}</strong><em>${escapeHtml(required)}</em></span>
    <span>${escapeHtml(question.question || "Open question")}</span>
    ${question.reason ? `<small>${escapeHtml(question.reason)}</small>` : ""}
    <textarea data-question-id="${escapeHtml(question.id || "")}" rows="3" placeholder="Answer or leave blank for AgentLoop assumptions">${escapeHtml(question.answer || "")}</textarea>
  </label>`;
}

async function submitAnalysisReview() {
  if (!state.selectedTaskId) return;
  const answers = {};
  for (const input of $("analysisReviewPanel").querySelectorAll("textarea[data-question-id]")) {
    answers[input.dataset.questionId] = input.value.trim();
  }
  const btn = $("submitAnalysisReviewBtn");
  btn.disabled = true;
  btn.textContent = "Continuing analysis...";
  try {
    state.detail = await apiFetch(`/api/tasks/${encodeURIComponent(state.selectedTaskId)}/analysis-review`, { method: "POST", body: JSON.stringify({ by: "ui", answers }) });
    await loadTasks(true);
    showBanner(null);
  } catch (error) {
    showBanner(error.message);
    btn.disabled = false;
    btn.textContent = "Continue analysis";
  }
}

function renderExecutionApproval(detail) {
  const panel = $("executionApprovalPanel");
  const approval = detail.execution_approval;
  if (!approval?.required) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  const artifacts = Array.isArray(approval.artifacts) ? approval.artifacts : [];
  const missing = Array.isArray(approval.missing_artifacts) ? approval.missing_artifacts : [];
  panel.classList.remove("hidden");
  panel.innerHTML = `
    <div class="execution-approval-head">
      <div>
        <h3>Execution approval</h3>
        <p>${escapeHtml(approval.meaning || "Review the completed plan before running changes.")}</p>
      </div>
      <span class="badge status-WAITING_FOR_ALIGNMENT">READY TO RUN</span>
    </div>
    <div class="approval-artifact-grid">
      ${artifacts.map((item) => `
        <div class="approval-artifact ${item.ready ? "is-ready" : "is-missing"}">
          <strong>${escapeHtml(item.name)}</strong>
          <span>${escapeHtml(item.file)}</span>
          <em>${item.ready ? "Ready" : "Missing"}</em>
        </div>`).join("")}
    </div>
    ${missing.length ? `<div class="dialog-error">Missing approval artifacts: ${escapeHtml(missing.join(", "))}</div>` : ""}
    <div class="execution-approval-actions">
      <button id="approveFromPanelBtn" class="primary" type="button" ${detail.actions.approve?.enabled ? "" : "disabled"}>Approve and run</button>
    </div>`;
  $("approveFromPanelBtn").addEventListener("click", () => mutate("approve"));
}

function renderHumanReview(detail) {
  const panel = $("humanReviewPanel");
  const review = detail.human_review;
  if (!review?.required) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  const latest = review.review || {};
  const comments = Array.isArray(latest.comments) ? latest.comments : [];
  const tests = Array.isArray(latest.test_results) ? latest.test_results : [];
  const failedTests = tests.filter((test) => typeof test.exit_code === "number" && test.exit_code !== 0);
  panel.classList.remove("hidden");
  panel.innerHTML = `
    <div class="human-review-head">
      <div>
        <h3>Human review required</h3>
        <p>${escapeHtml(review.meaning || "AgentLoop paused and needs human input before it can continue.")}</p>
      </div>
      <span class="badge status-WAITING_FOR_HUMAN">WAITING_FOR_HUMAN</span>
    </div>
    <div class="human-review-grid">
      <section>
        <h3>Block reason</h3>
        <p class="human-summary">${escapeHtml(latest.summary || "No review summary was recorded.")}</p>
        ${latest.artifact ? `<div class="task-sub">Review artifact: <code>${escapeHtml(latest.artifact)}</code></div>` : ""}
      </section>
      <section>
        <h3>Resume</h3>
        <textarea id="resumeNoteInput" rows="4" placeholder="What did you change or decide?"></textarea>
        <button id="resumeTaskBtn" class="primary" type="button">Resume automatic loop</button>
      </section>
    </div>
    <div class="human-review-grid">
      <section>
        <h3>Open comments</h3>
        ${comments.length ? `<div class="blocker-list">${comments.map(renderReviewComment).join("")}</div>` : '<div class="task-sub">No reviewer comments recorded.</div>'}
      </section>
      <section>
        <h3>Failed checks</h3>
        ${failedTests.length ? `<div class="blocker-list">${failedTests.map(renderFailedTest).join("")}</div>` : '<div class="task-sub">No failed test results recorded.</div>'}
      </section>
    </div>`;
  $("resumeTaskBtn").addEventListener("click", resumeHumanReview);
}

function renderReviewComment(comment) {
  const severity = comment?.severity || "info";
  const area = comment?.area || "review";
  const text = comment?.text || comment?.required_action || "No comment text.";
  const action = comment?.required_action ? `<small>${escapeHtml(comment.required_action)}</small>` : "";
  return `<article class="blocker-item"><strong>${escapeHtml(severity)} · ${escapeHtml(area)}</strong><p>${escapeHtml(text)}</p>${action}</article>`;
}

function renderFailedTest(test) {
  return `<article class="blocker-item"><strong>exit ${escapeHtml(test.exit_code)}</strong><p>${escapeHtml(test.command || "Command not recorded")}</p>${test.log ? `<small>${escapeHtml(test.log)}</small>` : ""}</article>`;
}

async function resumeHumanReview() {
  if (!state.selectedTaskId) return;
  const btn = $("resumeTaskBtn");
  const note = $("resumeNoteInput")?.value || "";
  btn.disabled = true;
  btn.textContent = "Resuming...";
  showBanner("Resuming task...");
  try {
    state.detail = await apiFetch(`/api/tasks/${encodeURIComponent(state.selectedTaskId)}/resume`, { method: "POST", body: JSON.stringify({ by: "ui", note }) });
    await loadTasks(true);
    showBanner(null);
  } catch (error) {
    showBanner(error.message);
    btn.disabled = false;
    btn.textContent = "Resume automatic loop";
  }
}

function renderArtifacts(detail) {
  const list = $("artifactList");
  list.innerHTML = "";
  const mdArtifacts = (detail.artifacts || []).filter((a) => /\.md$/i.test(a.name || ""));
  if (!mdArtifacts.length) {
    list.innerHTML = '<div class="task-sub">No markdown artifacts yet.</div>';
    return;
  }
  for (const artifact of mdArtifacts) {
    const node = document.createElement("section");
    node.className = "artifact-item";
    const truncated = artifact.preview?.truncated ? ` · truncated ${artifact.preview.bytes_returned}/${artifact.preview.bytes_total} bytes` : "";
    const head = document.createElement("div");
    head.className = "artifact-head";
    head.innerHTML = `<strong>${escapeHtml(artifact.name)}</strong><span class="task-sub">${artifact.size} bytes${truncated}</span>`;
    const body = document.createElement("div");
    body.className = "markdown-body";
    body.innerHTML = renderMarkdown(artifact.preview?.content || "");
    node.appendChild(head);
    node.appendChild(body);
    list.appendChild(node);
  }
}

function renderMarkdown(src) {
  const lines = String(src).replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0;
  const flushPara = (buf) => { if (buf.length) { out.push(`<p>${inlineMd(buf.join(" "))}</p>`); buf.length = 0; } };
  const paraBuf = [];
  while (i < lines.length) {
    const line = lines[i];
    // fenced code
    const fence = line.match(/^```(\w*)\s*$/);
    if (fence) {
      flushPara(paraBuf);
      const lang = fence[1] || "";
      const codeLines = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) { codeLines.push(lines[i]); i++; }
      i++;
      out.push(`<pre class="md-pre"><code${lang ? ` class="lang-${escapeHtml(lang)}"` : ""}>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
      continue;
    }
    // heading
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { flushPara(paraBuf); out.push(`<h${h[1].length} class="md-h">${inlineMd(h[2])}</h${h[1].length}>`); i++; continue; }
    // hr
    if (/^\s*([-*_])\s*\1\s*\1[-*_\s]*$/.test(line)) { flushPara(paraBuf); out.push('<hr class="md-hr" />'); i++; continue; }
    // blockquote
    if (/^>\s?/.test(line)) {
      flushPara(paraBuf);
      const qLines = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) { qLines.push(lines[i].replace(/^>\s?/, "")); i++; }
      out.push(`<blockquote class="md-quote">${inlineMd(qLines.join(" "))}</blockquote>`);
      continue;
    }
    // table (simple)
    if (i + 1 < lines.length && /\|/.test(line) && /^\s*\|?[\s:|-]+\|[\s:|-]+$/.test(lines[i + 1])) {
      flushPara(paraBuf);
      const splitRow = (r) => r.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());
      const headCells = splitRow(line);
      i += 2;
      const bodyRows = [];
      while (i < lines.length && /\|/.test(lines[i]) && lines[i].trim() !== "") { bodyRows.push(splitRow(lines[i])); i++; }
      const thead = `<thead><tr>${headCells.map((c) => `<th>${inlineMd(c)}</th>`).join("")}</tr></thead>`;
      const tbody = `<tbody>${bodyRows.map((r) => `<tr>${r.map((c) => `<td>${inlineMd(c)}</td>`).join("")}</tr>`).join("")}</tbody>`;
      out.push(`<div class="md-table-wrap"><table class="md-table">${thead}${tbody}</table></div>`);
      continue;
    }
    // list (ul/ol, single level for simplicity but supports nested via indent grouping)
    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      flushPara(paraBuf);
      const ordered = /^\s*\d+\.\s+/.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, ""));
        i++;
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag} class="md-list">${items.map((it) => `<li>${inlineMd(it)}</li>`).join("")}</${tag}>`);
      continue;
    }
    // blank line
    if (!line.trim()) { flushPara(paraBuf); i++; continue; }
    paraBuf.push(line);
    i++;
  }
  flushPara(paraBuf);
  return out.join("\n");
}

function inlineMd(text) {
  let s = escapeHtml(text);
  s = s.replace(/`([^`]+)`/g, '<code class="md-code">$1</code>');
  s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, url) => `<img alt="${alt}" src="${url}" class="md-img" />`);
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer noopener">$1</a>');
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
  s = s.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  return s;
}

function renderConfig(detail) {
  $("maxIterationsInput").value = detail.config.override.max_iterations || detail.config.effective.max_iterations || 7;
  const commands = detail.config.override.test_commands || detail.config.effective.test_commands || [];
  const list = $("commandsList");
  list.innerHTML = "";
  commands.forEach((command) => addCommandRow(command));
}

function runtimeOptionsHtml(selected) {
  const runtimes = (state.settings?.runtime?.runtimes || []).filter((runtime) => runtime.selectable);
  return runtimes.map((runtime) => {
    const name = runtime.name;
    return `<option value="${escapeHtml(name)}" ${name === selected ? "selected" : ""}>${escapeHtml(name)}</option>`;
  }).join("");
}

function renderCreateRuntimeSelectors() {
  const list = $("createRuntimeList");
  const roles = state.settings?.runtime?.role_defaults || [];
  if (!roles.length) {
    list.innerHTML = '<div class="task-sub">No runtime configuration found.</div>';
    return;
  }
  list.innerHTML = roles.map((role) => `
    <label class="role-runtime-row">
      <span>
        <strong>${escapeHtml(role.role)}</strong>
        <small>${role.uses_global_default ? "global default" : "role default"}</small>
      </span>
      <select data-role="${escapeHtml(role.role)}">${runtimeOptionsHtml(role.runtime)}</select>
    </label>`).join("");
}

async function openCreateDialog() {
  try {
    await loadSettings();
    renderCreateRuntimeSelectors();
    $("createError").classList.add("hidden");
    $("createError").textContent = "";
    $("createSubmitBtn").disabled = false;
    $("createSubmitBtn").textContent = "Create";
    showBanner(null);
    $("createDialog").showModal();
  } catch (error) {
    showBanner(error.message);
  }
}

function selectedRoleRuntimes() {
  const out = {};
  for (const select of $("createRuntimeList").querySelectorAll("select[data-role]")) {
    out[select.dataset.role] = select.value;
  }
  return out;
}

function renderSettingsUsage(settings) {
  const usage = settings.usage || {};
  const byStatus = usage.by_status || {};
  const statusRows = Object.entries(byStatus).sort((a, b) => a[0].localeCompare(b[0]));
  $("usageStats").innerHTML = `
    <div class="setting-stat"><span>Total tasks</span><strong>${escapeHtml(usage.task_count ?? 0)}</strong></div>
    <div class="setting-stat"><span>Current task</span><strong>${escapeHtml(usage.current_task_id || "-")}</strong></div>
    <div class="setting-stat wide"><span>Status breakdown</span><div class="status-stack">
      ${statusRows.length ? statusRows.map(([status, count]) => `<span><code>${escapeHtml(status)}</code>${escapeHtml(count)}</span>`).join("") : '<span>No tasks</span>'}
    </div></div>`;
}

function renderSettingsRuntime(settings) {
  const runtime = settings.runtime || {};
  const runtimes = runtime.runtimes || [];
  $("runtimeCatalog").innerHTML = runtimes.length ? runtimes.map((item) => {
    const status = runtimeEffectiveStatus(item);
    const args = Array.isArray(item.args) ? item.args.join(" ") : "";
    const command = item.command ? `${item.command}${args ? ` ${args}` : ""}` : (item.description || "manual runtime");
    return `<section class="runtime-card runtime-${escapeHtml(status)}">
      <div>
        <strong>${escapeHtml(item.name)}</strong>
        <span class="runtime-badges">
          <span class="runtime-status runtime-status-${escapeHtml(status)}">${escapeHtml(runtimeStatusLabel(status))}</span>
          <span class="badge">${escapeHtml(item.adapter)}</span>
        </span>
      </div>
      <code>${escapeHtml(command)}</code>
      <small>${escapeHtml(item.status_label || runtimeStatusDescription(status))}</small>
      ${item.stdin_file ? `<small>stdin: ${escapeHtml(item.stdin_file)}</small>` : ""}
    </section>`;
  }).join("") : '<div class="task-sub">No runtimes configured.</div>';

  const roles = runtime.role_defaults || [];
  $("roleDefaults").innerHTML = roles.map((role) => `
    <div class="role-runtime-row">
      <span><strong>${escapeHtml(role.role)}</strong><small>${role.uses_global_default ? "global default" : "role default"}</small></span>
      <code>${escapeHtml(role.runtime)}</code>
    </div>`).join("");
}

function runtimeEffectiveStatus(item) {
  if (item?.status) return item.status;
  if (item?.selectable || item?.configured || item?.command || item?.adapter === "manual") return "active";
  return "not_injected";
}

function runtimeStatusLabel(status) {
  if (status === "active") return "active";
  if (status === "manual_fallback") return "manual fallback";
  if (status === "configured_missing") return "missing";
  if (status === "detected_not_injected") return "detected";
  if (status === "not_injected") return "not injected";
  return "unknown";
}

function runtimeStatusDescription(status) {
  if (status === "active") return "configured runtime";
  if (status === "manual_fallback") return "manual fallback; writes prompts and does not call a coding agent";
  if (status === "configured_missing") return "configured but command was not found";
  if (status === "detected_not_injected") return "detected on this machine but not injected into config";
  if (status === "not_injected") return "preset is available but not injected";
  return "status unavailable";
}

async function openSettingsDialog() {
  try {
    const settings = await loadSettings();
    renderSettingsUsage(settings);
    renderSettingsRuntime(settings);
    showBanner(null);
    $("settingsDialog").showModal();
  } catch (error) {
    showBanner(error.message);
  }
}

function addCommandRow(value = "") {
  const row = document.createElement("div");
  row.className = "command-row";
  row.innerHTML = `<input value="${escapeHtml(value)}" /><button type="button">Remove</button>`;
  row.querySelector("button").addEventListener("click", () => row.remove());
  $("commandsList").appendChild(row);
}

function renderRuntime(detail) {
  const rt = detail.runtime || {};
  let byIter = rt.by_iteration || [];
  const latest = rt.latest_iteration ?? null;
  if (!byIter.length && ((rt.agents || []).length || (rt.tests || []).length)) {
    const iter = latest ?? 0;
    const agents = rt.agents || [];
    const tests = rt.tests || [];
    const passed = tests.filter((t) => t.exit_code === 0).length;
    const failed = tests.filter((t) => typeof t.exit_code === "number" && t.exit_code !== 0).length;
    byIter = [{ iteration: iter, agents, tests, agent_count: agents.length, test_count: tests.length, tests_passed: passed, tests_failed: failed }];
  }
  const bar = $("iterationBar");
  const tabs = $("runtimeTabs");
  const content = $("runtimeContent");
  bar.innerHTML = "";
  tabs.innerHTML = "";
  content.innerHTML = "";

  if (!byIter.length) {
    content.innerHTML = '<div class="task-sub">No runtime output yet.</div>';
    return;
  }
  if (state.iterationIndex == null || !byIter.some((it) => it.iteration === state.iterationIndex)) {
    state.iterationIndex = latest != null ? latest : byIter[byIter.length - 1].iteration;
  }

  byIter.forEach((it) => {
    const chip = document.createElement("button");
    chip.className = `iter-chip ${it.iteration === state.iterationIndex ? "active" : ""}${it.iteration === latest ? " is-latest" : ""}`;
    const failBadge = it.tests_failed ? `<span class="iter-chip-fail">${it.tests_failed}</span>` : "";
    const passBadge = it.tests_passed ? `<span class="iter-chip-pass">${it.tests_passed}</span>` : "";
    chip.innerHTML = `
      <span class="iter-chip-num">#${it.iteration}</span>
      <span class="iter-chip-meta">${it.agent_count} agent${it.agent_count === 1 ? "" : "s"} · ${it.test_count} test${it.test_count === 1 ? "" : "s"}</span>
      ${passBadge}${failBadge}`;
    chip.addEventListener("click", () => {
      state.iterationIndex = it.iteration;
      state.runtimeIndex = 0;
      renderRuntime(detail);
    });
    bar.appendChild(chip);
  });

  const current = byIter.find((it) => it.iteration === state.iterationIndex) || byIter[byIter.length - 1];
  const entries = [
    ...(current.agents || []).map((agent) => ({ type: "agent", label: agent.role || "agent", data: agent })),
    ...(current.tests || []).map((test) => ({ type: "test", label: test.name, data: test })),
  ];
  if (!entries.length) {
    content.innerHTML = `<div class="task-sub">Iteration #${current.iteration} has no agent or test output.</div>`;
    return;
  }
  if (state.runtimeIndex >= entries.length) state.runtimeIndex = 0;

  entries.forEach((entry, index) => {
    const button = document.createElement("button");
    const isTest = entry.type === "test";
    const exit = isTest ? entry.data.exit_code : entry.data.exit_code;
    const dot = exit === 0 ? "ok" : (typeof exit === "number" ? "fail" : "muted");
    button.innerHTML = `<span class="dot dot-${dot}"></span><span class="rt-label">${escapeHtml(entry.label)}</span><span class="rt-kind">${entry.type}</span>`;
    button.className = index === state.runtimeIndex ? "active" : "";
    button.addEventListener("click", () => { state.runtimeIndex = index; renderRuntime(detail); });
    tabs.appendChild(button);
  });

  const selected = entries[state.runtimeIndex] || entries[0];
  if (selected.type === "test") {
    const log = selected.data.log || {};
    const exitCode = selected.data.exit_code ?? "unknown";
    const duration = selected.data.duration_ms == null ? "unknown" : `${selected.data.duration_ms} ms`;
    const command = selected.data.command || "Command unknown";
    const logText = log.content || (log.missing ? "Missing test log" : "");
    content.innerHTML = `<div class="runtime-meta"><span>test</span><span>${escapeHtml(log.path || selected.label)}</span><span>exit ${escapeHtml(exitCode)}</span><span>${escapeHtml(duration)}</span>${log.truncated ? `<span>truncated ${log.bytes_returned}/${log.bytes_total} bytes</span>` : ""}</div><h3>command</h3><pre class="command-block">${escapeHtml(command)}</pre><h3>log</h3><pre class="log-block">${escapeHtml(logText)}</pre>`;
    return;
  }
  const agent = selected.data;
  const stdout = agent.stdout || {};
  const stderr = agent.stderr || {};
  content.innerHTML = `<div class="runtime-meta"><span>${escapeHtml(agent.runtime || "runtime")}</span><span>exit ${escapeHtml(agent.exit_code ?? "-")}</span><span>${escapeHtml(agent.duration_ms ?? "-")} ms</span><span>${escapeHtml(agent.command || "manual")}</span></div><h3>stdout</h3><pre class="log-block">${escapeHtml(stdout.content || (stdout.missing ? "Missing stdout log" : ""))}</pre><h3>stderr</h3><pre class="log-block">${escapeHtml(stderr.content || (stderr.missing ? "Missing stderr log" : ""))}</pre>`;
}

async function mutate(op) {
  if (!state.selectedTaskId) return;
  state.busy = true;
  renderDetail();
  showBanner(`Running ${op}...`);
  try {
    state.detail = await apiFetch(`/api/tasks/${encodeURIComponent(state.selectedTaskId)}/${op}`, { method: "POST", body: JSON.stringify({ by: "ui" }) });
    await loadTasks(true);
    showBanner(null);
  } catch (error) {
    showBanner(error.message);
  } finally {
    state.busy = false;
    if (state.detail) renderDetail();
  }
}

function openDeleteDialog() {
  if (!state.selectedTaskId) return;
  $("deleteTaskId").textContent = state.selectedTaskId;
  $("deleteError").classList.add("hidden");
  $("deleteError").textContent = "";
  $("deleteSubmitBtn").disabled = false;
  $("deleteSubmitBtn").textContent = "Delete";
  $("deleteDialog").showModal();
}

function wireEvents() {
  $("refreshBtn").addEventListener("click", () => loadTasks(true).catch((error) => showBanner(error.message)));
  $("settingsBtn").addEventListener("click", openSettingsDialog);
  $("searchInput").addEventListener("input", renderTaskList);
  $("newTaskBtn").addEventListener("click", openCreateDialog);
  $("addCommandBtn").addEventListener("click", () => addCommandRow(""));
  $("statusFilter").addEventListener("click", (event) => {
    if (event.target.tagName !== "BUTTON") return;
    state.filter = event.target.dataset.filter;
    [...$("statusFilter").querySelectorAll("button")].forEach((button) => button.classList.toggle("active", button === event.target));
    renderTaskList();
  });
  $("detailTabs").addEventListener("click", (event) => {
    if (event.target.tagName !== "BUTTON") return;
    const tab = event.target.dataset.tab;
    [...$("detailTabs").querySelectorAll("button")].forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
    [...document.querySelectorAll(".tab-panel")].forEach((panel) => panel.classList.toggle("active", panel.id === `${tab}Tab`));
  });
  $("createForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const request = $("requestInput").value.trim();
    const errorBox = $("createError");
    const submitBtn = $("createSubmitBtn");
    errorBox.classList.add("hidden");
    errorBox.textContent = "";
    if (!request) {
      errorBox.textContent = "Task description is required.";
      errorBox.classList.remove("hidden");
      $("requestInput").focus();
      return;
    }
    submitBtn.disabled = true;
    submitBtn.textContent = "Creating...";
    try {
      const detail = await apiFetch("/api/tasks", { method: "POST", body: JSON.stringify({ request, role_runtimes: selectedRoleRuntimes() }) });
      $("createDialog").close();
      $("requestInput").value = "";
      state.selectedTaskId = detail.state.task_id;
      state.detail = detail;
      renderDetail();
      await loadTasks(true);
      await loadDetail(detail.state.task_id);
      showBanner(null);
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
      showBanner(error.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Create";
    }
  });
  $("settingsTabs").addEventListener("click", (event) => {
    if (event.target.tagName !== "BUTTON") return;
    const tab = event.target.dataset.settingsTab;
    [...$("settingsTabs").querySelectorAll("button")].forEach((button) => button.classList.toggle("active", button.dataset.settingsTab === tab));
    $("settingsUsageTab").classList.toggle("active", tab === "usage");
    $("settingsRuntimeTab").classList.toggle("active", tab === "runtime");
  });
  $("deleteForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.selectedTaskId) return;
    const errorBox = $("deleteError");
    const submitBtn = $("deleteSubmitBtn");
    errorBox.classList.add("hidden");
    errorBox.textContent = "";
    submitBtn.disabled = true;
    submitBtn.textContent = "Deleting...";
    try {
      await apiFetch(`/api/tasks/${encodeURIComponent(state.selectedTaskId)}`, { method: "DELETE", body: JSON.stringify({ confirm: state.selectedTaskId }) });
      $("deleteDialog").close();
      state.selectedTaskId = null;
      await loadTasks(false);
      showBanner(null);
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
      showBanner(error.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Delete";
    }
  });
  $("configForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const commands = [...$("commandsList").querySelectorAll("input")].map((input) => input.value.trim()).filter(Boolean);
    try {
      state.detail = await apiFetch(`/api/tasks/${encodeURIComponent(state.selectedTaskId)}/config`, { method: "PATCH", body: JSON.stringify({ max_iterations: Number($("maxIterationsInput").value), test_commands: commands }) });
      renderDetail();
      showBanner(null);
    } catch (error) { showBanner(error.message); }
  });
}

wireEvents();
startAutoRefresh();
loadTasks(false).catch((error) => showBanner(error.message));
