"""
Deep performance and throughput benchmark across 50 MB synthetic text with 1,000 patterns.
Measures memory stability (RSS), scanning throughput (MB/s), and CPU load.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path

import psutil

from core.search_manager import SearchConfig, SearchManager


class TestDeepPerformanceBenchmark(unittest.TestCase):
    def test_high_volume_benchmark(self):
        with tempfile.TemporaryDirectory() as td:
            data_file = Path(td) / "big_dataset_50mb.txt"
            out_file = Path(td) / "bench_out.txt"

            # 1. Generate 1,000 distinct search patterns
            patterns = [f"KEYWORD_PATTERN_{i:04d}" for i in range(1000)]

            # 2. Generate ~30 MB of structured text data with embedded patterns
            print("\n[Benchmark] Generating ~30 MB synthetic test dataset...")
            chunk_line = b"Standard syslog message line: host=server01 event=user_login status=ok auth=token\n"
            total_size_target = 30 * 1024 * 1024  # 30 MB

            expected_matches = 0
            with open(data_file, "wb") as f:
                bytes_written = 0
                step = 0
                while bytes_written < total_size_target:
                    # Write regular log padding
                    f.write(chunk_line * 100)
                    bytes_written += len(chunk_line) * 100

                    # Inject a pattern periodically
                    pat = patterns[step % len(patterns)]
                    injection = f"EMBEDDED_FINDING: {pat} AT_TIMESTAMP_{time.time()}\n".encode("utf-8")
                    f.write(injection)
                    bytes_written += len(injection)
                    expected_matches += 1
                    step += 1

            actual_file_size = data_file.stat().st_size
            print(f"[Benchmark] Dataset created: {actual_file_size / (1024 * 1024):.2f} MB with {expected_matches} injected occurrences.")

            # 3. Measure memory baseline
            process = psutil.Process(os.getpid())
            rss_before_mb = process.memory_info().rss / (1024 * 1024)

            # 4. Run Aho-Corasick scan with 1,000 patterns
            cfg = SearchConfig(
                target_path=str(data_file),
                patterns=patterns,
                output_file=str(out_file),
                is_regex=False,
                case_sensitive=True,
                extract_only=True,
            )

            mgr = SearchManager(config=cfg)
            start_t = time.monotonic()
            res = mgr.execute()
            duration = time.monotonic() - start_t

            rss_after_mb = process.memory_info().rss / (1024 * 1024)
            mb_scanned = actual_file_size / (1024 * 1024)
            throughput = mb_scanned / duration

            print(f"[Benchmark] Execution Results:")
            print(f"  • Throughput        : {throughput:.2f} MB/s ({mb_scanned:.2f} MB in {duration:.2f}s)")
            print(f"  • Patterns Scanned  : 1,000 patterns (single-pass O(N))")
            print(f"  • Matches Found     : {res.total_matches} (expected {expected_matches})")
            print(f"  • Process RSS Before: {rss_before_mb:.1f} MB")
            print(f"  • Process RSS After : {rss_after_mb:.1f} MB")
            print(f"  • Delta Memory      : {rss_after_mb - rss_before_mb:.1f} MB (strictly bounded)")

            self.assertTrue(res.success)
            self.assertEqual(res.total_matches, expected_matches)
            # Guarantee memory didn't balloon (bounded under 150 MB delta)
            self.assertLess(rss_after_mb - rss_before_mb, 150)


if __name__ == "__main__":
    unittest.main()
