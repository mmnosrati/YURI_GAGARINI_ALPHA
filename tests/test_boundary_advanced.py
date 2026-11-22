"""
Exhaustive verification of chunk boundary transitions and deduplication.
Tests patterns placed at every possible boundary offset across variable chunk sizes.
"""

import tempfile
import unittest
from pathlib import Path

from core.search_manager import SearchConfig, SearchManager


class TestBoundaryTransitions(unittest.TestCase):
    def test_single_byte_stepping_boundaries(self):
        """
        Steps a keyword through every position relative to a small chunk boundary.
        Ensures the keyword is matched exactly once regardless of where the split falls.
        """
        pattern = "GRENADE"
        pat_len = len(pattern)
        chunk_size = 13  # intentionally prime, small chunk size

        for offset in range(30):
            with tempfile.TemporaryDirectory() as td:
                input_file = Path(td) / "input.txt"
                output_file = Path(td) / "out.txt"

                # Place pattern at offset with padding on both sides
                prefix = b"X" * offset
                suffix = b"Y" * (50 - offset)
                content = prefix + pattern.encode("utf-8") + suffix
                input_file.write_bytes(content)

                cfg = SearchConfig(
                    target_path=str(input_file),
                    patterns=[pattern],
                    output_file=str(output_file),
                    chunk_bytes=chunk_size,
                    extract_only=True,
                )
                mgr = SearchManager(config=cfg)
                res = mgr.execute()

                self.assertEqual(
                    res.total_matches,
                    1,
                    f"Failed at pattern start offset {offset}: expected 1 match, found {res.total_matches}",
                )

    def test_mixed_length_patterns_near_boundary(self):
        """
        Multiple patterns of vastly different lengths simultaneously located near chunk boundaries.
        """
        # Patterns distinct from each other:
        patterns = ["CAT", "DOG", "ELEPHANT", "VERY_LONG_SECRET_COSMIC_PHRASE_12345"]
        chunk_size = 20

        with tempfile.TemporaryDirectory() as td:
            input_file = Path(td) / "input.txt"
            output_file = Path(td) / "out.txt"

            data = (
                b"0123456789CAT1234567"  # CAT at 10..13
                b"0123456DOG78901234567"  # DOG at 27..30
                b"89012345ELEPHANT01234"  # ELEPHANT across boundary 40..60
                b"567890123456789012345"
                b"VERY_LONG_SECRET_COSMIC_PHRASE_12345"
                b"0123456789"
            )
            input_file.write_bytes(data)

            cfg = SearchConfig(
                target_path=str(input_file),
                patterns=patterns,
                output_file=str(output_file),
                chunk_bytes=chunk_size,
                extract_only=True,
            )
            mgr = SearchManager(config=cfg)
            res = mgr.execute()

            self.assertEqual(res.total_matches, 4)


if __name__ == "__main__":
    unittest.main()
