"""
Unit tests for Checkpoint state persistence and atomic resume.
"""

import tempfile
import unittest
from pathlib import Path

from core.checkpoint import CheckpointManager, CheckpointState


class TestCheckpointManager(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = CheckpointManager(directory=tmpdir)
            state = CheckpointState(
                job_id="test_job_123",
                target_path="/var/data",
                patterns=["needle1", "needle2"],
                is_regex=False,
                case_sensitive=True,
                extract_only=True,
                output_file="/var/data/out.txt",
                current_file_offset=4096000,
                total_matches_count=150,
            )
            mgr.save(state)

            loaded = mgr.load("test_job_123")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.job_id, "test_job_123")
            self.assertEqual(loaded.current_file_offset, 4096000)
            self.assertEqual(loaded.total_matches_count, 150)

            # Test list
            all_cp = mgr.list_checkpoints()
            self.assertEqual(len(all_cp), 1)

            # Test remove
            mgr.remove("test_job_123")
            self.assertIsNone(mgr.load("test_job_123"))


if __name__ == "__main__":
    unittest.main()
