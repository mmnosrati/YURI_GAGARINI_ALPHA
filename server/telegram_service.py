"""
Asynchronous Telegram Bot Dispatcher for Yuri Gagarin Search Engine.
Handles real-time search milestone updates, hourly progress reports,
and automatic 45 MB multipart splitting for large search result files.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("yurigagarin.server.telegram")


class TelegramService:
    """
    Robust asynchronous Telegram bot client.
    Dispatches notifications and delivers massive output files in 45 MB parts.
    """

    TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
    MAX_FILE_SIZE_BYTES = 45 * 1024 * 1024  # 45 MB safe limit for Telegram bot uploads

    def __init__(
        self,
        token: str = "",
        chat_id: str = "",
        enabled: bool = False,
        timeout: int = 60,
    ):
        self.token = token.strip()
        self.chat_id = chat_id.strip()
        self.enabled = enabled and bool(self.token and self.chat_id)
        self.timeout = timeout
        self._lock = threading.Lock()

    def update_credentials(self, token: str, chat_id: str, enabled: bool) -> None:
        """Updates Telegram connection settings."""
        with self._lock:
            self.token = token.strip()
            self.chat_id = chat_id.strip()
            self.enabled = enabled and bool(self.token and self.chat_id)

    def _api_call(self, method: str, data: bytes, content_type: str) -> Dict[str, Any]:
        """Performs raw HTTP POST to Telegram Bot API."""
        if not self.token:
            raise ValueError("Telegram Bot Token is not configured.")

        url = self.TELEGRAM_API_BASE.format(token=self.token, method=method)
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": content_type},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Sends a text message to the configured Telegram chat."""
        if not self.enabled:
            return False

        try:
            body = urllib.parse.urlencode({
                "chat_id": self.chat_id,
                "text": text[:4096],
                "parse_mode": parse_mode,
            }).encode("utf-8")

            res = self._api_call("sendMessage", body, "application/x-www-form-urlencoded")
            return res.get("ok", False)
        except Exception as e:
            logger.error("Telegram send_message failed: %s", e)
            return False

    def send_document(self, file_path: Path, caption: str = "") -> bool:
        """Uploads a single document to Telegram via multipart/form-data."""
        if not self.enabled or not file_path.exists():
            return False

        boundary = f"----YuriGagarinFormBoundary{int(time.time() * 1000)}"
        parts: List[bytes] = []

        def add_field(name: str, value: str):
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n".encode("utf-8")
            )

        add_field("chat_id", self.chat_id)
        if caption:
            add_field("caption", caption[:1024])
            add_field("parse_mode", "Markdown")

        # Add file part
        filename = file_path.name
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8")
        )
        parts.append(file_path.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))

        body = b"".join(parts)
        try:
            res = self._api_call(
                "sendDocument",
                body,
                f"multipart/form-data; boundary={boundary}",
            )
            return res.get("ok", False)
        except Exception as e:
            logger.error("Telegram send_document failed for %s: %s", file_path.name, e)
            return False

    def send_output_file_multipart(self, output_file: Path, summary_stats: Dict[str, Any]) -> bool:
        """
        Splits output files larger than 45 MB into consecutive parts and uploads them.
        Includes complete mission statistics, timestamp, target, and matches in the caption.
        """
        if not self.enabled or not output_file.exists():
            return False

        size_bytes = output_file.stat().st_size
        elapsed = summary_stats.get("elapsed_seconds", 0.0)
        speed = summary_stats.get("throughput_mb_s", 0.0)
        matches = summary_stats.get("total_matches", 0)
        target = summary_stats.get("target_path", "Unknown")
        job_id = summary_stats.get("job_id", "N/A")
        now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

        caption = (
            f"🔍 *YURI GAGARIN ALPHA - SEARCH MISSION REPORT*\n\n"
            f"• *Job ID*: `{job_id}`\n"
            f"• *Target*: `{target}`\n"
            f"• *Total Matches*: `{matches:,}`\n"
            f"• *Execution Time*: `{elapsed:.2f}s`\n"
            f"• *Average Throughput*: `{speed:.2f} MB/s`\n"
            f"• *Output File*: `{output_file.name}`\n"
            f"• *File Size*: `{size_bytes / (1024 * 1024):.2f} MB`\n"
            f"• *Completed At*: `{now_str}`\n"
        )

        if size_bytes <= self.MAX_FILE_SIZE_BYTES:
            return self.send_document(output_file, caption=caption)

        # Multipart split
        parts_count = math.ceil(size_bytes / self.MAX_FILE_SIZE_BYTES)
        self.send_message(
            f"📦 Output `{output_file.name}` ({size_bytes / (1024 * 1024):.1f} MB) "
            f"exceeds Telegram limit. Uploading in {parts_count} parts...\n"
            f"• Matches: `{matches:,}`\n• Target: `{target}`"
        )

        temp_dir = Path(tempfile.mkdtemp(prefix="yuri_tg_parts_"))
        all_ok = True

        try:
            with open(output_file, "rb") as fh:
                for i in range(parts_count):
                    chunk = fh.read(self.MAX_FILE_SIZE_BYTES)
                    if not chunk:
                        break

                    part_path = temp_dir / f"{output_file.stem}_part{i+1:03d}_of_{parts_count:03d}{output_file.suffix}"
                    part_path.write_bytes(chunk)

                    part_caption = f"[{i+1}/{parts_count}] {caption}"
                    ok = self.send_document(part_path, caption=part_caption)
                    if not ok:
                        all_ok = False
                    try:
                        part_path.unlink()
                    except OSError:
                        pass
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        if all_ok:
            self.send_message(f"✅ Successfully delivered all {parts_count} file parts to Telegram.")
        return all_ok

    def test_connection(self) -> Dict[str, Any]:
        """Tests the configured Bot Token by calling getMe API."""
        if not self.token:
            return {"success": False, "error": "Bot token is empty."}
        try:
            url = self.TELEGRAM_API_BASE.format(token=self.token, method="getMe")
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            if data.get("ok"):
                bot_user = data["result"].get("username", "UnknownBot")
                return {"success": True, "bot_username": bot_user}
            return {"success": False, "error": "Invalid response from Telegram API."}
        except Exception as e:
            return {"success": False, "error": str(e)}
