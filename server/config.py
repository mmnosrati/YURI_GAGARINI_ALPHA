"""
Server Configuration & Settings Persistence for Yuri Gagarin Search Engine.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("yurigagarin.server.config")

CONFIG_PATH = Path("config.json")


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    admin_password_hash: str = ""  # PBKDF2/SHA-256 hash or plain default on first run
    admin_token: str = ""
    tg_enabled: bool = False
    tg_token: str = ""
    tg_chat_id: str = ""
    tg_send_file: bool = True
    tg_chunk_mb: int = 45
    tg_retry_max: int = 5
    tg_timeout: int = 60
    progress_interval_hours: float = 1.0
    default_upload_dir: str = "uploads"
    default_output_dir: str = "output"
    max_ram_throttle_percent: float = 85.0
    detailed_stats: bool = True
    default_chunk_bytes: int = 8 * 1024 * 1024

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ServerConfig:
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


_GLOBAL_CONFIG: Optional[ServerConfig] = None


def get_server_config(config_path: Path = CONFIG_PATH) -> ServerConfig:
    global _GLOBAL_CONFIG
    if _GLOBAL_CONFIG is not None:
        return _GLOBAL_CONFIG

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _GLOBAL_CONFIG = ServerConfig.from_dict(data)
            return _GLOBAL_CONFIG
        except Exception as e:
            logger.warning("Failed to load config.json, using defaults: %s", e)

    _GLOBAL_CONFIG = ServerConfig()
    save_server_config(_GLOBAL_CONFIG, config_path)
    return _GLOBAL_CONFIG


def save_server_config(cfg: ServerConfig, config_path: Path = CONFIG_PATH) -> None:
    global _GLOBAL_CONFIG
    _GLOBAL_CONFIG = cfg
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("Failed to save config.json: %s", e)
