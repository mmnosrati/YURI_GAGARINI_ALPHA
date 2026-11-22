"""
FastAPI Enterprise Application & WebSocket Server for Yuri Gagarin Search Engine.
Provides comprehensive REST endpoints, live terminal streaming, and SPA dashboard delivery.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from core.engine_ripgrep import RipgrepEngine
from core.resource_guard import ResourceGuard
from core.search_manager import SearchConfig
from .auth import AuthManager
from .config import ServerConfig, get_server_config, save_server_config
from .file_manager import FileManager
from .job_queue import JobQueueManager
from .logger import read_recent_logs, setup_rotating_logger

logger = setup_rotating_logger()

app = FastAPI(
    title="YURI GAGARIN ALPHA",
    description="Enterprise High-Performance Big-Data Search Platform",
    version="17.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Services
server_cfg = get_server_config()
auth_mgr = AuthManager(server_cfg)
file_mgr = FileManager(upload_dir=server_cfg.default_upload_dir)
resource_guard = ResourceGuard(target_ram_threshold=server_cfg.max_ram_throttle_percent)

# Active WebSocket connections
_active_ws: List[WebSocket] = []
_loop: Optional[asyncio.AbstractEventLoop] = None


def broadcast_event(event_data: Dict[str, Any]) -> None:
    """Thread-safe WebSocket broadcaster."""
    global _loop
    if not _active_ws or _loop is None:
        return

    msg = json.dumps(event_data)
    for ws in list(_active_ws):
        try:
            asyncio.run_coroutine_threadsafe(ws.send_text(msg), _loop)
        except Exception:
            pass


job_queue = JobQueueManager(config=server_cfg, broadcast_callback=broadcast_event)


# Dependency: Authentication
def require_admin(authorization: Optional[str] = Header(None), token_query: Optional[str] = Query(None, alias="token")) -> bool:
    token = None
    if authorization:
        parts = authorization.split(" ")
        token = parts[1] if len(parts) == 2 else parts[0]
    elif token_query:
        token = token_query

    if not auth_mgr.validate_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin authorization token",
        )
    return True


@app.on_event("startup")
async def on_startup():
    global _loop
    _loop = asyncio.get_running_loop()
    logger.info("YURI GAGARIN ALPHA Server started on %s:%d", server_cfg.host, server_cfg.port)


# --- Static Files & Web SPA ---
WEB_DIR = Path(__file__).parent.parent / "web"
ASSETS_DIR = Path(__file__).parent.parent / "assets"

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h3>YURI GAGARIN ALPHA Web UI initializing...</h3>")


# --- Authentication Endpoints ---
@app.post("/api/auth/login")
async def login(payload: Dict[str, str]):
    password = payload.get("password", "")
    # Reload config in case config.json was edited manually on disk
    auth_mgr.config = get_server_config()
    token = auth_mgr.authenticate(password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid administrator credentials.")
    return {"success": True, "token": token}


@app.get("/api/auth/verify")
async def verify_auth(authorized: bool = Depends(require_admin)):
    return {"authenticated": True}


# --- System & Hardware Endpoints ---
@app.get("/api/system/profile")
async def get_system_profile(authorized: bool = Depends(require_admin)):
    profile = resource_guard.inspect_system()
    return {
        "platform": profile.platform,
        "cpu_count": profile.cpu_count,
        "total_ram_gb": round(profile.total_ram_bytes / (1024 ** 3), 2),
        "available_ram_gb": round(profile.available_ram_bytes / (1024 ** 3), 2),
        "ram_usage_percent": profile.ram_usage_percent,
        "swap_usage_percent": profile.swap_usage_percent,
        "cpu_load_1m": round(profile.cpu_load_1m, 2),
        "recommended_workers": profile.recommended_workers,
        "recommended_chunk_mb": profile.recommended_chunk_bytes // (1024 * 1024),
        "posix_fadvise": profile.posix_fadvise_supported,
    }


# --- Filesystem & Upload Endpoints ---
@app.get("/api/fs/browse")
async def browse_directory(path: Optional[str] = Query(None), authorized: bool = Depends(require_admin)):
    try:
        return file_mgr.list_directory(path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/fs/upload/init")
async def init_upload(payload: Dict[str, Any], authorized: bool = Depends(require_admin)):
    try:
        return file_mgr.init_upload(
            upload_id=payload["upload_id"],
            filename=payload["filename"],
            total_size=int(payload["total_size"]),
            total_chunks=int(payload["total_chunks"]),
            target_dir=payload.get("target_dir"),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/fs/upload/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    file: UploadFile = File(...),
    authorized: bool = Depends(require_admin),
):
    try:
        content = await file.read()
        return file_mgr.append_chunk(upload_id, chunk_index, content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/fs/upload/complete")
async def complete_upload(payload: Dict[str, Any], authorized: bool = Depends(require_admin)):
    try:
        return file_mgr.finalize_upload(
            upload_id=payload["upload_id"],
            expected_sha256=payload.get("sha256"),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Logs & Diagnostics Endpoints ---
@app.get("/api/logs/recent")
async def get_recent_server_logs(lines: int = Query(200, ge=10, le=2000), authorized: bool = Depends(require_admin)):
    """Retrieves up to 2-day historical server logs for admin diagnostics."""
    return {"logs": read_recent_logs(max_lines=lines)}


# --- Search Job Management Endpoints ---
@app.post("/api/jobs/start")
async def start_search_job(payload: Dict[str, Any], authorized: bool = Depends(require_admin)):
    patterns = payload.get("patterns", [])
    if isinstance(patterns, str):
        patterns = [p.strip() for p in patterns.splitlines() if p.strip()]

    if not patterns:
        raise HTTPException(status_code=400, detail="At least one search pattern is required.")

    target_path = payload.get("target_path", "").strip()
    if not target_path or not Path(target_path).exists():
        raise HTTPException(status_code=400, detail=f"Target path does not exist: {target_path}")

    out_file = payload.get("output_file", "").strip()
    if not out_file:
        safe_name = "".join(c for c in patterns[0] if c.isalnum() or c in ("-", "_"))[:20]
        out_file = str(Path(server_cfg.default_output_dir) / f"search_{safe_name}_{int(asyncio.get_event_loop().time())}.txt")

    cfg = SearchConfig(
        target_path=target_path,
        patterns=patterns,
        output_file=out_file,
        engine_type=str(payload.get("engine_type", "ripgrep")),
        is_regex=bool(payload.get("is_regex", False)),
        case_sensitive=bool(payload.get("case_sensitive", False)),
        output_format=str(payload.get("output_format", "clean")),
        extract_only=bool(payload.get("extract_only", False)),
        recursive=bool(payload.get("recursive", True)),
        skip_hidden=bool(payload.get("skip_hidden", True)),
        detailed_stats=bool(payload.get("detailed_stats", True)),
        low_memory_mode=bool(payload.get("low_memory_mode", False)),
        compress_algo=str(payload.get("compress_algo", "none")),
        rg_threads=int(payload.get("rg_threads", 0)),
        rg_mmap=bool(payload.get("rg_mmap", True)),
        rg_pcre2=bool(payload.get("rg_pcre2", True)),
        rg_smart_case=bool(payload.get("rg_smart_case", False)),
    )

    job = job_queue.start_job(cfg)
    return {"success": True, "job": job.to_dict()}


@app.get("/api/jobs/list")
async def list_jobs(authorized: bool = Depends(require_admin)):
    return {"jobs": job_queue.list_jobs()}


@app.post("/api/jobs/{job_id}/pause")
async def pause_job(job_id: str, authorized: bool = Depends(require_admin)):
    ok = job_queue.pause_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found or not in running state.")
    return {"success": True, "job_id": job_id, "status": "PAUSED"}


@app.post("/api/jobs/{job_id}/resume")
async def resume_job(job_id: str, authorized: bool = Depends(require_admin)):
    ok = job_queue.resume_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found or could not be resumed.")
    return {"success": True, "job_id": job_id, "status": "RUNNING"}


@app.post("/api/jobs/{job_id}/stop")
async def stop_job(job_id: str, authorized: bool = Depends(require_admin)):
    ok = job_queue.stop_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found or already stopped.")
    return {"success": True, "job_id": job_id, "status": "STOPPED"}


# --- Results & Download Endpoints ---
@app.get("/api/results/download")
async def download_result_file(
    file_path: str = Query(...),
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    require_admin(authorization=authorization, token_query=token)
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="Requested result file was not found.")
    return FileResponse(
        path=str(p),
        filename=p.name,
        media_type="application/octet-stream",
    )


# --- Settings & Telegram Endpoints ---
@app.get("/api/settings")
async def get_settings(authorized: bool = Depends(require_admin)):
    return {
        "hardware_profile": getattr(server_cfg, "hardware_profile", "eco"),
        "default_threads": getattr(server_cfg, "default_threads", 0),
        "tg_enabled": server_cfg.tg_enabled,
        "tg_token": server_cfg.tg_token,
        "tg_chat_id": server_cfg.tg_chat_id,
        "tg_chunk_mb": server_cfg.tg_chunk_mb,
        "tg_send_file": getattr(server_cfg, "tg_send_file", True),
        "max_ram_throttle_percent": server_cfg.max_ram_throttle_percent,
        "default_upload_dir": server_cfg.default_upload_dir,
        "default_output_dir": server_cfg.default_output_dir,
    }


@app.post("/api/settings/update")
async def update_settings(payload: Dict[str, Any], authorized: bool = Depends(require_admin)):
    if "hardware_profile" in payload:
        server_cfg.hardware_profile = str(payload["hardware_profile"])
    if "default_threads" in payload:
        server_cfg.default_threads = int(payload["default_threads"])
    if "tg_enabled" in payload:
        server_cfg.tg_enabled = bool(payload["tg_enabled"])
    if "tg_token" in payload:
        server_cfg.tg_token = str(payload["tg_token"]).strip()
    if "tg_chat_id" in payload:
        server_cfg.tg_chat_id = str(payload["tg_chat_id"]).strip()
    if "tg_chunk_mb" in payload:
        server_cfg.tg_chunk_mb = int(payload["tg_chunk_mb"])
    if "tg_send_file" in payload:
        server_cfg.tg_send_file = bool(payload["tg_send_file"])
    if "max_ram_throttle_percent" in payload:
        server_cfg.max_ram_throttle_percent = float(payload["max_ram_throttle_percent"])
    if "default_upload_dir" in payload:
        server_cfg.default_upload_dir = str(payload["default_upload_dir"])
    if "default_output_dir" in payload:
        server_cfg.default_output_dir = str(payload["default_output_dir"])

    # Password update
    if payload.get("new_password"):
        auth_mgr.set_admin_password(str(payload["new_password"]))
    else:
        save_server_config(server_cfg)

    job_queue.telegram.update_credentials(
        server_cfg.tg_token,
        server_cfg.tg_chat_id,
        server_cfg.tg_enabled,
    )
    return {"success": True, "message": "Settings updated successfully."}


@app.post("/api/telegram/test")
async def test_telegram(authorized: bool = Depends(require_admin)):
    res = job_queue.telegram.test_connection()
    return res


# --- WebSocket Telemetry & Real-Time Terminal ---
@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    _active_ws.append(websocket)
    try:
        # Send initial hardware state
        prof = resource_guard.inspect_system()
        await websocket.send_text(json.dumps({
            "event": "hardware",
            "data": {
                "cpu_load": prof.cpu_load_1m,
                "ram_percent": prof.ram_usage_percent,
                "ram_free_gb": round(prof.available_ram_bytes / (1024 ** 3), 2),
            }
        }))

        # Keepalive loop: gracefully handle disconnections without raising ASGI exceptions
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                try:
                    await websocket.send_text(json.dumps({"event": "pong"}))
                except Exception:
                    break
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if websocket in _active_ws:
            _active_ws.remove(websocket)
