"""
Search Manager & Unified Multiprocess Stream Orchestrator.
Coordinates Aho-Corasick, Regex, dynamic chunk buffers, checkpoints,
and parallel multi-core search across massive files and directories.
"""

from __future__ import annotations

import gzip
import logging
import math
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

from .checkpoint import CheckpointManager, CheckpointState
from .engine_aho import AhoCorasickEngine, AhoMatch
from .engine_regex import RegexEngine, RegexMatch
from .engine_ripgrep import RipgrepEngine, RipgrepOptions
from .resource_guard import ResourceGuard, SystemProfile

try:
    from server.config import get_server_config
except ImportError:
    get_server_config = None

logger = logging.getLogger("yurigagarin.manager")

# Optional compression modules
try:
    import zstandard as zstd
    _HAS_ZSTD = True
except ImportError:
    _HAS_ZSTD = False

try:
    import lz4.frame as lz4_frame
    _HAS_LZ4 = True
except ImportError:
    _HAS_LZ4 = False

TEXT_EXTENSIONS = frozenset({
    ".txt", ".log", ".csv", ".tsv", ".json", ".xml", ".md", ".rst",
    ".py", ".js", ".html", ".htm", ".css", ".php", ".java", ".c",
    ".cpp", ".go", ".rs", ".rb", ".sh", ".bash", ".sql", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".env",
    ".gitignore", ".list", ".dat", ".out", ".raw", ".pass",
    ".combo", ".cred",
})


@dataclass
class SearchConfig:
    target_path: str
    patterns: List[str]
    output_file: str
    engine_type: str = "ripgrep"  # "ripgrep", "aho", "regex"
    is_regex: bool = False
    case_sensitive: bool = False
    output_format: str = "clean"  # "clean" (line only), "separate" (heading), "prefix" (file:line), "extract_only"
    extract_only: bool = False
    recursive: bool = True
    skip_hidden: bool = True
    detailed_stats: bool = True
    low_memory_mode: bool = False
    num_workers: Optional[int] = None
    chunk_bytes: Optional[int] = None
    compress_algo: str = "none"  # "none", "gzip", "zstd", "lz4"
    compress_level: int = 6
    job_id: Optional[str] = None
    # Ripgrep specific
    rg_threads: int = 0
    rg_mmap: bool = True
    rg_pcre2: bool = True
    rg_smart_case: bool = False


@dataclass
class SearchResult:
    job_id: str
    target_path: str
    output_file: str
    patterns_count: int
    files_discovered: int
    files_searched: int
    files_with_matches: int
    total_bytes_scanned: int
    total_matches: int
    elapsed_seconds: float
    throughput_mb_s: float
    success: bool
    errors: List[Dict[str, str]] = field(default_factory=list)
    file_statistics: Dict[str, Dict[str, int]] = field(default_factory=dict)


class SearchManager:
    """
    Unified high-performance search manager.
    Handles single large files or recursively discovers thousands of files.
    """

    def __init__(
        self,
        config: SearchConfig,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ):
        self.config = config
        self.progress_callback = progress_callback
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()
        self.resource_guard = ResourceGuard()
        self.system_profile = self.resource_guard.inspect_system()

        self._stop_requested = threading.Event()
        self._pause_requested = threading.Event()

        # Determine effective chunk size
        if config.chunk_bytes:
            self.chunk_size = config.chunk_bytes
        elif config.low_memory_mode:
            self.chunk_size = 4 * 1024 * 1024
        else:
            self.chunk_size = self.system_profile.recommended_chunk_bytes

        # Generate or use job_id
        self.job_id = config.job_id or f"job_{int(time.time())}_{os.getpid()}"

    def request_stop(self) -> None:
        """Signals the search loop to cleanly halt."""
        self._stop_requested.set()

    def request_pause(self) -> None:
        """Signals the search loop to pause."""
        self._pause_requested.set()

    def resume(self) -> None:
        """Resumes a paused search loop."""
        self._pause_requested.clear()

    def discover_files(self, target: Path) -> List[Path]:
        """Discovers text files in target recursively or single file."""
        if target.is_file():
            return [target]

        found: List[Path] = []
        stack = [target]

        while stack:
            curr = stack.pop()
            try:
                for entry in curr.iterdir():
                    if self.config.skip_hidden and entry.name.startswith("."):
                        continue
                    if entry.is_file():
                        if entry.suffix.lower() in TEXT_EXTENSIONS or entry.stat().st_size < 50 * 1024 * 1024:
                            found.append(entry)
                    elif entry.is_dir() and self.config.recursive:
                        stack.append(entry)
            except (PermissionError, OSError) as e:
                logger.debug("Access denied skipping: %s (%s)", curr, e)

        return sorted(found)

    def _batch_files(self, files: List[Path], max_batch_size_mb: int = 100, max_files: int = 50) -> List[List[Path]]:
        """Group small files into batches for single ripgrep invocation.
        Large files (>100MB) are processed individually.
        """
        batches = []
        current_batch = []
        current_size_mb = 0.0

        for f in files:
            f_size_mb = f.stat().st_size / (1024 * 1024)
            if f_size_mb >= 100:
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_size_mb = 0.0
                batches.append([f])
            elif len(current_batch) >= max_files or current_size_mb + f_size_mb > max_batch_size_mb:
                batches.append(current_batch)
                current_batch = [f]
                current_size_mb = f_size_mb
            else:
                current_batch.append(f)
                current_size_mb += f_size_mb

        if current_batch:
            batches.append(current_batch)
        return batches

    def _get_hardware_profile(self) -> str:
        """Get active hardware profile from server config."""
        if get_server_config:
            try:
                cfg = get_server_config()
                return getattr(cfg, "hardware_profile", "eco")
            except Exception:
                pass
        return "eco"

    def _should_use_mmap(self, file_size_mb: float, profile: str) -> bool:
        """Determine if mmap should be used based on file size and hardware profile."""
        thresholds = {"eco": 100, "balanced": 50, "turbo": 10}
        threshold = thresholds.get(profile, 100)
        return file_size_mb >= threshold

    def execute(self) -> SearchResult:
        """
        Executes the search process with full error handling and live progress telemetry.
        """
        self.resource_guard.apply_process_priority()
        started_at = time.monotonic()
        target = Path(self.config.target_path)
        output_path = Path(self.config.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not target.exists():
            raise FileNotFoundError(f"Target path does not exist: {target}")

        files = self.discover_files(target)
        if not files:
            raise RuntimeError(f"No searchable files found in {target}")

        total_bytes = sum(f.stat().st_size for f in files)
        logger.info(
            "Search target: %s | Files: %d | Total Size: %.2f GB | Mode: %s",
            target,
            len(files),
            total_bytes / (1024 ** 3),
            "Ripgrep" if self.config.engine_type == "ripgrep" else ("Regex" if self.config.is_regex else "Aho-Corasick"),
        )

        # Primary Search Engine: Ripgrep Native Rust
        rg_engine = RipgrepEngine()
        use_rg = (self.config.engine_type == "ripgrep" or self.config.engine_type == "") and rg_engine.is_available()

        if use_rg:
            # Map hardware profile to optimal worker threads and niceness
            hw_profile = self._get_hardware_profile()
            cpu_count = self.system_profile.cpu_count
            if hw_profile == "turbo":
                safe_threads = self.config.rg_threads or cpu_count
                nice_level = 0
            elif hw_profile == "balanced":
                safe_threads = self.config.rg_threads or max(1, int(cpu_count * 0.75))
                nice_level = 2
            else:  # eco
                safe_threads = self.config.rg_threads or max(1, min(2, cpu_count))
                nice_level = 5

            self.resource_guard.apply_process_priority(hw_profile)

            # Strict PCRE2: ONLY enable PCRE2 if is_regex is explicitly True!
            effective_pcre2 = self.config.is_regex and self.config.rg_pcre2

            # Memory protection: Disable mmap for large datasets/directories to prevent Linux page-cache thrash
            use_mmap = bool(self.config.rg_mmap and target.is_file() and total_bytes < 50 * 1024 * 1024)

            engine_mode = "Ripgrep (fixed-strings)" if not self.config.is_regex else "Ripgrep (PCRE2 regex)"
            logger.info(
                "Search target: %s | Files: %d | Total Size: %.2f GB | Mode: %s | Profile: %s (%d threads, nice=%d, mmap=%s)",
                target,
                len(files),
                total_bytes / (1024 ** 3),
                engine_mode,
                hw_profile,
                safe_threads,
                nice_level,
                use_mmap,
            )

            # Determine effective format
            fmt = self.config.output_format
            if self.config.extract_only:
                fmt = "extract_only"

            rg_opts = RipgrepOptions(
                threads=safe_threads,
                mmap=use_mmap,
                pcre2=effective_pcre2,
                smart_case=self.config.rg_smart_case,
                case_sensitive=self.config.case_sensitive,
                output_format=fmt,
                hidden=not self.config.skip_hidden,
                no_ignore=True,
                recursive=self.config.recursive,
                nice_level=nice_level,
            )

            # Direct Native Ripgrep execution: File-by-file pipelining for directories
            # guarantees 100% accurate live progress, file names, ETA, and RAM page-cache release!
            total_matches = 0
            scanned_bytes = 0
            file_matches_map: Dict[str, int] = {}
            last_progress_emit = [0.0]

            # Send initial starting telemetry
            if self.progress_callback:
                self.progress_callback({
                    "job_id": self.job_id,
                    "file_current": files[0].name if files else target.name,
                    "file_index": 1,
                    "total_files": len(files),
                    "percent": 0.1,
                    "speed_mb_s": 0.0,
                    "eta_seconds": 0,
                    "total_matches": 0,
                    "bytes_processed": 0,
                    "total_bytes": total_bytes,
                })

            if target.is_file() or len(files) <= 1:
                # Single file execution
                def _handle_single_rg_progress(prog_info: Dict[str, Any]):
                    now_t = time.monotonic()
                    if now_t - last_progress_emit[0] < 0.6:
                        return
                    last_progress_emit[0] = now_t

                    elapsed_s = max(0.001, prog_info.get("elapsed", now_t - started_at))
                    cur_matches = prog_info.get("matches", 0)
                    cur_out_b = prog_info.get("out_bytes", 0)
                    cur_spd = (total_bytes / (1024 * 1024)) / elapsed_s if elapsed_s > 0 else 0.0

                    if self.progress_callback:
                        self.progress_callback({
                            "job_id": self.job_id,
                            "file_current": target.name,
                            "file_index": 1,
                            "total_files": 1,
                            "percent": 50.0,
                            "speed_mb_s": round(cur_spd, 2),
                            "eta_seconds": max(0, int((total_bytes - cur_out_b) / max(1, cur_spd * 1024 * 1024))),
                            "total_matches": cur_matches,
                            "bytes_processed": cur_out_b,
                            "total_bytes": total_bytes,
                        })

                total_matches, _ = rg_engine.execute_stream(
                    patterns=self.config.patterns,
                    target_path=str(target),
                    output_file=output_path,
                    options=rg_opts,
                    is_regex=self.config.is_regex,
                    progress_callback=_handle_single_rg_progress,
                    stop_event=self._stop_requested,
                    append=False,
                )
                if total_matches > 0:
                    file_matches_map[target.name] = total_matches
            else:
                # Directory execution: iterate over files sequentially
                # Ensures accurate per-file telemetry, granular progress percentage, and Linux Page Cache purge
                batches = self._batch_files(files, max_batch_size_mb=100, max_files=1 if len(files) < 20 else 10)
                file_idx_counter = 0

                for b_idx, batch in enumerate(batches):
                    if self._stop_requested.is_set():
                        break

                    batch_paths = [str(f) for f in batch]
                    batch_bytes = sum(f.stat().st_size for f in batch)
                    curr_file_name = batch[0].name if len(batch) == 1 else f"{batch[0].name} (+{len(batch)-1} files)"

                    def _handle_batch_rg_progress(prog_info: Dict[str, Any]):
                        now_t = time.monotonic()
                        if now_t - last_progress_emit[0] < 0.6:
                            return
                        last_progress_emit[0] = now_t

                        elapsed_s = max(0.001, now_t - started_at)
                        live_b = scanned_bytes
                        pct = min(99.9, (live_b / max(1, total_bytes)) * 100.0)
                        cur_spd = (live_b / (1024 * 1024)) / elapsed_s if elapsed_s > 0 else 0.0
                        rem_b = max(0, total_bytes - live_b)
                        eta_sec = int(rem_b / max(1.0, cur_spd * 1024 * 1024)) if cur_spd > 0 else 0

                        if self.progress_callback:
                            self.progress_callback({
                                "job_id": self.job_id,
                                "file_current": curr_file_name,
                                "file_index": file_idx_counter + 1,
                                "total_files": len(files),
                                "percent": round(pct, 1),
                                "speed_mb_s": round(cur_spd, 2),
                                "eta_seconds": eta_sec,
                                "total_matches": total_matches + prog_info.get("matches", 0),
                                "bytes_processed": live_b,
                                "total_bytes": total_bytes,
                            })

                    b_matches, _ = rg_engine.execute_stream(
                        patterns=self.config.patterns,
                        target_path="",
                        output_file=output_path,
                        options=rg_opts,
                        is_regex=self.config.is_regex,
                        progress_callback=_handle_batch_rg_progress,
                        stop_event=self._stop_requested,
                        append=(b_idx > 0),
                        file_list=batch_paths,
                    )

                    total_matches += b_matches
                    scanned_bytes += batch_bytes
                    file_idx_counter += len(batch)
                    if b_matches > 0:
                        if len(batch) == 1:
                            file_matches_map[batch[0].name] = file_matches_map.get(batch[0].name, 0) + b_matches
                        else:
                            file_matches_map[curr_file_name] = file_matches_map.get(curr_file_name, 0) + b_matches

                    # Release OS page cache for scanned batch files on Linux
                    for f in batch:
                        try:
                            with open(f, "rb") as probe_fh:
                                self.resource_guard.release_page_cache(probe_fh.fileno(), 0, f.stat().st_size)
                        except Exception:
                            pass

                    # Progress update after each batch
                    now_t = time.monotonic()
                    elapsed_s = max(0.001, now_t - started_at)
                    pct = min(100.0, (scanned_bytes / max(1, total_bytes)) * 100.0)
                    cur_spd = (scanned_bytes / (1024 * 1024)) / elapsed_s if elapsed_s > 0 else 0.0
                    rem_b = max(0, total_bytes - scanned_bytes)
                    eta_sec = int(rem_b / max(1.0, cur_spd * 1024 * 1024)) if cur_spd > 0 else 0

                    if self.progress_callback:
                        self.progress_callback({
                            "job_id": self.job_id,
                            "file_current": curr_file_name,
                            "file_index": file_idx_counter,
                            "total_files": len(files),
                            "percent": round(pct, 1),
                            "speed_mb_s": round(cur_spd, 2),
                            "eta_seconds": eta_sec,
                            "total_matches": total_matches,
                            "bytes_processed": scanned_bytes,
                            "total_bytes": total_bytes,
                        })

            # Generate and prepend rich mission metadata header to output file before compression (only in full format modes)
            if output_path.exists() and fmt != "extract_only":
                try:
                    # Sort top matched files by hit count
                    top_files = sorted(file_matches_map.items(), key=lambda x: x[1], reverse=True)[:5]
                    header_lines = [
                        "=" * 78,
                        " YURI GAGARIN ALPHA - ENTERPRISE BIG-DATA SEARCH MISSION REPORT",
                        "=" * 78,
                        f"• Job ID          : {self.job_id}",
                        f"• Date (UTC)      : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
                        f"• Target Path     : {target}",
                        f"• Total Files     : {len(files):,}",
                        f"• Total Data Size : {total_bytes / (1024**3):.2f} GB ({total_bytes:,} bytes)",
                        f"• Total Matches   : {total_matches:,}",
                        f"• Engine Type     : {engine_mode}",
                        f"• Output Format   : {fmt}",
                        f"• Case Sensitive  : {self.config.case_sensitive}",
                        f"• Patterns Count  : {len(self.config.patterns)}",
                        "-" * 78,
                        " SEARCH PATTERNS / KEYWORDS:",
                    ]
                    for idx, pat in enumerate(self.config.patterns[:10], start=1):
                        is_multi = "\n" in pat or "\r" in pat
                        tag = " [MULTILINE]" if is_multi else ""
                        pat_repr = repr(pat)[1:-1] if is_multi else pat
                        header_lines.append(f"  [{idx}] {pat_repr}{tag}")
                    if len(self.config.patterns) > 10:
                        header_lines.append(f"  ... and {len(self.config.patterns) - 10} more patterns.")

                    if top_files:
                        header_lines.append("-" * 78)
                        header_lines.append(" TOP MATCHED FILES (HIGHEST DENSITY):")
                        for rank, (fname, count) in enumerate(top_files, start=1):
                            pct_hits = (count / max(1, total_matches)) * 100
                            header_lines.append(f"  {rank}. {fname}: {count:,} matches ({pct_hits:.1f}%)")

                    header_lines.append("=" * 78)
                    header_lines.append("\n")
                    header_bytes = "\n".join(header_lines).encode("utf-8")

                    # Fast prepend using temp file (streamed in 8MB chunks, zero RAM overhead)
                    temp_headed = output_path.with_name(f"tmp_headed_{output_path.name}")
                    with open(temp_headed, "wb") as out_fh:
                        out_fh.write(header_bytes)
                        with open(output_path, "rb") as raw_fh:
                            shutil.copyfileobj(raw_fh, out_fh, length=8 * 1024 * 1024)
                    temp_headed.replace(output_path)
                except Exception as e:
                    logger.warning("Could not prepend mission header to output file: %s", e)

            # Post-process output (compression if enabled)
            final_output = output_path
            if self.config.compress_algo != "none" and output_path.exists():
                final_output = self._compress_file(output_path, self.config.compress_algo, self.config.compress_level)

            elapsed_total = max(0.001, time.monotonic() - started_at)
            mb_scanned = total_bytes / (1024 * 1024)
            final_throughput = mb_scanned / elapsed_total

            # Final 100% progress notification
            if self.progress_callback:
                self.progress_callback({
                    "job_id": self.job_id,
                    "file_current": "Complete",
                    "file_index": len(files),
                    "total_files": len(files),
                    "percent": 100.0,
                    "speed_mb_s": round(final_throughput, 2),
                    "eta_seconds": 0,
                    "total_matches": total_matches,
                    "bytes_processed": total_bytes,
                    "total_bytes": total_bytes,
                })

            return SearchResult(
                job_id=self.job_id,
                target_path=str(target),
                output_file=str(final_output),
                patterns_count=len(self.config.patterns),
                files_discovered=len(files),
                files_searched=len(files),
                files_with_matches=len(file_matches_map) if file_matches_map else (1 if total_matches > 0 else 0),
                total_bytes_scanned=total_bytes,
                total_matches=total_matches,
                elapsed_seconds=round(elapsed_total, 3),
                throughput_mb_s=round(final_throughput, 2),
                success=not self._stop_requested.is_set(),
                errors=[],
                file_statistics={k: {"matches": v} for k, v in file_matches_map.items()},
            )

        # Fallback to internal Python Aho-Corasick or Regex engine
        if self.config.is_regex:
            regex_engine = RegexEngine(
                self.config.patterns,
                case_sensitive=self.config.case_sensitive,
            )
            aho_engine = None
        else:
            aho_engine = AhoCorasickEngine(
                self.config.patterns,
                case_sensitive=self.config.case_sensitive,
            )
            regex_engine = None

        # Check existing checkpoint
        existing_cp = self.checkpoint_manager.load(self.job_id)
        completed_files_set = set(existing_cp.completed_files) if existing_cp else set()
        resume_offset = existing_cp.current_file_offset if existing_cp else 0
        current_resuming_file = existing_cp.current_file_path if existing_cp else ""

        total_matches = existing_cp.total_matches_count if existing_cp else 0
        total_scanned_bytes = existing_cp.total_bytes_processed if existing_cp else 0
        files_with_hits = 0
        files_searched = len(completed_files_set)
        errors: List[Dict[str, str]] = []
        file_stats: Dict[str, Dict[str, int]] = {}

        # Prepare output file
        write_mode = "a" if existing_cp else "w"
        with open(output_path, write_mode, encoding="utf-8", errors="replace", buffering=4 * 1024 * 1024) as fout:
            if not existing_cp:
                fout.write(f"=== YURI GAGARIN ALPHA - SEARCH REPORT ===\n")
                fout.write(f"Job ID: {self.job_id}\n")
                fout.write(f"Engine: {'Regex (JIT)' if self.config.is_regex else 'Aho-Corasick (Vectorized)'}\n")
                fout.write(f"Patterns: {len(self.config.patterns)} pattern(s)\n")
                fout.write(f"Target: {target}\n")
                fout.write(f"Case Sensitive: {self.config.case_sensitive}\n")
                fout.write(f"Extract Only: {self.config.extract_only}\n")
                fout.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")
                fout.write("=" * 60 + "\n\n")

            for idx, file_path in enumerate(files):
                file_str = str(file_path)
                if file_str in completed_files_set:
                    continue

                if self._stop_requested.is_set():
                    logger.info("Search job %s stopped by user.", self.job_id)
                    break

                # Handle pause
                while self._pause_requested.is_set() and not self._stop_requested.is_set():
                    time.sleep(0.5)

                file_offset = resume_offset if (file_str == current_resuming_file) else 0

                try:
                    f_matches, f_scanned = self._scan_single_file(
                        file_path=file_path,
                        aho_engine=aho_engine,
                        regex_engine=regex_engine,
                        fout=fout,
                        start_offset=file_offset,
                        file_index=idx,
                        total_files=len(files),
                        total_all_bytes=total_bytes,
                        accumulated_bytes=total_scanned_bytes,
                        accumulated_matches=total_matches,
                        started_at=started_at,
                    )

                    total_matches += f_matches
                    total_scanned_bytes += f_scanned
                    files_searched += 1
                    if f_matches > 0:
                        files_with_hits += 1

                    file_stats[file_str] = {"matches": f_matches, "bytes": f_scanned}
                    completed_files_set.add(file_str)

                    # Update checkpoint
                    cp_state = CheckpointState(
                        job_id=self.job_id,
                        target_path=str(target),
                        patterns=self.config.patterns,
                        is_regex=self.config.is_regex,
                        case_sensitive=self.config.case_sensitive,
                        extract_only=self.config.extract_only,
                        output_file=str(output_path),
                        status="RUNNING",
                        current_file_index=idx,
                        current_file_path=file_str,
                        current_file_offset=0,
                        completed_files=list(completed_files_set),
                        total_files_discovered=len(files),
                        total_bytes_discovered=total_bytes,
                        total_bytes_processed=total_scanned_bytes,
                        total_matches_count=total_matches,
                        elapsed_seconds=time.monotonic() - started_at,
                    )
                    self.checkpoint_manager.save(cp_state)

                except Exception as exc:
                    logger.exception("Error scanning %s: %s", file_path, exc)
                    errors.append({"file": file_str, "error": str(exc)})

                resume_offset = 0
                current_resuming_file = ""

        # Post-process output (compression if enabled)
        final_output = output_path
        if self.config.compress_algo != "none" and output_path.exists():
            final_output = self._compress_file(output_path, self.config.compress_algo, self.config.compress_level)

        elapsed = max(0.001, time.monotonic() - started_at)
        mb_scanned = total_scanned_bytes / (1024 * 1024)
        throughput = mb_scanned / elapsed

        is_completed = (not self._stop_requested.is_set()) and (len(errors) == 0)

        # Mark checkpoint done if complete
        if is_completed:
            self.checkpoint_manager.remove(self.job_id)

        result = SearchResult(
            job_id=self.job_id,
            target_path=str(target),
            output_file=str(final_output),
            patterns_count=len(self.config.patterns),
            files_discovered=len(files),
            files_searched=files_searched,
            files_with_matches=files_with_hits,
            total_bytes_scanned=total_scanned_bytes,
            total_matches=total_matches,
            elapsed_seconds=round(elapsed, 2),
            throughput_mb_s=round(throughput, 2),
            success=is_completed,
            errors=errors,
            file_statistics=file_stats if self.config.detailed_stats else {},
        )

        logger.info(
            "Search complete: %d matches found in %d files (%.2f MB scanned @ %.2f MB/s in %.2fs)",
            total_matches,
            files_searched,
            mb_scanned,
            throughput,
            elapsed,
        )

        return result

    def _scan_single_file(
        self,
        file_path: Path,
        aho_engine: Optional[AhoCorasickEngine],
        regex_engine: Optional[RegexEngine],
        fout,
        start_offset: int,
        file_index: int,
        total_files: int,
        total_all_bytes: int,
        accumulated_bytes: int,
        accumulated_matches: int,
        started_at: float,
    ) -> Tuple[int, int]:
        """
        Scans a single file chunk-by-chunk with boundary overlap handling and Linux Page Cache purge.
        """
        file_matches = 0
        file_size = file_path.stat().st_size
        bytes_read = 0
        chunk_sz = self.chunk_size

        overlap_len = 0
        if aho_engine:
            overlap_len = max(0, aho_engine.max_pattern_len - 1)
        elif regex_engine:
            overlap_len = 256 * 1024  # 256 KB safety overlap for regex

        carry = b""
        last_progress_emit = 0.0

        with open(file_path, "rb") as fh:
            fd = fh.fileno()
            if start_offset > 0:
                fh.seek(start_offset)
                bytes_read = start_offset

            # Kernel sequential read hint
            self.resource_guard.advise_sequential_read(fd, start_offset, file_size - start_offset)

            while True:
                if self._stop_requested.is_set():
                    break

                # Self-tuning throttling
                if self.resource_guard.should_throttle():
                    time.sleep(0.05)

                chunk = fh.read(chunk_sz)
                if not chunk:
                    break

                chunk_start_abs = bytes_read
                block = carry + chunk
                base_abs = chunk_start_abs - len(carry)
                bytes_read += len(chunk)

                # Execute matching
                # Guarantee: A match is newly discovered in this chunk iff m.absolute_end > chunk_start_abs
                # Matches with absolute_end <= chunk_start_abs were already emitted in prior chunks.
                if aho_engine:
                    matches, _ = aho_engine.scan_chunk(block, start_abs_offset=base_abs)
                    for m in matches:
                        if m.absolute_end > chunk_start_abs:
                            file_matches += 1
                            if self.config.extract_only:
                                fout.write(m.pattern_bytes.decode("utf-8", errors="replace") + "\n")
                            else:
                                # Context: Extract the surrounding line content for full readability
                                local_start = m.absolute_start - base_abs
                                line_start = block.rfind(b"\n", 0, local_start)
                                line_start = 0 if line_start == -1 else line_start + 1
                                line_end = block.find(b"\n", local_start)
                                line_end = len(block) if line_end == -1 else line_end
                                line_content = block[line_start:line_end].decode("utf-8", errors="replace").strip("\r")
                                if len(line_content) > 300:
                                    line_content = line_content[:300] + "..."
                                fout.write(f"[{file_path.name}:offset {m.absolute_start}] {line_content}\n")
                elif regex_engine:
                    r_matches = regex_engine.scan_block(block, start_abs_offset=base_abs)
                    for rm in r_matches:
                        if rm.absolute_end > chunk_start_abs:
                            file_matches += 1
                            if self.config.extract_only:
                                fout.write(rm.matched_bytes.decode("utf-8", errors="replace") + "\n")
                            else:
                                local_start = rm.absolute_start - base_abs
                                line_start = block.rfind(b"\n", 0, local_start)
                                line_start = 0 if line_start == -1 else line_start + 1
                                line_end = block.find(b"\n", local_start)
                                line_end = len(block) if line_end == -1 else line_end
                                line_content = block[line_start:line_end].decode("utf-8", errors="replace").strip("\r")
                                if len(line_content) > 300:
                                    line_content = line_content[:300] + "..."
                                fout.write(f"[{file_path.name}:offset {rm.absolute_start}] {line_content}\n")

                # Boundary carry
                carry = block[-overlap_len:] if (overlap_len and len(block) >= overlap_len) else block

                # Linux Kernel cache release
                self.resource_guard.release_page_cache(fd, base_abs, len(chunk))

                # Emit progress telemetry
                now = time.monotonic()
                if self.progress_callback and (now - last_progress_emit >= 0.8):
                    last_progress_emit = now
                    current_total_scanned = accumulated_bytes + bytes_read
                    elapsed = max(0.001, now - started_at)
                    spd = (current_total_scanned / (1024 * 1024)) / elapsed
                    pct = min(100.0, (current_total_scanned / max(1, total_all_bytes)) * 100.0)
                    rem_bytes = max(0, total_all_bytes - current_total_scanned)
                    eta_sec = int(rem_bytes / (spd * 1024 * 1024)) if spd > 0 else 0

                    self.progress_callback({
                        "job_id": self.job_id,
                        "file_current": file_path.name,
                        "file_index": file_index + 1,
                        "total_files": total_files,
                        "percent": round(pct, 1),
                        "speed_mb_s": round(spd, 2),
                        "eta_seconds": eta_sec,
                        "total_matches": accumulated_matches + file_matches,
                        "bytes_processed": current_total_scanned,
                        "total_bytes": total_all_bytes,
                    })

        return file_matches, bytes_read

    def _compress_file(self, src: Path, algo: str, level: int) -> Path:
        """Compresses search output file using requested algorithm."""
        ext = {"gzip": ".gz", "zstd": ".zst", "lz4": ".lz4"}.get(algo, ".gz")
        dst = src.with_suffix(src.suffix + ext)

        logger.info("Compressing output %s -> %s (algo=%s)", src.name, dst.name, algo)
        if algo == "gzip":
            with open(src, "rb") as fi, gzip.open(dst, "wb", compresslevel=level) as fo:
                shutil.copyfileobj(fi, fo, length=8 * 1024 * 1024)
        elif algo == "zstd" and _HAS_ZSTD:
            with open(src, "rb") as fi, open(dst, "wb") as fo:
                cctx = zstd.ZstdCompressor(level=level)
                cctx.copy_stream(fi, fo)
        elif algo == "lz4" and _HAS_LZ4:
            with open(src, "rb") as fi, lz4_frame.open(dst, "wb", compression_level=level) as fo:
                shutil.copyfileobj(fi, fo, length=8 * 1024 * 1024)
        else:
            with open(src, "rb") as fi, gzip.open(dst, "wb", compresslevel=6) as fo:
                shutil.copyfileobj(fi, fo, length=8 * 1024 * 1024)

        if dst.exists() and dst.stat().st_size > 0:
            try:
                src.unlink()
            except OSError:
                pass
        return dst
