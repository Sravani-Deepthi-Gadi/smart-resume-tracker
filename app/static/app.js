/* Smart Resume Tracker - front end.
 *
 * Deliberately dependency-free: one fetch helper, one state object, and a
 * render function per view. No build step, no framework, no bundler.
 */

"use strict";

/* ------------------------------------------------------------------ *
 * Constants
 * ------------------------------------------------------------------ */

const STATUSES = ["saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn"];
const CLOSED_STATUSES = ["rejected", "withdrawn"];
// The five progressive stages get the ordinal colour ramp; closed ones stay neutral.
const STAGE_RAMP = { saved: 1, applied: 2, screening: 3, interview: 4, offer: 5 };

const state = { resumes: [], jobs: [], applications: [], stats: null, runs: [] };

/* ------------------------------------------------------------------ *
 * Small helpers
 * ------------------------------------------------------------------ */

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

/** Escape text before it goes anywhere near innerHTML. */
function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function toast(message, isError = false) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.classList.add("show");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => node.classList.remove("show"), isError ? 5200 : 2800);
}

/** fetch wrapper that turns FastAPI error payloads into readable messages. */
async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (response.status === 204) return null;

  let payload = null;
  const text = await response.text();
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = { detail: text }; }
  }

  if (!response.ok) {
    throw new Error(detailToMessage(payload) || `${response.status} ${response.statusText}`);
  }
  return payload;
}

/** FastAPI returns either a string detail or a list of validation errors. */
function detailToMessage(payload) {
  const detail = payload && payload.detail;
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : "";
        return field ? `${field}: ${item.msg}` : item.msg;
      })
      .join("; ");
  }
  return JSON.stringify(detail);
}

function fmtDate(value) {
  if (!value) return "";
  const date = new Date(value.length <= 10 ? `${value}T00:00:00` : value);
  if (Number.isNaN(date.getTime())) return esc(value);
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function scoreBadge(score, verdict) {
  if (score === null || score === undefined) return '<span class="muted">-</span>';
  const band = verdict || (score >= 80 ? "strong" : score >= 65 ? "good" : score >= 45 ? "fair" : "weak");
  return `<span class="badge ${esc(band)}">${score.toFixed(0)}% ${esc(band)}</span>`;
}

function emptyState(message) {
  return `<p class="empty">${esc(message)}</p>`;
}

function chipList(items, className, title) {
  if (!items || !items.length) return "";
  const chips = items.map((item) => `<li class="chip ${className}">${esc(item)}</li>`).join("");
  return `${title ? `<p class="hint" style="margin:0.7rem 0 0">${esc(title)}</p>` : ""}<ul class="chips">${chips}</ul>`;
}

/** Fill a <select> with options, keeping the current value if it still exists. */
function fillSelect(select, items, { value, label, placeholder, keep = true }) {
  if (!select) return;
  const previous = keep ? select.value : "";
  const options = items.map((item) => {
    const optionValue = esc(item[value]);
    return `<option value="${optionValue}">${esc(label(item))}</option>`;
  });
  select.innerHTML = (placeholder ? `<option value="">${esc(placeholder)}</option>` : "") + options.join("");
  if (previous && Array.from(select.options).some((option) => option.value === previous)) {
    select.value = previous;
  }
}

/* ------------------------------------------------------------------ *
 * Data loading
 * ------------------------------------------------------------------ */

async function refresh(parts = ["stats", "resumes", "jobs", "applications"]) {
  const jobs = [];
  if (parts.includes("stats")) jobs.push(api("/api/stats").then((d) => (state.stats = d)));
  if (parts.includes("resumes")) jobs.push(api("/api/resumes").then((d) => (state.resumes = d)));
  if (parts.includes("jobs")) jobs.push(api("/api/jobs").then((d) => (state.jobs = d)));
  if (parts.includes("applications")) jobs.push(api("/api/applications").then((d) => (state.applications = d)));
  if (parts.includes("runs")) jobs.push(api("/api/screening/runs").then((d) => (state.runs = d)));

  try {
    await Promise.all(jobs);
  } catch (error) {
    toast(`Could not load data: ${error.message}`, true);
    return;
  }
  renderAll();
}

function renderAll() {
  renderDashboard();
  renderApplications();
  renderJobs();
  renderResumes();
  renderPickers();
  renderRuns();
}

/* ------------------------------------------------------------------ *
 * Dashboard
 * ------------------------------------------------------------------ */

function renderDashboard() {
  const stats = state.stats;
  if (!stats) return;

  const tiles = [
    { label: "Applications", value: stats.total_applications, sub: `${stats.active_applications} still live` },
    {
      label: "Average fit",
      value: stats.average_match_score === null ? "-" : `${stats.average_match_score}%`,
      sub: stats.best_match === null ? "no scores yet" : `best ${stats.best_match}%`,
    },
    {
      label: "Reached interview",
      value: stats.interview_rate === null ? "-" : `${stats.interview_rate}%`,
      sub: "of applications submitted",
    },
    { label: "Resumes", value: stats.resumes, sub: `${stats.jobs} jobs tracked` },
  ];
  $("#stat-tiles").innerHTML = tiles
    .map(
      (tile) => `<div class="tile">
        <div class="label">${esc(tile.label)}</div>
        <div class="value">${esc(tile.value)}</div>
        <div class="sub">${esc(tile.sub)}</div>
      </div>`
    )
    .join("");

  // Funnel: bar length is relative to the busiest stage, so an empty tracker
  // renders flat rather than dividing by zero.
  const funnel = stats.funnel || [];
  const peak = Math.max(1, ...funnel.map((stage) => stage.count));
  $("#funnel").innerHTML = funnel
    .map((stage) => {
      const ramp = STAGE_RAMP[stage.status] || "closed";
      const width = (stage.count / peak) * 100;
      return `<div class="funnel-row" title="${esc(stage.status)}: ${stage.count}">
        <span class="stage">${esc(stage.status)}</span>
        <div class="funnel-track">
          <div class="funnel-bar" data-stage="${esc(ramp)}" style="width:${width.toFixed(1)}%"></div>
        </div>
        <span class="count">${stage.count}</span>
      </div>`;
    })
    .join("");

  const closed = funnel.filter((s) => CLOSED_STATUSES.includes(s.status)).reduce((sum, s) => sum + s.count, 0);
  $("#funnel-note").textContent = closed
    ? `${closed} closed (rejected or withdrawn) shown in grey - they are not a stage you move through.`
    : "Counts are live applications by stage.";

  const missing = stats.top_missing_skills || [];
  $("#missing-skills").innerHTML = missing.length
    ? `<div class="table-wrap"><table>
        <thead><tr><th>Skill</th><th class="num">Jobs asking</th></tr></thead>
        <tbody>${missing
          .map((row) => `<tr><td>${esc(row.skill)}</td><td class="num">${row.count}</td></tr>`)
          .join("")}</tbody></table></div>`
    : emptyState("Nothing yet - add applications with a resume attached and gaps will surface here.");

  const upcoming = stats.upcoming || [];
  $("#upcoming").innerHTML = upcoming.length
    ? `<div class="table-wrap"><table>
        <thead><tr><th>Action</th><th>Role</th><th>Due</th></tr></thead>
        <tbody>${upcoming
          .map(
            (item) => `<tr>
              <td>${esc(item.next_action)}</td>
              <td>${esc(item.job_title)} <span class="muted">${esc(item.company)}</span></td>
              <td>${item.next_action_on ? fmtDate(item.next_action_on) : '<span class="muted">no date</span>'}
                  ${item.overdue ? '<span class="badge weak">! overdue</span>' : ""}</td>
            </tr>`
          )
          .join("")}</tbody></table></div>`
    : emptyState("No open next actions. Add one on an application to see it here.");
}

/* ------------------------------------------------------------------ *
 * Applications
 * ------------------------------------------------------------------ */

function renderApplications() {
  const filter = $("#app-filter").value;
  const rows = filter ? state.applications.filter((a) => a.status === filter) : state.applications;

  $("#applications-table").innerHTML = rows.length
    ? `<table>
        <thead><tr>
          <th>Role</th><th>Resume</th><th>Stage</th><th class="num">Fit</th>
          <th>Applied</th><th>Next action</th><th></th>
        </tr></thead>
        <tbody>${rows.map(applicationRow).join("")}</tbody>
      </table>`
    : emptyState(
        state.applications.length
          ? "No applications at that stage."
          : "Nothing tracked yet. Add a job, then track an application against it."
      );

  $$("#applications-table select[data-app-status]").forEach((select) => {
    select.addEventListener("change", async (event) => {
      const id = event.target.dataset.appStatus;
      try {
        await api(`/api/applications/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: event.target.value }),
        });
        toast("Stage updated.");
        await refresh(["stats", "applications"]);
      } catch (error) {
        toast(error.message, true);
      }
    });
  });

  $$("#applications-table button[data-delete-app]").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.dataset.deleteApp;
      if (!confirm("Stop tracking this application?")) return;
      try {
        await api(`/api/applications/${id}`, { method: "DELETE" });
        toast("Application removed.");
        await refresh(["stats", "applications"]);
      } catch (error) {
        toast(error.message, true);
      }
    });
  });
}

function applicationRow(application) {
  const options = STATUSES.map(
    (status) =>
      `<option value="${status}" ${status === application.status ? "selected" : ""}>${status}</option>`
  ).join("");
  return `<tr>
    <td><b>${esc(application.job_title)}</b><br><span class="muted">${esc(application.company)}${
      application.location ? ` &middot; ${esc(application.location)}` : ""
    }</span></td>
    <td>${application.resume_label ? esc(application.resume_label) : '<span class="muted">none</span>'}</td>
    <td><select data-app-status="${application.id}" aria-label="Stage">${options}</select></td>
    <td class="num">${scoreBadge(application.match_score)}</td>
    <td>${application.applied_on ? fmtDate(application.applied_on) : '<span class="muted">-</span>'}</td>
    <td>${
      application.next_action
        ? `${esc(application.next_action)}${
            application.next_action_on ? `<br><span class="muted">${fmtDate(application.next_action_on)}</span>` : ""
          }`
        : '<span class="muted">-</span>'
    }</td>
    <td class="row-actions"><button data-delete-app="${application.id}" title="Remove">&times;</button></td>
  </tr>`;
}

/* ------------------------------------------------------------------ *
 * Jobs
 * ------------------------------------------------------------------ */

function renderJobs() {
  $("#jobs-table").innerHTML = state.jobs.length
    ? `<table>
        <thead><tr><th>Title</th><th>Company</th><th>Location</th><th>Added</th><th></th></tr></thead>
        <tbody>${state.jobs
          .map(
            (job) => `<tr>
              <td><b>${esc(job.title)}</b>${
                job.source_url
                  ? ` <a href="${esc(job.source_url)}" target="_blank" rel="noopener noreferrer">link</a>`
                  : ""
              }</td>
              <td>${esc(job.company)}</td>
              <td>${job.location ? esc(job.location) : '<span class="muted">-</span>'}</td>
              <td>${fmtDate(job.created_at)}</td>
              <td class="row-actions"><button data-delete-job="${job.id}" title="Delete job">&times;</button></td>
            </tr>`
          )
          .join("")}</tbody>
      </table>`
    : emptyState("No jobs saved yet.");

  $$("#jobs-table button[data-delete-job]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!confirm("Delete this job and every application against it?")) return;
      try {
        await api(`/api/jobs/${button.dataset.deleteJob}`, { method: "DELETE" });
        toast("Job deleted.");
        await refresh();
      } catch (error) {
        toast(error.message, true);
      }
    });
  });
}

async function renderJobRequirements() {
  const jobId = $("#job-inspect").value;
  const target = $("#job-requirements");
  if (!jobId) {
    target.innerHTML = emptyState("Select a job.");
    return;
  }
  try {
    const job = await api(`/api/jobs/${jobId}`);
    const requirements = job.requirements || {};
    if (!requirements.skills || !Object.keys(requirements.skills).length) {
      target.innerHTML = emptyState("No skills recognised in that description - is the text complete?");
      return;
    }
    const years = requirements.required_years;
    target.innerHTML = `
      <p class="hint" style="margin:0">
        ${years ? `Asks for <b>${years} years</b> of experience.` : "No specific years of experience named."}
      </p>
      ${chipList(requirements.required_skills, "gap required", "Required")}
      ${chipList(requirements.preferred_skills, "chip", "Nice to have")}
      ${chipList((requirements.top_keywords || []).slice(0, 12), "chip", "Terms the posting leans on")}
    `;
  } catch (error) {
    target.innerHTML = emptyState(error.message);
  }
}

/* ------------------------------------------------------------------ *
 * Resumes
 * ------------------------------------------------------------------ */

function renderResumes() {
  $("#resumes-table").innerHTML = state.resumes.length
    ? `<table>
        <thead><tr><th>Label</th><th class="num">Skills</th><th class="num">Experience</th><th>Added</th><th></th></tr></thead>
        <tbody>${state.resumes
          .map(
            (resume) => `<tr>
              <td>
                <button class="row-link" data-open-resume="${resume.id}"
                        style="appearance:none;background:none;border:none;padding:0;font:inherit;color:var(--series-1);cursor:pointer;text-align:left">
                  <b>${esc(resume.label)}</b>
                </button>
                ${resume.is_primary ? ' <span class="badge good">primary</span>' : ""}
                ${resume.filename ? `<br><span class="muted">${esc(resume.filename)}</span>` : ""}
              </td>
              <td class="num">${resume.skills.length}</td>
              <td class="num">${resume.experience_years ? `${resume.experience_years} yr` : "-"}</td>
              <td>${fmtDate(resume.created_at)}</td>
              <td class="row-actions">
                ${resume.is_primary ? "" : `<button data-primary-resume="${resume.id}" title="Set as primary" aria-label="Set as primary resume">&#9733;</button>`}
                <button data-delete-resume="${resume.id}" title="Delete">&times;</button>
              </td>
            </tr>`
          )
          .join("")}</tbody>
      </table>`
    : emptyState("No resumes yet. Upload a file or paste your text above.");

  $$("#resumes-table button[data-open-resume]").forEach((button) =>
    button.addEventListener("click", () => showResume(button.dataset.openResume))
  );

  $$("#resumes-table button[data-primary-resume]").forEach((button) =>
    button.addEventListener("click", async () => {
      try {
        await api(`/api/resumes/${button.dataset.primaryResume}/primary`, { method: "POST" });
        toast("Primary resume updated.");
        await refresh(["resumes"]);
      } catch (error) {
        toast(error.message, true);
      }
    })
  );

  $$("#resumes-table button[data-delete-resume]").forEach((button) =>
    button.addEventListener("click", async () => {
      if (!confirm("Delete this resume version?")) return;
      try {
        await api(`/api/resumes/${button.dataset.deleteResume}`, { method: "DELETE" });
        $("#resume-detail-card").hidden = true;
        toast("Resume deleted.");
        await refresh();
      } catch (error) {
        toast(error.message, true);
      }
    })
  );
}

async function showResume(resumeId) {
  try {
    const resume = await api(`/api/resumes/${resumeId}`);
    const parsed = resume.parsed || {};
    const card = $("#resume-detail-card");
    card.hidden = false;
    $("#resume-detail-title").textContent = resume.label;

    const rows = [
      ["Name", parsed.name],
      ["Email", parsed.email],
      ["Phone", parsed.phone],
      ["LinkedIn", parsed.linkedin],
      ["GitHub", parsed.github],
      ["Degrees", (parsed.degrees || []).join(", ")],
      ["Experience", parsed.experience_years ? `${parsed.experience_years} years` : null],
      ["Words", parsed.word_count],
      ["Sections found", Object.keys(parsed.sections || {}).join(", ")],
    ];
    $("#resume-parsed").innerHTML = `<table><tbody>${rows
      .map(
        ([label, value]) =>
          `<tr><td style="width:40%;color:var(--text-muted)">${esc(label)}</td><td>${
            value ? esc(value) : '<span class="muted">not found</span>'
          }</td></tr>`
      )
      .join("")}</tbody></table>`;

    $("#resume-health").innerHTML = (resume.health || [])
      .map(
        (check) => `<li class="${check.passed ? "pass" : "fail"}">
          <span class="icon" aria-hidden="true">${check.passed ? "✓" : "⚠"}</span>
          <span><b>${esc(check.label)}</b> <span class="detail">${esc(check.detail)}</span></span>
        </li>`
      )
      .join("");

    $("#resume-skills").innerHTML = chipList(parsed.skills, "have", `Skills detected (${(parsed.skills || []).length})`);
    card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    toast(error.message, true);
  }
}

/* ------------------------------------------------------------------ *
 * Match
 * ------------------------------------------------------------------ */

function renderMatch(result) {
  const meters = [
    ["Skill coverage", result.skill_score, "share of the posting's skills your resume evidences"],
    ["Keyword similarity", result.keyword_score, "overlap of language across the whole documents"],
    ["Experience fit", result.experience_score, "your years against the years asked for"],
  ];

  $("#match-result").innerHTML = `
    <div class="card">
      <div class="score-head">
        <div class="score-big">${result.overall.toFixed(0)}<span>/100</span></div>
        ${scoreBadge(result.overall, result.verdict)}
        <div class="muted" style="font-size:0.85rem">
          ${
            result.required_years
              ? `Posting asks ${result.required_years} yr &middot; resume evidences ${result.candidate_years} yr`
              : "Posting names no required years"
          }
        </div>
      </div>
      <div class="meters">
        ${meters
          .map(([label, value, note]) =>
            value === null || value === undefined
              ? `<div class="meter"><div class="meter-head"><span>${esc(label)}</span>
                   <b class="muted">not scored</b></div>
                 <p class="hint" style="margin:0.1rem 0 0">Not enough in the posting to judge this, so its weight went to the other signals.</p></div>`
              : `<div class="meter">
                   <div class="meter-head"><span>${esc(label)} <span class="muted">- ${esc(note)}</span></span><b>${value.toFixed(0)}%</b></div>
                   <div class="meter-track"><div class="meter-fill" style="width:${Math.max(0, Math.min(100, value))}%"></div></div>
                 </div>`
          )
          .join("")}
      </div>
      <p class="funnel-note">Weights applied: ${Object.entries(result.weights_used || {})
        .map(([name, weight]) => `${esc(name)} ${Math.round(weight * 100)}%`)
        .join(" &middot; ")}</p>
    </div>

    <div class="grid two">
      <div class="card">
        <h3>Skills</h3>
        ${chipList(result.matched_skills, "have", `Matched (${result.matched_skills.length})`)}
        ${chipList(result.missing_required, "gap required", `Missing and required (${result.missing_required.length})`)}
        ${chipList(
          result.missing_skills.filter((skill) => !result.missing_required.includes(skill)),
          "gap",
          "Missing, not flagged as required"
        )}
        ${chipList(result.extra_skills, "chip", "On your resume, not asked for")}
      </div>
      <div class="card">
        <h3>What to change</h3>
        <ul class="notes">${(result.suggestions || []).map((note) => `<li>${esc(note)}</li>`).join("")}</ul>
      </div>
    </div>`;
  $("#match-result").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ------------------------------------------------------------------ *
 * Screening
 * ------------------------------------------------------------------ */

function renderScreeningRun(run) {
  $("#screening-result").innerHTML = `
    <div class="card">
      <h3>${esc(run.job_title || "Screening run")} <span class="muted">${esc(run.company || "")}</span></h3>
      <p class="hint">${run.candidate_count} candidate${run.candidate_count === 1 ? "" : "s"} ranked ${fmtDate(
    run.created_at
  )}.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th class="num">#</th><th>Candidate</th><th class="num">Score</th><th class="num">Exp</th><th>Matched</th><th>Gaps</th></tr></thead>
          <tbody>${run.candidates
            .map(
              (candidate) => `<tr>
                <td class="num">${candidate.rank}</td>
                <td><b>${esc(candidate.candidate_name || "Unnamed")}</b><br>
                    <span class="muted">${esc(candidate.filename)}${
                candidate.email ? ` &middot; ${esc(candidate.email)}` : ""
              }</span></td>
                <td class="num">${scoreBadge(candidate.score, candidate.verdict)}</td>
                <td class="num">${candidate.experience_years ? `${candidate.experience_years} yr` : "-"}</td>
                <td>${esc(candidate.matched_skills.slice(0, 6).join(", ")) || '<span class="muted">-</span>'}</td>
                <td class="muted">${esc(candidate.missing_skills.slice(0, 5).join(", ")) || "-"}</td>
              </tr>`
            )
            .join("")}</tbody>
        </table>
      </div>
    </div>`;
  $("#screening-result").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderRuns() {
  const target = $("#screening-runs");
  if (!target) return;
  target.innerHTML = state.runs.length
    ? `<table>
        <thead><tr><th>Job</th><th class="num">Candidates</th><th>Run</th><th></th></tr></thead>
        <tbody>${state.runs
          .map(
            (run) => `<tr>
              <td><button data-open-run="${run.id}"
                     style="appearance:none;background:none;border:none;padding:0;font:inherit;color:var(--series-1);cursor:pointer">
                     <b>${esc(run.job_title || "job")}</b></button>
                  <span class="muted">${esc(run.company || "")}</span></td>
              <td class="num">${run.candidate_count}</td>
              <td>${fmtDate(run.created_at)}</td>
              <td class="row-actions"><button data-delete-run="${run.id}" title="Delete run">&times;</button></td>
            </tr>`
          )
          .join("")}</tbody>
      </table>`
    : emptyState("No screening runs yet.");

  $$("#screening-runs button[data-open-run]").forEach((button) =>
    button.addEventListener("click", async () => {
      try {
        renderScreeningRun(await api(`/api/screening/runs/${button.dataset.openRun}`));
      } catch (error) {
        toast(error.message, true);
      }
    })
  );

  $$("#screening-runs button[data-delete-run]").forEach((button) =>
    button.addEventListener("click", async () => {
      if (!confirm("Delete this screening run?")) return;
      try {
        await api(`/api/screening/runs/${button.dataset.deleteRun}`, { method: "DELETE" });
        $("#screening-result").innerHTML = "";
        toast("Run deleted.");
        await refresh(["runs"]);
      } catch (error) {
        toast(error.message, true);
      }
    })
  );
}

/* ------------------------------------------------------------------ *
 * Pickers shared across views
 * ------------------------------------------------------------------ */

function renderPickers() {
  const jobLabel = (job) => `${job.title} - ${job.company}`;
  const resumeLabel = (resume) => `${resume.label}${resume.is_primary ? " (primary)" : ""}`;

  fillSelect($("#app-job"), state.jobs, { value: "id", label: jobLabel, placeholder: "Select a job" });
  fillSelect($("#app-resume"), state.resumes, { value: "id", label: resumeLabel, placeholder: "No resume yet" });
  fillSelect($("#match-job"), state.jobs, { value: "id", label: jobLabel, placeholder: "None - paste below" });
  fillSelect($("#match-resume"), state.resumes, { value: "id", label: resumeLabel, placeholder: "Select a resume" });
  fillSelect($("#screen-job"), state.jobs, { value: "id", label: jobLabel, placeholder: "Select a job" });
  fillSelect($("#job-inspect"), state.jobs, { value: "id", label: jobLabel, placeholder: "Select a job" });

  $("#application-form-hint").textContent = state.jobs.length
    ? ""
    : "Add a job first - an application needs one.";

  // Default the match and application pickers to the primary resume.
  const primary = state.resumes.find((resume) => resume.is_primary);
  for (const selector of ["#match-resume", "#app-resume"]) {
    const select = $(selector);
    if (select && !select.value && primary) select.value = String(primary.id);
  }
}

function fillStatusSelects() {
  const options = STATUSES.map((status) => `<option value="${status}">${status}</option>`).join("");
  $("#app-status").innerHTML = options;
  $("#app-filter").innerHTML = `<option value="">All stages</option>${options}`;
}

/* ------------------------------------------------------------------ *
 * Navigation and theme
 * ------------------------------------------------------------------ */

/** Render a view. The hash is the source of truth; this never writes to it. */
function showView(name) {
  $$(".view").forEach((view) => (view.hidden = view.id !== `view-${name}`));
  $$(".tab").forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.view === name)));
  if (name === "screening") refresh(["runs", "jobs"]);
}

/** The view named by the current hash, falling back to the dashboard. */
function viewFromHash() {
  const name = (location.hash || "#dashboard").slice(1);
  return $(`#view-${name}`) ? name : "dashboard";
}

/** Navigate by setting the hash, so back and forward move between views. */
function goToView(name) {
  if (viewFromHash() === name) {
    showView(name); // same hash fires no hashchange, so render directly
    return;
  }
  location.hash = `#${name}`;
}

function initTheme() {
  const stored = localStorage.getItem("srt-theme");
  if (stored === "light" || stored === "dark") {
    document.documentElement.dataset.theme = stored;
  }
  $("#theme-toggle").addEventListener("click", () => {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const current = document.documentElement.dataset.theme || (prefersDark ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("srt-theme", next);
    } catch {
      /* private browsing - the toggle still works for this visit */
    }
  });
}

/* ------------------------------------------------------------------ *
 * Form wiring
 * ------------------------------------------------------------------ */

/** Run an async submit handler with the button disabled and errors surfaced. */
function onSubmit(formSelector, handler) {
  const form = $(formSelector);
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type=submit]");
    const original = button ? button.textContent : "";
    if (button) {
      button.disabled = true;
      button.textContent = "Working...";
    }
    try {
      await handler(form);
    } catch (error) {
      toast(error.message, true);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
    }
  });
}

function wireForms() {
  onSubmit("#job-form", async (form) => {
    await api("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: $("#job-title").value.trim(),
        company: $("#job-company").value.trim(),
        location: $("#job-location").value.trim() || null,
        source_url: $("#job-url").value.trim() || null,
        description: $("#job-description").value,
      }),
    });
    form.reset();
    toast("Job saved.");
    await refresh();
  });

  onSubmit("#application-form", async (form) => {
    const jobId = $("#app-job").value;
    if (!jobId) throw new Error("Pick a job first.");
    const resumeId = $("#app-resume").value;
    await api("/api/applications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: Number(jobId),
        resume_id: resumeId ? Number(resumeId) : null,
        status: $("#app-status").value,
        applied_on: $("#app-applied").value || null,
        next_action: $("#app-next").value.trim() || null,
        next_action_on: $("#app-next-on").value || null,
        notes: $("#app-notes").value.trim() || null,
      }),
    });
    form.reset();
    fillStatusSelects();
    toast("Application tracked.");
    await refresh();
  });

  onSubmit("#resume-upload-form", async (form) => {
    const fileInput = $("#resume-file");
    if (!fileInput.files.length) throw new Error("Choose a file.");
    const body = new FormData();
    body.append("file", fileInput.files[0]);
    const label = $("#resume-upload-label").value.trim();
    if (label) body.append("label", label);
    body.append("is_primary", String($("#resume-upload-primary").checked));
    const resume = await api("/api/resumes/upload", { method: "POST", body });
    form.reset();
    toast(`Parsed ${resume.parsed.skills.length} skills from ${resume.label}.`);
    await refresh();
    showResume(resume.id);
  });

  onSubmit("#resume-paste-form", async (form) => {
    const resume = await api("/api/resumes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        label: $("#resume-paste-label").value.trim(),
        raw_text: $("#resume-paste-text").value,
      }),
    });
    form.reset();
    toast("Resume saved.");
    await refresh();
    showResume(resume.id);
  });

  onSubmit("#match-form", async () => {
    const resumeId = $("#match-resume").value;
    if (!resumeId) throw new Error("Pick a resume.");
    const pasted = $("#match-jd").value.trim();
    const jobId = $("#match-job").value;
    if (!pasted && !jobId) throw new Error("Pick a saved job or paste a description.");
    const payload = { resume_id: Number(resumeId) };
    // Pasted text wins, so you can score against something unsaved.
    if (pasted) payload.job_description = pasted;
    else payload.job_id = Number(jobId);
    renderMatch(await api("/api/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }));
  });

  onSubmit("#screening-form", async (form) => {
    const jobId = $("#screen-job").value;
    if (!jobId) throw new Error("Pick a job to screen against.");
    const files = $("#screen-files").files;
    if (!files.length) throw new Error("Choose at least one resume.");
    const body = new FormData();
    body.append("job_id", jobId);
    Array.from(files).forEach((file) => body.append("files", file));
    const run = await api("/api/screening/runs", { method: "POST", body });
    form.reset();
    toast(`Ranked ${run.candidate_count} candidates.`);
    renderScreeningRun(run);
    await refresh(["runs"]);
  });
}

/* ------------------------------------------------------------------ *
 * Boot
 * ------------------------------------------------------------------ */

function init() {
  initTheme();
  fillStatusSelects();
  wireForms();

  $$(".tab").forEach((tab) => tab.addEventListener("click", () => goToView(tab.dataset.view)));
  $("#app-filter").addEventListener("change", renderApplications);
  $("#job-inspect").addEventListener("change", renderJobRequirements);

  // Follow the hash on load and on back/forward, so views are linkable.
  window.addEventListener("hashchange", () => showView(viewFromHash()));
  showView(viewFromHash());

  refresh(["stats", "resumes", "jobs", "applications", "runs"]);
}

document.addEventListener("DOMContentLoaded", init);
