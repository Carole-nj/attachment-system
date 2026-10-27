"""Local browser-based attachment application tracker.

Run with: python web_server.py
This prototype binds to localhost and is not intended for public deployment.
"""

from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit


ROOT_DIR = Path(__file__).resolve().parent
WEB_DIR = ROOT_DIR / "web"
INDEX_FILE = WEB_DIR / "index.html"
DB_PATH = Path(
    os.environ.get("ATTACHMENT_WEB_DB", str(ROOT_DIR / "attachment_web.db"))
)
APPLICATION_STATUSES = {"pending", "approved", "rejected"}
MAX_BODY_SIZE = 16_384


def connect_database() -> sqlite3.Connection:
    """Open a configured SQLite connection with named-row access."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    """Create the application table if it does not exist yet."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_database()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                institution TEXT NOT NULL,
                course TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def validate_application(payload: object) -> dict[str, str]:
    """Validate and normalize data submitted for a new application."""
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    fields = ("full_name", "email", "phone", "institution", "course", "start_date", "end_date")
    values: dict[str, str] = {}
    limits = {
        "full_name": 120,
        "email": 254,
        "phone": 40,
        "institution": 160,
        "course": 160,
        "start_date": 10,
        "end_date": 10,
    }

    for field in fields:
        value = payload.get(field)
        if not isinstance(value, str):
            raise ValueError(f"{field.replace('_', ' ').capitalize()} is required.")
        value = value.strip()
        if not value:
            raise ValueError(f"{field.replace('_', ' ').capitalize()} is required.")
        if len(value) > limits[field]:
            raise ValueError(f"{field.replace('_', ' ').capitalize()} is too long.")
        values[field] = value

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values["email"]):
        raise ValueError("Enter a valid email address.")

    try:
        start = date.fromisoformat(values["start_date"])
        end = date.fromisoformat(values["end_date"])
    except ValueError as exc:
        raise ValueError("Enter valid start and end dates.") from exc

    if end < start:
        raise ValueError("End date must be on or after the start date.")

    return values


class AttachmentRequestHandler(BaseHTTPRequestHandler):
    """Serve the browser UI and its small JSON API."""

    server_version = "AttachmentTracker/1.0"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            self._serve_index()
        elif path == "/health":
            self._send_json(200, {"status": "ok"})
        elif path == "/api/applications":
            self._list_applications()
        else:
            self._send_json(404, {"error": "Not found."})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/applications":
            self._send_json(404, {"error": "Not found."})
            return

        try:
            values = validate_application(self._read_json())
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(connect_database()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO applications (
                    full_name, email, phone, institution, course,
                    start_date, end_date, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["full_name"],
                    values["email"],
                    values["phone"],
                    values["institution"],
                    values["course"],
                    values["start_date"],
                    values["end_date"],
                    created_at,
                ),
            )
            connection.commit()
            application_id = cursor.lastrowid

        self._send_json(201, {"id": application_id, **values, "status": "pending", "created_at": created_at})

    def do_PATCH(self) -> None:
        match = re.fullmatch(r"/api/applications/(\d+)/status", urlsplit(self.path).path)
        if match is None:
            self._send_json(404, {"error": "Not found."})
            return

        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        if not isinstance(payload, dict):
            self._send_json(400, {"error": "Request body must be a JSON object."})
            return
        status = payload.get("status")
        if not isinstance(status, str) or status not in APPLICATION_STATUSES:
            self._send_json(400, {"error": "Status must be pending, approved, or rejected."})
            return

        with closing(connect_database()) as connection:
            cursor = connection.execute(
                "UPDATE applications SET status = ? WHERE id = ?",
                (status, int(match.group(1))),
            )
            connection.commit()
            if cursor.rowcount == 0:
                self._send_json(404, {"error": "Application not found."})
                return

        self._send_json(200, {"id": int(match.group(1)), "status": status})

    def log_message(self, format_string: str, *args: object) -> None:
        """Use the standard access log without exposing submitted form values."""
        super().log_message(format_string, *args)

    def _serve_index(self) -> None:
        if not INDEX_FILE.is_file():
            self._send_json(500, {"error": "The web interface file is missing."})
            return
        content = INDEX_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(content)

    def _list_applications(self) -> None:
        with closing(connect_database()) as connection:
            rows = connection.execute(
                """
                SELECT id, full_name, email, phone, institution, course,
                       start_date, end_date, status, created_at
                FROM applications
                ORDER BY id DESC
                """
            ).fetchall()
        self._send_json(200, [dict(row) for row in rows])

    def _read_json(self) -> object:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length header is required.")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length header.") from exc
        if length < 0 or length > MAX_BODY_SIZE:
            raise ValueError("Request body is too large.")
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Request body must contain valid JSON.") from exc

    def _send_json(self, status_code: int, payload: object) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    initialize_database()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), AttachmentRequestHandler)
    print(f"Attachment tracker available at http://127.0.0.1:{port}")
    print("Local prototype only; do not expose this unauthenticated server to a network.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping attachment tracker.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
