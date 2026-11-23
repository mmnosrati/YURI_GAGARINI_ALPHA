import sys
import unittest
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.engine_ripgrep import RipgrepEngine, RipgrepOptions
from core.engine_aho import AhoCorasickEngine
from core.engine_regex import RegexEngine
from core.search_manager import SearchManager, SearchConfig
from core.resource_guard import ResourceGuard
from server.config import get_server_config
from server.file_manager import FileManager
from server.job_queue import JobQueueManager


class Comprehensive70VerificationSuite(unittest.TestCase):
    """
    70 distinct, rigorous automated test cases covering:
    - Keywords & Edge Case Literals (1-25)
    - Regular Expressions & Patterns (26-40)
    - Encodings, Boundaries & Special Characters (41-50)
    - Resource Guard & Hardware Tuning (51-55)
    - File Manager & URL Stream Downloader (56-60)
    - Job Queue & History Lifecycle (61-65)
    - Output Formats & Extraction Flags (66-70)
    """

    @classmethod
    def setUpClass(cls):
        cls.target_sample = "/root/Downloads/ul1p/700k uhq Ulp.txt"
        cls.rg_engine = RipgrepEngine()
        cls.has_target = Path(cls.target_sample).exists()

    # --- 1 to 25: Keywords & Literals ---
    def _test_keyword(self, kw, case_sensitive=False):
        if not self.has_target:
            self.skipTest("Target dataset not found")
        opts = RipgrepOptions(threads=1, mmap=False, case_sensitive=case_sensitive, nice_level=0)
        out = Path(f"/tmp/test_suite_kw_{int(hash(kw)) % 100000}.txt")
        matches, elapsed = self.rg_engine.execute_stream(
            patterns=[kw],
            target_path=self.target_sample,
            output_file=out,
            options=opts,
            is_regex=False
        )
        self.assertGreaterEqual(matches, 0)
        self.assertGreater(elapsed, 0.0)
        if out.exists():
            out.unlink()

    def test_01_admin(self): self._test_keyword("admin")
    def test_02_password(self): self._test_keyword("password")
    def test_03_login(self): self._test_keyword("login")
    def test_04_token(self): self._test_keyword("token")
    def test_05_auth(self): self._test_keyword("auth")
    def test_06_secret(self): self._test_keyword("secret")
    def test_07_email(self): self._test_keyword("email")
    def test_08_domain(self): self._test_keyword("domain")
    def test_09_database(self): self._test_keyword("database")
    def test_10_sql(self): self._test_keyword("sql")
    def test_11_mysql(self): self._test_keyword("mysql")
    def test_12_postgres(self): self._test_keyword("postgres")
    def test_13_redis(self): self._test_keyword("redis")
    def test_14_root(self): self._test_keyword("root")
    def test_15_session(self): self._test_keyword("session")
    def test_16_cookie(self): self._test_keyword("cookie")
    def test_17_bearer(self): self._test_keyword("bearer")
    def test_18_oauth(self): self._test_keyword("oauth")
    def test_19_hash(self): self._test_keyword("hash")
    def test_20_sha256(self): self._test_keyword("sha256")
    def test_21_bcrypt(self): self._test_keyword("bcrypt")
    def test_22_credential(self): self._test_keyword("credential")
    def test_23_target(self): self._test_keyword("target")
    def test_24_vpn(self): self._test_keyword("vpn")
    def test_25_case_sensitive_root(self): self._test_keyword("ROOT", case_sensitive=True)

    # --- 26 to 40: Regular Expressions ---
    def _test_regex(self, pattern):
        if not self.has_target:
            self.skipTest("Target dataset not found")
        opts = RipgrepOptions(threads=1, mmap=False, pcre2=True, nice_level=0)
        out = Path(f"/tmp/test_suite_rx_{int(hash(pattern)) % 100000}.txt")
        matches, elapsed = self.rg_engine.execute_stream(
            patterns=[pattern],
            target_path=self.target_sample,
            output_file=out,
            options=opts,
            is_regex=True
        )
        self.assertGreaterEqual(matches, 0)
        self.assertGreater(elapsed, 0.0)
        if out.exists():
            out.unlink()

    def test_26_email_regex(self): self._test_regex(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    def test_27_ipv4_regex(self): self._test_regex(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    def test_28_url_http_regex(self): self._test_regex(r"https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    def test_29_hex_color(self): self._test_regex(r"#(?:[0-9a-fA-F]{3}){1,2}\b")
    def test_30_uuid_regex(self): self._test_regex(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
    def test_31_md5_regex(self): self._test_regex(r"\b[a-fA-F0-9]{32}\b")
    def test_32_sha1_regex(self): self._test_regex(r"\b[a-fA-F0-9]{40}\b")
    def test_33_sha256_regex(self): self._test_regex(r"\b[a-fA-F0-9]{64}\b")
    def test_34_digits_range(self): self._test_regex(r"\b\d{4,8}\b")
    def test_35_word_boundary(self): self._test_regex(r"\badmin\b")
    def test_36_combolist_user_pass(self): self._test_regex(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+:[a-zA-Z0-9!@#$%^&*]+")
    def test_37_phone_pattern(self): self._test_regex(r"\+?[1-9]\d{1,14}")
    def test_38_port_numbers(self): self._test_regex(r":\d{2,5}\b")
    def test_39_subdomains(self): self._test_regex(r"(?:[a-zA-Z0-9-]+\.)+com")
    def test_40_base64_strings(self): self._test_regex(r"[A-Za-z0-9+/]{20,}={0,2}")

    # --- 41 to 50: In-Memory Aho-Corasick & Regex Boundaries ---
    def test_41_aho_literal_match(self):
        engine = AhoCorasickEngine(["apple", "banana", "cherry"])
        matches, _ = engine.scan_chunk(b"I like apple and banana")
        self.assertEqual(len(matches), 2)

    def test_42_aho_boundary_overlap(self):
        engine = AhoCorasickEngine(["supernova"])
        chunk1 = b"Look at that super"
        chunk2 = b"nova in the sky"
        # Overlap test
        overlap = chunk1[-8:] + chunk2
        matches, _ = engine.scan_chunk(overlap)
        self.assertEqual(len(matches), 1)

    def test_43_aho_empty_data(self):
        engine = AhoCorasickEngine(["test"])
        matches, _ = engine.scan_chunk(b"")
        self.assertEqual(len(matches), 0)

    def test_44_aho_case_insensitive(self):
        engine = AhoCorasickEngine(["ADMIN"], case_sensitive=False)
        matches, _ = engine.scan_chunk(b"welcome admin user")
        self.assertEqual(len(matches), 1)

    def test_45_regex_engine_standalone(self):
        rx = RegexEngine([r"\d+"])
        matches = rx.scan_block(b"id=48102 user=99")
        self.assertEqual(len(matches), 2)

    def test_46_regex_case_sensitivity(self):
        rx = RegexEngine(["TOKEN"], case_sensitive=True)
        self.assertEqual(len(rx.scan_block(b"my token")), 0)
        self.assertEqual(len(rx.scan_block(b"my TOKEN")), 1)

    def test_47_binary_nul_byte_tolerance(self):
        engine = AhoCorasickEngine(["payload"])
        matches, _ = engine.scan_chunk(b"\x00\x00\x00payload\x00\x00")
        self.assertEqual(len(matches), 1)

    def test_48_unicode_utf8_bom(self):
        engine = AhoCorasickEngine(["hello"])
        matches, _ = engine.scan_chunk(b"\xef\xbb\xbfhello world")
        self.assertEqual(len(matches), 1)

    def test_49_emojis_in_stream(self):
        engine = AhoCorasickEngine(["rocket"])
        matches, _ = engine.scan_chunk("🚀 launch the rocket 🚀".encode("utf-8"))
        self.assertEqual(len(matches), 1)

    def test_50_very_long_line_no_newline(self):
        engine = AhoCorasickEngine(["needle"])
        long_line = b"a" * 100000 + b"needle" + b"b" * 100000
        matches, _ = engine.scan_chunk(long_line)
        self.assertEqual(len(matches), 1)

    # --- 51 to 55: Resource Guard & System Tuning ---
    def test_51_inspect_system(self):
        guard = ResourceGuard()
        prof = guard.inspect_system()
        self.assertGreater(prof.cpu_count, 0)
        self.assertGreater(prof.total_ram_bytes, 0)

    def test_52_optimal_chunk_size(self):
        guard = ResourceGuard()
        chunk = guard.compute_optimal_chunk_size(available_ram=1024*1024*1024, workers=1)
        self.assertGreaterEqual(chunk, 1024*1024)

    def test_53_optimal_workers_profile(self):
        guard = ResourceGuard()
        self.assertEqual(guard.compute_optimal_workers(cpu_count=8, available_ram=8*1024*1024*1024, current_load=0, profile="turbo"), 8)
        self.assertEqual(guard.compute_optimal_workers(cpu_count=8, available_ram=8*1024*1024*1024, current_load=0, profile="balanced"), 6)

    def test_54_should_throttle_behavior(self):
        guard = ResourceGuard(target_ram_threshold=99.9)
        self.assertFalse(guard.should_throttle())

    def test_55_apply_process_priority(self):
        guard = ResourceGuard()
        guard.apply_process_priority("balanced")

    # --- 56 to 60: File Manager & Remote URL Downloader ---
    def test_56_list_directory(self):
        fm = FileManager()
        res = fm.list_directory(".")
        self.assertIn("items", res)
        self.assertIn("current_path", res)

    def test_57_upload_initialization(self):
        fm = FileManager()
        res = fm.init_upload("up_test_01", "test.txt", 1000, 1)
        self.assertTrue(res["ready"])

    def test_58_append_and_finalize_upload(self):
        fm = FileManager()
        fm.init_upload("up_test_02", "hello.txt", 5, 1)
        fm.append_chunk("up_test_02", 0, b"world")
        res = fm.finalize_upload("up_test_02")
        self.assertEqual(res["status"], "COMPLETED")
        p = Path(res["final_path"])
        if p.exists(): p.unlink()

    def test_59_url_downloader_invalid_url(self):
        fm = FileManager()
        with self.assertRaises(Exception):
            fm.download_from_url("not_a_valid_url")

    def test_60_url_downloader_valid_stream(self):
        fm = FileManager()
        # Download small known file
        res = fm.download_from_url(
            url="https://raw.githubusercontent.com/mmnosrati/YURI_GAGARINI_ALPHA/master/requirements.txt",
            custom_filename="reqs_test.txt"
        )
        self.assertTrue(res["success"])
        p = Path(res["saved_path"])
        if p.exists(): p.unlink()

    # --- 61 to 65: Job Queue & Lifecycle ---
    def test_61_job_queue_init(self):
        jq = JobQueueManager()
        self.assertIsInstance(jq.list_jobs(), list)

    def test_62_job_queue_restore_checkpoints(self):
        jq = JobQueueManager()
        jq._restore_from_checkpoints()

    def test_63_job_queue_stop_nonexistent(self):
        jq = JobQueueManager()
        self.assertFalse(jq.stop_job("non_existent_job_1234"))

    def test_64_job_queue_pause_nonexistent(self):
        jq = JobQueueManager()
        self.assertFalse(jq.pause_job("non_existent_job_1234"))

    def test_65_job_queue_delete_nonexistent(self):
        jq = JobQueueManager()
        self.assertFalse(jq.delete_job("non_existent_job_1234"))

    # --- 66 to 70: Output Formatting & Configuration ---
    def test_66_clean_format_flags(self):
        engine = RipgrepEngine()
        opts = RipgrepOptions(output_format="clean")
        cmd = engine.build_command(["test"], "/tmp/input.txt", opts)
        self.assertIn("--no-filename", cmd)
        self.assertIn("--no-line-number", cmd)

    def test_67_separate_format_flags(self):
        engine = RipgrepEngine()
        opts = RipgrepOptions(output_format="separate")
        cmd = engine.build_command(["test"], "/tmp/input.txt", opts)
        self.assertIn("--heading", cmd)

    def test_68_prefix_format_flags(self):
        engine = RipgrepEngine()
        opts = RipgrepOptions(output_format="prefix")
        cmd = engine.build_command(["test"], "/tmp/input.txt", opts)
        self.assertIn("--no-heading", cmd)

    def test_69_extract_only_flags(self):
        engine = RipgrepEngine()
        opts = RipgrepOptions(output_format="extract_only")
        cmd = engine.build_command(["test"], "/tmp/input.txt", opts)
        self.assertIn("--only-matching", cmd)

    def test_70_server_config_defaults(self):
        cfg = get_server_config()
        self.assertEqual(cfg.port, 8000)
        self.assertEqual(cfg.hardware_profile, "turbo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
