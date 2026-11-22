"""
Comprehensive Suite of 55 Distinct Complex Regex and Real-World Tests.
Covers real-world production data mining, security analysis, network dumps,
logs, token extraction, corrupted boundaries, ReDoS protection, and enterprise scenarios.
"""

import tempfile
import time
import unittest
from pathlib import Path

from core.engine_regex import RegexEngine
from core.search_manager import SearchConfig, SearchManager


class TestComplexRegexSuite55(unittest.TestCase):
    def scan_data(self, data: bytes, patterns: list[str], chunk_bytes: int = 1024, **kwargs):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "data.txt"
            out = Path(td) / "out.txt"
            src.write_bytes(data)
            cfg = SearchConfig(
                target_path=str(src),
                patterns=patterns,
                output_file=str(out),
                chunk_bytes=chunk_bytes,
                is_regex=True,
                **kwargs,
            )
            mgr = SearchManager(config=cfg)
            res = mgr.execute()
            matches = []
            if out.exists():
                lines = out.read_text(encoding="utf-8", errors="replace").splitlines()
                # Skip header lines
                data_lines = [l for l in lines if l and not l.startswith("=") and not l.startswith("Job ID") and not l.startswith("Engine") and not l.startswith("Patterns") and not l.startswith("Target") and not l.startswith("Case Sensitive") and not l.startswith("Extract Only") and not l.startswith("Date") and not l.startswith("=== ")]
                matches = data_lines
            return res, matches

    # 1. RFC 5322 Email Validation
    def test_01_rfc5322_email(self):
        pat = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
        data = b"Contact user.name+tag@sub.domain.co.uk and admin@space.org for help."
        res, m = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 2. IPv4 Address Extraction
    def test_02_ipv4_addresses(self):
        pat = r"\b(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
        data = b"Server IPs: 192.168.1.1, 10.0.0.254, 999.999.999.999 (invalid), 8.8.8.8"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 3)

    # 3. IPv6 Address Extraction
    def test_03_ipv6_addresses(self):
        pat = r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"
        data = b"Host connected from 2001:0db8:85a3:0000:0000:8a2e:0370:7334 via tunnel."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 4. URLs with Query Strings and Anchors
    def test_04_complex_urls(self):
        pat = r"https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
        data = b"See https://sub.example.com:8080/path/to/res?query=alpha&lang=en#heading-1 or http://test.org/index.html"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 5. UUID v4 Identification
    def test_05_uuid_v4(self):
        pat = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
        data = b"Session ID: c3a42d2a-7bf3-4f1a-9812-78d1ef32b910 generated."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 6. Credit Card Numbers (Luhn-compliant format, masked & dashed)
    def test_06_credit_card_format(self):
        pat = r"\b(?:\d{4}[ -]?){3}\d{4}\b"
        data = b"Card numbers: 4532-1234-5678-9012 and 5412 7512 3412 3456 verified."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 7. ISO 8601 Timestamps
    def test_07_iso8601_timestamps(self):
        pat = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
        data = b"Event logged at 2026-11-22T02:15:30.123Z and 2026-12-01T14:00:00+03:30."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 8. JWT Bearer Tokens
    def test_08_jwt_tokens(self):
        pat = r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"
        data = b"Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 9. GitHub Personal Access Tokens (classic & fine-grained)
    def test_09_github_tokens(self):
        pat = r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}"
        data = b"Token leaked: ghp_1234567890abcdefghijklmnopqrstuvwxyzAB in commits."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 10. AWS Access Key IDs
    def test_10_aws_access_keys(self):
        pat = r"\b(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b"
        data = b"AWS Credentials: AKIAIOSFODNN7EXAMPLE and AKIAI44QH8DHBEXAMPLE"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 11. Generic Private Key Headers (PEM format)
    def test_11_private_key_headers(self):
        pat = r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
        data = b"Config dump:\n-----BEGIN RSA PRIVATE KEY-----\nMIIEogIBAAKCAQEA..."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 12. SHA-256 Hashes
    def test_12_sha256_hashes(self):
        pat = r"\b[a-fA-F0-9]{64}\b"
        data = b"Checksum: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 13. MD5 Hashes
    def test_13_md5_hashes(self):
        pat = r"\b[a-fA-F0-9]{32}\b"
        data = b"MD5 sums: 098f6bcd4621d373cade4e832627b4f6 and 5d41402abc4b2a76b9719d911017c592"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 14. Bitcoin / Crypto Wallet Addresses (P2PKH & P2SH)
    def test_14_bitcoin_addresses(self):
        pat = r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b"
        data = b"Donations: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa or 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 15. Ethereum 0x Hex Addresses
    def test_15_ethereum_addresses(self):
        pat = r"\b0x[a-fA-F0-9]{40}\b"
        data = b"Deposit wallet: 0x71C7656EC7ab88b098defB751B7401B5f6d8976F received."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 16. MAC Addresses (Colon and Hyphen-separated)
    def test_16_mac_addresses(self):
        pat = r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}"
        data = b"Interface eth0: 00:1B:44:11:3A:B7 and wlan0: 00-14-22-01-23-45"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 17. HTML / XML Tag Extraction
    def test_17_html_tags(self):
        pat = r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s+[^>]*?)?/?>"
        data = b"<div class=\"main-card\"><span id=\"title\">Test</span><br/></div>"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 5)

    # 18. SemVer Version Strings
    def test_18_semver_strings(self):
        pat = r"\bv?(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9a-zA-Z.-]+)?(?:\+[0-9a-zA-Z.-]+)?\b"
        data = b"Upgrading from v1.0.0-alpha.1 to 2.14.3 and 17.0.0+build2026."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 3)

    # 19. International Phone Numbers (E.164)
    def test_19_phone_numbers(self):
        pat = r"\+?[1-9]\d{1,14}"
        data = b"Call +14155552671 or +442071838750 immediately."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 20. SQL Injection Signatures
    def test_20_sql_injection_patterns(self):
        pat = r"(?i)\b(?:UNION\s+ALL\s+SELECT|SELECT\s+.*?\s+FROM|DROP\s+TABLE|OR\s+1=1)\b"
        data = b"GET /search?q=' UNION ALL SELECT null, username, password FROM users--"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 21. Lookahead and Lookbehind Assertions
    def test_21_lookaround_assertions(self):
        pat = r"(?<=\$)\d+(?:\.\d{2})?"
        data = b"Price was $49.99, now on sale for $25 (cost in EUR: 30EUR)."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 22. Boundary Crossings with Multi-Line Regex
    def test_22_multiline_boundary_split(self):
        pat = r"(?s)START_BLOCK.*?END_BLOCK"
        # Split block across 50-byte chunk boundaries
        data = b"AAAA" + b"START_BLOCK" + b"X" * 80 + b"END_BLOCK" + b"BBBB"
        res, _ = self.scan_data(data, [pat], chunk_bytes=30)
        self.assertEqual(res.total_matches, 1)

    # 23. Hex Color Codes
    def test_23_hex_colors(self):
        pat = r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b"
        data = b"Theme palette: #FFF, #38BDF8, #1E293BFF, #123456"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 4)

    # 24. Apache / Nginx Common Log Format IP & Status
    def test_24_web_server_log_pattern(self):
        pat = r'\d+\.\d+\.\d+\.\d+\s+-\s+-\s+\[.*?\]\s+"(?:GET|POST|PUT)\s+.*?"\s+(\d{3})'
        data = b'192.168.1.100 - - [22/Nov/2026:10:00:00 +0000] "GET /api/v1/status HTTP/1.1" 200 1234'
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 25. Python Exception Tracebacks
    def test_25_python_traceback_pattern(self):
        pat = r"(?s)Traceback \(most recent call last\):.*?(?:[A-Z][a-zA-Z0-9]+Error|Exception):.*"
        data = b"Server crash log:\nTraceback (most recent call last):\n  File 'app.py', line 12\nZeroDivisionError: division by zero"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 26. Base64 Encoded Strings
    def test_26_base64_strings(self):
        pat = r"(?:[A-Za-z0-9+/]{4}){4,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?"
        data = b"Payload: dXNlcm5hbWU6cGFzc3dvcmQxMjM= in request."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 27. Cron Schedule Syntax (5 fields)
    def test_27_cron_expressions(self):
        pat = r"(?:[0-5]?\d|\*)\s+(?:[01]?\d|2[0-3]|\*)\s+(?:0?[1-9]|[12]\d|3[01]|\*)\s+(?:0?[1-9]|1[0-2]|\*)\s+(?:[0-6]|\*)"
        data = b"Jobs configured: */5 * * * * and 0 12 * * 1-5 active."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 28. Combolist User:Password Credentials
    def test_28_combolist_credentials(self):
        pat = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}:[^\s:]+"
        data = b"Dump:\nadmin@space.org:SecretP@ss123\nuser.test@mail.com:P@ssword!99\n"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 29. Subdomain Extraction
    def test_29_subdomains(self):
        pat = r"\b[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.(?:corp|internal|local)\b"
        data = b"Hosts: auth.corp, api.internal, db-cluster.local."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 3)

    # 30. JSON Key:Value Extraction
    def test_30_json_key_value(self):
        pat = r'"([a-zA-Z0-9_]+)"\s*:\s*"([^"]+)"'
        data = b'{"status": "active", "service": "yurigagarin", "version": "17.0"}'
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 3)

    # 31. Windows File Paths
    def test_31_windows_file_paths(self):
        pat = r"[a-zA-Z]:\\(?:[^\s\\/:*?\"<>|\r\n]+\\)*[^\s\\/:*?\"<>|\r\n]+"
        data = b"Target files: C:\\Users\\Admin\\data.log and D:\\Backups\\2026\\archive.tar"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 32. Linux Absolute File Paths
    def test_32_linux_file_paths(self):
        pat = r"/(?:[a-zA-Z0-9._-]+/)+[a-zA-Z0-9._-]+"
        data = b"Paths: /var/log/syslog and /opt/yurigagarin/run_server.py found."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 33. Port Numbers
    def test_33_port_numbers(self):
        pat = r":([1-9]\d{0,3}|[1-5]\d{4}|6[0-4]\d{3}|65[0-4]\d{2}|655[0-2]\d|6553[0-5])\b"
        data = b"Listening on 0.0.0.0:8000, 127.0.0.1:443, and 10.0.0.1:80"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 3)

    # 34. Webhook URLs (Mock Custom Format)
    def test_34_slack_webhooks(self):
        pat = r"https://api\.mockservices\.internal/hooks/T[a-zA-Z0-9_]+/B[a-zA-Z0-9_]+/[a-zA-Z0-9_]+"
        data = b"Webhook: https://api.mockservices.internal/hooks/T00000000/B00000000/MOCKTOKEN12345678901234"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 35. Google API Keys (Mock Format)
    def test_35_google_api_keys(self):
        pat = r"MOCK_API_KEY_[0-9A-Za-z-_]{25}"
        data = b"Maps key: MOCK_API_KEY_1234567890abcdefghijklmnopqrst"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 36. Payment Secret API Keys (Mock Format)
    def test_36_stripe_keys(self):
        pat = r"mockpay_(?:live|test)_[0-9a-zA-Z]{20,}"
        data = b"Keys: mockpay_live_51Abcdefghijklmnopqrstuvw and mockpay_test_0123456789abcdefghijkl"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 37. Chat Bot Tokens (Mock Format)
    def test_37_discord_tokens(self):
        pat = r"BOT_TOKEN_[A-Za-z\d]{15,20}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{20}"
        data = b"Bot token: BOT_TOKEN_123456789012345.GaBcDe.fGhIjKlMnOpQrStUvWxY"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 38. Password complexity matching (min 8 chars, uppercase, lowercase, number, symbol)
    def test_38_password_strength_pattern(self):
        pat = r"\b(?=[A-Za-z\d@$!%*?&]*[a-z])(?=[A-Za-z\d@$!%*?&]*[A-Z])(?=[A-Za-z\d@$!%*?&]*\d)(?=[A-Za-z\d@$!%*?&]*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}\b"
        data = b"Passwords checked: P@ssw0rd123 (strong), weakpass (invalid)"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 39. SSH Known Hosts Entries
    def test_39_ssh_known_hosts(self):
        pat = r"\|1\|[a-zA-Z0-9+/=]+\|[a-zA-Z0-9+/=]+\s+ssh-[a-z0-9-]+\s+[a-zA-Z0-9+/=]+"
        data = b"|1|kldjfsoidjf=|+ldksjfosidjf= ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI..."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 40. Environment Variable Exports
    def test_40_env_exports(self):
        pat = r"(?m)^export\s+([A-Z_][A-Z0-9_]*)=([^\s]+)"
        data = b"export DB_PORT=5432\nexport APP_ENV=production\nFOO=bar"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 41. Git Commit Hash References
    def test_41_git_commit_hashes(self):
        pat = r"\b[0-9a-f]{7,40}\b"
        data = b"Merged commit 493c87b into master (parent: 35cc666)."
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 42. Regex Boundary spanning over 3 small chunks
    def test_42_regex_over_multiple_chunks(self):
        pat = r"TARGET_START[0-9]+TARGET_END"
        # 10 byte chunks
        data = b"XXXX" + b"TARGET_START" + b"99999" + b"TARGET_END" + b"YYYY"
        res, _ = self.scan_data(data, [pat], chunk_bytes=10)
        self.assertEqual(res.total_matches, 1)

    # 43. Case Insensitive Regex
    def test_43_case_insensitive_regex(self):
        pat = r"error\s*\[\s*\d+\s*\]"
        data = b"ERROR[101] occurred and Error [202] and error   [303]"
        res, _ = self.scan_data(data, [pat], case_sensitive=False)
        self.assertEqual(res.total_matches, 3)

    # 44. Case Sensitive Regex Distinction
    def test_44_case_sensitive_regex(self):
        pat = r"CRITICAL_FAILURE"
        data = b"critical_failure and CRITICAL_FAILURE"
        res, _ = self.scan_data(data, [pat], case_sensitive=True)
        self.assertEqual(res.total_matches, 1)

    # 45. Multi-line Regex with Dots Matching Newlines
    def test_45_dotall_multiline_regex(self):
        pat = r"(?s)<!--.*?-->"
        data = b"<div><!-- This is a \n multi-line \n comment --></div>"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 1)

    # 46. Multiple Complex Patterns Combined
    def test_46_multiple_complex_patterns(self):
        patterns = [
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
            r"0x[a-fA-F0-9]{40}",
        ]
        data = b"Admin email: admin@cluster.space, IP: 10.0.0.1, Eth: 0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
        res, _ = self.scan_data(data, patterns)
        self.assertEqual(res.total_matches, 3)

    # 47. Non-greedy vs Greedy Quantifiers
    def test_47_non_greedy_quantifiers(self):
        pat = r"\[.*?\]"
        data = b"[first][second][third]"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 3)

    # 48. Words with specific length bounds
    def test_48_exact_word_length(self):
        pat = r"\b[a-zA-Z]{5}\b"
        data = b"one two three four seven eight"
        res, _ = self.scan_data(data, [pat])
        # three (5), seven (5), eight (5)
        self.assertEqual(res.total_matches, 3)

    # 49. Negative Lookaheads
    def test_49_negative_lookahead(self):
        pat = r"\bfoo(?!bar)\w*\b"
        data = b"foobaz foobar fooqux foobar"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 2)

    # 50. Empty Target File with Regex
    def test_50_empty_file_regex(self):
        res, _ = self.scan_data(b"", [r"\w+"])
        self.assertEqual(res.total_matches, 0)
        self.assertTrue(res.success)

    # 51. Zero Matching Lines in Big Dataset
    def test_51_zero_matches_big_data(self):
        data = b"Normal boring content.\n" * 5000  # ~115 KB
        res, _ = self.scan_data(data, [r"SUPER_RARE_KEYWORD_\d{10}"])
        self.assertEqual(res.total_matches, 0)
        self.assertTrue(res.success)

    # 52. Rapid successive duplicate matches on same line
    def test_52_consecutive_matches(self):
        pat = r"\d+"
        data = b"1 2 3 4 5 6 7 8 9 10"
        res, _ = self.scan_data(data, [pat])
        self.assertEqual(res.total_matches, 10)

    # 53. High volume random bytes with regex
    def test_53_high_volume_random_bytes_regex(self):
        data = b"RANDOM_1111_MATCH_1\n" + (b"B" * 10000) + b"\nRANDOM_2222_MATCH_2\n"
        pat = r"RANDOM_[A-Z0-9_]+_MATCH_[0-9]+"
        res, _ = self.scan_data(data, [pat], chunk_bytes=5000)
        self.assertEqual(res.total_matches, 2)

    # 54. Non-matching Catastrophic ReDoS with Watchdog Safety
    def test_54_catastrophic_redos_watchdog_safe(self):
        evil_pat = r"^(a+)+$"
        # Non-matching input with 28 'a's ending in '!' - causes 2^28 backtracking steps in standard regex
        data = b"a" * 28 + b"!\n" + b"Normal text line.\n"
        res, _ = self.scan_data(data, [evil_pat])
        self.assertEqual(res.total_matches, 0)
        self.assertTrue(res.success)

    # 55. Full Context Output with Complex Regex
    def test_55_full_context_regex_output(self):
        pat = r"CRITICAL:\s+\w+"
        data = b"INFO: normal event\nCRITICAL: core_dumped at memory 0x123\nDEBUG: done"
        res, matches = self.scan_data(data, [pat], extract_only=False)
        self.assertEqual(res.total_matches, 1)
        # Verify output contains the line preview
        self.assertTrue(any("CRITICAL: core_dumped" in m for m in matches))


if __name__ == "__main__":
    unittest.main()
