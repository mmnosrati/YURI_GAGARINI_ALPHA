"""
Integration tests for FastAPI endpoints, authentication, job queue, and filesystem APIs.
"""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import app
from server.auth import AuthManager
from server.config import get_server_config


class TestServerAPIIntegration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.cfg = get_server_config()
        self.auth = AuthManager(self.cfg)
        # Login and obtain token with password from config or fallback
        pwd = "yuri8310"
        res = self.client.post("/api/auth/login", json={"password": pwd})
        if res.status_code != 200:
            pwd = "admin"
            res = self.client.post("/api/auth/login", json={"password": pwd})
        self.assertEqual(res.status_code, 200)
        self.token = res.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_unauthorized_access_rejected(self):
        res = self.client.get("/api/system/profile")
        self.assertEqual(res.status_code, 401)

    def test_system_profile_endpoint(self):
        res = self.client.get("/api/system/profile", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("cpu_count", data)
        self.assertIn("total_ram_gb", data)
        self.assertIn("recommended_chunk_mb", data)

    def test_browse_directory_endpoint(self):
        res = self.client.get("/api/fs/browse", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("current_path", data)
        self.assertIn("items", data)
        self.assertIn("disk", data)

    def test_start_and_control_job_lifecycle(self):
        import time
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "sample.txt"
            target.write_text("line 1: admin\nline 2: user\nline 3: admin again\n")

            out = Path(td) / "results.txt"

            # 1. Start Job
            start_res = self.client.post(
                "/api/jobs/start",
                headers=self.headers,
                json={
                    "target_path": str(target),
                    "patterns": ["admin"],
                    "output_file": str(out),
                    "is_regex": False,
                },
            )
            self.assertEqual(start_res.status_code, 200)
            job_data = start_res.json()["job"]
            job_id = job_data["job_id"]

            # Wait briefly for thread execution to finish and release file handles
            for _ in range(20):
                time.sleep(0.05)
                chk = self.client.get("/api/jobs/list", headers=self.headers)
                jobs = chk.json()["jobs"]
                target_job = next((j for j in jobs if j["job_id"] == job_id), None)
                if target_job and target_job["status"] in ("COMPLETED", "FAILED"):
                    break

            # 2. List Jobs
            list_res = self.client.get("/api/jobs/list", headers=self.headers)
            self.assertEqual(list_res.status_code, 200)
            jobs = list_res.json()["jobs"]
            self.assertTrue(any(j["job_id"] == job_id for j in jobs))

    def test_settings_update_endpoint(self):
        res = self.client.post(
            "/api/settings/update",
            headers=self.headers,
            json={
                "max_ram_throttle_percent": 88.0,
                "tg_chunk_mb": 40,
            },
        )
        self.assertEqual(res.status_code, 200)

        # Verify
        get_res = self.client.get("/api/settings", headers=self.headers)
        self.assertEqual(get_res.status_code, 200)
        data = get_res.json()
        self.assertEqual(data["max_ram_throttle_percent"], 88.0)
        self.assertEqual(data["tg_chunk_mb"], 40)


if __name__ == "__main__":
    unittest.main()
