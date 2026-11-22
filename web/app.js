/**
 * YURI GAGARIN ALPHA - Enterprise Web UI Dashboard Client
 * Complete Single Page Application (100% English)
 */

let authToken = localStorage.getItem("yuri_auth_token") || "";
let activeJobId = null;
let ws = null;

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
  initSearchForm();
  initFileManager();
  initSettings();
  initJobControls();
});

// --- Authentication Subsystem ---
function initAuth() {
  const overlay = document.getElementById("authOverlay");
  const loginForm = document.getElementById("loginForm");
  const loginError = document.getElementById("loginError");
  const logoutBtn = document.getElementById("logoutBtn");

  if (authToken) {
    // Validate token with backend
    fetch("/api/auth/verify", {
      headers: { Authorization: `Bearer ${authToken}` },
    })
      .then((res) => {
        if (res.ok) {
          overlay.style.display = "none";
          onAuthenticated();
        } else {
          localStorage.removeItem("yuri_auth_token");
          authToken = "";
          overlay.style.display = "flex";
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
}

// --- Navigation Tabs ---
function initNavigation() {
  const navItems = document.querySelectorAll(".nav-item");
  navItems.forEach((item) => {
    item.addEventListener("click", () => {
      const tabId = item.getAttribute("data-tab");
      switchTab(tabId);
    });
  });
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
    liveMonitorTab: "Live Monitor & Logs",
    fileManagerTab: "File Manager & Chunked Upload",
    historyTab: "Jobs & Checkpoint History",
    serverLogsTab: "Server Diagnostic Logs (48h)",
    settingsTab: "System Settings & Telegram",
  };
  pageTitle.textContent = titles[tabId] || "Workspace";

  if (tabId === "serverLogsTab") {
    loadServerLogs();
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

function appendTerminal(text) {
  const term = document.getElementById("terminalConsole");
  const ts = new Date().toISOString().substring(11, 19);
  term.textContent += `\n[${ts}] ${text}`;
  term.scrollTop = term.scrollHeight;
}

function updateHardwareMeters(data) {
  document.getElementById("meterCpu").textContent = `${data.cpu_load.toFixed(1)}%`;
  document.getElementById("meterRam").textContent = `${data.ram_percent.toFixed(1)}%`;
  if (data.ram_free_gb) {
    document.getElementById("meterDisk").textContent = `${data.ram_free_gb} GB RAM`;
  }
}

function updateJobProgress(data) {
  activeJobId = data.job_id;
  document.getElementById("liveSpeed").textContent = `${data.speed_mb_s.toFixed(2)} MB/s`;
  document.getElementById("liveMatches").textContent = data.total_matches.toLocaleString();

  const eta = data.eta_seconds;
  const etaStr = eta > 0 ? `${Math.floor(eta / 60)}m ${eta % 60}s` : "Calculating...";
  document.getElementById("liveEta").textContent = etaStr;

  document.getElementById("liveJobBadge").textContent = "RUNNING";
  document.getElementById("liveJobBadge").className = "status-pill status-running";
  document.getElementById("liveCurrentFile").textContent = `Scanning: ${data.file_current} (${data.percent}%)`;
  document.getElementById("liveProgressBar").style.width = `${Math.max(2, data.percent)}%`;

  document.getElementById("btnPauseJob").disabled = false;
  document.getElementById("btnResumeJob").disabled = true;
  document.getElementById("btnStopJob").disabled = false;
}

function onJobFinished(job) {
  appendTerminal(`[Search Completed] Job ${job.job_id} finished. Matches: ${job.total_matches}`);
  document.getElementById("liveJobBadge").textContent = job.status;
  document.getElementById("liveJobBadge").className = `status-pill status-${job.status.toLowerCase()}`;
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
    document.getElementById("sysCpuCount").textContent = p.cpu_count;
    document.getElementById("sysTotalRam").textContent = `${p.total_ram_gb} GB`;
    document.getElementById("sysAvailRam").textContent = `${p.available_ram_gb} GB`;
    document.getElementById("sysWorkers").textContent = p.recommended_workers;
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
    const is_regex = engine_type === "regex" || (engine_type === "ripgrep" && document.getElementById("rgPcre2Check").checked);
    const patterns = document.getElementById("searchPatterns").value;
    const output_format = document.getElementById("optOutputFormat").value;
    const case_sensitive = document.getElementById("optCaseSensitive").checked;
    const extract_only = document.getElementById("optExtractOnly").checked || output_format === "extract_only";
    const recursive = document.getElementById("optRecursive").checked;
    const output_file = document.getElementById("searchOutput").value.trim();
    const compress_algo = document.getElementById("searchCompress").value;

    const rg_threads = parseInt(document.getElementById("rgThreadsSelect").value) || 0;
    const rg_mmap = document.getElementById("rgMmapCheck").checked;
    const rg_pcre2 = document.getElementById("rgPcre2Check").checked;
    const rg_smart_case = document.getElementById("rgSmartCaseCheck").checked;

    appendTerminal(`[Search] Launching scan on: ${target_path} (Engine: ${engine_type.toUpperCase()}, Format: ${output_format})...`);
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
    await fetch(`/api/jobs/${activeJobId}/pause`, {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
    });
    document.getElementById("btnPauseJob").disabled = true;
    document.getElementById("btnResumeJob").disabled = false;
  });

  document.getElementById("btnResumeJob").addEventListener("click", async () => {
    if (!activeJobId) return;
    await fetch(`/api/jobs/${activeJobId}/resume`, {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
    });
    document.getElementById("btnPauseJob").disabled = false;
    document.getElementById("btnResumeJob").disabled = true;
  });

  document.getElementById("btnStopJob").addEventListener("click", async () => {
    if (!activeJobId) return;
    if (confirm("Are you sure you want to stop this search?")) {
      await fetch(`/api/jobs/${activeJobId}/stop`, {
        method: "POST",
        headers: { Authorization: `Bearer ${authToken}` },
      });
    }
  });
}

// --- Jobs & Checkpoints History ---
async function loadJobHistory() {
  try {
    const res = await apiFetch("/api/jobs/list");
    if (!res.ok) return;
    const data = await res.json();
    const tbody = document.getElementById("historyTableBody");
    tbody.innerHTML = "";

    if (!data.jobs || data.jobs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-dim);">No job records found.</td></tr>`;
      return;
    }

    data.jobs.forEach((j) => {
      const tr = document.createElement("tr");
      // Format time in client's local timezone
      const startedDate = j.started_at ? new Date(j.started_at * 1000).toLocaleString() : (j.created_at ? new Date(j.created_at * 1000).toLocaleString() : "--");
      const outFileName = j.output_file ? j.output_file.split(/[\/\\]/).pop() : "--";

      tr.innerHTML = `
        <td style="font-family: var(--font-mono); font-weight: 600;">${j.job_id}</td>
        <td style="font-family: var(--font-mono); font-size: 12px;" title="${j.target_path}">${j.target_path.length > 30 ? j.target_path.slice(0, 15) + "..." + j.target_path.slice(-15) : j.target_path}</td>
        <td style="font-family: var(--font-mono); font-size: 12px; color: var(--accent-cyan);">${outFileName}</td>
        <td style="font-size: 12.5px; color: var(--text-muted);">${startedDate}</td>
        <td><span class="status-pill status-${j.status.toLowerCase()}">${j.status}</span></td>
        <td style="font-family: var(--font-mono);">${j.total_matches.toLocaleString()}</td>
        <td style="font-family: var(--font-mono);">${j.progress_percent}%</td>
        <td>
          ${j.status === "PAUSED" ? `<button class="btn btn-secondary" style="padding: 2px 8px; font-size: 11.5px;" onclick="resumeJob('${j.job_id}')">Resume</button>` : ""}
          ${j.output_file ? `<a href="/api/results/download?file_path=${encodeURIComponent(j.output_file)}&token=${encodeURIComponent(authToken)}" class="btn btn-cyan" style="padding: 2px 8px; font-size: 11.5px; text-decoration: none;" download>Download</a>` : ""}
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error(e);
  }
}

window.resumeJob = async (jobId) => {
  await apiFetch(`/api/jobs/${jobId}/resume`, { method: "POST" });
  switchTab("liveMonitorTab");
};

// --- Filesystem & Resumable Chunked Upload ---
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
      handleChunkedUpload(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
      handleChunkedUpload(fileInput.files[0]);
    }
  });
}

async function handleChunkedUpload(file) {
  const CHUNK_SIZE = 5 * 1024 * 1024; // 5 MB chunks
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
  const uploadId = `upload_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;

  const progressContainer = document.getElementById("uploadProgressContainer");
  const fileNameEl = document.getElementById("uploadFileName");
  const percentEl = document.getElementById("uploadPercent");
  const barEl = document.getElementById("uploadProgressBar");

  progressContainer.style.display = "block";
  fileNameEl.textContent = `${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MB)`;
  percentEl.textContent = "0%";
  barEl.style.width = "0%";

  appendTerminal(`[Upload] Starting resumable stream for ${file.name} (${totalChunks} chunks)...`);

  // Step 1: Init Upload
  const initRes = await fetch("/api/fs/upload/init", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify({
      upload_id: uploadId,
      filename: file.name,
      total_size: file.size,
      total_chunks: totalChunks,
    }),
  });

  if (!initRes.ok) {
    alert("Upload initialization failed.");
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
      alert(`Error uploading chunk ${i + 1}/${totalChunks}`);
      return;
    }

    const pct = Math.round(((i + 1) / totalChunks) * 100);
    percentEl.textContent = `${pct}%`;
    barEl.style.width = `${pct}%`;
  }

  // Step 3: Finalize
  const finalRes = await fetch("/api/fs/upload/complete", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify({ upload_id: uploadId }),
  });

  if (finalRes.ok) {
    appendTerminal(`[Upload Completed] File saved on server: ${file.name}`);
    loadDirectory();
  }
}

async function loadDirectory(path = "") {
  try {
    const url = path ? `/api/fs/browse?path=${encodeURIComponent(path)}` : "/api/fs/browse";
    const res = await apiFetch(url);
    if (!res.ok) return;

    const data = await res.json();
    document.getElementById("fsCurrentPath").textContent = data.current_path;
    const tbody = document.getElementById("fsTableBody");
    tbody.innerHTML = "";

    if (data.parent_path) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="cursor: pointer; color: var(--accent-cyan);" onclick="loadDirectory('${data.parent_path.replace(/\\/g, "/")}')">.. (Parent Directory)</td>
        <td>Directory</td>
        <td>--</td>
        <td><button class="btn btn-secondary" style="padding: 2px 8px; font-size: 11px;" onclick="selectAsTarget('${data.parent_path.replace(/\\/g, "/")}')">Select</button></td>
      `;
      tbody.appendChild(tr);
    }

    data.items.forEach((item) => {
      const tr = document.createElement("tr");
      const safePath = item.path.replace(/\\/g, "/");
      const sizeStr = item.is_dir ? "--" : `${(item.size_bytes / (1024 * 1024)).toFixed(2)} MB`;

      tr.innerHTML = `
        <td style="cursor: ${item.is_dir ? "pointer" : "default"}; color: ${item.is_dir ? "var(--accent-cyan)" : "var(--text-main)"};"
            ${item.is_dir ? `onclick="loadDirectory('${safePath}')"` : ""}>
          ${item.name}
        </td>
        <td>${item.is_dir ? "Directory" : "File"}</td>
        <td style="font-family: var(--font-mono);">${sizeStr}</td>
        <td>
          <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 11px;" onclick="selectAsTarget('${safePath}')">Set Target</button>
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

// --- Server Diagnostic Logs (Last 48 Hours) ---
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

document.addEventListener("DOMContentLoaded", () => {
  const btnRefreshLogs = document.getElementById("btnRefreshServerLogs");
  if (btnRefreshLogs) {
    btnRefreshLogs.addEventListener("click", loadServerLogs);
  }
  const linesSelect = document.getElementById("logLinesSelect");
  if (linesSelect) {
    linesSelect.addEventListener("change", loadServerLogs);
  }
});
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
    const max_ram_throttle_percent = parseFloat(document.getElementById("setRamCap").value) || 85.0;
    const default_upload_dir = document.getElementById("setDefaultUploadDir").value;
    const default_output_dir = document.getElementById("setDefaultOutputDir").value;
    const default_threads = parseInt(document.getElementById("setDefaultThreads").value) || 0;

    const res = await apiFetch("/api/settings/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_ram_throttle_percent, default_upload_dir, default_output_dir, default_threads }),
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
