"""
Ripgrep Native Rust Engine Wrapper.
Provides extreme search speeds (multi-gigabytes per second) across massive text datasets.
Auto-detects system ripgrep binary or falls back to project local bin/rg.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("yurigagarin.engine.ripgrep")


@dataclass
class RipgrepOptions:
    threads: int = 0                  # 0 = auto-detect CPU cores
    mmap: bool = True                 # Use memory-mapped I/O for extreme read speed
    pcre2: bool = True                # Enable PCRE2 engine with JIT
    smart_case: bool = False          # Case insensitive if pattern is lowercase
    case_sensitive: bool = False      # Strict case sensitivity
    max_count: Optional[int] = None   # Limit matches
    memory_limit: Optional[str] = None # Memory limit, e.g. "2G"
    extract_only: bool = True         # Only print matching parts (-o)
    invert_match: bool = False        # Invert match (-v)
    no_ignore: bool = True            # Do not respect .gitignore
    hidden: bool = False              # Search hidden files


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

        # 1. System PATH
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

        # Threads
        if options.threads > 0:
            cmd.extend(["--threads", str(options.threads)])

        # Memory mapping
        if options.mmap:
            cmd.append("--mmap")
        else:
            cmd.append("--no-mmap")

        # Fixed strings vs Regex
        if not is_regex:
            cmd.append("--fixed-strings")
        elif options.pcre2:
            cmd.append("--pcre2")

        # Case Sensitivity
        if options.case_sensitive:
            cmd.append("--case-sensitive")
        elif options.smart_case:
            cmd.append("--smart-case")
        else:
            cmd.append("--ignore-case")

        # Hidden & Git Ignore
        if options.no_ignore:
            cmd.append("--no-ignore")
        if options.hidden:
            cmd.append("--hidden")

        # Multi-line regex support
        if is_regex:
            cmd.append("--multiline")

        # Output formatting & Mode
        if json_mode:
            cmd.append("--json")
        else:
            if options.extract_only:
                cmd.append("--only-matching")
            cmd.append("--line-number")
            cmd.append("--color=never")

        # Add Patterns
        if patterns_file and patterns_file.exists():
            cmd.extend(["-f", str(patterns_file)])
        elif len(patterns) == 1:
            cmd.extend(["-e", patterns[0]])
        else:
            for p in patterns:
                cmd.extend(["-e", p])

        # Target Path
        cmd.append(str(target_path))
        return cmd

    def execute_stream(
        self,
        patterns: List[str],
        target_path: str,
        output_file: Path,
        options: Optional[RipgrepOptions] = None,
        is_regex: bool = False,
        progress_callback: Optional[Callable[[int, float], None]] = None,
    ) -> Tuple[int, float]:
        """
        Executes ripgrep directly streaming to output file on disk for maximum I/O throughput.
        Uses JSON mode for robust match counting and extraction.
        """
        import json
        opts = options or RipgrepOptions()
        output_file.parent.mkdir(parents=True, exist_ok=True)

        temp_pat_file = None
        if len(patterns) > 10:
            tf = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".patterns")
            tf.write("\n".join(patterns) + "\n")
            tf.close()
            temp_pat_file = Path(tf.name)

        # Decide mode: use direct high-speed text streaming for fixed strings / high throughput,
        # or JSON mode when multi-line regex structured parsing is required.
        use_json = is_regex

        cmd = self.build_command(
            patterns=patterns,
            target_path=target_path,
            options=opts,
            is_regex=is_regex,
            patterns_file=temp_pat_file,
            json_mode=use_json,
        )

        logger.info("Executing Ripgrep (JSON stream): %s", " ".join(cmd[:10]) + ("..." if len(cmd) > 10 else ""))
        start_t = time.monotonic()
        total_matches = 0

        try:
            with open(output_file, "w", encoding="utf-8", errors="replace", buffering=4 * 1024 * 1024) as out_f:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=4 * 1024 * 1024,
                )

                if proc.stdout:
                    if use_json:
                        for raw_line in proc.stdout:
                            try:
                                item = json.loads(raw_line)
                                msg_type = item.get("type")
                                if msg_type == "match":
                                    data = item.get("data", {})
                                    submatches = data.get("submatches", [])
                                    total_matches += len(submatches)
                                    if opts.extract_only:
                                        for sm in submatches:
                                            out_f.write(sm.get("match", {}).get("text", "") + "\n")
                                    else:
                                        line_text = data.get("lines", {}).get("text", "").rstrip("\r\n")
                                        line_no = data.get("line_number", 0)
                                        path_text = data.get("path", {}).get("text", "")
                                        out_f.write(f"[{path_text}:{line_no}] {line_text}\n")
                            except Exception:
                                pass
                    else:
                        # Raw native speed streaming (500+ MB/s)
                        for raw_line in proc.stdout:
                            line = raw_line.decode("utf-8", errors="replace")
                            out_f.write(line)
                            total_matches += 1

                    proc.stdout.close()

                if proc.stderr:
                    proc.stderr.close()

                proc.wait()

        finally:
            if temp_pat_file and temp_pat_file.exists():
                try:
                    temp_pat_file.unlink()
                except OSError:
                    pass

        elapsed = max(0.001, time.monotonic() - start_t)
        return total_matches, elapsed
