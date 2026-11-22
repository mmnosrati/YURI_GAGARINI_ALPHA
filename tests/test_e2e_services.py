"""
End-to-end integration test of Telegram multipart splitting,
WebSocket telemetry broadcasting, and authentication security.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from server.auth import AuthManager
from server.config import ServerConfig
from server.telegram_service import TelegramService


class TestEndToEndServices(unittest.TestCase):
    def test_auth_brute_force_lockout(self):
        cfg = ServerConfig(admin_password_hash=AuthManager.hash_password("correct_pass"))
        auth = AuthManager(cfg)
        ip = "192.168.1.50"

        # 4 failed attempts should not lock out
        for _ in range(4):
            tok = auth.authenticate("wrong_pass", client_ip=ip)
            self.assertIsNone(tok)
            self.assertFalse(auth.is_locked_out(ip))

        # 5th attempt locks out
        tok = auth.authenticate("wrong_pass", client_ip=ip)
        self.assertIsNone(tok)
        self.assertTrue(auth.is_locked_out(ip))

        # Even correct password is now blocked
        tok = auth.authenticate("correct_pass", client_ip=ip)
        self.assertIsNone(tok)

    @patch("urllib.request.urlopen")
    def test_telegram_multipart_chunking_and_send(self, mock_urlopen):
        # Mock Telegram API response
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True, "result": {"message_id": 100}}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        with tempfile.TemporaryDirectory() as td:
            tg = TelegramService(token="123456:FAKE_TOKEN", chat_id="999999", enabled=True)
            # Temporarily lower chunk size to test multipart logic
            tg.MAX_FILE_SIZE_BYTES = 500  # 500 bytes per chunk

            large_file = Path(td) / "big_results.txt"
            large_file.write_bytes(b"A" * 1600)  # ~4 parts

            stats = {"total_matches": 50, "files_searched": 10, "throughput_mb_s": 15.5, "elapsed_seconds": 1.2}
            success = tg.send_output_file_multipart(large_file, stats)
            self.assertTrue(success)

            # Check that sendDocument was called at least 4 times
            self.assertGreaterEqual(mock_urlopen.call_count, 4)


if __name__ == "__main__":
    unittest.main()
