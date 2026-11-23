"""
Ripgrep Native Rust Engine Wrapper.
Provides extreme search speeds (multi-gigabytes per second) across massive text datasets.
Auto-detects system ripgrep binary or falls back to project local bin/rg.
Non-blocking streaming with live telemetry and deadlock prevention.
Linux-optimized with ionice/cgroup support for production servers.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("yurigagarin.engine.ripgrep")


@dataclass
class RipgrepOptions:
    threads: int = 0                  # 0 = auto-detect CPU cores
    mmap: bool = False                # False = sequential streaming I/O (safe for 800+ GB), True = memory-mapped
    pcre2: bool = True                # Enable PCRE2 engine with JIT
    smart_case: bool = False          # Case insensitive if pattern is lowercase
    case_sensitive: bool = False      # Strict case sensitivity
    max_count: Optional[int] = None   # Limit matches
    memory_limit: Optional[str] = None # Memory limit, e.g. "2G"
    output_format: str = "clean"      # "clean" (match line only), "separate" (heading filename), "prefix" (file:line:content), "extract_only" (-o)
    extract_only: bool = False        # Backward compatibility flag
    invert_match: bool = False        # Invert match (-v)
    no_ignore: bool = True            # Do not respect .gitignore
    hidden: bool = False              # Search hidden files
    nice_level: int = 0               # Linux CPU niceness (0=max performance, 5=eco)
    recursive: bool = True            # Recursive directory traversal


class RipgrepEngine:
    """
    Subprocess manager for ripgrep (rg) binary with streaming output parsing.
    """

    def __init__(self, binary_path: Optional[str] = None):
        self.binary_path = self._locate_binary(binary_path)

    @staticmethod
    def _locate_binary(override_path: Optional[str] = None) -> str:
        """Finds ripgrep executable on system PATH or bundled bin/ folder."""
        if override_path and Path(override_path).exists():
            return override_path

        # 1. System PATH (/usr/bin/rg on Linux, etc.)
        system_rg = shutil.which("rg")
        if system_rg:
            return system_rg

        # 2. Local bin directory
        local_bin = Path(__file__).parent.parent / "bin"
        if sys.platform == "win32":
            candidate = local_bin / "rg.exe"
        else:
            candidate = local_bin / "rg"

        if candidate.exists():
            return str(candidate.resolve())

        # Fallback to plain "rg"
        return "rg"

    def is_available(self) -> bool:
        """Checks if ripgrep can be successfully invoked."""
        try:
            res = subprocess.run(
                [self.binary_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return res.returncode == 0
        except Exception:
            return False

    def build_command(
        self,
        patterns: List[str],
        target_path: str,
        options: RipgrepOptions,
        is_regex: bool = False,
        patterns_file: Optional[Path] = None,
        json_mode: bool = False,
    ) -> List[str]:
        """Builds command arguments for ripgrep."""
        cmd = [self.binary_path]

        # JSON mode
        if json_mode:
            cmd.append("--json")

        # Threads (concurrency cap)
        if options.threads > 0:
            cmd.extend(["--threads", str(options.threads)])

        # Memory mapping
        if options.mmap:
            cmd.append("--mmap")
        else:
            cmd.append("--no-mmap")

        # Case Sensitivity
        if options.case_sensitive:
            cmd.append("--case-sensitive")
        elif options.smart_case:
            cmd.append("--smart-case")
        else:
            cmd.append("--ignore-case")

        # Binary / Text mode: ALWAYS search as text (--text / -a) so corrupted bytes, NUL bytes, or encoding anomalies NEVER abort scanning
        cmd.append("--text")
        cmd.append("--no-messages")

        # Hidden & Git Ignore
        if options.no_ignore:
            cmd.append("--no-ignore")
        if options.hidden:
            cmd.append("--hidden")
        if not options.recursive:
            cmd.extend(["--max-depth", "1"])

        # Check if patterns contain multi-line plain text or multi-line regex expressions
        has_multiline_pattern = any(("\n" in p or "\r" in p or (is_regex and ("\\n" in p or "\\r" in p or "(?s)" in p))) for p in patterns)

        # Fixed strings vs Regex
        # If is_regex is False but pattern contains newlines, convert to cross-platform regex
        # matching both \r\n and \n without falling into -F line-boundary limitations
        active_patterns = patterns
        effective_is_regex = is_regex

        if not is_regex and has_multiline_pattern:
            # Multi-line plain text: translate literal segments with flexible line-break regex
            import re
            translated = []
            for p in patterns:
                if "\n" in p or "\r" in p:
                    lines = p.replace("\r\n", "\n").replace("\r", "\n").split("\n")
                    escaped_lines = [re.escape(l) for l in lines]
                    translated.append(r"\r?\n".join(escaped_lines))
                else:
                    translated.append(re.escape(p))
            active_patterns = translated
            effective_is_regex = True
            cmd.append("--multiline")
            if options.pcre2:
                cmd.append("--pcre2")
        elif not is_regex:
            cmd.append("--fixed-strings")
        else:
            if options.pcre2:
                cmd.append("--pcre2")
            if has_multiline_pattern:
                cmd.append("--multiline")
        effective_format = options.output_format
        if options.extract_only:
            effective_format = "extract_only"

        if effective_format == "clean":
            cmd.extend(["--no-filename", "--no-line-number"])
        elif effective_format == "separate":
            cmd.extend(["--with-filename", "--line-number", "--heading"])
        elif effective_format == "prefix":
            cmd.extend(["--with-filename", "--line-number", "--no-heading"])
        elif effective_format == "extract_only":
            cmd.extend(["--no-filename", "--no-line-number", "--only-matching"])
        else:
            cmd.extend(["--no-filename", "--no-line-number"])

        cmd.append("--color=never")

        # Add Patterns
        if patterns_file and patterns_file.exists():
            cmd.extend(["-f", str(patterns_file)])
        elif len(active_patterns) == 1:
            cmd.extend(["-e", active_patterns[0]])
        else:
            for p in active_patterns:
                cmd.extend(["-e", p])

        # Target Path
        cmd.append(str(target_path))
        return cmd

    @staticmethod
    def _get_linux_preexec(nice_level: int = 0):
        """Applies process niceness in Linux child process without unsafe fork subprocesses."""
        if not sys.platform.startswith("linux"):
            return None

        def _setup_child_priority():
            try:
                # Apply configurable niceness (0 for turbo, 2 for balanced, 5 for eco)
                if hasattr(os, "nice") and nice_level > 0:
                    os.nice(nice_level)
            except Exception:
                pass

        return _setup_child_priority

    def execute_stream(
        self,
        patterns: List[str],
        target_path: str,
        output_file: Path,
        options: Optional[RipgrepOptions] = None,
        is_regex: bool = False,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        stop_event: Optional[threading.Event] = None,
        append: bool = False,
        file_list: Optional[List[str]] = None,
    ) -> Tuple[int, float]:
        """
        Executes ripgrep directly streaming to output file on disk for maximum I/O throughput.
        Uses direct OS file descriptor redirection for 100% native kernel speed.
        Monitors file size growth in background to provide real-time telemetry.
        
        Args:
            file_list: Optional list of specific files to search. If provided, passes files
                       as positional arguments for efficient batch processing.
        """
        opts = options or RipgrepOptions()
        output_file.parent.mkdir(parents=True, exist_ok=True)

        temp_pat_file = None
        if len(patterns) > 10:
            tf = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".patterns")
            tf.write("\n".join(patterns) + "\n")
            tf.close()
            temp_pat_file = Path(tf.name)

        # Build clean raw command
        # If file_list provided, use those files instead of target_path
        cmd = self.build_command(
            patterns=patterns,
            target_path=target_path,
            options=opts,
            is_regex=is_regex,
            patterns_file=temp_pat_file,
            json_mode=False,
        )

        # If file_list provided, replace the target_path (last arg) with the file list
        if file_list:
            if cmd and not cmd[-1].startswith("-"):
                cmd.pop()  # remove target_path
            cmd.extend(file_list)

        logger.info("Executing Ripgrep: %s", " ".join(cmd[:12]) + ("..." if len(cmd) > 12 else ""))
        start_t = time.monotonic()
        proc = None
        mode = "ab" if append else "wb"
        preexec = self._get_linux_preexec(opts.nice_level)
        initial_size = output_file.stat().st_size if output_file.exists() and append else 0

        # Count line-level multiplier for multi-line patterns so match count reflects occurrences
        has_multiline_pattern = any(("\n" in p or "\r" in p or (is_regex and ("\\n" in p or "\\r" in p or "(?s)" in p))) for p in patterns)
        lines_per_match = 1
        if has_multiline_pattern:
            for p in patterns:
                nl_count = p.count("\n")
                if nl_count > 0:
                    lines_per_match = max(lines_per_match, nl_count + 1)
        current_matches = 0
        last_counted_offset = initial_size
        total_matched_lines = 0

        try:
            with open(output_file, mode) as out_f:
                # Direct file descriptor redirect: Kernel-level throughput (Multi-GB/s)
                proc = subprocess.Popen(
                    cmd,
                    stdout=out_f,
                    stderr=subprocess.PIPE,
                    preexec_fn=preexec,
                )

                # Monitor progress and handle instant cancellation without artificial sleep delays
                last_progress_check = 0.0
                while proc.poll() is None:
                    if stop_event and stop_event.is_set():
                        logger.info("Terminating Ripgrep process due to stop request...")
                        try:
                            proc.terminate()
                            proc.wait(timeout=1.0)
                        except Exception:
                            proc.kill()
                        break

                    try:
                        proc.wait(timeout=0.05)
                    except subprocess.TimeoutExpired:
                        pass

                    now = time.monotonic()
                    if progress_callback and (now - last_progress_check >= 0.5):
                        last_progress_check = now
                        try:
                            current_out_size = output_file.stat().st_size
                            if current_out_size > last_counted_offset:
                                with open(output_file, "rb") as probe_f:
                                    probe_f.seek(last_counted_offset)
                                    chunk = probe_f.read(current_out_size - last_counted_offset)
                                    if chunk:
                                        total_matched_lines += chunk.count(b"\n")
                                        current_matches = total_matched_lines // lines_per_match
                                        last_counted_offset += len(chunk)

                            progress_callback({
                                "out_bytes": current_out_size,
                                "matches": current_matches,
                                "elapsed": max(0.001, now - start_t),
                            })
                        except Exception:
                            pass

                # Ensure process finished and pipes closed
                if proc.poll() is None:
                    proc.wait()

                # Read and close stderr cleanly to prevent ResourceWarning
                if proc.stderr:
                    try:
                        if proc.returncode not in (0, 1):
                            err_msg = proc.stderr.read().decode("utf-8", errors="replace")
                            if err_msg.strip():
                                logger.warning("Ripgrep stderr: %s", err_msg.strip())
                        proc.stderr.close()
                    except Exception:
                        pass

        finally:
            if temp_pat_file and temp_pat_file.exists():
                try:
                    temp_pat_file.unlink()
                except OSError:
                    pass

        elapsed = max(0.001, time.monotonic() - start_t)

        # Final read to ensure all remaining matches appended are counted
        if output_file.exists():
            final_size = output_file.stat().st_size
            if final_size > last_counted_offset:
                try:
                    with open(output_file, "rb") as probe_f:
                        probe_f.seek(last_counted_offset)
                        buf_size = 8 * 1024 * 1024
                        while True:
                            chunk = probe_f.read(buf_size)
                            if not chunk:
                                break
                            total_matched_lines += chunk.count(b"\n")
                        current_matches = total_matched_lines // lines_per_match
                except Exception:
                    pass

        return current_matches, elapsed
