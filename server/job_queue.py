"""
Asynchronous Search Job Queue & Process Supervisor for Yuri Gagarin Search Engine.
Manages job lifecycle (Start, Pause, Resume, Stop) and emits real-time WebSocket telemetry.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.checkpoint import CheckpointManager, CheckpointState
from core.search_manager import SearchConfig, SearchManager, SearchResult
from .config import ServerConfig, get_server_config
from .telegram_service import TelegramService

logger = logging.getLogger("yurigagarin.server.jobs")


@dataclass
class JobInfo:
    job_id: str
    target_path: str
    patterns: List[str]
    is_regex: bool
    status: str  # IDLE, RUNNING, PAUSED, COMPLETED, STOPPED, FAILED
    progress_percent: float = 0.0
    speed_mb_s: float = 0.0
    eta_seconds: int = 0
    total_matches: int = 0
    bytes_processed: int = 0
    total_bytes: int = 0
    current_file: str = ""
    file_index: int = 0
    total_files: int = 0
    output_file: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class JobQueueManager:
    """
    Central supervisor for background search jobs.
    Coordinates execution threads, checkpoints, Telegram updates, and WebSocket broadcasting.
    """

    def __init__(
        self,
        config: Optional[ServerConfig] = None,
        broadcast_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.config = config or get_server_config()
        self.broadcast_callback = broadcast_callback
        self.checkpoint_manager = CheckpointManager()
        self.telegram = TelegramService(
            token=self.config.tg_token,
            chat_id=self.config.tg_chat_id,
            enabled=self.config.tg_enabled,
        )

        self._jobs: Dict[str, JobInfo] = {}
        self._active_managers: Dict[str, SearchManager] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._last_broadcast: Dict[str, float] = {}
        self._lock = threading.Lock()

        # Load persisted checkpoints into job history
        self._restore_from_checkpoints()

    def _restore_from_checkpoints(self) -> None:
        """Restores unfinished jobs from existing checkpoint files and completed outputs."""
        for cp in self.checkpoint_manager.list_checkpoints():
            if cp.job_id not in self._jobs:
                self._jobs[cp.job_id] = JobInfo(
                    job_id=cp.job_id,
                    target_path=cp.target_path,
                    patterns=cp.patterns,
                    is_regex=cp.is_regex,
                    status="PAUSED",  # Resumable
                    progress_percent=round((cp.total_bytes_processed / max(1, cp.total_bytes_discovered)) * 100.0, 1),
                    total_matches=cp.total_matches_count,
                    bytes_processed=cp.total_bytes_processed,
                    total_bytes=cp.total_bytes_discovered,
                    current_file=Path(cp.current_file_path).name if cp.current_file_path else "",
                    file_index=cp.current_file_index,
                    total_files=cp.total_files_discovered,
                    output_file=cp.output_file,
                    created_at=cp.created_at,
                )

        # Also populate history from existing files in output/ directory so finished jobs persist across restarts!
        output_dir = Path(self.config.default_output_dir)
        if output_dir.exists():
            for f in output_dir.glob("search_*.txt"):
                file_stem = f.stem
                job_id = f"job_{file_stem}"
                if job_id not in self._jobs:
                    stat = f.stat()
                    # Count matches from output file lines
                    match_count = 0
                    try:
                        with open(f, "rb") as probe_f:
                            while chunk := probe_f.read(4 * 1024 * 1024):
                                match_count += chunk.count(b"\n")
                    except Exception:
                        pass

                    self._jobs[job_id] = JobInfo(
                        job_id=job_id,
                        target_path=f"Historical Result ({f.name})",
                        patterns=[file_stem.replace("search_", "")],
                        is_regex=False,
                        status="COMPLETED",
                        progress_percent=100.0,
                        total_matches=match_count,
                        bytes_processed=stat.st_size,
                        total_bytes=stat.st_size,
                        current_file="Complete",
                        file_index=1,
                        total_files=1,
                        output_file=str(f),
                        created_at=stat.st_mtime,
                        started_at=stat.st_mtime,
                        completed_at=stat.st_mtime,
                    )

    def get_job(self, job_id: str) -> Optional[JobInfo]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [j.to_dict() for j in sorted(self._jobs.values(), key=lambda x: x.created_at, reverse=True)]

    def start_job(self, search_cfg: SearchConfig) -> JobInfo:
        """Spawns and executes a new search job in a background thread."""
        with self._lock:
            job_id = search_cfg.job_id or f"job_{int(time.time())}"
            search_cfg.job_id = job_id

            job_info = JobInfo(
                job_id=job_id,
                target_path=search_cfg.target_path,
                patterns=search_cfg.patterns,
                is_regex=search_cfg.is_regex,
                status="RUNNING",
                output_file=search_cfg.output_file,
                started_at=time.time(),
            )
            self._jobs[job_id] = job_info

        # Create SearchManager
        manager = SearchManager(
            config=search_cfg,
            progress_callback=self._handle_progress,
            checkpoint_manager=self.checkpoint_manager,
        )

        with self._lock:
            self._active_managers[job_id] = manager

        # Background thread
        t = threading.Thread(
            target=self._run_job_thread,
            args=(job_id, manager),
            daemon=True,
            name=f"job-{job_id}",
        )
        self._threads[job_id] = t
        t.start()

        # Telegram announcement
        if self.telegram.enabled:
            self.telegram.send_message(
                f"🚀 *YURI GAGARIN ALPHA - SEARCH JOB STARTED*\n\n"
                f"• *Job ID*: `{job_id}`\n"
                f"• *Target*: `{search_cfg.target_path}`\n"
                f"• *Patterns*: `{len(search_cfg.patterns)}`\n"
                f"• *Format*: `{search_cfg.output_format}`\n"
                f"• *Engine*: `{'Ripgrep' if search_cfg.engine_type == 'ripgrep' else ('Regex' if search_cfg.is_regex else 'Aho-Corasick')}`\n"
            )

        return job_info

    def _run_job_thread(self, job_id: str, manager: SearchManager) -> None:
        """Worker thread entry for job execution."""
        try:
            res: SearchResult = manager.execute()

            with self._lock:
                job_info = self._jobs.get(job_id)
                if job_info:
                    job_info.status = "COMPLETED" if res.success else "STOPPED"
                    job_info.completed_at = time.time()
                    job_info.total_matches = res.total_matches
                    job_info.bytes_processed = res.total_bytes_scanned
                    job_info.speed_mb_s = res.throughput_mb_s
                    job_info.progress_percent = 100.0 if res.success else job_info.progress_percent

            # Telegram delivery
            if self.telegram.enabled:
                res_dict = asdict(res)
                res_dict["patterns"] = manager.config.patterns
                self.telegram.send_output_file_multipart(
                    Path(res.output_file),
                    res_dict,
                )

        except Exception as e:
            logger.exception("Job %s crashed: %s", job_id, e)
            with self._lock:
                job_info = self._jobs.get(job_id)
                if job_info:
                    job_info.status = "FAILED"
                    job_info.error_message = str(e)
                    job_info.completed_at = time.time()

            if self.telegram.enabled:
                self.telegram.send_message(f"❌ *Job {job_id} Failed*: `{e}`")

        finally:
            with self._lock:
                self._active_managers.pop(job_id, None)

            if self.broadcast_callback:
                job = self.get_job(job_id)
                if job:
                    self.broadcast_callback({"event": "job_finished", "job": job.to_dict()})

    def pause_job(self, job_id: str) -> bool:
        """Pauses a running job."""
        with self._lock:
            manager = self._active_managers.get(job_id)
            job = self._jobs.get(job_id)
            if manager and job:
                manager.request_pause()
                job.status = "PAUSED"
                return True
        return False

    def resume_job(self, job_id: str) -> bool:
        """Resumes a paused or checkpointed job."""
        with self._lock:
            manager = self._active_managers.get(job_id)
            job = self._jobs.get(job_id)

            # If manager is running in memory
            if manager and job:
                manager.resume()
                job.status = "RUNNING"
                return True

            # If job was loaded from checkpoint
            cp = self.checkpoint_manager.load(job_id)
            if cp:
                cfg = SearchConfig(
                    target_path=cp.target_path,
                    patterns=cp.patterns,
                    output_file=cp.output_file,
                    is_regex=cp.is_regex,
                    case_sensitive=cp.case_sensitive,
                    extract_only=cp.extract_only,
                    job_id=cp.job_id,
                )
                self.start_job(cfg)
                return True

        return False

    def stop_job(self, job_id: str) -> bool:
        """Stops a running job."""
        with self._lock:
            manager = self._active_managers.get(job_id)
            job = self._jobs.get(job_id)
            if manager and job:
                manager.request_stop()
                job.status = "STOPPED"
                return True
        return False

    def delete_job(self, job_id: str, delete_file: bool = True) -> bool:
        """Deletes a job record and optionally removes its generated output file from disk."""
        with self._lock:
            job = self._jobs.pop(job_id, None)
            self._active_managers.pop(job_id, None)
            self._threads.pop(job_id, None)

        # Remove checkpoint
        self.checkpoint_manager.remove(job_id)

        # Remove output file from disk
        if job and delete_file and job.output_file:
            try:
                p = Path(job.output_file)
                if p.exists() and p.is_file():
                    p.unlink()
                    logger.info("Deleted output file for job %s: %s", job_id, p)
            except Exception as e:
                logger.warning("Could not delete output file %s: %s", job.output_file, e)

        return True if job else False

    def _handle_progress(self, progress_data: Dict[str, Any]) -> None:
        """Receives progress events and updates job info & rate-limited WebSocket broadcast."""
        job_id = progress_data.get("job_id")
        if not job_id:
            return

        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.status == "RUNNING":
                job.progress_percent = progress_data.get("percent", 0.0)
                job.speed_mb_s = progress_data.get("speed_mb_s", 0.0)
                job.eta_seconds = progress_data.get("eta_seconds", 0)
                job.total_matches = progress_data.get("total_matches", 0)
                job.bytes_processed = progress_data.get("bytes_processed", 0)
                job.total_bytes = progress_data.get("total_bytes", 0)
                job.current_file = progress_data.get("file_current", "")
                job.file_index = progress_data.get("file_index", 0)
                job.total_files = progress_data.get("total_files", 0)

        # Rate-limit broadcast to max 1 per 0.8s (except final 100% or initial start)
        pct = progress_data.get("percent", 0.0)
        now = time.monotonic()
        last_t = self._last_broadcast.get(job_id, 0.0)
        if (now - last_t >= 0.8) or pct >= 100.0 or pct <= 1.0:
            self._last_broadcast[job_id] = now
            if self.broadcast_callback:
                self.broadcast_callback({
                    "event": "progress",
                    "data": progress_data,
                })
