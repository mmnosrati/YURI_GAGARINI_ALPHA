"""
Comprehensive Automated Test Suite for Multi-line Plain Text Search,
Output File Mission Header Prepending, and Rich Telegram Reporting.
"""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from core.engine_ripgrep import RipgrepEngine, RipgrepOptions
from core.search_manager import SearchManager, SearchConfig
from server.telegram_service import TelegramService


class TestMultilineAndReportingSuite(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="yuri_multiline_test_"))
        self.engine = RipgrepEngine()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_multiline_literal_unix_lf(self):
        """Tests multi-line plain text search across standard LF line breaks."""
        test_file = self.temp_dir / "unix_sample.txt"
        test_file.write_bytes(
            b"Line 1\n"
            b"START_BLOCK\n"
            b"Target Payload Alpha\n"
            b"END_BLOCK\n"
            b"Line 5\n"
        )
        out_file = self.temp_dir / "out_01.txt"
        pattern = "START_BLOCK\nTarget Payload Alpha\nEND_BLOCK"

        matches, elapsed = self.engine.execute_stream(
            patterns=[pattern],
            target_path=str(test_file),
            output_file=out_file,
            options=RipgrepOptions(output_format="clean"),
            is_regex=False,
        )
        self.assertEqual(matches, 1)
        self.assertTrue(out_file.exists())
        content = out_file.read_text(encoding="utf-8")
        self.assertIn("Target Payload Alpha", content)

    def test_02_multiline_literal_windows_crlf(self):
        """Tests that a pattern containing LF matches files containing CRLF."""
        test_file = self.temp_dir / "windows_sample.txt"
        test_file.write_bytes(
            b"Header\r\n"
            b"AuthToken: 998877\r\n"
            b"User: Admin\r\n"
            b"Footer\r\n"
        )
        out_file = self.temp_dir / "out_02.txt"
        pattern = "AuthToken: 998877\nUser: Admin"

        matches, elapsed = self.engine.execute_stream(
            patterns=[pattern],
            target_path=str(test_file),
            output_file=out_file,
            options=RipgrepOptions(output_format="clean"),
            is_regex=False,
        )
        self.assertEqual(matches, 1)
        content = out_file.read_text(encoding="utf-8")
        self.assertIn("AuthToken: 998877", content)

    def test_03_multiline_literal_case_sensitivity(self):
        """Tests case sensitivity enforcement on multi-line literal searches."""
        test_file = self.temp_dir / "case_sample.txt"
        test_file.write_bytes(b"HELLO\nWORLD\nhello\nworld\n")
        out_file = self.temp_dir / "out_03.txt"

        # Case-sensitive: should match only 1
        matches_sens, _ = self.engine.execute_stream(
            patterns=["HELLO\nWORLD"],
            target_path=str(test_file),
            output_file=out_file,
            options=RipgrepOptions(case_sensitive=True, output_format="clean"),
            is_regex=False,
        )
        self.assertEqual(matches_sens, 1)

        # Case-insensitive: should match both 2
        out_file_insens = self.temp_dir / "out_03_insens.txt"
        matches_insens, _ = self.engine.execute_stream(
            patterns=["HELLO\nWORLD"],
            target_path=str(test_file),
            output_file=out_file_insens,
            options=RipgrepOptions(case_sensitive=False, output_format="clean"),
            is_regex=False,
        )
        self.assertEqual(matches_insens, 2)

    def test_04_directory_pipeline_multiline_and_header(self):
        """Tests file-by-file pipeline with multiline pattern and header prepending."""
        dir_target = self.temp_dir / "data_folder"
        dir_target.mkdir()

        # File A: 2 matches
        (dir_target / "file_a.txt").write_bytes(
            b"prefix\n[TAG]\nVALUE\nsuffix\n[TAG]\nVALUE\n"
        )
        # File B: 1 match
        (dir_target / "file_b.txt").write_bytes(
            b"random\n[TAG]\nVALUE\nend\n"
        )
        # File C: 0 matches
        (dir_target / "file_c.txt").write_bytes(b"no match here\n")

        out_dest = self.temp_dir / "final_report.txt"
        cfg = SearchConfig(
            target_path=str(dir_target),
            patterns=["[TAG]\nVALUE"],
            engine_type="ripgrep",
            is_regex=False,
            output_file=str(out_dest),
            output_format="clean",
        )
        mgr = SearchManager(cfg)
        result = mgr.execute()

        self.assertTrue(result.success)
        self.assertEqual(result.total_matches, 3)
        self.assertTrue(out_dest.exists())

        content = out_dest.read_text(encoding="utf-8")
        # Verify Mission Header presence
        self.assertIn("YURI GAGARIN ALPHA - ENTERPRISE BIG-DATA SEARCH MISSION REPORT", content)
        self.assertIn("• Total Matches   : 3", content)
        self.assertIn("TOP MATCHED FILES (HIGHEST DENSITY):", content)
        self.assertIn("file_a.txt: 2 matches", content)
        self.assertIn("file_b.txt: 1 matches", content)

    def test_05_telegram_rich_caption_generation(self):
        """Validates that Telegram caption correctly formats patterns and top matched files within length constraints."""
        tg = TelegramService(token="123:TEST", chat_id="999", enabled=True)
        dummy_out = self.temp_dir / "sample_results.txt"
        dummy_out.write_text("dummy results line\n")

        stats = {
            "job_id": "job_unit_test_8877",
            "target_path": "/root/Downloads/massive_data",
            "total_matches": 158200,
            "elapsed_seconds": 12.45,
            "throughput_mb_s": 765.20,
            "patterns": [
                "SELECT * FROM users\nWHERE is_admin=1",
                "api_key = sec_live_12345",
            ],
            "file_statistics": {
                "users_dump.sql": {"matches": 120000},
                "audit.log": {"matches": 38200},
            },
        }

        # Intercept caption formatting
        orig_send_document = tg.send_document
        captured_caption = []

        def mock_send_document(p, caption=""):
            captured_caption.append(caption)
            return True

        tg.send_document = mock_send_document
        tg.send_output_file_multipart(dummy_out, stats)

        self.assertTrue(len(captured_caption) > 0)
        cap = captured_caption[0]

        self.assertIn("YURI GAGARIN ALPHA - MISSION REPORT", cap)
        self.assertIn("158,200", cap)
        self.assertIn("SELECT * FROM users\\nWHERE is_admin=1", cap)
        self.assertIn("(Multi-line)", cap)
        self.assertIn("users_dump.sql", cap)
        self.assertIn("75.9%", cap)
        self.assertLessEqual(len(cap), 1024)

    def test_06_single_line_speed_preserved(self):
        """Verifies that single-line searches still use fast fixed-strings without multiline flag overhead."""
        cmd = self.engine.build_command(
            patterns=["simple_keyword"],
            target_path="/tmp/test.txt",
            options=RipgrepOptions(),
            is_regex=False,
        )
        self.assertIn("--fixed-strings", cmd)
        self.assertNotIn("--multiline", cmd)

        # Multi-line should have --multiline
        cmd_multi = self.engine.build_command(
            patterns=["line1\nline2"],
            target_path="/tmp/test.txt",
            options=RipgrepOptions(),
            is_regex=False,
        )
        self.assertIn("--multiline", cmd_multi)


if __name__ == "__main__":
    unittest.main(verbosity=2)
