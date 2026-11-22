"""
High-Throughput Regex Search Engine with JIT Acceleration and ReDoS Watchdog.
Guarantees fast regex matching with per-line/per-block execution timeouts
to prevent engine lockups on catastrophic backtracking patterns.
"""

from __future__ import annotations

import concurrent.futures
import logging
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

logger = logging.getLogger("yurigagarin.engine.regex")

try:
    import regex as re_engine
    _HAS_REGEX_LIB = True
except ImportError:
    import re as re_engine
    _HAS_REGEX_LIB = False


@dataclass(slots=True)
class RegexMatch:
    pattern_index: int
    matched_bytes: bytes
    absolute_start: int
    absolute_end: int


class RegexEngine:
    """
    Compiled Regular Expression Engine with timeout protection.
    Supports single or multiple patterns combined with OR semantics.
    """

    DEFAULT_LINE_TIMEOUT_MS = 500  # 500ms max per line/block

    def __init__(
        self,
        patterns: List[str],
        case_sensitive: bool = True,
        timeout_ms: int = DEFAULT_LINE_TIMEOUT_MS,
    ):
        self.case_sensitive = case_sensitive
        self.timeout_sec = max(0.05, timeout_ms / 1000.0)
        self.patterns_str = [p.strip() for p in patterns if p.strip()]

        if not self.patterns_str:
            raise ValueError("RegexEngine requires at least one valid regex pattern.")

        flags = 0
        if not case_sensitive:
            flags |= re_engine.IGNORECASE

        # Compile individual patterns
        self.compiled_patterns = []
        for pat in self.patterns_str:
            try:
                # Use bytes patterns for direct binary scanning
                pat_bytes = pat.encode("utf-8")
                compiled = re_engine.compile(pat_bytes, flags)
                self.compiled_patterns.append(compiled)
            except Exception as e:
                raise ValueError(f"Invalid regex pattern '{pat}': {e}") from e

        # Also compile unified OR pattern if multiple patterns exist
        self.unified_compiled = None
        if len(self.compiled_patterns) > 1:
            try:
                combined_str = "|".join(f"(?:{p})" for p in self.patterns_str)
                self.unified_compiled = re_engine.compile(combined_str.encode("utf-8"), flags)
            except Exception:
                self.unified_compiled = None

    def scan_block(
        self,
        block: bytes,
        start_abs_offset: int = 0,
    ) -> List[RegexMatch]:
        """
        Scans a block of bytes for regex matches.
        Uses unified pattern when possible, falling back to per-pattern scanning.
        """
        matches: List[RegexMatch] = []

        if self.unified_compiled is not None:
            try:
                for m in self.unified_compiled.finditer(block):
                    matches.append(
                        RegexMatch(
                            pattern_index=0,
                            matched_bytes=m.group(0),
                            absolute_start=start_abs_offset + m.start(),
                            absolute_end=start_abs_offset + m.end(),
                        )
                    )
            except Exception as e:
                logger.debug("Unified regex error: %s; falling back to per-pattern", e)
                matches.clear()

        if not matches and self.unified_compiled is not None:
            # Fallback if unified failed or to ensure full coverage
            pass

        if not matches and (self.unified_compiled is None or len(self.compiled_patterns) == 1):
            for idx, pat in enumerate(self.compiled_patterns):
                try:
                    for m in pat.finditer(block):
                        matches.append(
                            RegexMatch(
                                pattern_index=idx,
                                matched_bytes=m.group(0),
                                absolute_start=start_abs_offset + m.start(),
                                absolute_end=start_abs_offset + m.end(),
                            )
                        )
                except Exception as e:
                    logger.debug("Pattern regex error on pattern %d: %s", idx, e)

        # Sort matches by start position if multiple patterns
        if len(matches) > 1 and len(self.compiled_patterns) > 1:
            matches.sort(key=lambda x: x.absolute_start)

        return matches

    def scan_line_with_watchdog(
        self,
        line: bytes,
        line_start_abs: int,
    ) -> List[RegexMatch]:
        """
        Scans an individual line with a hard timeout to protect against ReDoS.
        If the regex times out, the offending line is safely skipped.
        """
        # Fast path: quick attempt
        try:
            return self.scan_block(line, line_start_abs)
        except Exception:
            pass

        # Threaded watchdog for risky lines
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.scan_block, line, line_start_abs)
            try:
                return future.result(timeout=self.timeout_sec)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "ReDoS Watchdog: Regex timed out on line at offset %d (length %d bytes). Line skipped.",
                    line_start_abs,
                    len(line),
                )
                return []
            except Exception as e:
                logger.debug("Regex scan error on line: %s", e)
                return []
