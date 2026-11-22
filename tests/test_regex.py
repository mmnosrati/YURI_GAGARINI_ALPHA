"""
Unit & ReDoS watchdog tests for JIT Regex search engine.
"""

import unittest
from core.engine_regex import RegexEngine


class TestRegexEngine(unittest.TestCase):
    def test_regex_matching(self):
        engine = RegexEngine([r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"], case_sensitive=False)
        data = b"Contact us at admin@yurigagarin.space or test.user@domain.com today."
        matches = engine.scan_block(data)
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0].matched_bytes, b"admin@yurigagarin.space")
        self.assertEqual(matches[1].matched_bytes, b"test.user@domain.com")

    def test_catastrophic_backtracking_watchdog(self):
        # Known catastrophic backtracking pattern: (a+)+$
        engine = RegexEngine([r"^(a+)+$"], timeout_ms=100)
        evil_line = b"a" * 30 + b"!"
        # Watchdog should prevent timeout lockup and safely return empty list
        matches = engine.scan_line_with_watchdog(evil_line, line_start_abs=0)
        self.assertEqual(len(matches), 0)


if __name__ == "__main__":
    unittest.main()
