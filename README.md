<div align="center">
  <img src="assets/logo.svg" alt="YURI GAGARIN ALPHA" width="100%" max-width="780" />
  <br />
  <h3>Enterprise High-Performance Big-Data Text Search Engine & Admin Web UI</h3>
  <p>
    <b>Engineered to scan thousands of 100+ GB text files with bounded memory, self-tuning resource guard, and zero system lockups.</b>
  </p>

  <p>
    <img src="https://img.shields.io/badge/version-17.0%20Enterprise-38BDF8?style=flat-square" alt="Version" />
    <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Windows-6366F1?style=flat-square" alt="Platform" />
    <img src="https://img.shields.io/badge/engine-Aho--Corasick%20%2B%20JIT%20Regex-10B981?style=flat-square" alt="Engine" />
    <img src="https://img.shields.io/badge/license-MIT-F59E0B?style=flat-square" alt="License" />
  </p>
</div>

---

## ⚡ Highlights & Key Innovations

* **Extreme Search Throughput with Native Ripgrep (Rust SIMD)**:
  * Integrated **Ripgrep** engine delivering **500 - 1,000+ MB/s** real-world scan speeds with memory-mapped I/O (`--mmap`) and multi-core CPU scaling (`--threads`).
  * Supported by PCRE2 JIT compilation for advanced regular expressions and smart-case matching.
* **Dual Fallback Core (Aho-Corasick & Python Regex)**:
  * **Vectorized Aho-Corasick**: Single-pass $O(N)$ multi-pattern literal matcher. Searches tens of thousands of keywords concurrently.
  * **PCRE2 / JIT Regex**: High-performance regular expression matching with an active watchdog timer (500ms max) that catches and neutralizes catastrophic backtracking (ReDoS).
* **48-Hour Historical Server Logs & Live Diagnostic Viewer**:
  * Rolling 2-day server audit logs (`logs/server.log`) for complete debugging, troubleshooting, and error diagnosis directly inside the Admin Web UI.
* **Linux Kernel Optimizer**:
  * Utilizes `posix_fadvise(POSIX_FADV_SEQUENTIAL)` and `POSIX_FADV_DONTNEED` to instruct the Linux kernel to immediately release file page cache after processing. Scanning a 500 GB file will not starve server RAM or evict system applications.
  * Automatic `nice 10` and `ionice` scheduling to keep SSH sessions and web services responsive under heavy disk load.
* **Modern Admin Web UI (100% English)**:
  * Sleek Single Page Application (SPA) dashboard without Node.js/npm dependencies.
  * Real-time hardware telemetry gauges (CPU %, RAM %, Disk capacity).
  * Live WebSocket terminal streaming progress, throughput (MB/s), ETA, and match counters.
  * Dedicated **Ripgrep Configuration Panel** to tweak worker threads, memory-mapped I/O, and PCRE2 options on the fly.
* **Resumable Chunked File Upload Manager**:
  * Upload multi-gigabyte files directly to the server through the browser.
  * Transfers data in small sequential chunks with SHA-256 integrity verification.
* **Telegram Bot Integration**:
  * Dispatches search milestone announcements, periodic progress reports, and hardware alerts.
  * Automatically splits search result files exceeding Telegram's 45 MB limit into sequential parts and delivers them directly to your chat.
* **Atomic Checkpoints & Disaster Recovery**:
  * Persists exact byte-level progress (`checkpoints/<job_id>.json`).
  * Instant pause/resume support across reboots without re-scanning previously processed bytes.

---

## 🚀 Quick Start Guide

### 1. Requirements & Dependencies

* Python 3.9+ (Python 3.11 - 3.14 recommended)
* Virtual environment (e.g. `C:\.VENV` or standard `python3 -m venv venv`)

Install core requirements:
```bash
pip install -r requirements.txt
```

### 2. Launch the Web UI & Management Dashboard

Start the high-performance FastAPI server:
```bash
python run_server.py --host 0.0.0.0 --port 8000
```

Open your browser at `http://localhost:8000` (or your server's IP address).
* **Default Master Password**: `admin`
*(You can update this immediately from the Settings tab).*

### 3. CLI Worker Mode (Terminal & Headless Automation)

Run direct high-speed scans from the command line:

```bash
# High-speed literal search (Aho-Corasick) across a directory
python worker.py --search /path/to/data --pattern "target_keyword"

# Multi-pattern literal search (OR semantics)
python worker.py --search /path/to/data --pattern "keyword1
keyword2
keyword3"

# Advanced regex search (with JIT and ReDoS watchdog)
python worker.py --search /path/to/data --pattern "\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b" --regex

# Compressed output with Gzip, Zstandard, or LZ4
python worker.py --search /path/to/data --pattern "admin" --compress zstd --compress-level 6
```

---

## ⚙️ CLI Reference

| Flag | Short | Description |
| :--- | :---: | :--- |
| `--search PATH` | `-s` | Target file or directory to scan |
| `--pattern PAT` | `-p` | Search keyword or pattern (newline-separated for multiple) |
| `--pattern-file FILE` | | File containing search patterns (one per line) |
| `--output FILE` | `-o` | Output file path (defaults to timestamp in `output/`) |
| `--regex` | | Treat patterns as regular expressions (JIT enabled) |
| `--case-sensitive` | | Enable exact case matching |
| `--no-recursive` | | Do not scan subdirectories recursively |
| `--full-context` | | Output matched lines with offset rather than extracted terms |
| `--low-memory` | | Optimize memory for constrained VPS servers (4 MB chunks) |
| `--compress ALGO` | | Compress output file (`none`, `gzip`, `zstd`, `lz4`) |
| `--job-id ID` | | Specify job ID for resuming interrupted checkpoints |
| `--no-telegram` | | Disable Telegram bot notifications for this run |

---

## 🛡️ Production Linux Deployment (Systemd Service)

To run the Web UI as a persistent system daemon on Linux:

Create `/etc/systemd/system/yurigagarin.service`:
```ini
[Unit]
Description=YURI GAGARIN ALPHA - Search Engine Web Platform
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/YURI_GAGARIN_ALPHA_FINAL
ExecStart=/opt/YURI_GAGARIN_ALPHA_FINAL/venv/bin/python run_server.py --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now yurigagarin
```

---

## 🧪 Comprehensive Automated Testing

The codebase includes an exhaustive test suite verifying boundary conditions, ReDoS prevention, memory scaling, chunked uploads, and stress performance:

```bash
python -m unittest discover -s tests -v
```

### Test Suite Structure
* `tests/test_aho.py`: Verifies multi-pattern literal matching and matches split across chunk boundaries.
* `tests/test_regex.py`: Verifies regex extraction and the catastrophic backtracking watchdog.
* `tests/test_checkpoint.py`: Tests atomic JSON state persistence and exact byte-level resume.
* `tests/test_resource.py`: Tests dynamic RAM/chunk scaling and `posix_fadvise` compatibility.
* `tests/test_upload.py`: Tests resumable chunked upload and SHA-256 integrity verification.
* `tests/test_stress_large.py`: Multi-megabyte synthetic dataset stress tests verifying memory boundedness.

---

## 📄 License
This project is licensed under the MIT License.
