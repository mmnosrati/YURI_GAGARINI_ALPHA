"""
Hardware-Aware Resource Guard & Linux Kernel Optimization Subsystem.
Monitors CPU, RAM, swap, and disk I/O; dynamically auto-tunes chunk sizes,
and leverages Linux posix_fadvise to prevent Page Cache pollution on large datasets.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("yurigagarin.resource")


@dataclass
class SystemProfile:
    platform: str
    cpu_count: int
    total_ram_bytes: int
    available_ram_bytes: int
    ram_usage_percent: float
    swap_usage_percent: float
    cpu_load_1m: float
    recommended_workers: int
    recommended_chunk_bytes: int
    posix_fadvise_supported: bool


class ResourceGuard:
    """
    Self-tuning hardware monitor and execution throttler.
    Guarantees the host system stays responsive during multi-gigabyte scans.
    """

    MIN_CHUNK_BYTES = 1 * 1024 * 1024       # 1 MB minimum
    DEFAULT_CHUNK_BYTES = 8 * 1024 * 1024   # 8 MB default
    MAX_CHUNK_BYTES = 64 * 1024 * 1024      # 64 MB maximum
    RAM_THROTTLE_THRESHOLD = 80.0           # 80% RAM alert/throttle threshold
    CPU_MAX_TARGET_LOAD = 0.90              # 90% CPU load target

    def __init__(self, target_ram_threshold: float = 80.0):
        self.target_ram_threshold = target_ram_threshold
        self._posix_fadvise_available = hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_DONTNEED")
        self._psutil = self._try_import_psutil()

    @staticmethod
    def _try_import_psutil():
        try:
            import psutil
            return psutil
        except ImportError:
            return None

    def inspect_system(self) -> SystemProfile:
        """Inspects live system resources and computes optimal runtime parameters."""
        cpu_count = os.cpu_count() or 1
        total_ram = 4 * 1024 * 1024 * 1024  # Default 4GB assumption
        avail_ram = 2 * 1024 * 1024 * 1024
        ram_percent = 50.0
        swap_percent = 0.0
        load_1m = 0.0

        if self._psutil:
            try:
                vm = self._psutil.virtual_memory()
                total_ram = vm.total
                avail_ram = vm.available
                ram_percent = vm.percent

                sm = self._psutil.swap_memory()
                swap_percent = sm.percent
            except Exception as e:
                logger.debug("psutil inspect failed: %s", e)

        # CPU Load
        if hasattr(os, "getloadavg"):
            try:
                load_1m = os.getloadavg()[0]
            except Exception:
                pass
        elif self._psutil:
            try:
                load_1m = self._psutil.cpu_percent(interval=None) / 100.0 * cpu_count
            except Exception:
                pass

        # Compute dynamic recommendations
        rec_workers = self.compute_optimal_workers(cpu_count, avail_ram, load_1m)
        rec_chunk = self.compute_optimal_chunk_size(avail_ram, rec_workers)

        return SystemProfile(
            platform=sys.platform,
            cpu_count=cpu_count,
            total_ram_bytes=total_ram,
            available_ram_bytes=avail_ram,
            ram_usage_percent=ram_percent,
            swap_usage_percent=swap_percent,
            cpu_load_1m=load_1m,
            recommended_workers=rec_workers,
            recommended_chunk_bytes=rec_chunk,
            posix_fadvise_supported=self._posix_fadvise_available,
        )

    def compute_optimal_workers(self, cpu_count: int, available_ram: int, current_load: float, profile: str = "eco") -> int:
        """Determines safe concurrency worker count based on hardware profile."""
        if profile == "turbo":
            # Maximum dedicated server utilization: all CPU cores
            return max(1, cpu_count)
        elif profile == "balanced":
            # Standard balanced mode: 75% CPU cores
            return max(1, int(cpu_count * 0.75))
        else:
            # "eco" / VPS Safe mode: guarantees SSH and Web panel stay snappy
            if cpu_count <= 1:
                return 1
            elif cpu_count <= 2 or available_ram < 1500 * 1024 * 1024:
                return max(1, min(2, cpu_count))
            elif cpu_count <= 4:
                return max(1, cpu_count - 1)
            else:
                return max(2, int(cpu_count * 0.5))

    def compute_optimal_chunk_size(self, available_ram: int, workers: int) -> int:
        """Calculates optimal buffer chunk size based on available system memory."""
        per_worker_budget = available_ram // max(1, workers)

        if per_worker_budget < 512 * 1024 * 1024:  # Under 512 MB per worker
            chunk = 4 * 1024 * 1024                 # 4 MB
        elif per_worker_budget < 2 * 1024 * 1024 * 1024:  # Under 2 GB per worker
            chunk = 8 * 1024 * 1024                 # 8 MB
        elif per_worker_budget < 8 * 1024 * 1024 * 1024:  # Under 8 GB per worker
            chunk = 16 * 1024 * 1024                # 16 MB
        else:
            chunk = 32 * 1024 * 1024                # 32 MB

        return max(self.MIN_CHUNK_BYTES, min(chunk, self.MAX_CHUNK_BYTES))

    def advise_sequential_read(self, fd: int, offset: int, length: int) -> None:
        """
        Advises the operating system kernel that file data will be accessed sequentially.
        """
        if self._posix_fadvise_available:
            try:
                os.posix_fadvise(fd, offset, length, os.POSIX_FADV_SEQUENTIAL)
            except OSError:
                pass

    def release_page_cache(self, fd: int, offset: int, length: int) -> None:
        """
        Critical for 100+ GB scans on Linux: informs the kernel that scanned data
        is no longer needed in the OS Page Cache, preventing RAM exhaustion.
        """
        if self._posix_fadvise_available:
            try:
                os.posix_fadvise(fd, offset, length, os.POSIX_FADV_DONTNEED)
            except OSError:
                pass

    def apply_process_priority(self, profile: str = "balanced") -> None:
        """Sets safe CPU priority based on hardware profile without starving I/O throughput."""
        if hasattr(os, "nice"):
            try:
                # Safe nice levels: 0 for turbo, 2 for balanced, 5 for eco
                target_nice = 0 if profile == "turbo" else (2 if profile == "balanced" else 5)
                os.nice(target_nice)
            except OSError:
                pass

    def should_throttle(self) -> bool:
        """Returns True if current system memory exceeds safety limits."""
        if self._psutil:
            try:
                vm = self._psutil.virtual_memory()
                return vm.percent >= self.target_ram_threshold
            except Exception:
                pass
        return False
