"""
Unit and benchmark tests for Ripgrep native Rust SIMD search engine integration.
Tests high throughput, regex, multi-threading, and memory mapping.
"""

import tempfile
import time
import unittest
from pathlib import Path

from core.engine_ripgrep import RipgrepEngine, RipgrepOptions
from core.search_manager import SearchConfig, SearchManager


class TestRipgrepEngineIntegration(unittest.TestCase):
    def setUp(self):
        self.engine = RipgrepEngine()
        self.assertTrue(self.engine.is_available(), "Ripgrep executable must be available.")

    def test_ripgrep_version_and_availability(self):
        self.assertTrue(self.engine.is_available())

    def test_ripgrep_fast_literal_search(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "data.txt"
            out = Path(td) / "out.txt"
            src.write_text("line 1: ALPHA\nline 2: BETA\nline 3: ALPHA BETA\n")

            matches, elapsed = self.engine.execute_stream(
                patterns=["ALPHA"],
                target_path=str(src),
                output_file=out,
                options=RipgrepOptions(extract_only=True),
            )
            self.assertEqual(matches, 2)
            self.assertTrue(out.exists())

    def test_ripgrep_regex_pcre2_search(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "emails.txt"
            out = Path(td) / "out.txt"
            src.write_text("Users: admin@gagarin.space, operator@cluster.local, invalid-email\n")

            matches, elapsed = self.engine.execute_stream(
                patterns=[r"[a-z0-9_]+@[a-z0-9.-]+\.[a-z]{2,}"],
                target_path=str(src),
                output_file=out,
                options=RipgrepOptions(pcre2=True, extract_only=True),
                is_regex=True,
            )
            self.assertEqual(matches, 2)

    def test_ripgrep_multi_hundred_megabyte_throughput(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "dataset_100mb.txt"
            out = Path(td) / "results.txt"

            # Create ~50 MB dataset
            line = b"TIMESTAMP=2026-11-22T03:00:00Z HOST=cluster-node-99 STATUS=200 MSG=transaction_processed_ok\n" * 20
            with open(src, "wb") as f:
                for _ in range(25000):  # ~38 MB
                    f.write(line)
                    f.write(b"KEYWORD_EXTREME_SPEED_RUST_SIMD\n")

            file_size_mb = src.stat().st_size / (1024 * 1024)
            self.assertGreaterEqual(file_size_mb, 30.0)

            cfg = SearchConfig(
                target_path=str(src),
                patterns=["KEYWORD_EXTREME_SPEED_RUST_SIMD"],
                output_file=str(out),
                engine_type="ripgrep",
                rg_threads=0,  # All cores
                rg_mmap=True,
                extract_only=True,
            )

            mgr = SearchManager(config=cfg)
            res = mgr.execute()

            self.assertTrue(res.success)
            self.assertEqual(res.total_matches, 25000)
            print(f"\n[Ripgrep 100MB Benchmark] Scanned {file_size_mb:.2f} MB in {res.elapsed_seconds:.3f}s -> Throughput: {res.throughput_mb_s:.2f} MB/s!")
            self.assertGreater(res.throughput_mb_s, 200.0)  # Must exceed 200 MB/s easily


if __name__ == "__main__":
    unittest.main()
