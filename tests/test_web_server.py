import json
from contextlib import closing
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

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
            connection.execute("DELETE FROM staff_sessions")
            connection.execute("DELETE FROM staff_users")
            connection.commit()
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, response = self.request_json(
            "/api/auth/setup",
            "POST",
            {"username": "admin", "password": "a secure password phrase"},
        )
        self.assertEqual(status, 200, response)

    def request_json(
        self,
        path: str,
        method: str = "GET",
        payload: object | None = None,
        opener=None,
    ) -> tuple[int, object]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Origin": self.base_url,
            },
            method=method,
        )
        try:
            with (opener or self.opener).open(request) as response:
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
            self.assertIn(b"Attachment Application", response.read())
        with urlopen(self.base_url + "/staff") as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"Staff sign in", response.read())
        status, health = self.request_json("/health")
        self.assertEqual(status, 200)
        self.assertEqual(health, {"status": "ok"})

    def test_student_submission_is_private_and_staff_can_review(self) -> None:
        anonymous = build_opener(HTTPCookieProcessor(CookieJar()))
        status, created = self.request_json(
            "/api/applications",
            "POST",
            self.sample_application(),
            opener=anonymous,
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["status"], "pending")
        self.assertEqual(created["entry_type"], "student")

        status, error = self.request_json(
            "/api/applications", opener=anonymous
        )
        self.assertEqual(status, 401)
        self.assertIn("Staff sign-in required", error["error"])

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

    def test_staff_can_enter_an_application_and_setup_is_one_time(self) -> None:
        status, created = self.request_json(
            "/api/applications", "POST", self.sample_application()
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["entry_type"], "staff")

        status, error = self.request_json(
            "/api/auth/setup",
            "POST",
            {"username": "another", "password": "another secure password"},
        )
        self.assertEqual(status, 409)
        self.assertIn("already complete", error["error"])

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

    def test_staff_listing_and_status_change_require_authentication(self) -> None:
        anonymous = build_opener(HTTPCookieProcessor(CookieJar()))
        status, error = self.request_json(
            "/api/applications/1/status",
            "PATCH",
            {"status": "approved"},
            opener=anonymous,
        )
        self.assertEqual(status, 401)
        self.assertIn("Staff sign-in required", error["error"])

    def test_login_and_logout_manage_staff_session(self) -> None:
        status, response = self.request_json(
            "/api/auth/login",
            "POST",
            {"username": "admin", "password": "a secure password phrase"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(response["authenticated"])
        status, _ = self.request_json(
            "/api/auth/logout", "POST", {}
        )
        self.assertEqual(status, 200)
        status, error = self.request_json("/api/applications")
        self.assertEqual(status, 401)
        self.assertIn("Staff sign-in required", error["error"])


class DatabaseMigrationTests(unittest.TestCase):
    def test_existing_applications_are_preserved(self) -> None:
        original_db_path = web_server.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            web_server.DB_PATH = Path(temp_dir) / "legacy.db"
            with closing(sqlite3.connect(web_server.DB_PATH)) as connection:
                connection.execute(
                    """
                    CREATE TABLE applications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        full_name TEXT NOT NULL,
                        email TEXT NOT NULL,
                        phone TEXT NOT NULL,
                        institution TEXT NOT NULL,
                        course TEXT NOT NULL,
                        start_date TEXT NOT NULL,
                        end_date TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO applications (
                        full_name, email, phone, institution, course,
                        start_date, end_date, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "Existing Student",
                        "existing@example.org",
                        "0700000000",
                        "Test College",
                        "Computing",
                        "2026-11-01",
                        "2027-02-01",
                        "2026-10-27T00:00:00+00:00",
                    ),
                )
                connection.commit()

            try:
                web_server.initialize_database()
                with closing(web_server.connect_database()) as connection:
                    row = connection.execute(
                        "SELECT full_name, entry_type FROM applications WHERE id = 1"
                    ).fetchone()
                self.assertEqual(row["full_name"], "Existing Student")
                self.assertEqual(row["entry_type"], "student")
            finally:
                web_server.DB_PATH = original_db_path


if __name__ == "__main__":
    unittest.main()
