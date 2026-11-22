"""
Authentication & Single-Admin Security Module.
Provides secure password hashing (PBKDF2-HMAC-SHA256) and session tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Dict, Optional

from .config import ServerConfig, get_server_config, save_server_config


class AuthManager:
    """
    Manages single-admin authentication with rate limiting and secure tokens.
    """

    DEFAULT_ADMIN_PASSWORD = "admin"  # Default password on first start

    def __init__(self, config: Optional[ServerConfig] = None):
        self.config = config or get_server_config()
        self._active_sessions: Dict[str, float] = {}  # token -> expiry_timestamp
        self._failed_attempts: Dict[str, int] = {}    # ip -> count
        self._lockout_until: Dict[str, float] = {}    # ip -> timestamp

        # Initialize default password if unset
        if not self.config.admin_password_hash:
            self.set_admin_password(self.DEFAULT_ADMIN_PASSWORD)

    @staticmethod
    def hash_password(password: str, salt: Optional[bytes] = None) -> str:
        """Hashes password using PBKDF2-HMAC-SHA256."""
        if salt is None:
            salt = secrets.token_bytes(16)
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return f"{salt.hex()}:{key.hex()}"

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        """Verifies plain password against stored salt:hash, or plain text if unhashed."""
        if not stored_hash or not password:
            return False

        # Support direct plain text match (e.g. if set manually in config.json)
        if hmac.compare_digest(password, stored_hash):
            return True

        try:
            parts = stored_hash.split(":")
            if len(parts) != 2:
                return False
            salt = bytes.fromhex(parts[0])
            expected_key = bytes.fromhex(parts[1])
            actual_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
            return hmac.compare_digest(expected_key, actual_key)
        except Exception:
            return False

    def set_admin_password(self, new_password: str) -> None:
        """Updates the master admin password and static token."""
        hashed = self.hash_password(new_password)
        self.config.admin_password_hash = hashed
        self.config.admin_token = new_password  # Keep static token in sync for API calls
        save_server_config(self.config)

    def is_locked_out(self, client_ip: str) -> bool:
        """Checks if client IP is temporarily locked out due to brute force."""
        unlock_time = self._lockout_until.get(client_ip, 0)
        if time.time() < unlock_time:
            return True
        elif unlock_time > 0:
            del self._lockout_until[client_ip]
            self._failed_attempts.pop(client_ip, None)
        return False

    def _generate_signed_token(self) -> str:
        """Generates a cryptographic HMAC-signed token that survives server restarts."""
        expiry = int(time.time() + 86400 * 30)  # 30 days validity
        signing_key = self.config.admin_password_hash.encode("utf-8")
        payload = f"admin:{expiry}".encode("utf-8")
        sig = hmac.new(signing_key, payload, hashlib.sha256).hexdigest()
        return f"admin:{expiry}:{sig}"

    def authenticate(self, password: str, client_ip: str = "127.0.0.1") -> Optional[str]:
        """Validates password and creates a persistent signed session token."""
        if self.is_locked_out(client_ip):
            return None

        if self.verify_password(password, self.config.admin_password_hash):
            self._failed_attempts.pop(client_ip, None)
            token = self._generate_signed_token()
            self._active_sessions[token] = time.time() + 86400 * 30
            return token
        else:
            fails = self._failed_attempts.get(client_ip, 0) + 1
            self._failed_attempts[client_ip] = fails
            if fails >= 5:
                self._lockout_until[client_ip] = time.time() + 300  # 5 min lockout
            return None

    def validate_token(self, token: Optional[str]) -> bool:
        """Validates a signed cryptographic token or static admin token."""
        if not token:
            return False

        # 1. Check static admin token from config
        if self.config.admin_token and hmac.compare_digest(token, self.config.admin_token):
            return True

        # 2. Check signed cryptographic token (survives reboots)
        try:
            parts = token.split(":")
            if len(parts) == 3 and parts[0] == "admin":
                expiry = int(parts[1])
                client_sig = parts[2]
                if time.time() < expiry:
                    signing_key = self.config.admin_password_hash.encode("utf-8")
                    expected_sig = hmac.new(signing_key, f"admin:{expiry}".encode("utf-8"), hashlib.sha256).hexdigest()
                    if hmac.compare_digest(client_sig, expected_sig):
                        return True
        except Exception:
            pass

        # 3. Check in-memory session token fallback
        expiry = self._active_sessions.get(token)
        if expiry and time.time() < expiry:
            return True
        elif expiry:
            del self._active_sessions[token]
        return False

    def logout(self, token: str) -> None:
        """Revokes a session token."""
        self._active_sessions.pop(token, None)
