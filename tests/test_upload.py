"""
Unit tests for chunked upload manager and SHA-256 verification.
"""

import hashlib
import tempfile
import unittest
from pathlib import Path

from server.file_manager import FileManager


class TestFileManagerUpload(unittest.TestCase):
    def test_chunked_upload_flow(self):
        with tempfile.TemporaryDirectory() as upload_dir, tempfile.TemporaryDirectory() as temp_dir:
            fm = FileManager(upload_dir=upload_dir, temp_dir=temp_dir)
            content = b"This is a massive multi-gigabyte simulation file." * 1000
            content_sha = hashlib.sha256(content).hexdigest()

            upload_id = "test_upload_999"
            chunk_size = 5000
            total_chunks = (len(content) + chunk_size - 1) // chunk_size

            fm.init_upload(
                upload_id=upload_id,
                filename="simulated_big_data.txt",
                total_size=len(content),
                total_chunks=total_chunks,
            )

            # Upload chunks
            for i in range(total_chunks):
                part = content[i * chunk_size : (i + 1) * chunk_size]
                fm.append_chunk(upload_id, i, part)

            res = fm.finalize_upload(upload_id, expected_sha256=content_sha)
            self.assertEqual(res["status"], "COMPLETED")

            saved_file = Path(res["final_path"])
            self.assertTrue(saved_file.exists())
            self.assertEqual(saved_file.stat().st_size, len(content))


if __name__ == "__main__":
    unittest.main()
