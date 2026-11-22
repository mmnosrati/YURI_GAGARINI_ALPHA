"""
YURIGAGARIN ALPHA - Core Search Engine & Resource Management Subsystem
"""

from .checkpoint import CheckpointManager, CheckpointState
from .resource_guard import ResourceGuard, SystemProfile
from .engine_aho import AhoCorasickEngine, AhoMatch
from .engine_regex import RegexEngine, RegexMatch
from .search_manager import SearchManager, SearchConfig, SearchResult

__all__ = [
    "CheckpointManager",
    "CheckpointState",
    "ResourceGuard",
    "SystemProfile",
    "AhoCorasickEngine",
    "AhoMatch",
    "RegexEngine",
    "RegexMatch",
    "SearchManager",
    "SearchConfig",
    "SearchResult",
]
