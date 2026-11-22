"""
Unit tests for ResourceGuard and dynamic hardware scaling.
"""

import unittest
from core.resource_guard import ResourceGuard


class TestResourceGuard(unittest.TestCase):
    def test_inspect_system(self):
        guard = ResourceGuard()
        profile = guard.inspect_system()
        self.assertGreater(profile.cpu_count, 0)
        self.assertGreater(profile.total_ram_bytes, 0)
        self.assertGreater(profile.recommended_workers, 0)
        self.assertGreater(profile.recommended_chunk_bytes, 0)

    def test_chunk_scaling(self):
        guard = ResourceGuard()
        # 256MB RAM budget -> 4MB chunk
        c1 = guard.compute_optimal_chunk_size(available_ram=256 * 1024 * 1024, workers=1)
        self.assertEqual(c1, 4 * 1024 * 1024)

        # 16GB RAM budget -> 32MB chunk
        c2 = guard.compute_optimal_chunk_size(available_ram=16 * 1024 * 1024 * 1024, workers=1)
        self.assertEqual(c2, 32 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
