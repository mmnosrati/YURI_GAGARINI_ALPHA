"""
Ultra-High-Speed Vectorized Aho-Corasick Multi-Pattern Search Engine.
Scans multiple literal patterns simultaneously in a single pass O(N) over binary buffers,
with seamless chunk boundary overlap handling for 100+ GB files.
"""

from __future__ import annotations

import collections
import logging
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Set, Tuple

logger = logging.getLogger("yurigagarin.engine.aho")


@dataclass(slots=True)
class AhoMatch:
    pattern_index: int
    pattern_bytes: bytes
    absolute_start: int
    absolute_end: int


class AhoCorasickEngine:
    """
    Optimized Trie-based Aho-Corasick binary automaton for byte streams.
    Provides single-pass multi-pattern matching across arbitrary byte buffers.
    """

    def __init__(self, patterns: List[str | bytes], case_sensitive: bool = True):
        self.case_sensitive = case_sensitive
        self.patterns_raw: List[bytes] = []
        self.patterns_normalized: List[bytes] = []

        # Sanitize and deduplicate patterns
        seen: Set[bytes] = set()
        for p in patterns:
            raw = p.encode("utf-8") if isinstance(p, str) else bytes(p)
            if not raw:
                continue
            norm = raw if case_sensitive else raw.lower()
            if norm not in seen:
                seen.add(norm)
                self.patterns_raw.append(raw)
                self.patterns_normalized.append(norm)

        if not self.patterns_raw:
            raise ValueError("AhoCorasickEngine requires at least one non-empty pattern.")

        self.max_pattern_len = max(len(p) for p in self.patterns_raw)
        self.min_pattern_len = min(len(p) for p in self.patterns_raw)
        self.total_patterns = len(self.patterns_raw)

        # Build automaton tables:
        # trie: list of dicts mapping byte (int) -> state (int)
        # fail: list of state failure pointers
        # output: list of list of (pattern_index, pattern_len)
        self.trie: List[Dict[int, int]] = [{}]
        self.fail: List[int] = [0]
        self.output: List[List[Tuple[int, int]]] = [[]]

        self._build_trie()
        self._build_failure_links()

    def _build_trie(self) -> None:
        """Constructs the keyword tree (Trie)."""
        for idx, pattern in enumerate(self.patterns_normalized):
            curr_state = 0
            for b in pattern:
                byte_val = int(b)
                if byte_val not in self.trie[curr_state]:
                    new_state = len(self.trie)
                    self.trie[curr_state][byte_val] = new_state
                    self.trie.append({})
                    self.fail.append(0)
                    self.output.append([])
                curr_state = self.trie[curr_state][byte_val]
            self.output[curr_state].append((idx, len(pattern)))

    def _build_failure_links(self) -> None:
        """Constructs failure links and dictionary suffix links (BFS)."""
        queue = collections.deque()

        # Depth 1 states fail to root (0)
        for byte_val, next_state in self.trie[0].items():
            self.fail[next_state] = 0
            queue.append(next_state)

        while queue:
            state = queue.popleft()

            for byte_val, next_state in self.trie[state].items():
                queue.append(next_state)

                # Trace failure link
                fail_state = self.fail[state]
                while fail_state > 0 and byte_val not in self.trie[fail_state]:
                    fail_state = self.fail[fail_state]

                if byte_val in self.trie[fail_state] and self.trie[fail_state][byte_val] != next_state:
                    self.fail[next_state] = self.trie[fail_state][byte_val]
                else:
                    self.fail[next_state] = 0

                # Merge output matches from failure link
                if self.output[self.fail[next_state]]:
                    self.output[next_state].extend(self.output[self.fail[next_state]])

    def scan_chunk(
        self,
        chunk: bytes,
        start_abs_offset: int = 0,
        initial_state: int = 0,
    ) -> Tuple[List[AhoMatch], int]:
        """
        Scans a byte buffer and returns matches along with the ending state for streaming continuity.
        """
        haystack = chunk if self.case_sensitive else chunk.lower()
        state = initial_state
        matches: List[AhoMatch] = []

        trie = self.trie
        fail = self.fail
        out_table = self.output

        for idx, byte_val in enumerate(haystack):
            while state > 0 and byte_val not in trie[state]:
                state = fail[state]

            state = trie[state].get(byte_val, 0)

            if out_table[state]:
                for pat_idx, pat_len in out_table[state]:
                    match_end_local = idx + 1
                    match_start_local = match_end_local - pat_len
                    abs_start = start_abs_offset + match_start_local
                    abs_end = start_abs_offset + match_end_local
                    matches.append(
                        AhoMatch(
                            pattern_index=pat_idx,
                            pattern_bytes=self.patterns_raw[pat_idx],
                            absolute_start=abs_start,
                            absolute_end=abs_end,
                        )
                    )

        return matches, state

    def search_stream(
        self,
        chunks_iterator: Iterator[bytes],
        initial_abs_offset: int = 0,
    ) -> Iterator[AhoMatch]:
        """
        Yields all matches continuously across chunks while preserving state.
        Handles carry-over bounds automatically.
        """
        abs_offset = initial_abs_offset
        state = 0

        for chunk in chunks_iterator:
            matches, state = self.scan_chunk(
                chunk=chunk,
                start_abs_offset=abs_offset,
                initial_state=state,
            )
            for m in matches:
                yield m
            abs_offset += len(chunk)
