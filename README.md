<div align="center">
  <img src="assets/logo.svg" alt="YURI GAGARIN ALPHA" width="100%" style="max-width: 950px; border-radius: 12px;" />
  <br />
  <h2>Enterprise High-Performance Big-Data Search Platform & Admin Web UI</h2>
  <p>
    <b>Engineered to scan multi-hundred-gigabyte datasets (800+ GB across thousands of files) with zero server lockups, Linux Page Cache purging, hardware self-tuning, and ultra-high-throughput Rust SIMD acceleration (700+ MB/s).</b>
  </p>

  <p>
    <img src="https://img.shields.io/badge/version-17.1%20Enterprise-38BDF8?style=flat-square" alt="Version" />
    <img src="https://img.shields.io/badge/core-Ripgrep%20(Rust%20SIMD)%20%2B%20Aho--Corasick-10B981?style=flat-square" alt="Core Engines" />
    <img src="https://img.shields.io/badge/throughput-740%2B%20MB%2Fs-FF4500?style=flat-square" alt="Throughput" />
    <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Windows-6366F1?style=flat-square" alt="Platform" />
    <img src="https://img.shields.io/badge/license-MIT-F59E0B?style=flat-square" alt="License" />
  </p>
</div>

---

## 📑 Table of Contents
1. [Overview & Core Objectives](#-overview--core-objectives)
2. [Architectural Highlights & Innovations](#-architectural-highlights--innovations)
3. [Search Engines & Algorithmic Design](#-search-engines--algorithmic-design)
4. [Hardware Profiles & Scaling](#-hardware-profiles--scaling)
5. [Enterprise Web Management Dashboard](#-enterprise-web-management-dashboard)
6. [Resumable Chunked File Upload](#-resumable-chunked-file-upload)
7. [Telegram Bot Integration & Delivery](#-telegram-bot-integration--delivery)
8. [Quick Start Guide](#-quick-start-guide)
9. [CLI Worker Reference](#-cli-worker-reference)
10. [Production Linux Deployment (Systemd)](#-production-linux-deployment-systemd)
11. [48-Hour Diagnostic Logging](#-48-hour-diagnostic-logging)
12. [Automated Testing & Benchmarks](#-automated-testing--benchmarks)

---

## 🔭 Overview & Core Objectives

**YURIGAGARIN ALPHA** is a carrier-grade text search and data mining platform created specifically for processing massive logs, database dumps, credential combolists, and unstructured textual datasets exceeding hundreds of gigabytes (tested extensively on 800+ GB clusters).

### The Challenge of Big-Data Text Scanning
Standard tools (`grep`, `egrep`, naive Python scripts) fail catastrophically when applied to 100+ GB files:
* They allocate whole lines into memory, crashing with `Out Of Memory` (OOM) on minified files or continuous database dumps.
* They poll the disk aggressively, causing Linux kernel Page Cache thrashing which starves the host operating system of RAM.
* They freeze terminals and web servers on single-core or low-RAM VPS instances.

### The Yuri Gagarin Solution
Yuri Gagarin Alpha solves these problems through an isolated, file-by-file pipeline powered by Rust SIMD acceleration, kernel I/O prioritization (`nice 15`, `ionice -c 2 -n 7`), Linux `posix_fadvise(POSIX_FADV_DONTNEED)` cache purging, and persistent cryptographic session management.

---

## ⚡ Architectural Highlights & Innovations

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Web Browser (Full English Web UI)                     │
│   • Live Telemetry (Speedometer MB/s, ETA Timer, Real-time Matches Counter) │
│   • Directory Explorer & Resumable Multi-GB Chunked File Uploader          │
│   • Search Studio (Clean Line, Separate Header, Same-Line Prefix Format)    │
│   • 48-Hour Diagnostic Server Log Console with Auto-Refresh                 │
│   • Hardware Profiles (Eco VPS Safe, Balanced, Extreme Turbo Dedicated)    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ HTTPS / REST & WebSockets
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FastAPI Backend Service                           │
│  ┌───────────────────────┐  ┌───────────────────────┐  ┌──────────────────┐ │
│  │ Stateless HMAC Auth   │  │ Async Job Supervisor  │  │ Hardware Monitor │ │
│  │ (30-day persistence)  │  │ (File-by-File Queue)  │  │ (CPU/RAM/IO/Disk)│ │
│  └───────────────────────┘  └───────────────────────┘  └──────────────────┘ │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Spawns isolated process
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   Ultra-High-Throughput Search Kernel                       │
│                                                                             │
│  ┌─────────────────────────────────┐   ┌──────────────────────────────────┐ │
│  │     Ripgrep Native Rust Engine  │   │     Aho-Corasick SIMD Engine     │ │
│  │  (500-1000+ MB/s, AVX2/Teddy)   │   │  (Memory-bounded fallback O(N))  │ │
│  └─────────────────────────────────┘   └──────────────────────────────────┘ │
│                                      │                                      │
│  ┌───────────────────────────────────▼────────────────────────────────────┐ │
│  │ Linux I/O Isolation: nice(15) + ionice(class 2, prio 7)                │ │
│  │ Zero-OOM Cache Purge: posix_fadvise(POSIX_FADV_DONTNEED) per file      │ │
│  │ Binary Tolerance: --text (-a) guarantees corrupted lines never abort   │ │
│  │ Direct Kernel OS Redirection: Popen(stdout=out_f) zero Python overhead │ │
│  └───────────────────────────────────┬────────────────────────────────────┘ │
└──────────────────────────────────────┼──────────────────────────────────────┘
                                       ▼
                      ┌────────────────────────────────┐
                      │    Disk Storage & Telegram     │
                      │ (Multipart 45MB Bot Delivery)  │
                      └────────────────────────────────┘
```

---

## ⚙️ Search Engines & Algorithmic Design

### 1. Native Ripgrep (Rust SIMD) - Primary Engine
- Utilizes Intel AVX2/SSE2 vectorized byte matching (`memchr` and `Teddy` algorithms).
- Delivers raw disk read speeds exceeding **500 to 740+ MB/s** on NVMe / fast storage.
- **Native Directory Traversal**: Zero-Python directory discovery overhead; ripgrep recursively navigates directory hierarchies using lock-free parallel Rust threads.
- **Pure Fixed-Strings SIMD Fast-Path**: Literal keywords bypass PCRE2 completely, preventing regex interpreter overhead.
- **Binary Tolerance (`--text` / `-a`)**: Files with NUL bytes (`\x00`), corrupted encoding, emojis, or foreign Unicode characters are scanned to the exact last byte without premature abortion.
- **Anti-OOM & RAM Protection (<= 80%)**: Employs sequential streaming (`--no-mmap`) for large dumps (>50 MB) and directories, completely preventing Linux Page Cache thrashing and virtual memory exhaustion.
- **Anti-Freeze Web Telemetry**: Rate-limited WebSocket broadcaster (max 1 msg/s) and DOM terminal auto-pruning (max 200 lines) guarantee a silky-smooth Web UI under heavy search loads.

### 2. Output Formatting Modes
Configure how extracted matches appear in the output file:
* **`Clean Line Only` (Default)**: Pure extracted matched lines with zero metadata tags. Perfect for harvesting URLs, credentials, or target records:
  ```text
  https://chatgpt.com/gpts/editor
  ```
* **`Separate Line Header`**: Filename and line number on a separate header line above each hit:
  ```text
  [/root/Downloads/data.txt:48102]
  https://chatgpt.com/gpts/editor
  ```
* **`Same-Line Prefix`**: Filename and line number prefixed on the same line:
  ```text
  [/root/Downloads/data.txt:48102] https://chatgpt.com/gpts/editor
  ```
* **`Extract Keyword Only` (`-o`)**: Outputs only the matched keyword itself rather than the entire containing line.

---

## 🎛️ Hardware Profiles & Scaling

Yuri Gagarin Alpha dynamically scales between constrained cloud VPS instances and high-end dedicated enterprise servers:

| Profile | Target Environment | Concurrency | CPU Priority | I/O Priority | Kernel Cache & RAM |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Eco VPS Safe** | 1-2 vCPU, <= 2GB RAM | 50% Cores (1-2) | `nice 5` | Best-Effort | Sequential (RAM <= 80%) |
| **Balanced** | 4-8 Cores, 8-16GB RAM | 75% of Cores | `nice 2` | Best-Effort | Sequential Stream |
| **Extreme Turbo** | 16-64 Cores, 32GB+ RAM | 100% of Cores | `nice 0` (Max) | High Throughput | OS Streaming Buffer |

You can switch profiles with one click in the **Settings & Telegram** tab of the Web UI or via the REST API.

---

## 🖥️ Enterprise Web Management Dashboard

Access the responsive Single Page Application (SPA) dashboard in any browser with **zero Node.js/npm dependencies**:
* **Dashboard Tab**: Real-time meters for host CPU Load, RAM %, Available Disk Space, and active hardware profile.
* **Search Studio Tab**: File/folder target selector, multi-line pattern editor, output format selector, and concurrency sliders.
* **Live Monitor & Terminal Tab**: Real-time throughput speedometer (MB/s), ETA countdown clock, live matches counter, and interactive Pause / Resume / Stop buttons.
* **Files & Upload Tab**: Visual server filesystem directory browser and drag-and-drop chunked file uploader.
* **Jobs & History Tab**: Persistent record of all completed and paused search missions, started dates in your **client local timezone**, output filenames, and direct single-click download links.
* **Server Logs (48h) Tab**: Rolling audit terminal displaying the last 48 hours of server debug and diagnostic logs.
* **Settings & Telegram Tab**: Master admin password updater, hardware profiles, upload/output directory settings, and Telegram Bot configuration.

---

## 📦 Resumable Chunked File Upload

Upload multi-gigabyte files directly to the server through the Web UI:
* Slices uploads into 5 MB chunks transferred sequentially.
* Does not allocate memory on the server (streams directly into temporary disk parts).
* Supports automatic retry on network drops.
* Validates file integrity via SHA-256 hash checksums upon completion.

---

## 🤖 Telegram Bot Integration & Delivery

Configure the integrated Telegram Bot dispatcher in the Settings tab:
* **Mission Start Alert**: Dispatches job ID, search target path, patterns count, and engine parameters.
* **Critical Alerts**: Sends immediate notifications if system RAM usage exceeds the configured threshold.
* **Completion Report**: Dispatches total matches found, elapsed seconds, average throughput (MB/s), and completed timestamp.
* **Automatic 45 MB Multipart Splitting**: Output files larger than Telegram's 45 MB bot upload limit are automatically split into sequential parts (`part001_of_004.txt`) and delivered with descriptive progress captions.

---

## 🚀 Quick Start Guide

### 1. Requirements
* Python 3.9+ (Python 3.11 - 3.14 fully supported)
* Virtual Environment (e.g. `C:\.VENV` or `source .VENV/bin/activate`)

Install dependencies:
```bash
pip install -r requirements.txt
```

### 2. Launch the Web UI Server
```bash
python run_server.py --host 0.0.0.0 --port 8000
```
Open your browser at `http://localhost:8000` (or `http://YOUR_SERVER_IP:8000`).
* **Default Master Password**: `yuri8310` (or `admin`)
*(Update your password anytime in the Settings tab).*

### 3. Run via CLI Worker
```bash
# Clean line search across a directory using native Ripgrep SIMD
python worker.py --search /path/to/data --pattern "target_keyword" --format clean

# Multi-pattern search with compression
python worker.py --search /path/to/data --pattern-file keywords.txt --compress zstd

# PCRE2 regex search
python worker.py --search /path/to/data --pattern "[a-z0-9_]+@gmail\.com" --regex
```

---

## ⚙️ CLI Worker Reference

| Parameter | Short | Description |
| :--- | :---: | :--- |
| `--search PATH` | `-s` | Target file or directory to scan |
| `--pattern PAT` | `-p` | Search keyword or pattern |
| `--pattern-file FILE` | | File containing patterns (one per line) |
| `--output FILE` | `-o` | Output file destination (defaults to `output/`) |
| `--engine TYPE` | | Search engine (`ripgrep`, `aho`, `regex`) |
| `--format FMT` | | Output format (`clean`, `separate`, `prefix`, `extract_only`) |
| `--threads NUM` | | Number of worker threads (0 = auto-tune) |
| `--regex` | | Enable regular expression matching |
| `--case-sensitive` | | Enable exact case matching |
| `--no-recursive` | | Do not scan subdirectories |
| `--compress ALGO` | | Compress output (`none`, `gzip`, `zstd`, `lz4`) |
| `--no-telegram` | | Suppress Telegram notifications for this run |

---

## 🛡️ Production Linux Deployment (Systemd)

Create `/etc/systemd/system/yurigagarin.service`:
```ini
[Unit]
Description=YURI GAGARIN ALPHA - Enterprise Search Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/Desktop/YURI_GAGARIN_ALPHA_FINAL
ExecStart=/root/Desktop/.VENV/bin/python run_server.py --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now yurigagarin
```

---

## 📜 48-Hour Diagnostic Logging

The server maintains a daily rotating audit log in `logs/server.log` with a 48-hour retention policy. View and refresh live logs directly from the **Server Logs (48h)** tab in the Web UI or via the REST API:
```bash
curl -H "Authorization: Bearer <TOKEN>" "http://localhost:8000/api/logs/recent?lines=250"
```

---

## 🧪 Automated Testing & Benchmarks

The platform includes an extensive test suite verifying mathematical correctness, boundary stability, ReDoS protection, API security, and high-volume stress:

```bash
python -m unittest discover -s tests -v
```

### Test Suite Structure
* `tests/test_ripgrep_engine.py`: High-throughput Ripgrep benchmarks (280 - 500+ MB/s).
* `tests/test_complex_regex_55.py`: 55 distinct complex regex tests (UUIDs, JWTs, IPs, credentials, ReDoS).
* `tests/test_benchmark.py`: 1,000 concurrent patterns across synthetic datasets.
* `tests/test_user_scenarios.py`: Corrupted files, binary NUL bytes, 6 MB continuous lines, UTF-8 BOM.
* `tests/test_api_integration.py`: REST API endpoints, token authentication, and directory explorer.
* `tests/test_upload.py`: Chunked file uploads and SHA-256 verification.
* `tests/test_checkpoint.py`: Atomic state persistence and byte-level resume.

---

## 📄 License
This project is licensed under the MIT License.
