"""
Unit & boundary tests for Aho-Corasick multi-pattern search engine.
"""

import unittest
from core.engine_aho import AhoCorasickEngine


class TestAhoCorasickEngine(unittest.TestCase):
    def test_single_pattern_match(self):
        engine = AhoCorasickEngine(["alpha"], case_sensitive=True)
        data = b"xyz alpha 123"
        matches, _ = engine.scan_chunk(data)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].pattern_bytes, b"alpha")
        self.assertEqual(matches[0].absolute_start, 4)
        self.assertEqual(matches[0].absolute_end, 9)

    def test_multi_pattern_match(self):
        engine = AhoCorasickEngine(["alpha", "beta", "gamma"], case_sensitive=False)
        data = b"alpha GAMMA beta ALPHA"
        matches, _ = engine.scan_chunk(data)
        self.assertEqual(len(matches), 4)

    def test_case_insensitivity(self):
        engine = AhoCorasickEngine(["TARGET"], case_sensitive=False)
        data = b"target Target TARGET tArGeT"
        matches, _ = engine.scan_chunk(data)
        self.assertEqual(len(matches), 4)

    def test_chunk_streaming_state(self):
        engine = AhoCorasickEngine(["splitpattern"], case_sensitive=True)
        part1 = b"some prefix split"
        part2 = b"pattern suffix"

        m1, state = engine.scan_chunk(part1, start_abs_offset=0, initial_state=0)
        self.assertEqual(len(m1), 0)

        m2, _ = engine.scan_chunk(part2, start_abs_offset=len(part1), initial_state=state)
        self.assertEqual(len(m2), 1)
        self.assertEqual(m2[0].pattern_bytes, b"splitpattern")
        self.assertEqual(m2[0].absolute_start, 12)
        self.assertEqual(m2[0].absolute_end, 24)


if __name__ == "__main__":
    unittest.main()
