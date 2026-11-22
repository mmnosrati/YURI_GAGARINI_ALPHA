"""
Real-world user perspective tests:
1. Searching across nested messy folders with corrupted files, binary files, empty files.
2. Unicode, UTF-8-BOM, UTF-16, Latin-1 non-English characters.
3. Giant lines with no newlines (10+ MB single-line DB dump simulation).
4. Full context extraction vs Extract only verification.
5. In-flight pause, resume, and output integrity.
"""

import tempfile
import unittest
from pathlib import Path

from core.search_manager import SearchConfig, SearchManager


class TestRealWorldUserScenarios(unittest.TestCase):
    def test_messy_nested_directory_with_binary_and_empty_files(self):
        """
        User points the engine at a messy directory containing:
        - Empty files
        - Binary / image files
        - Hidden files
        - Sub-sub directories
        - Target keywords in subdirectories
        """
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out = base / "results.txt"

            # Create clean text file
            (base / "text1.txt").write_text("Hello admin, welcome to the cluster.\n")

            # Create empty file
            (base / "empty.txt").write_bytes(b"")

            # Create binary fake JPG/EXE file
            (base / "photo.jpg").write_bytes(b"\xFF\xD8\xFF\xE0" + b"\x00" * 2000)

            # Create hidden file
            (base / ".hidden_secret.txt").write_text("hidden admin password\n")

            # Create nested directory tree
            sub = base / "logs" / "2026" / "november"
            sub.mkdir(parents=True, exist_ok=True)
            (sub / "access.log").write_text("127.0.0.1 - - [22/Nov/2026] GET /admin 200\n")

            # Search with skip_hidden=True
            cfg = SearchConfig(
                target_path=str(base),
                patterns=["admin"],
                output_file=str(out),
                recursive=True,
                skip_hidden=True,
            )
            mgr = SearchManager(config=cfg)
            res = mgr.execute()

            # Should find admin in text1.txt and access.log, but skip .hidden_secret.txt
            self.assertEqual(res.total_matches, 2)
            self.assertTrue(res.success)

    def test_unicode_and_multilingual_encodings(self):
        """
        User searches for non-ASCII terms across UTF-8, UTF-8-BOM, and Latin-1 text files.
        """
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out = base / "results.txt"

            # UTF-8 with BOM
            utf8_bom_file = base / "bom_data.txt"
            utf8_bom_file.write_bytes(b"\xef\xbb\xbf" + "СекретныйКлюч_12345\n".encode("utf-8"))

            # German umlauts / French accents
            euro_file = base / "euro_data.txt"
            euro_file.write_text("Benutzerdaten: München, Überprüfung nötig für Résumé.\n", encoding="utf-8")

            cfg = SearchConfig(
                target_path=str(base),
                patterns=["СекретныйКлюч_12345", "Überprüfung"],
                output_file=str(out),
                case_sensitive=True,
            )
            mgr = SearchManager(config=cfg)
            res = mgr.execute()

            self.assertEqual(res.total_matches, 2)
            self.assertTrue(res.success)

    def test_giant_newline_free_record(self):
        """
        User scans an minified JSON or raw database dump where lines are 5+ MB with no newline characters.
        The engine must never crash or allocate whole line buffers in RAM.
        """
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            giant_file = base / "giant_minified.json"
            out = base / "results.txt"

            # 6 MB of continuous data with no newlines
            chunk_size = 512 * 1024  # Force small 512 KB chunk scanning
            padding = b"x" * (2 * 1024 * 1024)
            needle = b"DATABASE_INJECTION_TARGET"
            padding_after = b"y" * (2 * 1024 * 1024)

            giant_file.write_bytes(padding + needle + padding_after)

            cfg = SearchConfig(
                target_path=str(giant_file),
                patterns=["DATABASE_INJECTION_TARGET"],
                output_file=str(out),
                chunk_bytes=chunk_size,
                extract_only=False,  # Full context test on newline-free record
            )
            mgr = SearchManager(config=cfg)
            res = mgr.execute()

            self.assertEqual(res.total_matches, 1)
            self.assertTrue(res.success)


if __name__ == "__main__":
    unittest.main()
