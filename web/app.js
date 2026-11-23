/**
 * YURI GAGARIN ALPHA - Enterprise Big-Data Search Platform Dashboard
 * Ultra-Responsive SPA Client v17.2
 */

let authToken = localStorage.getItem("yuri_auth_token") || "";
let activeJobId = null;
let ws = null;
let currentExplorerDirectory = "";
let cachedJobs = [];

// --- Centralized API Client with Auto-Auth Handling ---
async function apiFetch(url, options = {}) {
  const headers = options.headers || {};
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }
  options.headers = headers;

  const res = await fetch(url, options);
  if (res.status === 401) {
    console.warn("Session expired or unauthorized. Showing login modal.");
    localStorage.removeItem("yuri_auth_token");
    authToken = "";
    document.getElementById("authOverlay").style.display = "flex";
    throw new Error("Session expired. Please sign in again.");
  }
  return res;
}

// --- DOM Ready Initialization ---
document.addEventListener("DOMContentLoaded", () => {
  initAuth();
  initNavigation();
  initMobileDrawer();
  initSearchForm();
  initFileManager();
  initUrlDownloader();
  initJobHistoryFilters();
  initSettings();
  initJobControls();
  initServerLogActions();
});

// --- Authentication Subsystem ---
function initAuth() {
  const overlay = document.getElementById("authOverlay");
  const loginForm = document.getElementById("loginForm");
  const loginError = document.getElementById("loginError");
  const logoutBtn = document.getElementById("logoutBtn");

  if (authToken) {
    fetch("/api/auth/verify", {
      headers: { Authorization: `Bearer ${authToken}` },
    })
      .then((res) => {
        if (res.ok) {
          overlay.style.display = "none";
          onAuthenticated();
        } else if (res.status === 401) {
          localStorage.removeItem("yuri_auth_token");
          authToken = "";
          overlay.style.display = "flex";
        } else {
          overlay.style.display = "none";
          onAuthenticated();
        }
      })
      .catch(() => {
        overlay.style.display = "none";
        onAuthenticated();
      });
  } else {
    overlay.style.display = "flex";
  }

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const password = document.getElementById("adminPassword").value;
    loginError.style.display = "none";

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const data = await res.json();
      if (res.ok && data.token) {
        authToken = data.token;
        localStorage.setItem("yuri_auth_token", authToken);
        overlay.style.display = "none";
        onAuthenticated();
      } else {
        loginError.textContent = data.detail || "Authentication failed.";
        loginError.style.display = "block";
      }
    } catch (err) {
      loginError.textContent = "Unable to connect to server.";
      loginError.style.display = "block";
    }
  });

  logoutBtn.addEventListener("click", () => {
    localStorage.removeItem("yuri_auth_token");
    authToken = "";
    location.reload();
  });
}

function onAuthenticated() {
  connectWebSocket();
  loadSystemProfile();
  loadDirectory();
  loadJobHistory();
  loadSettings();
  restoreActiveJobMonitor();
}

async function restoreActiveJobMonitor() {
  try {
    const res = await apiFetch("/api/jobs/list");
    if (!res.ok) return;
    const data = await res.json();
    cachedJobs = data.jobs || [];
    const runningJob = cachedJobs.find((j) => j.status === "RUNNING");
    if (runningJob) {
      activeJobId = runningJob.job_id;
      document.getElementById("liveJobBadge").textContent = "RUNNING";
      document.getElementById("liveJobBadge").className = "status-pill status-running";
      document.getElementById("liveCurrentFile").textContent = `Scanning: ${runningJob.current_file || runningJob.target_path}`;
      document.getElementById("liveSpeed").textContent = `${(runningJob.speed_mb_s || 0).toFixed(2)} MB/s`;
      document.getElementById("liveMatches").textContent = (runningJob.total_matches || 0).toLocaleString();
      document.getElementById("liveProgressBar").style.width = `${Math.max(2, runningJob.progress_percent || 0)}%`;
      document.getElementById("btnPauseJob").disabled = false;
      document.getElementById("btnResumeJob").disabled = true;
      document.getElementById("btnStopJob").disabled = false;
    }
  } catch (e) {
    console.error("Error restoring active job:", e);
  }
}

// --- Navigation Tabs & Mobile Drawer ---
function initNavigation() {
  const navItems = document.querySelectorAll(".nav-item");
  navItems.forEach((item) => {
    item.addEventListener("click", () => {
      const tabId = item.getAttribute("data-tab");
      switchTab(tabId);
      closeMobileDrawer();
    });
  });
}

function initMobileDrawer() {
  const menuBtn = document.getElementById("mobileMenuBtn");
  const sidebar = document.getElementById("mainSidebar");
  const backdrop = document.getElementById("sidebarOverlay");

  if (menuBtn && sidebar && backdrop) {
    menuBtn.addEventListener("click", () => {
      sidebar.classList.toggle("open");
      backdrop.classList.toggle("active");
    });
    backdrop.addEventListener("click", closeMobileDrawer);
  }
}

function closeMobileDrawer() {
  const sidebar = document.getElementById("mainSidebar");
  const backdrop = document.getElementById("sidebarOverlay");
  if (sidebar) sidebar.classList.remove("open");
  if (backdrop) backdrop.classList.remove("active");
}

function switchTab(tabId) {
  document.querySelectorAll(".nav-item").forEach((i) => i.classList.remove("active"));
  document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));

  const targetNav = document.querySelector(`[data-tab="${tabId}"]`);
  const targetPane = document.getElementById(tabId);

  if (targetNav) targetNav.classList.add("active");
  if (targetPane) targetPane.classList.add("active");

  const pageTitle = document.getElementById("pageTitle");
  const titles = {
    dashboardTab: "Cluster Dashboard",
    searchStudioTab: "Search Studio",
    liveMonitorTab: "Live Monitor & Speedometer",
    fileManagerTab: "Files & Advanced Upload",
    historyTab: "Jobs & Checkpoints History",
    serverLogsTab: "Server Diagnostics (Rolling 48h)",
    settingsTab: "System Settings & Telegram",
  };
  pageTitle.textContent = titles[tabId] || "Workspace";

  if (tabId === "serverLogsTab") {
    loadServerLogs();
  } else if (tabId === "historyTab") {
    loadJobHistory();
  }
}

// --- WebSocket Telemetry & Logging ---
function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${location.host}/ws/telemetry`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    appendTerminal("[WebSocket] Connected to Yuri Gagarin Telemetry Stream.");
    setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 25000);
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.event === "hardware") {
        updateHardwareMeters(msg.data);
      } else if (msg.event === "progress") {
        updateJobProgress(msg.data);
      } else if (msg.event === "job_finished") {
        onJobFinished(msg.job);
      }
    } catch (e) {
      appendTerminal(event.data);
    }
  };

  ws.onclose = () => {
    setTimeout(connectWebSocket, 3000);
  };
}

const MAX_TERM_LINES = 200;
let termLines = [];

function appendTerminal(text) {
  const term = document.getElementById("terminalConsole");
  if (!term) return;
  const ts = new Date().toISOString().substring(11, 19);
  termLines.push(`[${ts}] ${text}`);
  if (termLines.length > MAX_TERM_LINES) {
    termLines = termLines.slice(-MAX_TERM_LINES);
  }
  term.textContent = termLines.join("\n");
  term.scrollTop = term.scrollHeight;
}

function updateHardwareMeters(data) {
  document.getElementById("meterCpu").textContent = `${data.cpu_load.toFixed(1)}%`;
  document.getElementById("meterRam").textContent = `${data.ram_percent.toFixed(1)}%`;
  if (data.ram_free_gb) {
    document.getElementById("meterDisk").textContent = `${data.ram_free_gb} GB Free`;
  }
}

let progressRafPending = false;
let pendingProgressData = null;

function updateJobProgress(data) {
  pendingProgressData = data;
  if (!progressRafPending) {
    progressRafPending = true;
    requestAnimationFrame(() => {
      progressRafPending = false;
      if (pendingProgressData) {
        renderJobProgress(pendingProgressData);
      }
    });
  }
}

function renderJobProgress(data) {
  activeJobId = data.job_id;
  const speed = data.speed_mb_s || 0;
  document.getElementById("liveSpeed").textContent = `${speed.toFixed(2)} MB/s`;
  document.getElementById("liveMatches").textContent = (data.total_matches || 0).toLocaleString();

  const eta = data.eta_seconds || 0;
  let etaStr = "Calculating...";
  if (eta > 0) {
    const hours = Math.floor(eta / 3600);
    const mins = Math.floor((eta % 3600) / 60);
    const secs = eta % 60;
    etaStr = hours > 0 ? `${hours}h ${mins}m ${secs}s` : `${mins}m ${secs}s`;
  } else if (speed > 0) {
    etaStr = "Finishing...";
  }
  document.getElementById("liveEta").textContent = etaStr;

  document.getElementById("liveJobBadge").textContent = "RUNNING";
  document.getElementById("liveJobBadge").className = "status-pill status-running";
  const pct = (data.percent !== undefined && data.percent !== null) ? Number(data.percent).toFixed(1) : "0.0";
  const curFile = data.file_current || "Analyzing...";
  const fileIdxStr = (data.file_index && data.total_files) ? `[${data.file_index}/${data.total_files}] ` : "";
  document.getElementById("liveCurrentFile").textContent = `Scanning: ${fileIdxStr}${curFile} (${pct}%)`;
  document.getElementById("liveProgressBar").style.width = `${Math.max(2, Math.min(100, data.percent || 0))}%`;

  document.getElementById("btnPauseJob").disabled = false;
  document.getElementById("btnResumeJob").disabled = true;
  document.getElementById("btnStopJob").disabled = false;
}

function onJobFinished(job) {
  appendTerminal(`[Search Completed] Job ${job.job_id} finished. Matches: ${job.total_matches}`);
  document.getElementById("liveJobBadge").textContent = job.status;
  document.getElementById("liveJobBadge").className = `status-pill status-${job.status.toLowerCase()}`;
  document.getElementById("liveProgressBar").style.width = job.status === "COMPLETED" ? "100%" : document.getElementById("liveProgressBar").style.width;
  document.getElementById("liveCurrentFile").textContent = job.status === "COMPLETED" ? "Mission Finished" : "Mission Stopped";
  document.getElementById("liveEta").textContent = "0s";
  document.getElementById("liveMatches").textContent = (job.total_matches || 0).toLocaleString();
  if (job.speed_mb_s) {
    document.getElementById("liveSpeed").textContent = `${job.speed_mb_s.toFixed(2)} MB/s`;
  }
  document.getElementById("btnPauseJob").disabled = true;
  document.getElementById("btnResumeJob").disabled = job.status === "PAUSED";
  document.getElementById("btnStopJob").disabled = true;
  loadJobHistory();
}

// --- Dashboard & System Profile ---
async function loadSystemProfile() {
  try {
    const res = await apiFetch("/api/system/profile");
    if (!res.ok) return;
    const p = await res.json();
    document.getElementById("sysPlatform").textContent = p.platform.toUpperCase();
    document.getElementById("sysCpuCount").textContent = `${p.cpu_count} Cores`;
    document.getElementById("sysTotalRam").textContent = `${p.total_ram_gb} GB`;
    document.getElementById("sysAvailRam").textContent = `${p.available_ram_gb} GB`;
    document.getElementById("sysWorkers").textContent = `${p.recommended_workers} Workers`;
    document.getElementById("dashChunkSize").textContent = `${p.recommended_chunk_mb} MB`;
    document.getElementById("dashKernelOpt").textContent = p.posix_fadvise ? "Active (posix_fadvise)" : "Standard";
  } catch (e) {
    console.error(e);
  }
}

// --- Search Studio Form ---
function initSearchForm() {
  const form = document.getElementById("searchForm");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const target_path = document.getElementById("searchTarget").value.trim();
    const engine_type = document.getElementById("searchEngineSelect").value;
    const is_regex = engine_type === "regex";
    const patterns = document.getElementById("searchPatterns").value;
    const output_format = document.getElementById("optOutputFormat").value;
    const case_sensitive = document.getElementById("optCaseSensitive").checked;
    const extract_only = document.getElementById("optExtractOnly").checked || output_format === "extract_only";
    const recursive = document.getElementById("optRecursive").checked;
    const output_file = document.getElementById("searchOutput").value.trim();
    const compress_algo = document.getElementById("searchCompress").value;

    const rg_threads = parseInt(document.getElementById("rgThreadsSelect").value) || 0;
    const rg_mmap = document.getElementById("rgMmapCheck").checked;
    const rg_pcre2 = is_regex && document.getElementById("rgPcre2Check").checked;
    const rg_smart_case = document.getElementById("rgSmartCaseCheck").checked;

    appendTerminal(`[Search] Launching scan on: ${target_path} (Engine: ${engine_type.toUpperCase()}, Format: ${output_format})...`);

    // Reset Live Monitor UI
    document.getElementById("liveJobBadge").textContent = "STARTING";
    document.getElementById("liveJobBadge").className = "status-pill status-running";
    document.getElementById("liveCurrentFile").textContent = `Preparing target: ${target_path}`;
    document.getElementById("liveSpeed").textContent = "Calculating...";
    document.getElementById("liveMatches").textContent = "0";
    document.getElementById("liveProgressBar").style.width = "2%";
    document.getElementById("btnPauseJob").disabled = false;
    document.getElementById("btnResumeJob").disabled = true;
    document.getElementById("btnStopJob").disabled = false;

    switchTab("liveMonitorTab");

    try {
      const res = await apiFetch("/api/jobs/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_path,
          patterns,
          engine_type,
          is_regex,
          case_sensitive,
          output_format,
          extract_only,
          recursive,
          output_file,
          compress_algo,
          rg_threads,
          rg_mmap,
          rg_pcre2,
          rg_smart_case,
        }),
      });

      const data = await res.json();
      if (res.ok && data.success) {
        activeJobId = data.job.job_id;
        appendTerminal(`[Job Started] Job ID: ${activeJobId}`);
        loadJobHistory();
      } else {
        alert(data.detail || "Search launch failed.");
      }
    } catch (err) {
      alert("Error starting search: " + err.message);
    }
  });
}

// --- Job Control Buttons ---
function initJobControls() {
  document.getElementById("btnPauseJob").addEventListener("click", async () => {
    if (!activeJobId) return;
    await apiFetch(`/api/jobs/${activeJobId}/pause`, { method: "POST" });
    document.getElementById("btnPauseJob").disabled = true;
    document.getElementById("btnResumeJob").disabled = false;
  });

  document.getElementById("btnResumeJob").addEventListener("click", async () => {
    if (!activeJobId) return;
    await apiFetch(`/api/jobs/${activeJobId}/resume`, { method: "POST" });
    document.getElementById("btnPauseJob").disabled = false;
    document.getElementById("btnResumeJob").disabled = true;
  });

  document.getElementById("btnStopJob").addEventListener("click", async () => {
    if (!activeJobId) return;
    if (confirm("Are you sure you want to stop this search mission?")) {
      await apiFetch(`/api/jobs/${activeJobId}/stop`, { method: "POST" });
    }
  });
}

// --- Jobs & Checkpoints History with Search and Deletion ---
function initJobHistoryFilters() {
  const searchInput = document.getElementById("historySearchInput");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      renderJobHistoryTable(searchInput.value.trim().toLowerCase());
    });
  }
}

async function loadJobHistory() {
  try {
    const res = await apiFetch("/api/jobs/list");
    if (!res.ok) return;
    const data = await res.json();
    cachedJobs = data.jobs || [];
    renderJobHistoryTable();
  } catch (e) {
    console.error(e);
  }
}

function renderJobHistoryTable(filterQuery = "") {
  const tbody = document.getElementById("historyTableBody");
  tbody.innerHTML = "";

  const filtered = filterQuery
    ? cachedJobs.filter((j) => {
        return (
          (j.job_id && j.job_id.toLowerCase().includes(filterQuery)) ||
          (j.target_path && j.target_path.toLowerCase().includes(filterQuery)) ||
          (j.output_file && j.output_file.toLowerCase().includes(filterQuery)) ||
          (j.status && j.status.toLowerCase().includes(filterQuery))
        );
      })
    : cachedJobs;

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-dim">No job records matching filter.</td></tr>`;
    return;
  }

  filtered.forEach((j) => {
    const tr = document.createElement("tr");
    const startedDate = j.started_at ? new Date(j.started_at * 1000).toLocaleString() : (j.created_at ? new Date(j.created_at * 1000).toLocaleString() : "--");
    const outFileName = j.output_file ? j.output_file.split(/[\/\\]/).pop() : "--";

    tr.innerHTML = `
      <td class="font-mono" style="font-weight: 700;">${j.job_id}</td>
      <td class="font-mono font-sm text-truncate" title="${j.target_path}">${j.target_path.length > 25 ? j.target_path.slice(0, 12) + "..." + j.target_path.slice(-12) : j.target_path}</td>
      <td class="font-mono font-sm text-cyan" title="${j.output_file}">${outFileName}</td>
      <td class="font-sm text-muted">${startedDate}</td>
      <td><span class="status-pill status-${j.status.toLowerCase()}">${j.status}</span></td>
      <td class="font-mono">${j.total_matches.toLocaleString()}</td>
      <td class="font-mono">${j.progress_percent}%</td>
      <td class="text-right">
        <div style="display: flex; gap: 6px; justify-content: flex-end;">
          ${j.status === "PAUSED" ? `<button class="btn btn-secondary btn-sm" onclick="resumeJob('${j.job_id}')">Resume</button>` : ""}
          ${j.output_file ? `<a href="/api/results/download?file_path=${encodeURIComponent(j.output_file)}&token=${encodeURIComponent(authToken)}" class="btn btn-cyan btn-sm" download>Download</a>` : ""}
          <button class="btn btn-danger btn-sm" onclick="deleteJobRecord('${j.job_id}')" title="Delete record and output file">Delete</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

window.resumeJob = async (jobId) => {
  await apiFetch(`/api/jobs/${jobId}/resume`, { method: "POST" });
  switchTab("liveMonitorTab");
};

window.deleteJobRecord = async (jobId) => {
  if (confirm(`Permanently delete job ${jobId} and its generated result file from the server?`)) {
    try {
      const res = await apiFetch(`/api/jobs/${jobId}?delete_file=true`, { method: "DELETE" });
      if (res.ok) {
        appendTerminal(`[History] Job ${jobId} and its result file deleted.`);
        loadJobHistory();
      } else {
        alert("Failed to delete job.");
      }
    } catch (e) {
      alert("Error deleting job: " + e.message);
    }
  }
};

// --- Filesystem & Multi-File Chunked Upload with Destination Folder ---
function initFileManager() {
  const dropzone = document.getElementById("uploadDropzone");
  const fileInput = document.getElementById("fileUploadInput");

  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleBatchUpload(Array.from(e.dataTransfer.files));
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
      handleBatchUpload(Array.from(fileInput.files));
      fileInput.value = "";
    }
  });
}

window.useCurrentExplorerPathAsUploadDir = () => {
  const targetDirInput = document.getElementById("uploadTargetDir");
  if (currentExplorerDirectory) {
    targetDirInput.value = currentExplorerDirectory;
  }
};

async function handleBatchUpload(files) {
  const targetDir = document.getElementById("uploadTargetDir").value.trim() || "uploads";
  const progressContainer = document.getElementById("uploadProgressContainer");
  const queueStatus = document.getElementById("uploadQueueStatus");
  progressContainer.style.display = "block";

  appendTerminal(`[Batch Upload] Starting queue of ${files.length} file(s) into: ${targetDir}`);

  for (let idx = 0; idx < files.length; idx++) {
    const file = files[idx];
    queueStatus.textContent = `Processing file ${idx + 1} of ${files.length}...`;
    await uploadSingleFileChunked(file, targetDir);
  }

  queueStatus.textContent = `All ${files.length} file(s) uploaded successfully!`;
  loadDirectory(currentExplorerDirectory);
}

async function uploadSingleFileChunked(file, targetDir) {
  const CHUNK_SIZE = 5 * 1024 * 1024; // 5 MB chunks
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
  const uploadId = `upload_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;

  const fileNameEl = document.getElementById("uploadFileName");
  const percentEl = document.getElementById("uploadPercent");
  const barEl = document.getElementById("uploadProgressBar");

  fileNameEl.textContent = `${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MB)`;
  percentEl.textContent = "0%";
  barEl.style.width = "0%";

  appendTerminal(`[Upload] Uploading ${file.name} (${totalChunks} chunks) to ${targetDir}...`);

  // Step 1: Init Upload
  const initRes = await apiFetch("/api/fs/upload/init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      upload_id: uploadId,
      filename: file.name,
      total_size: file.size,
      total_chunks: totalChunks,
      target_dir: targetDir,
    }),
  });

  if (!initRes.ok) {
    alert(`Failed to initialize upload for ${file.name}`);
    return;
  }

  // Step 2: Upload Chunks Sequentially
  for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const end = Math.min(file.size, start + CHUNK_SIZE);
    const chunkBlob = file.slice(start, end);

    const formData = new FormData();
    formData.append("upload_id", uploadId);
    formData.append("chunk_index", i.toString());
    formData.append("file", chunkBlob);

    const chunkRes = await fetch("/api/fs/upload/chunk", {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
      body: formData,
    });

    if (!chunkRes.ok) {
      alert(`Error uploading chunk ${i + 1}/${totalChunks} for ${file.name}`);
      return;
    }

    const pct = Math.round(((i + 1) / totalChunks) * 100);
    percentEl.textContent = `${pct}%`;
    barEl.style.width = `${pct}%`;
  }

  // Step 3: Finalize
  const finalRes = await apiFetch("/api/fs/upload/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ upload_id: uploadId }),
  });

  if (finalRes.ok) {
    appendTerminal(`[Upload Completed] Saved: ${file.name}`);
  }
}

// --- Remote URL Downloader ---
function initUrlDownloader() {
  const form = document.getElementById("urlDownloadForm");
  const statusBox = document.getElementById("urlDownloadStatus");
  const btn = document.getElementById("btnStartUrlDownload");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = document.getElementById("remoteDownloadUrl").value.trim();
    const target_dir = document.getElementById("remoteDownloadDir").value.trim() || "uploads";
    const filename = document.getElementById("remoteCustomFilename").value.trim();

    btn.disabled = true;
    btn.textContent = "Downloading Stream...";
    statusBox.style.display = "block";
    statusBox.innerHTML = `<span class="text-cyan">Connecting to remote server and streaming to disk: ${url}...</span>`;
    appendTerminal(`[URL Download] Fetching: ${url} into ${target_dir}...`);

    try {
      const res = await apiFetch("/api/fs/download-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, target_dir, filename }),
      });

      const data = await res.json();
      if (res.ok && data.success) {
        const r = data.result;
        statusBox.innerHTML = `
          <strong class="text-emerald">Download Completed Successfully!</strong><br>
          File: <span class="font-mono text-cyan">${r.filename}</span> (${(r.size_bytes / (1024 * 1024)).toFixed(2)} MB)<br>
          Speed: <span class="font-mono">${r.speed_mb_s} MB/s</span> in ${r.elapsed_seconds}s<br>
          Saved to: <span class="font-mono text-muted">${r.saved_path}</span>
        `;
        appendTerminal(`[URL Download Completed] ${r.filename} (${(r.size_bytes / (1024 * 1024)).toFixed(2)} MB @ ${r.speed_mb_s} MB/s)`);
        loadDirectory(currentExplorerDirectory);
        document.getElementById("remoteDownloadUrl").value = "";
      } else {
        statusBox.innerHTML = `<span class="text-rose">Error: ${data.detail || "Download failed"}</span>`;
      }
    } catch (err) {
      statusBox.innerHTML = `<span class="text-rose">Network error: ${err.message}</span>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "Start Remote Download";
    }
  });
}

// --- Filesystem Explorer ---
async function loadDirectory(path = "") {
  try {
    const url = path ? `/api/fs/browse?path=${encodeURIComponent(path)}` : "/api/fs/browse";
    const res = await apiFetch(url);
    if (!res.ok) return;

    const data = await res.json();
    currentExplorerDirectory = data.current_path;
    document.getElementById("fsCurrentPath").textContent = data.current_path;

    const tbody = document.getElementById("fsTableBody");
    tbody.innerHTML = "";

    if (data.parent_path) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="cursor: pointer; color: var(--accent-cyan); font-weight: 600;" onclick="loadDirectory('${data.parent_path.replace(/\\/g, "/")}')">.. (Parent Directory)</td>
        <td>Folder</td>
        <td>--</td>
        <td class="text-right">
          <button class="btn btn-secondary btn-sm" onclick="selectAsTarget('${data.parent_path.replace(/\\/g, "/")}')">Set Search Target</button>
        </td>
      `;
      tbody.appendChild(tr);
    }

    data.items.forEach((item) => {
      const tr = document.createElement("tr");
      const safePath = item.path.replace(/\\/g, "/");
      const sizeStr = item.is_dir ? "--" : `${(item.size_bytes / (1024 * 1024)).toFixed(2)} MB`;

      tr.innerHTML = `
        <td style="cursor: ${item.is_dir ? "pointer" : "default"}; color: ${item.is_dir ? "var(--accent-cyan)" : "var(--text-main)"}; font-weight: ${item.is_dir ? "600" : "400"};"
            ${item.is_dir ? `onclick="loadDirectory('${safePath}')"` : ""}>
          ${item.is_dir ? "&#128193; " : "&#128196; "} ${item.name}
        </td>
        <td>${item.is_dir ? "Directory" : "File"}</td>
        <td class="font-mono font-sm">${sizeStr}</td>
        <td class="text-right">
          <div style="display: flex; gap: 6px; justify-content: flex-end;">
            <button class="btn btn-secondary btn-sm" onclick="selectAsTarget('${safePath}')">Set Search Target</button>
            ${item.is_dir ? `<button class="btn btn-secondary btn-sm" onclick="selectAsUploadFolder('${safePath}')">Upload Here</button>` : ""}
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error(e);
  }
}

window.selectAsTarget = (path) => {
  document.getElementById("searchTarget").value = path;
  switchTab("searchStudioTab");
};

window.selectAsUploadFolder = (path) => {
  document.getElementById("uploadTargetDir").value = path;
  document.getElementById("remoteDownloadDir").value = path;
  alert(`Storage destination set to: ${path}`);
};

// --- Server Diagnostic Logs & Log Clearing ---
function initServerLogActions() {
  const btnRefreshLogs = document.getElementById("btnRefreshServerLogs");
  if (btnRefreshLogs) {
    btnRefreshLogs.addEventListener("click", loadServerLogs);
  }

  const linesSelect = document.getElementById("logLinesSelect");
  if (linesSelect) {
    linesSelect.addEventListener("change", loadServerLogs);
  }

  const btnClearLogs = document.getElementById("btnClearServerLogs");
  if (btnClearLogs) {
    btnClearLogs.addEventListener("click", async () => {
      if (confirm("Are you sure you want to permanently clear the server diagnostic log file?")) {
        try {
          const res = await apiFetch("/api/logs/clear", { method: "DELETE" });
          if (res.ok) {
            appendTerminal("[Server Logs] Audit logs cleared by administrator.");
            loadServerLogs();
          } else {
            alert("Failed to clear logs.");
          }
        } catch (e) {
          alert("Error clearing logs: " + e.message);
        }
      }
    });
  }
}

async function loadServerLogs() {
  const terminal = document.getElementById("serverLogTerminal");
  const linesCount = document.getElementById("logLinesSelect").value || 250;

  try {
    const res = await apiFetch(`/api/logs/recent?lines=${linesCount}`);
    if (!res.ok) return;
    const data = await res.json();
    terminal.textContent = data.logs.join("\n");
    terminal.scrollTop = terminal.scrollHeight;
  } catch (e) {
    terminal.textContent = `[Error loading server logs: ${e}]`;
  }
}

// --- System & Telegram Settings ---
function initSettings() {
  document.getElementById("telegramSettingsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const tg_enabled = document.getElementById("setTgEnabled").checked;
    const tg_token = document.getElementById("setTgToken").value;
    const tg_chat_id = document.getElementById("setTgChatId").value;
    const tg_chunk_mb = parseInt(document.getElementById("setTgChunkMb").value) || 45;
    const tg_send_file = document.getElementById("setTgSendFile").checked;

    const res = await apiFetch("/api/settings/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tg_enabled, tg_token, tg_chat_id, tg_chunk_mb, tg_send_file }),
    });
    if (res.ok) alert("Telegram configuration updated.");
  });

  document.getElementById("systemSettingsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const hardware_profile = document.getElementById("setHardwareProfile").value;
    const default_threads = parseInt(document.getElementById("setDefaultThreads").value) || 0;
    const max_ram_throttle_percent = parseFloat(document.getElementById("setRamCap").value) || 85.0;
    const default_upload_dir = document.getElementById("setDefaultUploadDir").value;
    const default_output_dir = document.getElementById("setDefaultOutputDir").value;

    const res = await apiFetch("/api/settings/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hardware_profile, default_threads, max_ram_throttle_percent, default_upload_dir, default_output_dir }),
    });
    if (res.ok) alert("System engine limits updated successfully.");
  });

  document.getElementById("btnTestTg").addEventListener("click", async () => {
    const res = await apiFetch("/api/telegram/test", { method: "POST" });
    const d = await res.json();
    if (d.success) {
      alert(`Telegram Bot Verified Successfully! Username: @${d.bot_username}`);
    } else {
      alert(`Telegram Verification Failed: ${d.error}`);
    }
  });

  document.getElementById("passwordSettingsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const new_password = document.getElementById("setNewPassword").value;
    const res = await apiFetch("/api/settings/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password }),
    });
    if (res.ok) {
      alert("Master admin password updated successfully!");
      document.getElementById("setNewPassword").value = "";
    }
  });
}

async function loadSettings() {
  try {
    const res = await apiFetch("/api/settings");
    if (!res.ok) return;
    const s = await res.json();
    if (s.hardware_profile) {
      document.getElementById("setHardwareProfile").value = s.hardware_profile;
    }
    if (s.default_threads !== undefined) {
      document.getElementById("setDefaultThreads").value = s.default_threads;
    }
    document.getElementById("setTgEnabled").checked = s.tg_enabled;
    document.getElementById("setTgToken").value = s.tg_token;
    document.getElementById("setTgChatId").value = s.tg_chat_id;
    document.getElementById("setTgChunkMb").value = s.tg_chunk_mb || 45;
    if (s.tg_send_file !== undefined) {
      document.getElementById("setTgSendFile").checked = s.tg_send_file;
    }
    document.getElementById("setRamCap").value = s.max_ram_throttle_percent;
    document.getElementById("setDefaultUploadDir").value = s.default_upload_dir || "uploads";
    document.getElementById("setDefaultOutputDir").value = s.default_output_dir || "output";
  } catch (e) {
    console.error(e);
  }
}
