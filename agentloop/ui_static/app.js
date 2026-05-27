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
  approvalSelection: {},
  researchSelection: {},
  viewPhase: {},
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
  { key: "framing", label: "Framing", sub: "clarify the problem", tab: "basic", match: ["CREATED", "FRAMING_REVIEW"], roles: [{ key: "framer", label: "Framer", icon: "FR" }] },
  { key: "research", label: "Researching", sub: "investigate & design", tab: "basic", match: ["INVESTIGATING", "DESIGNING"], roles: [{ key: "investigator", label: "Investigator", icon: "IN" }, { key: "architect", label: "Architect", icon: "AR" }] },
  { key: "approve", label: "Awaiting approval", sub: "review the plan", tab: "basic", match: ["WAITING_FOR_ALIGNMENT"], roles: [{ key: "human", label: "You", icon: "YOU" }] },
  { key: "run", label: "Running", sub: "iterations executing", tab: "execlog", match: ["READY_TO_START", "RUNNING", "EXECUTING", "IMPLEMENTING_AND_TESTING", "REVIEWING", "WAITING_FOR_HUMAN"], roles: [{ key: "implementer", label: "Implementer", icon: "IM" }, { key: "tester", label: "Tester", icon: "TS" }, { key: "reviewer", label: "Reviewer", icon: "RV" }] },
  { key: "done", label: "Done", sub: "task complete", tab: "basic", match: ["DONE", "CANCELLED", "FAILED"], roles: [{ key: "integrator", label: "Integrator", icon: "IT" }] },
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
  framing: ["framing.md"],
  research: ["research.md", "proposal.md", "acceptance.md", "test-plan.md"],
  approval: ["research.md", "proposal.md", "acceptance.md", "test-plan.md"],
  running: ["final-report.md"],
  done: ["final-report.md"],
};

// Map between lifecycle step keys and renderBasic phase identifiers.
const STEP_TO_PHASE = { framing: "framing", research: "research", approve: "approval", run: "running", done: "done" };
const PHASE_TO_STEP = { framing: "framing", research: "research", approval: "approve", running: "run", done: "done" };

function reachedPhases(task) {
  const cancelled = String(task.status || "").toUpperCase() === "CANCELLED";
  const currentIdx = cancelled
    ? lifecycleIndex(task.cancelled_from || task.status)
    : lifecycleIndex(task.status);
  return LIFECYCLE_STEPS.slice(0, currentIdx + 1).map((s) => STEP_TO_PHASE[s.key]);
}

function resolveViewPhase(task) {
  const reached = reachedPhases(task);
  if (!reached.length) return "framing";
  const stored = state.viewPhase[task.task_id];
  if (stored && reached.includes(stored)) return stored;
  return reached[reached.length - 1];
}

function renderLifecycle(task, viewedPhase) {
  const root = $("lifecycle");
  root.innerHTML = "";
  const cancelled = String(task.status || "").toUpperCase() === "CANCELLED";
  // For cancelled tasks, derive position from the pre-cancel status so prior phases still look completed
  // and the cancelled phase is marked red. Steps after stay gray.
  const current = cancelled
    ? lifecycleIndex(task.cancelled_from || "FRAMING_REVIEW")
    : lifecycleIndex(task.status);
  const viewedStepKey = viewedPhase ? PHASE_TO_STEP[viewedPhase] : null;
  // A phase is "actively running" when an agent is working and the UI is not blocking
  // on a human prompt. These statuses keep the current lifecycle dot pulsing.
  const ACTIVE_STATUSES = new Set([
    "CREATED", "FRAMING",
    "INVESTIGATING", "DESIGNING",
    "READY_TO_START", "RUNNING", "EXECUTING", "IMPLEMENTING_AND_TESTING", "REVIEWING",
    "INTEGRATING",
  ]);
  const isActive = !cancelled && ACTIVE_STATUSES.has(String(task.status || "").toUpperCase());
  LIFECYCLE_STEPS.forEach((step, idx) => {
    const li = document.createElement("li");
    const stepState = idx < current ? "done" : idx === current ? "current" : "pending";
    const reached = idx <= current;
    const isViewed = reached && step.key === viewedStepKey;
    const isRunning = stepState === "current" && isActive;
    li.className = `lc-step lc-${stepState}${cancelled && idx === current ? " lc-cancelled" : ""}${isViewed ? " lc-viewed" : ""}${isRunning ? " lc-running" : ""}`;
    const rolesHtml = (step.roles || []).map((r) => `
      <span class="lc-role lc-role-${escapeHtml(r.key)}" title="${escapeHtml(r.label)}">
        <span class="lc-role-icon" aria-hidden="true">${escapeHtml(r.icon)}</span>
        <span class="sr-only">${escapeHtml(r.label)}</span>
      </span>`).join("");
    const tip = reached
      ? (isViewed ? `Viewing ${step.label}` : `Click to view ${step.label}`)
      : "Not started yet";
    const dotText = idx < current ? "✓" : (cancelled && step.key === "done" && idx > current ? "-" : idx + 1);
    li.innerHTML = `
      <button type="button" class="lc-btn" data-tab="${step.tab}" data-step="${escapeHtml(step.key)}" data-state="${stepState}" ${reached ? "" : "disabled"} aria-pressed="${isViewed ? "true" : "false"}" title="${escapeHtml(tip)}">
        <span class="lc-rail">
          <span class="lc-line lc-line-left"></span>
          <span class="lc-dot">${dotText}</span>
          <span class="lc-line lc-line-right"></span>
          <span class="lc-working">working</span>
        </span>
        <span class="lc-label">${escapeHtml(step.label)}</span>
        <span class="lc-sub">${escapeHtml(step.sub)}</span>
        ${rolesHtml ? `<span class="lc-roles">${rolesHtml}</span>` : ""}
      </button>`;
    root.appendChild(li);
  });
  root.onclick = (event) => {
    const btn = event.target.closest(".lc-btn");
    if (!btn || btn.disabled || btn.dataset.state === "pending") return;
    const tab = btn.dataset.tab;
    [...$("detailTabs").querySelectorAll("button")].forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    [...document.querySelectorAll(".tab-panel")].forEach((panel) => panel.classList.toggle("active", panel.id === `${tab}Tab`));
    const stepKey = btn.dataset.step;
    const targetPhase = stepKey ? STEP_TO_PHASE[stepKey] : null;
    if (targetPhase && state.detail) {
      state.viewPhase[state.detail.state.task_id] = targetPhase;
      renderDetail();
    }
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

function renderOverviewCta(detail, phase) {
  const cta = $("overviewCta");
  if (!cta) return;
  const status = String(detail.state.status || "").toUpperCase();
  const approveEnabled = detail.actions?.approve?.enabled;
  // Only surface the floating CTA while the user is viewing the approval (or running)
  // phase — never under framing or research.
  const allowedPhase = phase === "approval" || phase === "running";
  if (allowedPhase && status === "WAITING_FOR_ALIGNMENT" && approveEnabled) {
    cta.classList.remove("hidden");
    cta.innerHTML = `
      <div class="overview-cta-text">
        <strong>Plan ready for review.</strong>
        <span>Read the goal, phases, and acceptance above, then approve to start running.</span>
      </div>
      <button type="button" class="primary" id="overviewApproveBtn">Approve &amp; run →</button>`;
    $("overviewApproveBtn").onclick = () => approveAndRun();
    $("overviewApproveBtn").disabled = state.busy;
  } else if (allowedPhase && status === "READY_TO_START" && detail.actions?.run?.enabled) {
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
  const phase = resolveViewPhase(task);
  $("taskIdLabel").textContent = task.task_id;
  $("taskTitle").textContent = task.title || task.task_id;
  $("taskMeta").innerHTML = `<span class="${statusClass(task.status)}">${escapeHtml(task.status)}</span> ${escapeHtml(task.current_phase || "-")} · ${task.iteration ?? "-"}/${task.max_iterations ?? "-"} · updated ${escapeHtml(task.updated_at || "-")}`;
  const basicSub = $("basicTabSub");
  if (basicSub) basicSub.textContent = PHASE_LABELS[phase] || "current phase";
  const basicPanel = $("basicTab");
  if (basicPanel) basicPanel.dataset.phase = phase;
  renderLifecycle(task, phase);
  configurePrimaryAction(detail);
  renderBasic(detail, phase);
  renderOverviewCta(detail, phase);
  renderArtifacts(detail);
  renderConfig(detail);
  renderRuntime(detail);
  renderContext(detail);
}

function renderBasic(detail, phase) {
  const task = detail.state;
  const isCancelled = String(task.status || "").toUpperCase() === "CANCELLED";
  // Detach sections we may have embedded back to their safe parent (basicTab) BEFORE
  // running sub-renderers that wipe panel innerHTML — otherwise the embedded nodes
  // get destroyed when their host panel re-renders.
  const basicTabEl = $("basicTab");
  ["phaseArtifactSection", "acceptanceSection"].forEach((id) => {
    const node = document.getElementById(id);
    if (node && basicTabEl && node.parentElement !== basicTabEl) {
      basicTabEl.appendChild(node);
      node.classList.remove("is-embedded-in-approval");
    }
  });
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
  // In approval phase, the acceptance list is gated by the "Acceptance" card selection.
  // Research phase mirrors that behavior with researchSelection.
  // Other phases keep the previous default (hidden in framing/done, visible otherwise).
  const approvalSelected = phase === "approval" ? resolveApprovalSelection(detail) : null;
  const researchSelected = phase === "research" ? state.researchSelection[detail.state.task_id] || null : null;
  const accVisibleInApproval = approvalSelected === "acceptance.md";
  const accVisibleInResearch = researchSelected === "acceptance.md";
  if (accSec) {
    if (phase === "approval") {
      accSec.classList.toggle("hidden", !accVisibleInApproval);
    } else if (phase === "research") {
      accSec.classList.toggle("hidden", !accVisibleInResearch);
    } else {
      accSec.classList.toggle("hidden", phase === "framing" || phase === "done");
    }
  }
  // Acceptance content
  renderAcceptance(task);
  // Phase-specific artifact preview:
  // - approval phase: only show the artifact selected via the approval cards,
  //   except the Acceptance card which delegates to the structured AC list above
  // - research phase: mirror approval — show only the selected card's file
  let wantedOverride = null;
  if (phase === "approval") {
    wantedOverride = approvalSelected && !accVisibleInApproval ? [approvalSelected] : [];
  } else if (phase === "research") {
    wantedOverride = researchSelected && !accVisibleInResearch ? [researchSelected] : [];
  }
  renderPhaseArtifacts(detail, phase, wantedOverride);
  // Embed the selected artifact preview (or acceptance list) INSIDE the host phase panel
  // (right under the design-package cards) for both research and approval phases.
  const phaseSection = $("phaseArtifactSection");
  const approvalPanel = $("executionApprovalPanel");
  const researchPanel = $("researchProgressPanel");
  const basicTab = $("basicTab");
  const acceptanceAnchor = $("acceptanceSection");
  let host = null;
  if (phase === "approval" && approvalPanel) host = approvalPanel;
  else if (phase === "research" && researchPanel) host = researchPanel;
  // Move the artifact preview section
  if (phaseSection && basicTab) {
    if (host && !phaseSection.classList.contains("hidden")) {
      if (phaseSection.parentElement !== host) host.appendChild(phaseSection);
      phaseSection.classList.add("is-embedded-in-approval");
    } else {
      phaseSection.classList.remove("is-embedded-in-approval");
      if (phaseSection.parentElement !== basicTab) {
        if (acceptanceAnchor && acceptanceAnchor.parentElement === basicTab) {
          basicTab.insertBefore(phaseSection, acceptanceAnchor.nextSibling);
        } else {
          basicTab.appendChild(phaseSection);
        }
      }
    }
  }
  // Move the acceptance section into the same host when the Acceptance card is selected
  if (acceptanceAnchor && basicTab) {
    const acceptanceSelected = (phase === "approval" && accVisibleInApproval) || (phase === "research" && accVisibleInResearch);
    if (host && acceptanceSelected && !acceptanceAnchor.classList.contains("hidden")) {
      if (acceptanceAnchor.parentElement !== host) host.appendChild(acceptanceAnchor);
      acceptanceAnchor.classList.add("is-embedded-in-approval");
    } else {
      acceptanceAnchor.classList.remove("is-embedded-in-approval");
      if (acceptanceAnchor.parentElement !== basicTab) {
        const goalSec = $("goalSection");
        if (goalSec && goalSec.parentElement === basicTab) {
          basicTab.insertBefore(acceptanceAnchor, goalSec.nextSibling);
        } else {
          basicTab.appendChild(acceptanceAnchor);
        }
      }
    }
  }
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
  // Keep non-goals / assumptions expanded while the user is still framing the
  // problem (they need that context to answer open questions). Once framing is
  // done, collapse them to save space — a summary line lists the counts.
  const phase = currentPhase(task.status);
  const collapse = phase !== "framing";
  const extras = [];
  if (nonGoals.length) {
    extras.push({
      label: "Non-goals",
      count: nonGoals.length,
      html: `<ul>${nonGoals.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>`,
    });
  }
  if (assumptions.length) {
    extras.push({
      label: "Assumptions",
      count: assumptions.length,
      html: `<ul>${assumptions.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>`,
    });
  }
  if (extras.length) {
    if (collapse) {
      const summary = extras.map((e) => `${e.count} ${e.label.toLowerCase()}`).join(" · ");
      const body = extras
        .map((e) => `<div class="goal-section"><div class="goal-label">${escapeHtml(e.label)}</div>${e.html}</div>`)
        .join("");
      parts.push(`<details class="goal-extras"><summary>Show ${escapeHtml(summary)}</summary>${body}</details>`);
    } else {
      for (const e of extras) {
        parts.push(`<div class="goal-section"><div class="goal-label">${escapeHtml(e.label)}</div>${e.html}</div>`);
      }
    }
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
  // Show open (unanswered) questions first so the user always sees what still
  // needs their attention; answered ones move to the bottom for reference.
  const sortedQuestions = questions.slice().sort((a, b) => {
    const aOpen = isQuestionOpen(a) ? 0 : 1;
    const bOpen = isQuestionOpen(b) ? 0 : 1;
    if (aOpen !== bOpen) return aOpen - bOpen;
    return 0;
  });
  const blocking = review.blocking_count || 0;
  const ready = !!review.ready_for_research;
  const badge = ready ? "READY FOR RESEARCH" : (blocking ? `${blocking} BLOCKING` : "NEEDS REVIEW");
  const badgeClass = ready ? "status-READY_TO_START" : "status-FRAMING_REVIEW";
  const errorText = review.error ? String(review.error) : "";
  const signature = `review:${ready ? 1 : 0}:${blocking}:${errorText}:${sortedQuestions.map((q) => `${q.id}|${q.question}|${q.blocking ? 1 : 0}|${q.answer || ""}`).join("§")}`;
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
    ${errorText ? `<div class="dialog-error"><strong>Framer failed.</strong><pre class="framing-error-pre">${escapeHtml(errorText)}</pre></div>` : ""}
    <div class="question-list">
      ${sortedQuestions.length ? sortedQuestions.map(renderFramingQuestion).join("") : '<div class="task-sub">No open questions. Click "Start research" to continue.</div>'}
    </div>
    <div class="framing-review-actions">
      <button id="submitFramingBtn" class="secondary" type="button" ${ready ? "hidden" : ""}>Submit answers</button>
      <button id="startResearchBtn" class="primary" type="button" ${ready ? "" : "disabled"} title="${ready ? "" : "Answer the required questions first"}">Start research →</button>
    </div>`;
  $("submitFramingBtn").addEventListener("click", submitFramingAnswers);
  $("startResearchBtn").addEventListener("click", startResearch);
  panel.querySelectorAll("textarea[data-question-id]").forEach((ta) => {
    ta.addEventListener("input", () => refreshFramingReadiness(questions));
  });
}

const PLACEHOLDER_ANSWERS = new Set(["", "unanswered", "n/a", "na", "tbd", "none"]);

function isQuestionOpen(question) {
  if (!question) return true;
  const raw = String(question.answer || "").trim().toLowerCase();
  return PLACEHOLDER_ANSWERS.has(raw);
}

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
  const submitBtn = panel.querySelector("#submitFramingBtn");
  if (submitBtn) submitBtn.hidden = ready;
  const startBtn = panel.querySelector("#startResearchBtn");
  if (startBtn) {
    startBtn.disabled = !ready;
    startBtn.title = ready ? "" : "Answer the required questions first";
  }
}

function renderFramingQuestion(question) {
  const required = question.blocking ? "required" : "optional";
  const raw = String(question.answer || "").trim();
  const answer = raw.toLowerCase() === "unanswered" ? "" : raw;
  const open = isQuestionOpen(question);
  const stateClass = open ? "is-open" : "is-answered";
  const stateLabel = open ? "open" : "answered";
  return `<label class="question-item ${stateClass}">
    <span class="question-top">
      <strong>${escapeHtml(question.id || "Q")}</strong>
      <em>${escapeHtml(required)}</em>
      <span class="question-state-pill ${stateClass}">${stateLabel}</span>
    </span>
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
    activateDetailTab("execlog");
    state.iterationIndex = state.detail.runtime?.latest_iteration ?? null;
    state.runtimeIndex = 0;
    await loadTasks(true);
    showBanner(null);
  } catch (error) {
    showBanner(error.message);
  } finally {
    state.busy = false;
    if (state.detail) renderDetail();
  }
}

function activateDetailTab(tab) {
  [...$("detailTabs").querySelectorAll("button")].forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  [...document.querySelectorAll(".tab-panel")].forEach((panel) => panel.classList.toggle("active", panel.id === `${tab}Tab`));
}

function renderResearchProgress(detail) {
  const panel = $("researchProgressPanel");
  if (!panel) return;
  const status = String(detail.state.status || "").toUpperCase();
  const stillRunning = ["INVESTIGATING", "DESIGNING"].includes(status);
  const artifacts = detail.artifacts || [];
  const byName = new Map(artifacts.map((a) => [String(a.name || "").toLowerCase(), a]));
  const items = [
    { file: "research.md", name: "Research", description: "Investigator's dossier of current state." },
    { file: "proposal.md", name: "Proposal", description: "Architect's design proposal." },
    { file: "acceptance.md", name: "Acceptance", description: "Acceptance criteria for the implementation." },
    { file: "test-plan.md", name: "Test plan", description: "How the implementation will be verified." },
  ].map((it) => ({ ...it, ready: byName.has(it.file.toLowerCase()) }));
  if (!items.some((it) => it.ready) && !stillRunning) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  const selected = resolveResearchSelection(detail, items);
  panel.classList.remove("hidden");
  const stage = status === "INVESTIGATING"
    ? "Investigating current state"
    : status === "DESIGNING"
      ? "Drafting proposal, acceptance & test plan"
      : "Research outputs";
  const badge = stillRunning
    ? `<span class="badge status-${escapeHtml(status)}">${escapeHtml(status)}</span>`
    : `<span class="badge status-READY_TO_START">RESEARCH COMPLETE</span>`;
  panel.innerHTML = `
    <div class="research-progress-head">
      <div>
        <h3>Researching</h3>
        <p>${escapeHtml(stage)}</p>
      </div>
      ${badge}
    </div>
    <div class="design-package-cards" role="tablist">
      ${items.map((item) => {
        const isSelected = item.ready && item.file === selected;
        const classes = [
          "design-package-card",
          item.ready ? "is-ready" : "is-missing",
          isSelected ? "is-selected" : "",
        ].filter(Boolean).join(" ");
        const stateLabel = item.ready ? (isSelected ? "Viewing" : "Ready") : (stillRunning ? "Generating…" : "Missing");
        return `
        <button type="button" class="${classes}" data-file="${escapeHtml(item.file)}" ${item.ready ? "" : "disabled"} role="tab" aria-selected="${isSelected ? "true" : "false"}">
          <div class="dpc-head">
            <strong>${escapeHtml(item.name)}</strong>
            <em>${escapeHtml(stateLabel)}</em>
          </div>
          <p>${escapeHtml(item.description)}</p>
          <code>${escapeHtml(item.file)}</code>
        </button>`;
      }).join("")}
    </div>
    ${stillRunning ? `<div class="framing-loading"><span class="spinner" aria-hidden="true"></span> ${escapeHtml(stage)}…</div>` : ""}`;
  panel.querySelectorAll(".design-package-card[data-file]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      const file = btn.dataset.file;
      if (!file) return;
      state.researchSelection[detail.state.task_id] = file;
      renderBasic(detail, "research");
    });
  });
}

function resolveResearchSelection(detail, items) {
  const ready = items.filter((it) => it.ready).map((it) => it.file);
  if (!ready.length) return null;
  const taskId = detail.state.task_id;
  const remembered = state.researchSelection[taskId];
  if (remembered && ready.includes(remembered)) return remembered;
  const preferred = ready.includes("research.md") ? "research.md" : ready[0];
  state.researchSelection[taskId] = preferred;
  return preferred;
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
  const selected = resolveApprovalSelection(detail);
  panel.classList.remove("hidden");
  panel.innerHTML = `
    <div class="execution-approval-head">
      <div>
        <h3>Awaiting approval</h3>
        <p>${escapeHtml(approval.meaning || "Review the design package below, then approve to start the implementation loop.")}</p>
      </div>
      <span class="badge status-WAITING_FOR_ALIGNMENT">READY TO RUN</span>
    </div>
    <div class="design-package-cards" role="tablist">
      ${pkg.map((item) => {
        const isSelected = item.ready && item.file === selected;
        const classes = [
          "design-package-card",
          item.ready ? "is-ready" : "is-missing",
          isSelected ? "is-selected" : "",
        ].filter(Boolean).join(" ");
        return `
        <button type="button" class="${classes}" data-file="${escapeHtml(item.file)}" ${item.ready ? "" : "disabled"} role="tab" aria-selected="${isSelected ? "true" : "false"}">
          <div class="dpc-head">
            <strong>${escapeHtml(item.name)}</strong>
            <em>${item.ready ? (isSelected ? "Viewing" : "Ready") : "Missing"}</em>
          </div>
          <p>${escapeHtml(item.description || "")}</p>
          <code>${escapeHtml(item.file)}</code>
        </button>`;
      }).join("")}
    </div>
    ${missing.length ? `<div class="dialog-error">Missing approval artifacts: ${escapeHtml(missing.join(", "))}</div>` : ""}`;
  panel.querySelectorAll(".design-package-card[data-file]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      const file = btn.dataset.file;
      if (!file) return;
      state.approvalSelection[detail.state.task_id] = file;
      renderBasic(detail, "approval");
    });
  });
}

function resolveApprovalSelection(detail) {
  const approval = detail.execution_approval;
  if (!approval?.required) return null;
  const pkg = Array.isArray(approval.design_package) ? approval.design_package : [];
  const ready = pkg.filter((item) => item.ready).map((item) => item.file);
  if (!ready.length) return null;
  const taskId = detail.state.task_id;
  const remembered = state.approvalSelection[taskId];
  if (remembered && ready.includes(remembered)) return remembered;
  const preferred = ready.includes("proposal.md") ? "proposal.md" : ready[0];
  state.approvalSelection[taskId] = preferred;
  return preferred;
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
  if (n === "research.md") return "Research";
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

function formatRuntimeDuration(ms) {
  if (ms == null) return "duration -";
  const n = Number(ms);
  if (!Number.isFinite(n)) return `${ms} ms`;
  if (n < 1000) return `${Math.round(n)} ms`;
  return `${Math.round(n / 100) / 10}s`;
}

function lifecycleRole(role) {
  const key = String(role || "").toLowerCase();
  for (const step of LIFECYCLE_STEPS) {
    const found = (step.roles || []).find((r) => r.key === key || r.label.toLowerCase() === key);
    if (found) return found;
  }
  return { key, label: role || "agent", icon: String(role || "AG").slice(0, 2).toUpperCase() };
}

function runtimeMetaHtml(items) {
  return `<div class="runtime-meta">${items.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>`;
}

function runtimeDetailRow(label, value) {
  if (!value) return "";
  return `
    <div class="runtime-detail-row">
      <span class="runtime-detail-key">${escapeHtml(label)}</span>
      <code class="runtime-detail-value" title="${escapeHtml(value)}">${escapeHtml(value)}</code>
      <button type="button" class="runtime-copy-btn" data-copy="${escapeHtml(value)}">copy</button>
    </div>`;
}

function runtimeLogSection(id, title, text, log) {
  const body = text || "";
  const truncated = log?.truncated ? `<span class="runtime-truncated" title="Log exceeded the read limit${log.path ? `; open ${escapeHtml(log.path)} on disk` : ""}">truncated ${escapeHtml(log.bytes_returned ?? "?")}/${escapeHtml(log.bytes_total ?? "?")} bytes</span>` : "";
  return `
    <div class="runtime-log-head">
      <h3>${escapeHtml(title)}</h3>
      <div class="runtime-log-actions">
        ${truncated}
        <button type="button" data-copy="${escapeHtml(body)}">copy</button>
        <button type="button" data-log-bottom="${escapeHtml(id)}">bottom</button>
        <button type="button" data-log-wrap="${escapeHtml(id)}" aria-pressed="false">wrap</button>
      </div>
    </div>
    <pre id="${escapeHtml(id)}" class="log-block">${escapeHtml(body)}</pre>`;
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text || "");
    return;
  }
  const area = document.createElement("textarea");
  area.value = text || "";
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}

function renderRuntime(detail) {
  const rt = detail.runtime || {};
  const status = String(detail?.state?.status || "").toUpperCase();
  const isRunning = ["INVESTIGATING", "DESIGNING", "READY_TO_START", "RUNNING", "EXECUTING", "IMPLEMENTING_AND_TESTING", "REVIEWING"].includes(status);
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
    content.innerHTML = isRunning
      ? `<div class="runtime-loading"><span class="spinner"></span><span>${escapeHtml(status.toLowerCase().replaceAll("_", " "))} — waiting for first output…</span></div>`
      : '<div class="task-sub">No runtime output yet.</div>';
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
      <span class="iter-chip-num">Iteration ${escapeHtml(it.iteration)}</span>
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
  const summary = document.createElement("div");
  summary.className = "runtime-iteration-summary";
  summary.textContent = `Iteration ${current.iteration} · ${current.agent_count ?? (current.agents || []).length} agent${(current.agent_count ?? (current.agents || []).length) === 1 ? "" : "s"} · ${current.test_count ?? (current.tests || []).length} test${(current.test_count ?? (current.tests || []).length) === 1 ? "" : "s"}`;
  bar.prepend(summary);
  if (!entries.length) {
    content.innerHTML = isRunning
      ? `<div class="runtime-loading"><span class="spinner"></span><span>${escapeHtml(status.toLowerCase().replaceAll("_", " "))} — starting agent…</span></div>`
      : `<div class="task-sub">Iteration ${escapeHtml(current.iteration)} has no agent or test output.</div>`;
    return;
  }
  if (state.runtimeIndex >= entries.length) state.runtimeIndex = 0;

  entries.forEach((entry, index) => {
    const button = document.createElement("button");
    const isTest = entry.type === "test";
    const exit = isTest ? entry.data.exit_code : entry.data.exit_code;
    const live = entry.type === "agent" && isRunning && exit == null;
    const dot = exit === 0 ? "ok" : (typeof exit === "number" ? "fail" : (live ? "live" : "pending"));
    const duration = formatRuntimeDuration(entry.data.duration_ms);
    const role = isTest ? null : lifecycleRole(entry.data.role || entry.label);
    const roleIcon = role ? `<span class="rt-role" title="${escapeHtml(role.label)}">${escapeHtml(role.icon)}</span>` : "";
    const exitTag = isTest && exit != null ? `<span class="rt-exit">exit ${escapeHtml(exit)}</span>` : "";
    button.innerHTML = `
      <span class="dot dot-${dot}"></span>
      ${roleIcon}
      <span class="rt-main">
        <span class="rt-label">${escapeHtml(entry.label || entry.type)}</span>
        <span class="rt-subline"><span>${escapeHtml(duration)}</span>${exitTag}<span class="rt-kind">${entry.type}</span></span>
      </span>`;
    button.className = index === state.runtimeIndex ? "active" : "";
    button.addEventListener("click", () => { state.runtimeIndex = index; renderRuntime(detail); });
    tabs.appendChild(button);
  });

  const selected = entries[state.runtimeIndex] || entries[0];
  if (selected.type === "test") {
    const log = selected.data.log || {};
    const exitCode = selected.data.exit_code ?? "unknown";
    const duration = formatRuntimeDuration(selected.data.duration_ms);
    const command = selected.data.command || "Command unknown";
    const logText = log.content || (log.missing ? "Missing test log" : "");
    content.innerHTML = `
      ${runtimeMetaHtml(["test", `exit ${exitCode}`, duration])}
      ${runtimeDetailRow("command", command)}
      ${runtimeDetailRow("log path", log.path || selected.label || "")}
      ${runtimeLogSection("runtime-log-main", "log", logText, log)}`;
    return;
  }
  const agent = selected.data;
  const stdout = agent.stdout || {};
  const stderr = agent.stderr || {};
  const agentRunning = isRunning && (agent.exit_code == null);
  const liveTag = agentRunning ? '<span class="runtime-live"><span class="spinner"></span>live</span>' : "";
  const stdoutText = stdout.content || (stdout.missing ? "Missing stdout log" : (agentRunning ? "Waiting for output…" : ""));
  const stderrText = stderr.content || (stderr.missing ? "Missing stderr log" : "");
  const stderrHtml = stderrText ? runtimeLogSection("runtime-log-stderr", "stderr", stderrText, stderr) : "";
  content.innerHTML = `
    ${runtimeMetaHtml([agent.runtime || "runtime", `exit ${agent.exit_code ?? "-"}`, formatRuntimeDuration(agent.duration_ms)])}
    ${liveTag}
    ${runtimeDetailRow("command", agent.command || "manual")}
    ${runtimeDetailRow("stdout path", stdout.path || "")}
    ${stderr.path ? runtimeDetailRow("stderr path", stderr.path) : ""}
    ${runtimeLogSection("runtime-log-stdout", "stdout", stdoutText, stdout)}
    ${stderrHtml}`;
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
  $("runtimeContent").addEventListener("click", async (event) => {
    const copyBtn = event.target.closest("button[data-copy]");
    if (copyBtn) {
      await copyText(copyBtn.dataset.copy || "");
      return;
    }
    const bottomBtn = event.target.closest("button[data-log-bottom]");
    if (bottomBtn) {
      const pre = document.getElementById(bottomBtn.dataset.logBottom);
      if (pre) pre.scrollTop = pre.scrollHeight;
      return;
    }
    const wrapBtn = event.target.closest("button[data-log-wrap]");
    if (wrapBtn) {
      const pre = document.getElementById(wrapBtn.dataset.logWrap);
      if (!pre) return;
      const wrapped = pre.classList.toggle("is-wrapped");
      wrapBtn.setAttribute("aria-pressed", wrapped ? "true" : "false");
    }
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

if ($("refreshBtn")) {
  wireEvents();
  startAutoRefresh();
  loadTasks(false).catch((error) => showBanner(error.message));
}

// ============================================================
// Chat module (independent from tasks)
// ============================================================

const chatState = {
  chats: [],
  selectedId: null,
  detail: null,
  busy: false,
  pollTimer: null,
  search: "",
  abortController: null,
};

const CHAT_REFRESH_MS = 4000;

function chatShowBanner(message) {
  const banner = $("chatBanner");
  if (!message) {
    banner.classList.add("hidden");
    banner.textContent = "";
    return;
  }
  banner.textContent = message;
  banner.classList.remove("hidden");
}

async function loadChats(keepSelection = true) {
  try {
    const data = await apiFetch("/api/chats");
    chatState.chats = data.chats || [];
    // Only fall back to chats[0] when explicitly told to drop selection,
    // or when nothing is selected. Do NOT clobber a non-null selectedId
    // that's missing from the list — a freshly-created chat may be in
    // flight, or a stale polled response may have arrived after a newer
    // create. The next poll will reconcile.
    if (!keepSelection || !chatState.selectedId) {
      chatState.selectedId = chatState.chats[0]?.chat_id || null;
    }
    renderChatList();
    if (chatState.selectedId && !chatState.detail) {
      await loadChatDetail(chatState.selectedId);
    } else {
      renderChatDetail();
    }
  } catch (error) {
    chatShowBanner(error.message);
  }
}

function renderChatList() {
  const search = ($("chatSearchInput").value || "").toLowerCase().trim();
  const list = $("chatList");
  list.innerHTML = "";
  const filtered = chatState.chats.filter((c) => {
    if (!search) return true;
    const text = `${c.chat_id} ${c.title || ""} ${c.preview || ""}`.toLowerCase();
    return text.includes(search);
  });
  if (!filtered.length) {
    list.innerHTML = '<div class="task-sub">No chats yet. Click "New chat" to start one.</div>';
    return;
  }
  for (const chat of filtered) {
    const button = document.createElement("button");
    button.className = `task-row ${chat.chat_id === chatState.selectedId ? "active" : ""}`;
    const statusBadge = chat.status && chat.status !== "idle"
      ? `<span class="badge status-${escapeHtml(chat.status)}">${escapeHtml(chat.status)}</span>`
      : "";
    const isError = chat.status === "error" || chat.error;
    const inlineDelete = isError
      ? `<span class="row-delete" data-delete="${escapeHtml(chat.chat_id)}" title="Delete this chat">×</span>`
      : "";
    button.innerHTML = `
      <div class="task-row-top">
        <span class="task-title">${escapeHtml(chat.title || chat.chat_id)}</span>
        ${statusBadge}
        ${inlineDelete}
      </div>
      <div class="task-sub">
        <span>${escapeHtml(chat.runtime || "?")}</span>
        <span>${chat.message_count || 0} msgs</span>
        <span>${escapeHtml(chat.updated_at || "")}</span>
      </div>
      <div class="task-sub chat-preview">${escapeHtml(chat.preview || "")}</div>`;
    button.addEventListener("click", async (e) => {
      const del = e.target.closest("[data-delete]");
      if (del) {
        e.preventDefault();
        e.stopPropagation();
        const id = del.dataset.delete;
        if (!confirm("Delete this chat permanently?")) return;
        try {
          await apiFetch(`/api/chats/${encodeURIComponent(id)}`, { method: "DELETE" });
          if (chatState.selectedId === id) {
            chatState.selectedId = null;
            chatState.detail = null;
          }
          await loadChats(true);
          renderChatDetail();
        } catch (error) {
          chatShowBanner(error.message);
        }
        return;
      }
      selectChat(chat.chat_id);
    });
    list.appendChild(button);
  }
}

async function selectChat(chatId) {
  chatState.selectedId = chatId;
  renderChatList();
  await loadChatDetail(chatId);
}

async function loadChatDetail(chatId) {
  try {
    chatState.detail = await apiFetch(`/api/chats/${encodeURIComponent(chatId)}`);
    renderChatDetail();
    chatShowBanner(null);
  } catch (error) {
    chatShowBanner(error.message);
  }
}

function renderChatDetail() {
  const empty = $("chatEmpty");
  const composer = $("chatComposer");
  const messages = $("chatMessages");
  const runtimeSelect = $("chatRuntimeSelect");
  const renameBtn = $("chatRenameBtn");
  const deleteBtn = $("chatDeleteBtn");
  const compactBtn = $("chatCompactBtn");

  if (!chatState.detail) {
    $("chatIdLabel").textContent = "No chat selected";
    $("chatTitleHeader").textContent = "Select a chat";
    $("chatMeta").textContent = "";
    messages.innerHTML = "";
    composer.classList.add("hidden");
    empty.classList.remove("hidden");
    runtimeSelect.hidden = true;
    renameBtn.hidden = true;
    deleteBtn.hidden = true;
    compactBtn.hidden = true;
    return;
  }

  const s = chatState.detail.state;
  $("chatIdLabel").textContent = s.chat_id;
  $("chatTitleHeader").textContent = s.title || s.chat_id;
  $("chatMeta").innerHTML = `
    <span>runtime: ${escapeHtml(s.runtime || "?")}</span>
    <span>messages: ${(s.messages || []).length}</span>
    <span>status: ${escapeHtml(s.status || "idle")}</span>
    ${s.working_dir ? `<span>cwd: ${escapeHtml(s.working_dir)}</span>` : ""}`;

  // Runtime selector
  runtimeSelect.hidden = false;
  renameBtn.hidden = false;
  deleteBtn.hidden = false;
  compactBtn.hidden = false;
  compactBtn.disabled = !(s.messages || []).length || s.status === "streaming" || chatState.compacting;
  compactBtn.textContent = chatState.compacting ? "Compacting…" : "Compact";
  const available = chatState.detail.available_runtimes || [];
  runtimeSelect.innerHTML = available.map(
    (rt) => `<option value="${escapeHtml(rt)}" ${rt === s.runtime ? "selected" : ""}>${escapeHtml(rt)}</option>`
  ).join("");

  // Messages
  empty.classList.add("hidden");
  composer.classList.remove("hidden");
  messages.innerHTML = "";
  const isStreaming = s.status === "streaming";
  const msgs = s.messages || [];
  const compactCut = s.compact_up_to_message_id || null;
  const compactSummary = s.compact_summary || "";
  for (let mi = 0; mi < msgs.length; mi++) {
    const msg = msgs[mi];
    const wrap = document.createElement("div");
    wrap.className = `chat-msg chat-msg-${msg.role}`;
    const meta = msg.meta || {};
    const metaParts = [];
    if (meta.duration_ms) metaParts.push(`${Math.round(meta.duration_ms / 100) / 10}s`);
    if (meta.cancelled) metaParts.push('<span class="chat-msg-cancelled">cancelled</span>');
    const metaLine = metaParts.length ? `<span class="task-sub">${metaParts.join(" · ")}</span>` : "";
    const roleLabel = msg.role === "assistant" && meta.runtime ? meta.runtime : msg.role;
    wrap.innerHTML = `
      <div class="chat-msg-head">
        <span class="chat-msg-role">${escapeHtml(roleLabel)}</span>
        <span class="task-sub">${escapeHtml(msg.ts || "")}</span>
        ${metaLine}
      </div>
      <div class="chat-msg-body"></div>
      <div class="chat-msg-actions"></div>`;
    const body = wrap.querySelector(".chat-msg-body");
    const isLast = mi === msgs.length - 1;
    const isLiveAssistant = isStreaming && isLast && msg.role === "assistant";
    if (msg.role === "assistant" && !isLiveAssistant) {
      // Render markdown + syntax highlight for completed assistant messages.
      body.classList.add("markdown-body");
      body.innerHTML = renderMarkdown(msg.content || "");
      highlightCodeBlocks(body);
    } else if (isLiveAssistant) {
      // Streaming bubble: plain text, with a typing indicator while empty.
      if (msg.content) {
        body.textContent = msg.content;
      } else {
        body.innerHTML = '<span class="typing-indicator"><span></span><span></span><span></span></span>';
      }
    } else {
      // User messages: plain text.
      body.textContent = msg.content || "";
    }
    const actions = wrap.querySelector(".chat-msg-actions");
    const copyBtn = document.createElement("button");
    copyBtn.textContent = "Copy";
    copyBtn.addEventListener("click", () => navigator.clipboard.writeText(msg.content || ""));
    actions.appendChild(copyBtn);
    if (msg.role === "user") {
      const retryBtn = document.createElement("button");
      retryBtn.textContent = "Retry";
      retryBtn.addEventListener("click", () => retryFromMessage(msg.id));
      actions.appendChild(retryBtn);
    }
    const delBtn = document.createElement("button");
    delBtn.className = "danger-link";
    delBtn.textContent = "Delete";
    delBtn.addEventListener("click", () => deleteMessage(msg.id));
    actions.appendChild(delBtn);
    messages.appendChild(wrap);
    if (compactCut && msg.id === compactCut) {
      const divider = document.createElement("div");
      divider.className = "chat-compact-divider";
      divider.innerHTML = `
        <div class="chat-compact-line">
          <span>— context compacted: runtime sees a summary of everything above —</span>
          <button type="button" class="chat-compact-toggle">View summary</button>
        </div>
        <pre class="chat-compact-summary hidden"></pre>`;
      divider.querySelector(".chat-compact-summary").textContent = compactSummary;
      const toggle = divider.querySelector(".chat-compact-toggle");
      const pre = divider.querySelector(".chat-compact-summary");
      toggle.addEventListener("click", () => {
        const hidden = pre.classList.toggle("hidden");
        toggle.textContent = hidden ? "View summary" : "Hide summary";
      });
      messages.appendChild(divider);
    }
  }
  messages.scrollTop = messages.scrollHeight;

  // Status hint + composer
  const hint = $("chatStatusHint");
  if (s.status === "streaming") {
    hint.textContent = "Waiting for runtime…";
  } else if (s.status === "error") {
    hint.textContent = s.last_error || "Last turn failed.";
  } else {
    hint.textContent = "";
  }
  $("chatSendBtn").disabled = chatState.busy ? false : (s.status === "streaming");
}

async function sendChatMessage() {
  if (!chatState.selectedId) return;
  if (chatState.busy) {
    // Stop button: abort the in-flight stream. Server will detect the
    // disconnect, kill the runtime subprocess, and persist a partial
    // assistant message marked cancelled.
    if (chatState.abortController) chatState.abortController.abort();
    return;
  }
  const input = $("chatInputBox");
  const content = input.value.trim();
  if (!content) return;
  chatState.busy = true;
  setSendButtonStop(true);
  input.value = "";

  const detail = chatState.detail;
  if (!detail?.state) {
    chatState.busy = false;
    setSendButtonStop(false);
    return;
  }
  const placeholderUser = { id: "tmp-user", role: "user", content, ts: "" };
  const placeholderAsst = { id: "tmp-asst", role: "assistant", content: "", ts: "", meta: { streaming: true } };
  detail.state.messages = [...(detail.state.messages || []), placeholderUser, placeholderAsst];
  detail.state.status = "streaming";
  renderChatDetail();

  const chatId = chatState.selectedId;
  const controller = new AbortController();
  chatState.abortController = controller;
  let buf = "";
  let assistantText = "";
  let gotError = null;
  let aborted = false;

  try {
    const response = await fetch(`/api/chats/${encodeURIComponent(chatId)}/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify({ content }),
      signal: controller.signal,
    });
    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const ev = parseSseEvent(raw);
        if (!ev) continue;
        if (ev.event === "chunk") {
          assistantText += ev.data.delta || "";
          updateStreamingMessage(assistantText);
        } else if (ev.event === "user_message") {
          const real = ev.data.message;
          if (real && detail.state.messages) {
            const tu = detail.state.messages.find((m) => m.id === "tmp-user");
            if (tu) { tu.id = real.id; tu.ts = real.ts; }
          }
        } else if (ev.event === "done") {
          chatState.detail = { ...chatState.detail, state: ev.data.state };
        } else if (ev.event === "error") {
          gotError = ev.data.message || "Stream error";
        }
      }
    }
  } catch (error) {
    if (error.name === "AbortError") {
      aborted = true;
    } else {
      gotError = error.message;
    }
  } finally {
    chatState.busy = false;
    chatState.abortController = null;
    setSendButtonStop(false);
    if (gotError) {
      chatShowBanner(gotError);
      await loadChatDetail(chatId);
    } else if (aborted) {
      // Refresh authoritative state: server saved a partial cancelled message.
      await loadChatDetail(chatId);
    } else {
      renderChatDetail();
    }
    loadChats(true);
  }
}

function setSendButtonStop(streaming) {
  const btn = $("chatSendBtn");
  if (streaming) {
    btn.textContent = "Stop";
    btn.classList.add("danger");
    btn.classList.remove("primary");
    btn.disabled = false;
  } else {
    btn.textContent = "Send";
    btn.classList.add("primary");
    btn.classList.remove("danger");
    btn.disabled = false;
  }
}

function parseSseEvent(raw) {
  let event = "message";
  const dataLines = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch (e) {
    return null;
  }
}

function updateStreamingMessage(text) {
  // Cheap in-place update of the placeholder assistant message body without
  // re-rendering the entire pane (avoids flicker and scroll jumps).
  const messages = $("chatMessages");
  const last = messages.querySelector(".chat-msg-assistant:last-of-type .chat-msg-body");
  if (last) {
    last.textContent = text;  // wipes the typing indicator on first chunk
    messages.scrollTop = messages.scrollHeight;
  }
  // Keep state in sync for any subsequent renderChatDetail()
  const d = chatState.detail?.state?.messages;
  if (d && d.length) {
    const lastMsg = d[d.length - 1];
    if (lastMsg.role === "assistant") lastMsg.content = text;
  }
}

async function retryFromMessage(messageId) {
  if (!chatState.selectedId) return;
  try {
    chatState.detail = await apiFetch(
      `/api/chats/${encodeURIComponent(chatState.selectedId)}/messages/${encodeURIComponent(messageId)}/retry`,
      { method: "POST", body: "{}" },
    );
    renderChatDetail();
    loadChats(true);
  } catch (error) {
    chatShowBanner(error.message);
  }
}

async function deleteMessage(messageId) {
  if (!chatState.selectedId) return;
  if (!confirm("Delete this message?")) return;
  try {
    chatState.detail = await apiFetch(
      `/api/chats/${encodeURIComponent(chatState.selectedId)}/messages/${encodeURIComponent(messageId)}`,
      { method: "DELETE" },
    );
    renderChatDetail();
  } catch (error) {
    chatShowBanner(error.message);
  }
}

async function openNewChatDialog() {
  // Populate runtime list from settings.
  try {
    const settings = await apiFetch("/api/settings");
    const runtimes = (settings.runtime?.runtimes || [])
      .filter((r) => r.status === "active" || r.status === "manual_fallback")
      .map((r) => r.name);
    const fallback = settings.runtime?.default_runtime ? [settings.runtime.default_runtime] : ["manual"];
    const options = (runtimes.length ? runtimes : fallback);
    $("newChatRuntimeSelect").innerHTML = options.map(
      (rt) => `<option value="${escapeHtml(rt)}">${escapeHtml(rt)}</option>`
    ).join("");
  } catch (error) {
    $("newChatRuntimeSelect").innerHTML = '<option value="manual">manual</option>';
  }
  $("newChatTitleInput").value = "";
  $("newChatWorkingDir").value = "";
  $("newChatSystemPrompt").value = "";
  $("newChatError").classList.add("hidden");
  $("newChatDialog").showModal();
}

async function createChat(event) {
  event.preventDefault();
  const payload = {
    title: $("newChatTitleInput").value.trim() || null,
    runtime: $("newChatRuntimeSelect").value,
    working_dir: $("newChatWorkingDir").value.trim() || null,
    system_prompt: $("newChatSystemPrompt").value || null,
  };
  try {
    const data = await apiFetch("/api/chats", { method: "POST", body: JSON.stringify(payload) });
    $("newChatDialog").close();
    chatState.selectedId = data.state.chat_id;
    chatState.detail = data;
    await loadChats(true);
    renderChatDetail();
  } catch (error) {
    const err = $("newChatError");
    err.textContent = error.message;
    err.classList.remove("hidden");
  }
}

async function changeChatRuntime() {
  if (!chatState.selectedId || !chatState.detail) return;
  const select = $("chatRuntimeSelect");
  const newRuntime = select.value;
  const s = chatState.detail.state;
  const oldRuntime = s.runtime;
  if (!newRuntime || newRuntime === oldRuntime) return;

  const hasMessages = (s.messages || []).length > 0;
  if (!hasMessages) {
    // Empty chat — just switch silently.
    try {
      chatState.detail = await apiFetch(
        `/api/chats/${encodeURIComponent(chatState.selectedId)}`,
        { method: "PATCH", body: JSON.stringify({ runtime: newRuntime }) },
      );
      renderChatDetail();
      loadChats(true);
    } catch (error) {
      chatShowBanner(error.message);
      select.value = oldRuntime;
    }
    return;
  }

  // Ask the user how to handle the switch.
  const dlg = $("switchRuntimeDialog");
  $("switchRuntimeMsg").textContent = `From "${oldRuntime}" to "${newRuntime}".`;
  const handler = async (event) => {
    const btn = event.target.closest(".switch-runtime-choice");
    if (!btn) return;
    event.preventDefault();
    dlg.removeEventListener("click", handler);
    const choice = btn.dataset.choice;
    dlg.close(choice);
    if (choice === "continue") {
      await switchRuntimeContinue(oldRuntime, newRuntime);
    } else if (choice === "new") {
      await switchRuntimeNewChat(newRuntime, s);
    }
  };
  dlg.addEventListener("click", handler);
  dlg.addEventListener("close", function onClose() {
    dlg.removeEventListener("close", onClose);
    dlg.removeEventListener("click", handler);
    if (dlg.returnValue === "cancel" || dlg.returnValue === "") {
      // User cancelled — revert dropdown to the actual chat runtime.
      select.value = oldRuntime;
    }
  }, { once: false });
  dlg.returnValue = "";
  dlg.showModal();
}

async function switchRuntimeContinue(oldRuntime, newRuntime) {
  // 1) Compact under the OLD runtime so it produces the summary.
  // 2) PATCH runtime — server clears session_id automatically.
  // 3) Next user message goes to the new runtime with the summary as context.
  chatState.compacting = true;
  chatState.busy = true;
  renderChatDetail();
  try {
    chatState.detail = await apiFetch(
      `/api/chats/${encodeURIComponent(chatState.selectedId)}/compact`,
      { method: "POST", body: JSON.stringify({ runtime: oldRuntime }) },
    );
    chatState.detail = await apiFetch(
      `/api/chats/${encodeURIComponent(chatState.selectedId)}`,
      { method: "PATCH", body: JSON.stringify({ runtime: newRuntime }) },
    );
    loadChats(true);
  } catch (error) {
    chatShowBanner(error.message);
    // Revert dropdown on failure.
    $("chatRuntimeSelect").value = oldRuntime;
  } finally {
    chatState.compacting = false;
    chatState.busy = false;
    renderChatDetail();
  }
}

async function switchRuntimeNewChat(newRuntime, sourceState) {
  // Create a fresh chat using the new runtime, inheriting title/cwd/system prompt.
  const baseTitle = (sourceState.title || "New chat").replace(/\s*\((cont|new)\).*$/, "");
  const payload = {
    title: `${baseTitle} (${newRuntime})`.slice(0, 120),
    runtime: newRuntime,
    working_dir: sourceState.working_dir || null,
    system_prompt: sourceState.system_prompt || null,
  };
  // Block the poll timer so a stale in-flight GET /api/chats can't clobber
  // selectedId after we point it at the new chat.
  chatState.busy = true;
  try {
    const data = await apiFetch("/api/chats", { method: "POST", body: JSON.stringify(payload) });
    chatState.selectedId = data.state.chat_id;
    chatState.detail = data;
    await loadChats(true);
    renderChatDetail();
    const input = $("chatInputBox");
    if (input) input.focus();
  } catch (error) {
    chatShowBanner(error.message);
    // Revert the original chat's dropdown to its true runtime.
    $("chatRuntimeSelect").value = sourceState.runtime;
  } finally {
    chatState.busy = false;
  }
}

function openRenameChat() {
  if (!chatState.detail?.state) return;
  $("renameChatInput").value = chatState.detail.state.title || "";
  $("renameChatDialog").showModal();
}

async function submitRenameChat(event) {
  event.preventDefault();
  const title = $("renameChatInput").value.trim();
  if (!title || !chatState.selectedId) return;
  try {
    chatState.detail = await apiFetch(
      `/api/chats/${encodeURIComponent(chatState.selectedId)}`,
      { method: "PATCH", body: JSON.stringify({ title }) },
    );
    $("renameChatDialog").close();
    renderChatDetail();
    loadChats(true);
  } catch (error) {
    chatShowBanner(error.message);
  }
}

async function deleteCurrentChat() {
  if (!chatState.selectedId) return;
  if (!confirm("Delete this chat permanently?")) return;
  try {
    await apiFetch(`/api/chats/${encodeURIComponent(chatState.selectedId)}`, { method: "DELETE" });
    chatState.selectedId = null;
    chatState.detail = null;
    await loadChats(false);
  } catch (error) {
    chatShowBanner(error.message);
  }
}

async function compactCurrentChat() {
  if (!chatState.selectedId || chatState.compacting) return;
  const s = chatState.detail?.state;
  if (!s || !(s.messages || []).length) return;
  if (!confirm(
    "Ask the current runtime to summarize the conversation and compact history?\n\n" +
    "Future turns will send the summary instead of the raw messages above. " +
    "All messages stay visible in this UI."
  )) return;
  chatState.compacting = true;
  renderChatDetail();
  try {
    chatState.detail = await apiFetch(
      `/api/chats/${encodeURIComponent(chatState.selectedId)}/compact`,
      { method: "POST", body: JSON.stringify({}) },
    );
  } catch (error) {
    chatShowBanner(error.message);
  } finally {
    chatState.compacting = false;
    renderChatDetail();
  }
}

function setMode(mode) {
  const tasksShell = $("tasksShell");
  const chatsShell = $("chatsShell");
  const buttons = $("modeSwitch").querySelectorAll("button");
  buttons.forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  if (mode === "chats") {
    tasksShell.classList.add("hidden");
    chatsShell.classList.remove("hidden");
    if (!chatState.pollTimer) {
      chatState.pollTimer = setInterval(() => {
        if (chatState.busy) return;
        loadChats(true);
      }, CHAT_REFRESH_MS);
    }
    loadChats(false);
  } else {
    chatsShell.classList.add("hidden");
    tasksShell.classList.remove("hidden");
    if (chatState.pollTimer) {
      clearInterval(chatState.pollTimer);
      chatState.pollTimer = null;
    }
  }
  try { location.hash = mode; } catch (e) {}
}

function wireChatEvents() {
  $("modeSwitch").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-mode]");
    if (btn) setMode(btn.dataset.mode);
  });
  $("newChatBtn").addEventListener("click", openNewChatDialog);
  $("newChatForm").addEventListener("submit", createChat);
  $("renameChatForm").addEventListener("submit", submitRenameChat);
  $("chatRefreshBtn").addEventListener("click", () => loadChats(true));
  $("chatSearchInput").addEventListener("input", renderChatList);
  $("chatSendBtn").addEventListener("click", sendChatMessage);
  $("chatInputBox").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage();
    }
  });
  $("chatRuntimeSelect").addEventListener("change", changeChatRuntime);
  $("chatRenameBtn").addEventListener("click", openRenameChat);
  $("chatDeleteBtn").addEventListener("click", deleteCurrentChat);
  $("chatCompactBtn").addEventListener("click", compactCurrentChat);
}

// ----------------------------------------------------------
// Minimal multi-language syntax highlighter for fenced code.
// Tokens: comment, string, keyword, number, function-call.
// Covers js/ts, py, json, html/xml, css, bash/sh, sql, go, rust, java.
// Not a full parser — just regex passes good enough for chat output.
// ----------------------------------------------------------

const HL_KEYWORDS = {
  js: "var let const function return if else for while do switch case break continue new delete typeof instanceof in of class extends super this null undefined true false async await yield throw try catch finally import export from default void as static get set",
  ts: "var let const function return if else for while do switch case break continue new delete typeof instanceof in of class extends super this null undefined true false async await yield throw try catch finally import export from default void as static get set interface type enum implements public private protected readonly abstract namespace declare keyof infer never unknown",
  py: "def class return if elif else for while break continue pass import from as with try except finally raise lambda yield global nonlocal in is not and or None True False async await match case",
  go: "func var const type struct interface map chan return if else for switch case break continue defer go select package import range nil true false",
  rust: "fn let mut const static struct enum impl trait pub use mod return if else for while loop match break continue self Self where as move ref true false None Some Ok Err",
  java: "public private protected class interface extends implements return if else for while do switch case break continue new this super null true false static final void int long double float boolean char String byte short throw throws try catch finally package import abstract synchronized",
  sql: "select from where group by order having limit offset insert into values update set delete create table drop alter index view as join inner left right outer on union all distinct case when then end and or not null is in like between",
  bash: "if then else elif fi for in do done while case esac function return local export readonly declare unset echo printf cd pwd ls true false",
  css: "important inherit initial unset auto none",
  json: "true false null",
};
HL_KEYWORDS.sh = HL_KEYWORDS.bash;
HL_KEYWORDS.shell = HL_KEYWORDS.bash;
HL_KEYWORDS.javascript = HL_KEYWORDS.js;
HL_KEYWORDS.jsx = HL_KEYWORDS.js;
HL_KEYWORDS.tsx = HL_KEYWORDS.ts;
HL_KEYWORDS.typescript = HL_KEYWORDS.ts;
HL_KEYWORDS.python = HL_KEYWORDS.py;
HL_KEYWORDS.golang = HL_KEYWORDS.go;

const HL_COMMENTS = {
  js: [["//", "\n"], ["/*", "*/"]],
  ts: [["//", "\n"], ["/*", "*/"]],
  go: [["//", "\n"], ["/*", "*/"]],
  rust: [["//", "\n"], ["/*", "*/"]],
  java: [["//", "\n"], ["/*", "*/"]],
  css: [["/*", "*/"]],
  py: [["#", "\n"]],
  bash: [["#", "\n"]],
  sql: [["--", "\n"], ["/*", "*/"]],
  html: [["<!--", "-->"]],
  xml: [["<!--", "-->"]],
};
HL_COMMENTS.sh = HL_COMMENTS.bash;
HL_COMMENTS.shell = HL_COMMENTS.bash;
HL_COMMENTS.javascript = HL_COMMENTS.js;
HL_COMMENTS.jsx = HL_COMMENTS.js;
HL_COMMENTS.tsx = HL_COMMENTS.ts;
HL_COMMENTS.typescript = HL_COMMENTS.ts;
HL_COMMENTS.python = HL_COMMENTS.py;
HL_COMMENTS.golang = HL_COMMENTS.go;

function highlightCode(src, lang) {
  const text = String(src);
  const keywords = (HL_KEYWORDS[lang] || "").split(/\s+/).filter(Boolean);
  const comments = HL_COMMENTS[lang] || [];
  // Tokenize by scanning. We emit a list of [type, text] segments and join
  // at the end. Tokens are: 'plain', 'comment', 'string', 'number', 'kw', 'fn'.
  const out = [];
  let i = 0;
  const n = text.length;

  const isWord = (c) => /[A-Za-z0-9_$]/.test(c);
  const startsWith = (s, off) => text.startsWith(s, off);

  while (i < n) {
    let matched = false;

    // Comments
    for (const [open, close] of comments) {
      if (startsWith(open, i)) {
        const end = close === "\n"
          ? (text.indexOf("\n", i + open.length) === -1 ? n : text.indexOf("\n", i + open.length))
          : (text.indexOf(close, i + open.length) === -1 ? n : text.indexOf(close, i + open.length) + close.length);
        out.push(["comment", text.slice(i, end)]);
        i = end;
        matched = true;
        break;
      }
    }
    if (matched) continue;

    // Strings: ", ', `
    const ch = text[i];
    if (ch === '"' || ch === "'" || ch === "`") {
      const quote = ch;
      let j = i + 1;
      while (j < n) {
        if (text[j] === "\\" && j + 1 < n) { j += 2; continue; }
        if (text[j] === quote) { j++; break; }
        j++;
      }
      out.push(["string", text.slice(i, j)]);
      i = j;
      continue;
    }

    // Numbers
    if (/[0-9]/.test(ch) && (i === 0 || !isWord(text[i - 1]))) {
      let j = i;
      while (j < n && /[0-9a-fA-FxXoObB._]/.test(text[j])) j++;
      out.push(["number", text.slice(i, j)]);
      i = j;
      continue;
    }

    // Identifiers / keywords / function calls
    if (isWord(ch) && !/[0-9]/.test(ch)) {
      let j = i;
      while (j < n && isWord(text[j])) j++;
      const word = text.slice(i, j);
      // peek next non-space for "(" => function call
      let k = j;
      while (k < n && /\s/.test(text[k])) k++;
      if (keywords.includes(word)) {
        out.push(["kw", word]);
      } else if (text[k] === "(") {
        out.push(["fn", word]);
      } else {
        out.push(["plain", word]);
      }
      i = j;
      continue;
    }

    // HTML/XML tags (very rough): <tag ...>
    if ((lang === "html" || lang === "xml") && ch === "<") {
      const close = text.indexOf(">", i);
      if (close !== -1) {
        out.push(["kw", text.slice(i, close + 1)]);
        i = close + 1;
        continue;
      }
    }

    out.push(["plain", ch]);
    i++;
  }

  return out.map(([type, t]) => {
    const esc = escapeHtml(t);
    if (type === "plain") return esc;
    return `<span class="hl-${type}">${esc}</span>`;
  }).join("");
}

function highlightCodeBlocks(root) {
  const blocks = root.querySelectorAll("pre.md-pre > code");
  for (const code of blocks) {
    const cls = code.className || "";
    const m = cls.match(/lang-([\w+-]+)/);
    const lang = m ? m[1].toLowerCase() : "";
    if (!lang) continue;
    // Header bar with language label + copy button
    const pre = code.parentElement;
    if (!pre.querySelector(".md-pre-head")) {
      const head = document.createElement("div");
      head.className = "md-pre-head";
      head.innerHTML = `<span class="md-pre-lang">${escapeHtml(lang)}</span>`;
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "md-pre-copy";
      copy.textContent = "Copy";
      copy.addEventListener("click", () => navigator.clipboard.writeText(code.textContent || ""));
      head.appendChild(copy);
      pre.insertBefore(head, code);
    }
    // Render syntax-highlighted HTML
    code.innerHTML = highlightCode(code.textContent || "", lang);
  }
}

if ($("modeSwitch")) {
  wireChatEvents();
  if (location.hash === "#chats") setMode("chats");
}
