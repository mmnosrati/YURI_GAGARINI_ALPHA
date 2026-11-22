#!/usr/bin/env python3
"""
YURIGAGARIN ALPHA - ENTERPRISE CLI WORKER (VERSION 17.0)
High-performance command-line search worker.
Leverages the core/ search subsystem for maximum scanning speed across 100+ GB files.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from core.checkpoint import CheckpointManager
from core.resource_guard import ResourceGuard
from core.search_manager import SearchConfig, SearchManager, SearchResult
from server.config import get_server_config
from server.telegram_service import TelegramService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("yurigagarin.cli")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yurigagarin",
        description="YURIGAGARIN ALPHA v17.0 - Enterprise Big-Data Text Search Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--search", "-s", metavar="PATH", help="Target file or directory to scan")
    p.add_argument("--pattern", "-p", metavar="PATTERN", help="Keyword or regex pattern (use newline for multiple)")
    p.add_argument("--pattern-file", metavar="FILE", help="File containing search patterns (one per line)")
    p.add_argument("--output", "-o", metavar="FILE", help="Output file path")
    p.add_argument("--regex", action="store_true", help="Treat patterns as regular expressions (JIT compiled)")
    p.add_argument("--case-sensitive", action="store_true", help="Enable case-sensitive matching")
    p.add_argument("--no-recursive", action="store_true", help="Disable recursive directory traversal")
    p.add_argument("--full-context", action="store_true", help="Output match lines instead of extracted terms only")
    p.add_argument("--low-memory", action="store_true", help="Force low-memory buffer mode (4 MB chunks)")
    p.add_argument("--compress", choices=["gzip", "zstd", "lz4", "none"], default="none", help="Compress search output")
    p.add_argument("--compress-level", type=int, default=6, help="Compression level (1-9)")
    p.add_argument("--chunk-bytes", type=int, default=None, help="Explicit chunk size in bytes")
    p.add_argument("--job-id", metavar="ID", help="Explicit job ID (for resuming checkpoints)")
    p.add_argument("--no-telegram", action="store_true", help="Disable Telegram alerts for this run")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.search:
        parser.print_help()
        sys.exit(1)

    patterns = []
    if args.pattern:
        patterns.extend([p.strip() for p in args.pattern.splitlines() if p.strip()])
    if args.pattern_file:
        pf = Path(args.pattern_file)
        if pf.exists():
            patterns.extend([p.strip() for p in pf.read_text(encoding="utf-8", errors="replace").splitlines() if p.strip()])
        else:
            logger.error("Pattern file not found: %s", args.pattern_file)
            sys.exit(1)

    if not patterns:
        logger.error("No valid search patterns specified. Use --pattern or --pattern-file.")
        sys.exit(1)

    target_path = Path(args.search)
    if not target_path.exists():
        logger.error("Target search path does not exist: %s", target_path)
        sys.exit(1)

    output_file = args.output
    if not output_file:
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in patterns[0] if c.isalnum() or c in ("-", "_"))[:20]
        output_file = str(out_dir / f"search_{safe}_{int(time.time())}.txt")

    cfg = SearchConfig(
        target_path=str(target_path.resolve()),
        patterns=patterns,
        output_file=output_file,
        is_regex=args.regex,
        case_sensitive=args.case_sensitive,
        extract_only=not args.full_context,
        recursive=not args.no_recursive,
        low_memory_mode=args.low_memory,
        chunk_bytes=args.chunk_bytes,
        compress_algo=args.compress,
        compress_level=args.compress_level,
        job_id=args.job_id,
    )

    server_cfg = get_server_config()
    tg = TelegramService(
        token=server_cfg.tg_token,
        chat_id=server_cfg.tg_chat_id,
        enabled=server_cfg.tg_enabled and not args.no_telegram,
    )

    def on_progress(p):
        logger.info(
            "Progress: %5.1f%% | Speed: %6.2f MB/s | ETA: %4ds | Matches: %d | File: %s",
            p["percent"],
            p["speed_mb_s"],
            p["eta_seconds"],
            p["total_matches"],
            p["file_current"],
        )

    logger.info("=" * 64)
    logger.info("YURI GAGARIN ALPHA - HIGH-PERFORMANCE SEARCH WORKER")
    logger.info("Target: %s | Patterns: %d | Engine: %s", target_path, len(patterns), "Regex" if args.regex else "Aho-Corasick")
    logger.info("=" * 64)

    if tg.enabled:
        tg.send_message(
            f"🚀 *YURI GAGARIN ALPHA (CLI)* Starting Search\n"
            f"Target: `{target_path.name}`\n"
            f"Patterns: `{len(patterns)}`\n"
            f"Engine: `{'Regex' if args.regex else 'Aho-Corasick'}`"
        )

    manager = SearchManager(config=cfg, progress_callback=on_progress)

    try:
        res: SearchResult = manager.execute()
        logger.info("=" * 64)
        logger.info("SEARCH COMPLETED SUCCESSFULLY")
        logger.info("Total Matches  : %d", res.total_matches)
        logger.info("Files Scanned  : %d / %d", res.files_searched, res.files_discovered)
        logger.info("Throughput     : %.2f MB/s", res.throughput_mb_s)
        logger.info("Execution Time : %.2fs", res.elapsed_seconds)
        logger.info("Output File    : %s", res.output_file)
        logger.info("=" * 64)

        if tg.enabled:
            tg.send_output_file_multipart(Path(res.output_file), res.__dict__)

    except KeyboardInterrupt:
        logger.warning("Interrupted by user. State saved in checkpoints.")
        sys.exit(0)
    except Exception as e:
        logger.exception("Fatal search worker error: %s", e)
        if tg.enabled:
            tg.send_message(f"❌ *CLI Search Failed*: `{e}`")
        sys.exit(1)


if __name__ == "__main__":
    main()
