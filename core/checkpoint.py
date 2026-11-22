"""
Atomic Checkpoint & State Persistence Manager for Yuri Gagarin Search Engine.
Enables instant pause, crash recovery, and byte-exact resume across multi-gigabyte files.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("yurigagarin.checkpoint")


@dataclass
class CheckpointState:
    job_id: str
    target_path: str
    patterns: List[str]
    is_regex: bool
    case_sensitive: bool
    extract_only: bool
    output_file: str
    status: str = "RUNNING"  # RUNNING, PAUSED, COMPLETED, STOPPED, FAILED
    current_file_index: int = 0
    current_file_path: str = ""
    current_file_offset: int = 0
    completed_files: List[str] = field(default_factory=list)
    total_files_discovered: int = 0
    total_bytes_discovered: int = 0
    total_bytes_processed: int = 0
    total_matches_count: int = 0
    elapsed_seconds: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CheckpointState:
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


class CheckpointManager:
    """
    Thread-safe and process-safe checkpoint store using atomic filesystem writes.
    """

    DEFAULT_CHECKPOINT_DIR = Path("yurigagarin_checkpoints")

    def __init__(self, directory: Optional[Path | str] = None):
        self.directory = Path(directory or self.DEFAULT_CHECKPOINT_DIR)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _get_path(self, job_id: str) -> Path:
        safe_id = "".join(c for c in job_id if c.isalnum() or c in ("-", "_"))
        return self.directory / f"{safe_id}.json"

    def save(self, state: CheckpointState) -> None:
        """
        Atomically saves state using a temporary file and rename to prevent corrupted writes.
        """
        state.updated_at = time.time()
        final_path = self._get_path(state.job_id)
        temp_file = None

        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=str(self.directory),
                delete=False,
                encoding="utf-8",
                suffix=".tmp",
            ) as tf:
                temp_file = Path(tf.name)
                json.dump(state.to_dict(), tf, indent=2, ensure_ascii=False)
                tf.flush()
                os.fsync(tf.fileno())

            # Atomic replace
            os.replace(temp_file, final_path)
        except Exception as e:
            logger.error("Failed to persist checkpoint for %s: %s", state.job_id, e)
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise

    def load(self, job_id: str) -> Optional[CheckpointState]:
        """Loads state from checkpoint JSON file."""
        path = self._get_path(job_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return CheckpointState.from_dict(data)
        except Exception as e:
            logger.error("Failed to load checkpoint for %s: %s", job_id, e)
            return None

    def list_checkpoints(self) -> List[CheckpointState]:
        """Lists all existing checkpoint states sorted by update time."""
        results = []
        for p in self.directory.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                results.append(CheckpointState.from_dict(data))
            except Exception as e:
                logger.warning("Corrupted checkpoint file skipped: %s (%s)", p.name, e)
        results.sort(key=lambda s: s.updated_at, reverse=True)
        return results

    def remove(self, job_id: str) -> bool:
        """Deletes a checkpoint file."""
        path = self._get_path(job_id)
        if path.exists():
            try:
                path.unlink()
                return True
            except OSError as e:
                logger.error("Error removing checkpoint %s: %s", job_id, e)
        return False
