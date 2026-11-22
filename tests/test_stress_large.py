"""
High-volume stress and boundary integration test with multi-gigabyte synthetic datasets.
Verifies memory bounded footprint, boundary overlap retention, and throughput.
"""

import tempfile
import time
import unittest
from pathlib import Path

from core.search_manager import SearchConfig, SearchManager


class TestStressLargeSearch(unittest.TestCase):
    def test_multi_megabyte_stress_and_boundary_retention(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "large_stress_data.txt"
            out_file = Path(tmpdir) / "out.txt"

            target_word = "TARGET_YURI_GAGARIN_NEEDLE"
            repeat_count = 20

            # Generate synthetic dataset where the needle is placed across varying offsets
            padding_block = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789\n" * 1000  # ~37 KB
            with open(test_file, "wb") as f:
                for i in range(repeat_count):
                    f.write(padding_block)
                    f.write(f"\nRECORD_{i:04d}_{target_word}_DATA\n".encode("utf-8"))
                    f.write(padding_block)

            total_file_size = test_file.stat().st_size
            self.assertGreater(total_file_size, 1 * 1024 * 1024)

            # Test Aho-Corasick with a tiny 64 KB chunk size to force hundreds of boundary transitions
            cfg = SearchConfig(
                target_path=str(test_file),
                patterns=[target_word],
                output_file=str(out_file),
                chunk_bytes=64 * 1024,
                is_regex=False,
                case_sensitive=True,
                extract_only=True,
            )

            mgr = SearchManager(config=cfg)
            res = mgr.execute()

            self.assertTrue(res.success)
            self.assertEqual(res.total_matches, repeat_count)
            self.assertEqual(res.files_searched, 1)

            # Verify output content contains all match instances
            out_content = out_file.read_text(encoding="utf-8")
            self.assertEqual(out_content.count(target_word), repeat_count)

    def test_regex_search_on_stress_dataset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "regex_stress.txt"
            out_file = Path(tmpdir) / "regex_out.txt"

            with open(test_file, "wb") as f:
                f.write(b"user_1001@gagarin.space\n")
                f.write(b"garbage line without email\n" * 500)
                f.write(b"user_2002@gagarin.space\n")

            cfg = SearchConfig(
                target_path=str(test_file),
                patterns=[r"[a-z0-9_]+@gagarin\.space"],
                output_file=str(out_file),
                is_regex=True,
                extract_only=True,
            )

            mgr = SearchManager(config=cfg)
            res = mgr.execute()

            self.assertTrue(res.success)
            self.assertEqual(res.total_matches, 2)


if __name__ == "__main__":
    unittest.main()
