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
  selectedTranscript: null,
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
  if (state.filter === "running") return ["INVESTIGATING", "DESIGNING", "IMPLEMENTING_AND_TESTING", "REVIEWING"].includes(status);
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
  $("lifecycle").innerHTML = "";
  $("primaryActionBtn").hidden = true;
  $("cancelBtn").hidden = true;
  $("deleteBtn").hidden = true;
  const cta = $("overviewCta");
  if (cta) { cta.classList.add("hidden"); cta.innerHTML = ""; }
}

const LIFECYCLE_STEPS = [
  { key: "framing", label: "Framing", sub: "clarify the problem", tab: "overview", match: ["CREATED", "FRAMING_REVIEW"], roles: [{ key: "framer", label: "Framer", icon: "?" }] },
  { key: "research", label: "Researching", sub: "investigate & design", tab: "overview", match: ["INVESTIGATING", "DESIGNING"], roles: [{ key: "investigator", label: "Investigator", icon: "I" }, { key: "architect", label: "Architect", icon: "A" }] },
  { key: "approve", label: "Awaiting approval", sub: "review the plan", tab: "overview", match: ["WAITING_FOR_ALIGNMENT"], roles: [{ key: "human", label: "You", icon: "@" }] },
  { key: "run", label: "Running", sub: "iterations executing", tab: "runtime", match: ["READY_TO_START", "RUNNING", "EXECUTING", "IMPLEMENTING_AND_TESTING", "REVIEWING", "WAITING_FOR_HUMAN"], roles: [{ key: "implementer", label: "Implementer", icon: "⚙" }, { key: "tester", label: "Tester", icon: "✓" }, { key: "reviewer", label: "Reviewer", icon: "👁" }] },
  { key: "done", label: "Done", sub: "task complete", tab: "artifacts", match: ["DONE", "CANCELLED", "FAILED"], roles: [{ key: "integrator", label: "Integrator", icon: "★" }] },
];

function lifecycleIndex(status) {
  const idx = LIFECYCLE_STEPS.findIndex((step) => step.match.includes(String(status || "").toUpperCase()));
  return idx === -1 ? 0 : idx;
}

function currentPhase(status) {
  const s = String(status || "").toUpperCase();
  if (["FRAMING", "FRAMING_REVIEW", "CREATED"].includes(s)) return "framing";
  if (["INVESTIGATING", "DESIGNING"].includes(s)) return "research";
  if (s === "WAITING_FOR_ALIGNMENT") return "approval";
  if (["IMPLEMENTING_AND_TESTING", "REVIEWING", "WAITING_FOR_HUMAN", "READY_TO_START"].includes(s)) return "running";
  if (["DONE", "INTEGRATING"].includes(s)) return "done";
  if (s === "CANCELLED") return "done";
  return "framing";
}

const PHASE_LABELS = { framing: "Framing", research: "Researching", approval: "Awaiting approval", running: "Running", done: "Done" };
const PHASE_ARTIFACTS = {
  framing: [],
  research: ["dossier.md", "proposal.md", "acceptance.md", "test-plan.md"],
  approval: ["dossier.md", "proposal.md", "acceptance.md", "test-plan.md"],
  running: ["final-report.md"],
  done: [],
};

function renderLifecycle(task) {
  const root = $("lifecycle");
  root.innerHTML = "";
  const cancelled = String(task.status || "").toUpperCase() === "CANCELLED";
  // For cancelled tasks, derive position from the pre-cancel status so prior phases still look completed
  // and the cancelled phase is marked red. Steps after stay gray.
  const current = cancelled
    ? lifecycleIndex(task.cancelled_from || "FRAMING_REVIEW")
    : lifecycleIndex(task.status);
  LIFECYCLE_STEPS.forEach((step, idx) => {
    const li = document.createElement("li");
    const state = idx < current ? "done" : idx === current ? "current" : "pending";
    li.className = `lc-step lc-${state}${cancelled && idx === current ? " lc-cancelled" : ""}`;
    const rolesHtml = (step.roles || []).map((r) => `
      <span class="lc-role lc-role-${escapeHtml(r.key)}" title="${escapeHtml(r.label)}">
        <span class="lc-role-icon">${escapeHtml(r.icon)}</span>
        <span class="lc-role-label">${escapeHtml(r.label)}</span>
      </span>`).join("");
    li.innerHTML = `
      <button type="button" class="lc-btn" data-tab="${step.tab}" data-state="${state}" ${state === "pending" ? "disabled" : ""} title="${escapeHtml(state === "pending" ? "Not started yet" : step.sub)}">
        <span class="lc-dot">${idx < current ? "✓" : idx + 1}</span>
        <span class="lc-text">
          <span class="lc-label">${escapeHtml(step.label)}</span>
          <span class="lc-sub">${escapeHtml(step.sub)}</span>
          ${rolesHtml ? `<span class="lc-roles">${rolesHtml}</span>` : ""}
        </span>
      </button>`;
    root.appendChild(li);
  });
  root.onclick = (event) => {
    const btn = event.target.closest(".lc-btn");
    if (!btn || btn.disabled || btn.dataset.state === "pending") return;
    const tab = btn.dataset.tab;
    [...$("detailTabs").querySelectorAll("button")].forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    [...document.querySelectorAll(".tab-panel")].forEach((panel) => panel.classList.toggle("active", panel.id === `${tab}Tab`));
  };
}

function configurePrimaryAction(detail) {
  const task = detail.state;
  const actions = detail.actions || {};
  const status = String(task.status || "").toUpperCase();
  const primary = $("primaryActionBtn");
  const cancel = $("cancelBtn");
  const deleteBtn = $("deleteBtn");

  let primaryConfig = null;
  if (status === "WAITING_FOR_ALIGNMENT" && actions.approve?.enabled) {
    primaryConfig = { label: "Approve plan & run", handler: () => approveAndRun(), title: "" };
  } else if (status === "READY_TO_START" && actions.run?.enabled) {
    primaryConfig = { label: "Run", handler: () => mutate("run"), title: "" };
  } else if (["RUNNING", "EXECUTING", "IMPLEMENTING_AND_TESTING", "REVIEWING"].includes(status)) {
    primaryConfig = { label: `Running · iter ${task.iteration ?? "-"}/${task.max_iterations ?? "-"}`, handler: null, title: "Task in progress", disabled: true };
  } else if (status === "FRAMING_REVIEW") {
    if (actions.start_research?.enabled) {
      primaryConfig = { label: "Start research →", handler: () => startResearch(), title: "" };
    } else if (actions.submit_framing?.enabled) {
      primaryConfig = { label: "Submit answers", handler: () => submitFramingAnswers(), title: "Answer the open questions to continue" };
    }
  } else if (["INVESTIGATING", "DESIGNING"].includes(status)) {
    primaryConfig = { label: "Researching…", handler: null, title: "Investigator and Architect are running", disabled: true };
  } else if (status === "CREATED" || status === "FRAMING") {
    primaryConfig = { label: "Framing…", handler: null, title: "Framer is drafting the problem statement", disabled: true };
  } else if (status === "WAITING_FOR_HUMAN") {
    primaryConfig = { label: "Resume", handler: () => {
      const panel = $("humanReviewPanel");
      if (panel && !panel.classList.contains("hidden")) {
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }, title: "Review the blocker, then resume" };
  } else if (status === "DONE") {
    primaryConfig = { label: "View report", handler: () => {
      [...$("detailTabs").querySelectorAll("button")].forEach((b) => b.classList.toggle("active", b.dataset.tab === "artifacts"));
      [...document.querySelectorAll(".tab-panel")].forEach((p) => p.classList.toggle("active", p.id === "artifactsTab"));
    }, title: "Open the final report" };
  }

  if (primaryConfig) {
    primary.hidden = false;
    primary.textContent = primaryConfig.label;
    primary.disabled = !!primaryConfig.disabled || state.busy;
    primary.title = primaryConfig.title || "";
    primary.onclick = primaryConfig.handler;
  } else {
    primary.hidden = true;
    primary.onclick = null;
  }

  cancel.hidden = !actions.cancel?.enabled && status !== "RUNNING";
  cancel.disabled = !actions.cancel?.enabled || state.busy;
  cancel.title = actions.cancel?.reason || "";
  cancel.onclick = () => mutate("cancel");

  setAction("deleteBtn", actions.delete, () => openDeleteDialog());
  deleteBtn.hidden = !actions.delete?.enabled;
}

function closeMoreMenu() { /* no-op kept for callsite safety */ }

function renderOverviewCta(detail) {
  const cta = $("overviewCta");
  if (!cta) return;
  const status = String(detail.state.status || "").toUpperCase();
  const approveEnabled = detail.actions?.approve?.enabled;
  if (status === "WAITING_FOR_ALIGNMENT" && approveEnabled) {
    cta.classList.remove("hidden");
    cta.innerHTML = `
      <div class="overview-cta-text">
        <strong>Plan ready for review.</strong>
        <span>Read the goal, phases, and acceptance above, then approve to start running.</span>
      </div>
      <button type="button" class="primary" id="overviewApproveBtn">Approve &amp; run →</button>`;
    $("overviewApproveBtn").onclick = () => approveAndRun();
    $("overviewApproveBtn").disabled = state.busy;
  } else if (status === "READY_TO_START" && detail.actions?.run?.enabled) {
    cta.classList.remove("hidden");
    cta.innerHTML = `
      <div class="overview-cta-text">
        <strong>Approved.</strong>
        <span>Start the first iteration when ready.</span>
      </div>
      <button type="button" class="primary" id="overviewRunBtn">Run →</button>`;
    $("overviewRunBtn").onclick = () => mutate("run");
    $("overviewRunBtn").disabled = state.busy;
  } else {
    cta.classList.add("hidden");
    cta.innerHTML = "";
  }
}

function renderDetail() {
  const detail = state.detail;
  const task = detail.state;
  const isCancelled = String(task.status || "").toUpperCase() === "CANCELLED";
  const phase = isCancelled
    ? currentPhase(task.cancelled_from || task.status)
    : currentPhase(task.status);
  $("taskIdLabel").textContent = task.task_id;
  $("taskTitle").textContent = task.title || task.task_id;
  $("taskMeta").innerHTML = `<span class="${statusClass(task.status)}">${escapeHtml(task.status)}</span> ${escapeHtml(task.current_phase || "-")} · ${task.iteration ?? "-"}/${task.max_iterations ?? "-"} · updated ${escapeHtml(task.updated_at || "-")}`;
  const basicSub = $("basicTabSub");
  if (basicSub) basicSub.textContent = PHASE_LABELS[phase] || "current phase";
  const basicPanel = $("basicTab");
  if (basicPanel) basicPanel.dataset.phase = phase;
  renderLifecycle(task);
  configurePrimaryAction(detail);
  renderBasic(detail, phase);
  renderOverviewCta(detail);
  renderArtifacts(detail);
  renderConfig(detail);
  renderRuntime(detail);
  renderContext(detail);
}

function renderBasic(detail, phase) {
  const task = detail.state;
  const isCancelled = String(task.status || "").toUpperCase() === "CANCELLED";
  // gate sub-panels: each render*() already toggles its own hidden class based on detail
  // but we additionally force-hide ones that don't belong to current phase
  const gate = (id, allowed) => {
    const el = $(id);
    if (!el) return;
    if (!allowed) el.classList.add("hidden");
  };
  // Run sub-renderers first
  renderFramingReview(detail);
  renderResearchProgress(detail);
  renderExecutionApproval(detail);
  renderHumanReview(detail);
  renderGoal(task);
  // Then phase-gate (interactive panels hide entirely for cancelled tasks)
  gate("framingReviewPanel", !isCancelled && phase === "framing");
  gate("researchProgressPanel", !isCancelled && phase === "research");
  gate("executionApprovalPanel", !isCancelled && phase === "approval");
  gate("humanReviewPanel", !isCancelled && phase === "running");
  // Goal & acceptance visibility
  const goalSec = $("goalSection");
  const accSec = $("acceptanceSection");
  if (goalSec) goalSec.classList.toggle("hidden", phase === "done");
  if (accSec) accSec.classList.toggle("hidden", phase === "framing" || phase === "done");
  // Acceptance content
  renderAcceptance(task);
  // Phase-specific artifact preview (for cancelled tasks in framing phase, surface framing.md
  // since the interactive panel is hidden; other phases already list artifacts via PHASE_ARTIFACTS)
  const wantedOverride = isCancelled && phase === "framing" ? ["framing.md"] : null;
  renderPhaseArtifacts(detail, phase, wantedOverride);
  // Done placeholder
  const empty = $("basicEmpty");
  if (empty) empty.classList.toggle("hidden", phase !== "done");
}

function renderAcceptance(task) {
  const list = $("acceptanceList");
  if (!list) return;
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

function renderPhaseArtifacts(detail, phase, wantedOverride) {
  const section = $("phaseArtifactSection");
  const body = $("phaseArtifactBody");
  const heading = $("phaseArtifactHeading");
  if (!section || !body) return;
  const wanted = wantedOverride || PHASE_ARTIFACTS[phase] || [];
  const editable = phase === "approval" && !wantedOverride;
  const all = detail.artifacts || [];
  const byName = new Map(all.map((a) => [String(a.name || "").toLowerCase(), a]));
  // For approval, prefer .edited.* if present
  const pick = (base) => {
    if (editable) {
      const edited = byName.get(base.replace(/\.([a-z]+)$/i, ".edited.$1").toLowerCase());
      if (edited) return { artifact: edited, isEdited: true };
    }
    const orig = byName.get(base.toLowerCase());
    return orig ? { artifact: orig, isEdited: false } : null;
  };
  const items = wanted.map(pick).filter(Boolean);
  if (!items.length) {
    section.classList.add("hidden");
    body.innerHTML = "";
    return;
  }
  section.classList.remove("hidden");
  if (heading) {
    heading.textContent = phase === "approval" ? "Design package — editable" : phase === "research" ? "Research outputs" : phase === "framing" ? "Framing" : "Outputs";
  }
  body.innerHTML = "";
  for (const { artifact, isEdited } of items) {
    const node = document.createElement("section");
    node.className = "phase-artifact-card" + (editable ? " is-editable" : "");
    const content = artifact.preview?.content || "";
    const truncated = artifact.preview?.truncated;
    const headHtml = `<div class="phase-artifact-head"><strong>${escapeHtml(artifact.name)}</strong>${isEdited ? '<span class="badge badge-edited">edited</span>' : ""}<span class="task-sub">${artifact.size} bytes${truncated ? ` · truncated` : ""}</span></div>`;
    if (editable && !truncated) {
      node.innerHTML = `${headHtml}
        <textarea class="phase-artifact-editor" data-original-name="${escapeHtml(artifact.name.replace(/\.edited\.([a-z]+)$/i, ".$1"))}" rows="14">${escapeHtml(content)}</textarea>
        <div class="phase-artifact-actions">
          <button type="button" class="phase-artifact-save primary" data-base="${escapeHtml(artifact.name.replace(/\.edited\.([a-z]+)$/i, ".$1"))}">Save edits</button>
          ${isEdited ? `<button type="button" class="phase-artifact-revert" data-base="${escapeHtml(artifact.name.replace(/\.edited\.([a-z]+)$/i, ".$1"))}">Revert to original</button>` : ""}
          <span class="phase-artifact-save-status task-sub"></span>
        </div>`;
    } else {
      node.innerHTML = `${headHtml}<div class="markdown-body">${renderMarkdown(content)}</div>${truncated ? '<div class="task-sub">Preview truncated — open full file from Execution log.</div>' : ""}`;
    }
    body.appendChild(node);
  }
  // Wire edit handlers
  body.querySelectorAll(".phase-artifact-save").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const base = btn.dataset.base;
      const textarea = btn.closest(".phase-artifact-card").querySelector(".phase-artifact-editor");
      const statusEl = btn.parentElement.querySelector(".phase-artifact-save-status");
      if (statusEl) statusEl.textContent = "Saving…";
      try {
        await apiFetch(`/api/tasks/${encodeURIComponent(detail.state.task_id)}/edit-artifact`, {
          method: "POST",
          body: JSON.stringify({ name: base, content: textarea.value }),
        });
        if (statusEl) statusEl.textContent = "Saved.";
        loadDetail(detail.state.task_id).catch(() => {});
      } catch (err) {
        if (statusEl) statusEl.textContent = `Error: ${err.message}`;
      }
    });
  });
  body.querySelectorAll(".phase-artifact-revert").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const base = btn.dataset.base;
      if (!confirm(`Discard your edits to ${base}?`)) return;
      try {
        await apiFetch(`/api/tasks/${encodeURIComponent(detail.state.task_id)}/edit-artifact`, {
          method: "POST",
          body: JSON.stringify({ name: base, content: null }),
        });
        loadDetail(detail.state.task_id).catch(() => {});
      } catch (err) {
        showBanner(err.message);
      }
    });
  });
}


function setAction(id, action, handler) {
  const button = $(id);
  button.disabled = !action?.enabled || state.busy;
  button.title = action?.reason || "";
  button.onclick = handler;
}

function renderGoal(task) {
  const el = $("goalText");
  if (!el) return;
  const framing = task.framing && typeof task.framing === "object" ? task.framing : {};
  const statement = String(framing.problem_statement || "").trim();
  const nonGoals = Array.isArray(framing.non_goals) ? framing.non_goals.filter((x) => String(x || "").trim()) : [];
  const assumptions = Array.isArray(framing.assumptions) ? framing.assumptions.filter((x) => String(x || "").trim()) : [];
  const raw = String(task.goal?.raw_request || task.title || "").trim();
  if (!statement) {
    el.classList.add("copy-block");
    el.classList.remove("goal-structured");
    el.innerHTML = "";
    el.textContent = raw || "Framer hasn't drafted a problem statement yet.";
    return;
  }
  el.classList.remove("copy-block");
  el.classList.add("goal-structured");
  const parts = [
    `<div class="goal-section"><div class="goal-label">Problem statement</div><p>${escapeHtml(statement)}</p></div>`,
  ];
  if (nonGoals.length) {
    parts.push(`<div class="goal-section"><div class="goal-label">Non-goals</div><ul>${nonGoals.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul></div>`);
  }
  if (assumptions.length) {
    parts.push(`<div class="goal-section"><div class="goal-label">Assumptions</div><ul>${assumptions.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul></div>`);
  }
  if (raw && raw !== statement) {
    parts.push(`<details class="goal-raw"><summary>Original request</summary><pre>${escapeHtml(raw)}</pre></details>`);
  }
  el.innerHTML = parts.join("");
}

function renderFramingReview(detail) {
  const panel = $("framingReviewPanel");
  const review = detail.framing_review;
  if (!review?.required) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    panel.dataset.signature = "";
    return;
  }
  if (review.running) {
    panel.classList.remove("hidden");
    const runningSig = `running:${review.error || ""}`;
    if (panel.dataset.signature === runningSig) return;
    panel.dataset.signature = runningSig;
    const errBlock = review.error
      ? `<div class="dialog-error">Framer failed: ${escapeHtml(String(review.error))}</div>`
      : "";
    panel.innerHTML = `
      <div class="framing-review-head">
        <div>
          <h3>Framing</h3>
          <p>Framer is drafting open questions. This page will update automatically when it's ready.</p>
        </div>
        <span class="badge status-FRAMING_REVIEW">FRAMING…</span>
      </div>
      <div class="framing-loading"><span class="spinner" aria-hidden="true"></span> Working…</div>
      ${errBlock}`;
    return;
  }
  const questions = Array.isArray(review.questions) ? review.questions : [];
  const blocking = review.blocking_count || 0;
  const ready = !!review.ready_for_research;
  const badge = ready ? "READY FOR RESEARCH" : (blocking ? `${blocking} BLOCKING` : "NEEDS REVIEW");
  const badgeClass = ready ? "status-READY_TO_START" : "status-FRAMING_REVIEW";
  const signature = `review:${ready ? 1 : 0}:${blocking}:${questions.map((q) => `${q.id}|${q.question}|${q.blocking ? 1 : 0}|${q.answer || ""}`).join("§")}`;
  panel.classList.remove("hidden");
  if (panel.dataset.signature === signature) {
    // Same content — keep existing DOM so the user's in-progress typing is preserved.
    return;
  }
  panel.dataset.signature = signature;
  panel.innerHTML = `
    <div class="framing-review-head">
      <div>
        <h3>Framing</h3>
        <p>${escapeHtml(review.meaning || "Review the problem framing. Answer blocking questions, then start research.")}</p>
      </div>
      <span class="badge ${badgeClass}">${escapeHtml(badge)}</span>
    </div>
    <div class="question-list">
      ${questions.length ? questions.map(renderFramingQuestion).join("") : '<div class="task-sub">No open questions. Click "Start research" to continue.</div>'}
    </div>
    <div class="framing-review-actions">
      <button id="submitFramingBtn" class="secondary" type="button">Submit answers</button>
      <button id="startResearchBtn" class="primary" type="button" ${ready ? "" : "disabled"} title="${ready ? "" : "Answer the required questions first"}">Start research →</button>
    </div>`;
  $("submitFramingBtn").addEventListener("click", submitFramingAnswers);
  $("startResearchBtn").addEventListener("click", startResearch);
  panel.querySelectorAll("textarea[data-question-id]").forEach((ta) => {
    ta.addEventListener("input", () => refreshFramingReadiness(questions));
  });
}

const PLACEHOLDER_ANSWERS = new Set(["", "unanswered", "n/a", "na", "tbd", "none"]);

function refreshFramingReadiness(questions) {
  const panel = $("framingReviewPanel");
  if (!panel) return;
  const answers = new Map();
  for (const ta of panel.querySelectorAll("textarea[data-question-id]")) {
    answers.set(ta.dataset.questionId, ta.value.trim().toLowerCase());
    if (ta.value.trim()) ta.classList.remove("invalid");
  }
  let blocking = 0;
  for (const q of questions) {
    if (!q || !q.blocking) continue;
    const v = answers.get(String(q.id || "")) ?? "";
    if (PLACEHOLDER_ANSWERS.has(v)) blocking += 1;
  }
  const ready = blocking === 0;
  const badgeEl = panel.querySelector(".framing-review-head .badge");
  if (badgeEl) {
    badgeEl.textContent = ready ? "READY FOR RESEARCH" : `${blocking} BLOCKING`;
    badgeEl.className = `badge ${ready ? "status-READY_TO_START" : "status-FRAMING_REVIEW"}`;
  }
}

function renderFramingQuestion(question) {
  const required = question.blocking ? "required" : "optional";
  const raw = String(question.answer || "").trim();
  const answer = raw.toLowerCase() === "unanswered" ? "" : raw;
  return `<label class="question-item">
    <span class="question-top"><strong>${escapeHtml(question.id || "Q")}</strong><em>${escapeHtml(required)}</em></span>
    <span>${escapeHtml(question.question || "Open question")}</span>
    ${question.reason ? `<small>${escapeHtml(question.reason)}</small>` : ""}
    <textarea data-question-id="${escapeHtml(question.id || "")}" rows="2" placeholder="${question.blocking ? "Required answer" : "Optional — leave blank to use Framer assumptions"}">${escapeHtml(answer)}</textarea>
  </label>`;
}

async function submitFramingAnswers() {
  if (!state.selectedTaskId) return;
  const panel = $("framingReviewPanel");
  const textareas = Array.from(panel.querySelectorAll("textarea[data-question-id]"));
  const questionsById = new Map();
  const review = state.detail?.framing_review;
  for (const q of (review?.questions || [])) {
    if (q && q.id) questionsById.set(String(q.id), q);
  }
  const missing = [];
  const answers = {};
  for (const input of textareas) {
    const id = input.dataset.questionId;
    const value = input.value.trim();
    answers[id] = value;
    const q = questionsById.get(id);
    const blocking = q ? !!q.blocking : false;
    input.classList.remove("invalid");
    if (blocking && !value) missing.push(input);
  }
  if (missing.length) {
    for (const input of missing) input.classList.add("invalid");
    missing[0].focus();
    showBanner(`Please answer ${missing.length} required question${missing.length === 1 ? "" : "s"} before submitting.`);
    return;
  }
  const btn = $("submitFramingBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Re-framing…"; }
  showBanner("Re-framing problem with your answers…");
  try {
    state.detail = await apiFetch(`/api/tasks/${encodeURIComponent(state.selectedTaskId)}/submit-framing`, { method: "POST", body: JSON.stringify({ by: "ui", answers }) });
    await loadTasks(true);
    showBanner(null);
  } catch (error) {
    showBanner(error.message);
    if (btn) { btn.disabled = false; btn.textContent = "Submit answers"; }
  }
}

async function startResearch() {
  if (!state.selectedTaskId) return;
  state.busy = true;
  renderDetail();
  showBanner("Starting research…");
  try {
    state.detail = await apiFetch(`/api/tasks/${encodeURIComponent(state.selectedTaskId)}/start-research`, { method: "POST", body: JSON.stringify({ by: "ui" }) });
    await loadTasks(true);
    showBanner(null);
  } catch (error) {
    showBanner(error.message);
  } finally {
    state.busy = false;
    if (state.detail) renderDetail();
  }
}

function renderResearchProgress(detail) {
  const panel = $("researchProgressPanel");
  if (!panel) return;
  const status = String(detail.state.status || "").toUpperCase();
  if (!["INVESTIGATING", "DESIGNING"].includes(status)) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  const stage = status === "INVESTIGATING" ? "Investigating current state" : "Drafting proposal, acceptance & test plan";
  panel.classList.remove("hidden");
  panel.innerHTML = `
    <div class="research-progress-head">
      <div>
        <h3>Researching</h3>
        <p>${escapeHtml(stage)}</p>
      </div>
      <span class="badge status-${escapeHtml(status)}">${escapeHtml(status)}</span>
    </div>`;
}

function renderExecutionApproval(detail) {
  const panel = $("executionApprovalPanel");
  const approval = detail.execution_approval;
  if (!approval?.required) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  const pkg = Array.isArray(approval.design_package) ? approval.design_package : [];
  const missing = Array.isArray(approval.missing_artifacts) ? approval.missing_artifacts : [];
  panel.classList.remove("hidden");
  panel.innerHTML = `
    <div class="execution-approval-head">
      <div>
        <h3>Awaiting approval</h3>
        <p>${escapeHtml(approval.meaning || "Review the design package below, then approve to start the implementation loop.")}</p>
      </div>
      <span class="badge status-WAITING_FOR_ALIGNMENT">READY TO RUN</span>
    </div>
    <div class="design-package-cards">
      ${pkg.map((item) => `
        <div class="design-package-card ${item.ready ? "is-ready" : "is-missing"}">
          <div class="dpc-head">
            <strong>${escapeHtml(item.name)}</strong>
            <em>${item.ready ? "Ready" : "Missing"}</em>
          </div>
          <p>${escapeHtml(item.description || "")}</p>
          <code>${escapeHtml(item.file)}</code>
        </div>`).join("")}
    </div>
    ${missing.length ? `<div class="dialog-error">Missing approval artifacts: ${escapeHtml(missing.join(", "))}</div>` : ""}
    <div class="execution-approval-actions">
      <button id="approveFromPanelBtn" class="primary" type="button" ${detail.actions.approve?.enabled ? "" : "disabled"}>Approve and run</button>
    </div>`;
  $("approveFromPanelBtn").addEventListener("click", () => approveAndRun());
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

function artifactPhase(name) {
  const n = String(name || "").toLowerCase();
  if (n.startsWith("framing.")) return "Framing";
  if (n === "dossier.md") return "Research";
  if (n === "proposal.md" || n.startsWith("acceptance.") || n === "test-plan.md") return "Design";
  if (/^review-.*\.json$/i.test(name)) return "Reviews";
  if (n === "final-report.md") return "Final";
  return "Other";
}

const ARTIFACT_PHASE_ORDER = ["Framing", "Research", "Design", "Reviews", "Final", "Other"];

function renderArtifacts(detail) {
  const list = $("artifactList");
  list.innerHTML = "";
  const mdArtifacts = (detail.artifacts || []).filter((a) => /\.md$/i.test(a.name || ""));
  if (!mdArtifacts.length) {
    list.innerHTML = '<div class="task-sub">No markdown artifacts yet.</div>';
    return;
  }
  const groups = new Map();
  for (const artifact of mdArtifacts) {
    const phase = artifactPhase(artifact.name);
    if (!groups.has(phase)) groups.set(phase, []);
    groups.get(phase).push(artifact);
  }
  for (const phase of ARTIFACT_PHASE_ORDER) {
    const items = groups.get(phase);
    if (!items?.length) continue;
    const group = document.createElement("section");
    group.className = "artifact-group";
    const head = document.createElement("div");
    head.className = "artifact-group-head";
    head.innerHTML = `<h3>${escapeHtml(phase)}</h3><span class="task-sub">${items.length} file${items.length === 1 ? "" : "s"}</span>`;
    group.appendChild(head);
    for (const artifact of items) {
      const node = document.createElement("section");
      node.className = "artifact-item";
      const truncated = artifact.preview?.truncated ? ` · truncated ${artifact.preview.bytes_returned}/${artifact.preview.bytes_total} bytes` : "";
      const itemHead = document.createElement("div");
      itemHead.className = "artifact-head";
      itemHead.innerHTML = `<strong>${escapeHtml(artifact.name)}</strong><span class="task-sub">${artifact.size} bytes${truncated}</span>`;
      const body = document.createElement("div");
      body.className = "markdown-body";
      body.innerHTML = renderMarkdown(artifact.preview?.content || "");
      node.appendChild(itemHead);
      node.appendChild(body);
      group.appendChild(node);
    }
    list.appendChild(group);
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
  renderConfigRoleRuntimes(detail);
}

function renderConfigRoleRuntimes(detail) {
  const container = $("configRoleRuntimes");
  if (!container) return;
  const effective = detail.config.effective || {};
  const roles = effective.roles && typeof effective.roles === "object" ? effective.roles : {};
  const defaultRuntime = effective.default_runtime || "manual";
  const entries = Object.entries(roles);
  if (!entries.length) {
    container.innerHTML = '<div class="task-sub">No role runtimes configured.</div>';
    return;
  }
  container.innerHTML = entries.map(([role, cfg]) => {
    const runtime = (cfg && cfg.runtime) || defaultRuntime;
    const usesDefault = !(cfg && cfg.runtime);
    return `<label class="role-runtime-row">
      <span><strong>${escapeHtml(role)}</strong><small>${usesDefault ? "global default" : "role override"}</small></span>
      <code>${escapeHtml(runtime)}</code>
    </label>`;
  }).join("");
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
  const container = $("roleDefaults");
  const saveBtn = $("roleDefaultsSaveBtn");
  const statusEl = $("roleDefaultsStatus");
  container.innerHTML = roles.map((role) => `
    <label class="role-runtime-row">
      <span><strong>${escapeHtml(role.role)}</strong><small>${role.uses_global_default ? "global default" : "role default"}</small></span>
      <select data-role="${escapeHtml(role.role)}" data-original="${escapeHtml(role.runtime)}">${runtimeOptionsHtml(role.runtime)}</select>
    </label>`).join("");
  statusEl.classList.add("hidden");
  statusEl.textContent = "";
  saveBtn.disabled = true;
  const updateDirty = () => {
    const dirty = Array.from(container.querySelectorAll("select[data-role]")).some(
      (s) => s.value !== s.dataset.original,
    );
    saveBtn.disabled = !dirty;
    if (dirty) {
      statusEl.classList.remove("hidden");
      statusEl.textContent = "Unsaved changes";
      statusEl.classList.remove("saved");
    } else {
      statusEl.classList.add("hidden");
    }
  };
  for (const select of container.querySelectorAll("select[data-role]")) {
    select.addEventListener("change", updateDirty);
  }
}

async function saveRoleDefaults() {
  const container = $("roleDefaults");
  const saveBtn = $("roleDefaultsSaveBtn");
  const statusEl = $("roleDefaultsStatus");
  const role_runtimes = {};
  for (const select of container.querySelectorAll("select[data-role]")) {
    if (select.value !== select.dataset.original) {
      role_runtimes[select.dataset.role] = select.value;
    }
  }
  if (!Object.keys(role_runtimes).length) return;
  saveBtn.disabled = true;
  statusEl.classList.remove("hidden");
  statusEl.textContent = "Saving…";
  statusEl.classList.remove("saved");
  try {
    state.settings = await apiFetch("/api/settings", { method: "PATCH", body: JSON.stringify({ role_runtimes }) });
    renderSettingsRuntime(state.settings);
    statusEl.classList.remove("hidden");
    statusEl.classList.add("saved");
    statusEl.textContent = "Saved";
    setTimeout(() => statusEl.classList.add("hidden"), 1500);
  } catch (error) {
    statusEl.classList.remove("hidden");
    statusEl.classList.remove("saved");
    statusEl.textContent = error.message;
    saveBtn.disabled = false;
  }
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

  byIter.forEach((it, idx) => {
    const chip = document.createElement("button");
    chip.className = `iter-chip ${it.iteration === state.iterationIndex ? "active" : ""}${it.iteration === latest ? " is-latest" : ""}`;
    const failBadge = it.tests_failed ? `<span class="iter-chip-fail">${it.tests_failed}</span>` : "";
    const passBadge = it.tests_passed ? `<span class="iter-chip-pass">${it.tests_passed}</span>` : "";
    chip.innerHTML = `
      <span class="iter-chip-num">Iteration ${idx + 1}</span>
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
  const currentDisplayNum = (byIter.findIndex((it) => it.iteration === current.iteration) + 1) || 1;
  const entries = [
    ...(current.agents || []).map((agent) => ({ type: "agent", label: agent.role || "agent", data: agent })),
    ...(current.tests || []).map((test) => ({ type: "test", label: test.name, data: test })),
  ];
  if (!entries.length) {
    content.innerHTML = `<div class="task-sub">Iteration ${currentDisplayNum} has no agent or test output.</div>`;
    return;
  }
  if (state.runtimeIndex >= entries.length) state.runtimeIndex = 0;

  entries.forEach((entry, index) => {
    const button = document.createElement("button");
    const isTest = entry.type === "test";
    const exit = isTest ? entry.data.exit_code : entry.data.exit_code;
    const dot = exit === 0 ? "ok" : (typeof exit === "number" ? "fail" : "muted");
    button.innerHTML = `<span class="dot dot-${dot}"></span><span class="rt-label">${escapeHtml(entry.label)}</span><span class="rt-iter">Iteration ${currentDisplayNum}</span><span class="rt-kind">${entry.type}</span>`;
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

function renderContext(detail) {
  const ctx = detail.context || {};
  const sessions = ctx.role_sessions || [];
  const timeline = ctx.context_log || [];
  const sessionsEl = $("contextSessions");
  const timelineEl = $("contextTimeline");
  const viewerEl = $("transcriptViewer");
  if (!sessionsEl || !timelineEl || !viewerEl) return;

  if (!sessions.length) {
    sessionsEl.innerHTML = '<div class="task-sub">No warm sessions yet. Sessions appear once a role completes a turn with a resume-capable runtime.</div>';
  } else {
    sessionsEl.innerHTML = sessions
      .map((s) => {
        const sid = s.session_id || "(no session_id)";
        const short = String(sid).slice(0, 8);
        const turns = s.turns != null ? `${s.turns} turn${s.turns === 1 ? "" : "s"}` : "";
        return `
          <div class="context-session">
            <div class="ctx-role">${escapeHtml(s.role || "?")}</div>
            <div class="ctx-runtime">${escapeHtml(s.runtime || "-")}</div>
            <div class="ctx-session-id" title="${escapeHtml(sid)}">${escapeHtml(short)}</div>
            <div class="task-sub">${escapeHtml(turns)} · ${escapeHtml(s.updated_at || "-")}</div>
          </div>`;
      })
      .join("");
  }

  if (!timeline.length) {
    timelineEl.innerHTML = '<div class="task-sub">No context entries yet.</div>';
  } else {
    timelineEl.innerHTML = timeline
      .map((entry, idx) => {
        const role = entry.role || "?";
        const turn = entry.turn ?? "?";
        const key = `${role}-${turn}`;
        const isSelected = state.selectedTranscript === key;
        const resumedBadge = entry.resumed ? '<span class="ctx-badge resumed" title="Resumed session">🔁 resume</span>' : "";
        const handoffBadge = entry.handoff_present === false
          ? '<span class="ctx-badge muted" title="No handoff (manual runtime)">no handoff</span>'
          : entry.handoff_ref
            ? '<span class="ctx-badge ok" title="Handoff written">handoff</span>'
            : "";
        const transcriptBadge = entry.transcript_ref ? '<span class="ctx-badge ok" title="Transcript captured">transcript</span>' : "";
        const sidShort = entry.session_id ? String(entry.session_id).slice(0, 8) : "";
        return `
          <button type="button" class="context-row ${isSelected ? "active" : ""}" data-role="${escapeHtml(role)}" data-turn="${escapeHtml(turn)}">
            <span class="ctx-turn">#${escapeHtml(turn)}</span>
            <span class="ctx-role">${escapeHtml(role)}</span>
            <span class="ctx-runtime">${escapeHtml(entry.runtime || "-")}</span>
            <span class="ctx-badges">${resumedBadge}${handoffBadge}${transcriptBadge}</span>
            <span class="ctx-session-id task-sub" title="${escapeHtml(entry.session_id || "")}">${escapeHtml(sidShort)}</span>
            <span class="ctx-at task-sub">${escapeHtml(entry.at || "")}</span>
          </button>`;
      })
      .join("");
    timelineEl.querySelectorAll(".context-row").forEach((btn) => {
      btn.addEventListener("click", () => {
        const role = btn.dataset.role;
        const turn = btn.dataset.turn;
        loadTranscript(role, turn);
      });
    });
  }

  if (!state.selectedTranscript) {
    viewerEl.innerHTML = '<div class="task-sub">Select a turn to view its transcript.</div>';
  }
}

async function loadTranscript(role, turn) {
  if (!state.selectedTaskId) return;
  const key = `${role}-${turn}`;
  state.selectedTranscript = key;
  const viewerEl = $("transcriptViewer");
  if (!viewerEl) return;
  viewerEl.innerHTML = '<div class="task-sub">Loading transcript…</div>';
  // refresh active highlight
  document.querySelectorAll("#contextTimeline .context-row").forEach((row) => {
    row.classList.toggle("active", row.dataset.role === role && row.dataset.turn === String(turn));
  });
  try {
    const data = await apiFetch(`/api/tasks/${encodeURIComponent(state.selectedTaskId)}/transcripts/${encodeURIComponent(role)}/${encodeURIComponent(turn)}`);
    renderTranscript(data);
  } catch (error) {
    viewerEl.innerHTML = `<div class="dialog-error">${escapeHtml(error.message)}</div>`;
  }
}

function renderTranscript(t) {
  const viewerEl = $("transcriptViewer");
  if (!viewerEl) return;
  const meta = [
    ["role", t.role],
    ["turn", t.turn],
    ["runtime", t.runtime],
    ["exit", t.exit_code],
    ["duration", t.duration_ms != null ? `${t.duration_ms} ms` : "-"],
    ["session_id", t.session_id || "-"],
    ["resumed", t.resumed ? "yes" : "no"],
    ["written_at", t.written_at || "-"],
  ];
  const metaHtml = meta.map(([k, v]) => `<span><strong>${escapeHtml(k)}</strong> ${escapeHtml(String(v ?? "-"))}</span>`).join("");
  const cmd = t.command ? `<h3>command</h3><pre class="command-block">${escapeHtml(t.command)}</pre>` : "";
  const prompt = t.prompt ? `<h3>prompt</h3><pre class="log-block">${escapeHtml(t.prompt)}</pre>` : "";
  const stdout = t.stdout ? `<h3>stdout</h3><pre class="log-block">${escapeHtml(t.stdout)}</pre>` : "";
  const stderr = t.stderr ? `<h3>stderr</h3><pre class="log-block">${escapeHtml(t.stderr)}</pre>` : "";
  viewerEl.innerHTML = `<div class="runtime-meta transcript-meta">${metaHtml}</div>${cmd}${prompt}${stdout}${stderr}`;
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

async function approveAndRun() {
  if (!state.selectedTaskId) return;
  const taskId = state.selectedTaskId;
  state.busy = true;
  renderDetail();
  showBanner("Approving...");
  try {
    state.detail = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/approve`, { method: "POST", body: JSON.stringify({ by: "ui" }) });
    if (state.detail?.actions?.run?.enabled) {
      showBanner("Starting run...");
      state.detail = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/run`, { method: "POST", body: JSON.stringify({ by: "ui" }) });
    }
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
  $("roleDefaultsSaveBtn").addEventListener("click", saveRoleDefaults);
  $("taskSettingsBtn").addEventListener("click", () => {
    const dlg = $("taskSettingsDialog");
    if (dlg && typeof dlg.showModal === "function") dlg.showModal();
  });
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
    const btn = event.target.closest("button[data-tab]");
    if (!btn) return;
    const tab = btn.dataset.tab;
    [...$("detailTabs").querySelectorAll("button")].forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
    [...document.querySelectorAll(".tab-panel")].forEach((panel) => panel.classList.toggle("active", panel.id === `${tab}Tab`));
  });
  $("createForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const request = $("requestInput").value.trim();
    const codePath = $("codePathInput").value.trim();
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
    if (!codePath) {
      errorBox.textContent = "Code path is required.";
      errorBox.classList.remove("hidden");
      $("codePathInput").focus();
      return;
    }
    submitBtn.disabled = true;
    submitBtn.textContent = "Creating...";
    try {
      const maxIter = Number($("createMaxIterations").value) || 7;
      const detail = await apiFetch("/api/tasks", { method: "POST", body: JSON.stringify({ request, code_path: codePath, role_runtimes: selectedRoleRuntimes(), max_iterations: maxIter }) });
      $("createDialog").close();
      $("requestInput").value = "";
      $("codePathInput").value = "";
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
      state.detail = await apiFetch(`/api/tasks/${encodeURIComponent(state.selectedTaskId)}/config`, { method: "PATCH", body: JSON.stringify({ test_commands: commands }) });
      renderDetail();
      showBanner(null);
    } catch (error) { showBanner(error.message); }
  });
}

wireEvents();
startAutoRefresh();
loadTasks(false).catch((error) => showBanner(error.message));
