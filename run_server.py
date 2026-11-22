#!/usr/bin/env python3
"""
YURIGAGARIN ALPHA - Web Application Launcher
Starts the enterprise FastAPI backend and serves the English Admin Web UI.
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from server.config import get_server_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("yurigagarin.launcher")


def main():
    parser = argparse.ArgumentParser(
        description="Launch YURIGAGARIN ALPHA Web UI & API Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    cfg = get_server_config()

    parser.add_argument("--host", default=cfg.host, help="Bind network host")
    parser.add_argument("--port", "-p", type=int, default=cfg.port, help="Bind port number")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code change (development)")

    args = parser.parse_args()

    print(r"""
 __     __ _    _ _____  _____   _____          _____          _____  _____ _   _ 
 \ \   / /| |  | |  __ \|_   _| / ____|   /\   / ____|   /\   |  __ \|_   _| \ | |
  \ \_/ / | |  | | |__) | | |  | |  __   /  \ | |  __   /  \  | |__) | | | |  \| |
   \   /  | |  | |  _  /  | |  | | |_ | / /\ \| | |_ | / /\ \ |  _  /  | | | . ` |
    | |   | |__| | | \ \ _| |_ | |__| |/ ____ \ |__| |/ ____ \| | \ \ _| |_| |\  |
    |_|    \____/|_|  \_\_____| \_____/_/    \_\_____/_/    \_\_|  \_\_____|_| \_|
                 ENTERPRISE BIG-DATA SEARCH PLATFORM (v17.0)
    """)
    logger.info("Starting Web UI at http://%s:%d", args.host, args.port)
    logger.info("Default Admin Password: admin (change in Settings tab)")

    uvicorn.run(
        "server.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
