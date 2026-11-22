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
from .resource_guard import ResourceGuard, SystemProfile

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
    is_regex: bool = False
    case_sensitive: bool = False
    extract_only: bool = True
    recursive: bool = True
    skip_hidden: bool = True
    detailed_stats: bool = True
    low_memory_mode: bool = False
    num_workers: Optional[int] = None
    chunk_bytes: Optional[int] = None
    compress_algo: str = "none"  # "none", "gzip", "zstd", "lz4"
    compress_level: int = 6
    job_id: Optional[str] = None


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
            "Regex" if self.config.is_regex else "Aho-Corasick",
        )

        # Initialize engines
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
