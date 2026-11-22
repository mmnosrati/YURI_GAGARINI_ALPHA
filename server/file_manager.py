"""
Filesystem Explorer & Resumable Chunked File Upload Manager.
Supports uploading massive files (multi-gigabyte) chunk-by-chunk with SHA-256 verification.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("yurigagarin.server.fs")


@dataclass
class UploadSession:
    upload_id: str
    filename: str
    target_dir: str
    total_size: int
    total_chunks: int
    uploaded_chunks: set[int]
    temp_file_path: Path
    created_at: float


class FileManager:
    """
    Manages server filesystem exploration and multi-gigabyte chunked file uploads.
    """

    def __init__(self, upload_dir: str = "uploads", temp_dir: str = "temp_uploads"):
        self.upload_dir = Path(upload_dir)
        self.temp_dir = Path(temp_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._active_uploads: Dict[str, UploadSession] = {}

    def list_directory(self, target_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Lists directory contents with file sizes, types, and free disk space.
        """
        path = Path(target_path) if target_path else Path.cwd()
        if not path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")
        if not path.is_dir():
            path = path.parent

        items: List[Dict[str, Any]] = []
        try:
            for entry in path.iterdir():
                try:
                    stat = entry.stat()
                    items.append({
                        "name": entry.name,
                        "path": str(entry.resolve()),
                        "is_dir": entry.is_dir(),
                        "size_bytes": stat.st_size if entry.is_file() else 0,
                        "modified_at": stat.st_mtime,
                    })
                except (PermissionError, OSError):
                    pass
        except (PermissionError, OSError) as e:
            logger.warning("Access denied browsing %s: %s", path, e)

        # Sort: directories first, then alphabetically
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

        # Disk space
        total, used, free = shutil.disk_usage(str(path))

        return {
            "current_path": str(path.resolve()),
            "parent_path": str(path.parent.resolve()) if path.parent != path else None,
            "items": items,
            "disk": {
                "total_bytes": total,
                "used_bytes": used,
                "free_bytes": free,
                "free_gb": round(free / (1024 ** 3), 2),
            },
        }

    def init_upload(
        self,
        upload_id: str,
        filename: str,
        total_size: int,
        total_chunks: int,
        target_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Initializes a new chunked upload session."""
        dest_dir = Path(target_dir) if target_dir else self.upload_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        safe_name = "".join(c for c in filename if c.isalnum() or c in (".", "-", "_"))
        temp_file = self.temp_dir / f"{upload_id}_{safe_name}.part"

        # Create or truncate temp file
        temp_file.touch(exist_ok=True)

        session = UploadSession(
            upload_id=upload_id,
            filename=safe_name,
            target_dir=str(dest_dir.resolve()),
            total_size=total_size,
            total_chunks=total_chunks,
            uploaded_chunks=set(),
            temp_file_path=temp_file,
            created_at=time.time(),
        )
        self._active_uploads[upload_id] = session

        logger.info("Initialized chunked upload: %s (%d bytes, %d chunks)", safe_name, total_size, total_chunks)
        return {
            "upload_id": upload_id,
            "filename": safe_name,
            "total_chunks": total_chunks,
            "ready": True,
        }

    def append_chunk(self, upload_id: str, chunk_index: int, chunk_data: bytes) -> Dict[str, Any]:
        """Appends a chunk to the temporary upload file."""
        session = self._active_uploads.get(upload_id)
        if not session:
            raise ValueError(f"Upload session not found: {upload_id}")

        # Append chunk data
        with open(session.temp_file_path, "ab") as f:
            f.write(chunk_data)

        session.uploaded_chunks.add(chunk_index)
        progress = len(session.uploaded_chunks) / session.total_chunks * 100.0

        return {
            "upload_id": upload_id,
            "chunk_index": chunk_index,
            "received_chunks": len(session.uploaded_chunks),
            "total_chunks": session.total_chunks,
            "progress_percent": round(progress, 1),
        }

    def finalize_upload(
        self,
        upload_id: str,
        expected_sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validates and moves completed upload to target directory."""
        session = self._active_uploads.get(upload_id)
        if not session:
            raise ValueError(f"Upload session not found: {upload_id}")

        final_dest = Path(session.target_dir) / session.filename

        # Verify SHA-256 if provided
        if expected_sha256:
            hasher = hashlib.sha256()
            with open(session.temp_file_path, "rb") as f:
                while chunk := f.read(4 * 1024 * 1024):
                    hasher.update(chunk)
            actual_sha = hasher.hexdigest().lower()
            if actual_sha != expected_sha256.lower():
                try:
                    session.temp_file_path.unlink()
                except OSError:
                    pass
                del self._active_uploads[upload_id]
                raise ValueError(f"Checksum mismatch: expected {expected_sha256}, got {actual_sha}")

        # Move to destination
        shutil.move(str(session.temp_file_path), str(final_dest))
        del self._active_uploads[upload_id]

        logger.info("Upload finalized successfully: %s -> %s", session.filename, final_dest)
        return {
            "upload_id": upload_id,
            "status": "COMPLETED",
            "final_path": str(final_dest.resolve()),
            "size_bytes": final_dest.stat().st_size,
        }
