import json
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_server


class AttachmentWebServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = web_server.DB_PATH
        web_server.DB_PATH = Path(cls.temp_dir.name) / "test.db"
        web_server.initialize_database()
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), web_server.AttachmentRequestHandler
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        web_server.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def setUp(self) -> None:
        with closing(web_server.connect_database()) as connection:
            connection.execute("DELETE FROM applications")
            connection.commit()

    def request_json(
        self, path: str, method: str = "GET", payload: object | None = None
    ) -> tuple[int, object]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    @staticmethod
    def sample_application(**updates: str) -> dict[str, str]:
        application = {
            "full_name": "Test Student",
            "email": "student@example.org",
            "phone": "0700000000",
            "institution": "Test College",
            "course": "Computing",
            "start_date": "2026-11-01",
            "end_date": "2027-02-01",
        }
        application.update(updates)
        return application

    def test_ui_and_health_endpoint(self) -> None:
        with urlopen(self.base_url + "/") as response:
            self.assertEqual(response.status, 200)
            self.assertIn(
                b"Attachment Application Tracker", response.read()
            )
        status, health = self.request_json("/health")
        self.assertEqual(status, 200)
        self.assertEqual(health, {"status": "ok"})

    def test_create_list_and_review_application(self) -> None:
        status, created = self.request_json(
            "/api/applications", "POST", self.sample_application()
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["status"], "pending")

        status, applications = self.request_json("/api/applications")
        self.assertEqual(status, 200)
        self.assertEqual(len(applications), 1)
        self.assertEqual(applications[0]["id"], created["id"])

        status, review = self.request_json(
            f"/api/applications/{created['id']}/status",
            "PATCH",
            {"status": "approved"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(review["status"], "approved")

    def test_invalid_date_range_and_status_are_rejected(self) -> None:
        status, error = self.request_json(
            "/api/applications",
            "POST",
            self.sample_application(end_date="2026-10-01"),
        )
        self.assertEqual(status, 400)
        self.assertIn("End date", error["error"])

        status, error = self.request_json(
            "/api/applications/1/status", "PATCH", {"status": []}
        )
        self.assertEqual(status, 400)
        self.assertIn("Status must be", error["error"])


if __name__ == "__main__":
    unittest.main()
