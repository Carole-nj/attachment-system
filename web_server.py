"""Local browser-based attachment application tracker.

Run with: python web_server.py
This prototype binds to localhost and is not intended for public deployment.
"""

from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import secrets
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
SESSION_HOURS = 12


def connect_database() -> sqlite3.Connection:
    """Open a configured SQLite connection with named-row access."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    """Create tables and add fields while preserving existing application records."""
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
                created_at TEXT NOT NULL,
                entry_type TEXT NOT NULL DEFAULT 'student'
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(applications)")
        }
        if "entry_type" not in columns:
            connection.execute(
                "ALTER TABLE applications ADD COLUMN entry_type TEXT NOT NULL DEFAULT 'student'"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS staff_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS staff_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES staff_users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
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


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Hash a password with a per-user salt using Python's scrypt implementation."""
    salt = salt or secrets.token_bytes(16)
    password_hash = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1
    )
    return salt, password_hash


class AttachmentRequestHandler(BaseHTTPRequestHandler):
    """Serve the browser UI and its small JSON API."""

    server_version = "AttachmentTracker/1.0"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            self._serve_page(INDEX_FILE)
        elif path == "/staff":
            self._serve_page(WEB_DIR / "staff.html")
        elif path == "/health":
            self._send_json(200, {"status": "ok"})
        elif path == "/api/auth/status":
            self._auth_status()
        elif path == "/api/applications":
            self._list_applications()
        else:
            self._send_json(404, {"error": "Not found."})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path in {"/api/auth/setup", "/api/auth/login", "/api/auth/logout"}:
            if not self._same_origin():
                self._send_json(403, {"error": "This request origin is not allowed."})
                return
            if path == "/api/auth/setup":
                self._setup_staff_account()
            elif path == "/api/auth/login":
                self._login_staff()
            else:
                self._logout_staff()
            return

        if path != "/api/applications":
            self._send_json(404, {"error": "Not found."})
            return
        if not self._same_origin():
            self._send_json(403, {"error": "This request origin is not allowed."})
            return

        try:
            values = validate_application(self._read_json())
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        staff_user = self._get_authenticated_staff()
        entry_type = "staff" if staff_user else "student"
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(connect_database()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO applications (
                    full_name, email, phone, institution, course,
                    start_date, end_date, created_at, entry_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    entry_type,
                ),
            )
            connection.commit()
            application_id = cursor.lastrowid

        self._send_json(
            201,
            {
                "id": application_id,
                **values,
                "status": "pending",
                "entry_type": entry_type,
                "created_at": created_at,
            },
        )

    def do_PUT(self) -> None:
        self._send_json(404, {"error": "Not found."})

    def do_PATCH(self) -> None:
        match = re.fullmatch(r"/api/applications/(\d+)/status", urlsplit(self.path).path)
        if match is None:
            self._send_json(404, {"error": "Not found."})
            return
        if not self._same_origin():
            self._send_json(403, {"error": "This request origin is not allowed."})
            return
        if not self._get_authenticated_staff():
            self._send_json(401, {"error": "Staff sign-in required."})
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

    def _serve_page(self, page: Path) -> None:
        if not page.is_file():
            self._send_json(500, {"error": "The web interface file is missing."})
            return
        content = page.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(content)

    def _auth_status(self) -> None:
        staff_user = self._get_authenticated_staff()
        with closing(connect_database()) as connection:
            setup_required = (
                connection.execute("SELECT COUNT(*) FROM staff_users").fetchone()[0] == 0
            )
        self._send_json(
            200,
            {
                "setup_required": setup_required,
                "authenticated": staff_user is not None,
                "username": staff_user["username"] if staff_user else None,
            },
        )

    def _setup_staff_account(self) -> None:
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "Request body must be a JSON object."})
            return

        username = payload.get("username")
        password = payload.get("password")
        if not isinstance(username, str) or not re.fullmatch(
            r"[A-Za-z0-9._-]{3,48}", username.strip()
        ):
            self._send_json(
                400,
                {"error": "Username must be 3-48 letters, numbers, dots, underscores, or hyphens."},
            )
            return
        username = username.strip()
        if not isinstance(password, str) or len(password) < 12:
            self._send_json(400, {"error": "Password must be at least 12 characters."})
            return
        if len(password) > 1024:
            self._send_json(400, {"error": "Password is too long."})
            return

        salt, password_hash = hash_password(password)
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(connect_database()) as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO staff_users (username, password_salt, password_hash, created_at)
                    SELECT ?, ?, ?, ?
                    WHERE NOT EXISTS (SELECT 1 FROM staff_users)
                    """,
                    (username, salt, password_hash, created_at),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                self._send_json(409, {"error": "That username is already in use."})
                return
            if cursor.rowcount == 0:
                self._send_json(409, {"error": "Initial staff setup is already complete."})
                return
            user_id = cursor.lastrowid

        self._create_staff_session(user_id)

    def _login_staff(self) -> None:
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "Request body must be a JSON object."})
            return
        username = payload.get("username")
        password = payload.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            self._send_json(400, {"error": "Username and password are required."})
            return
        if len(password) > 1024:
            self._send_json(400, {"error": "Password is too long."})
            return
        with closing(connect_database()) as connection:
            user = connection.execute(
                "SELECT id, username, password_salt, password_hash FROM staff_users WHERE username = ?",
                (username.strip(),),
            ).fetchone()
        if not user:
            self._send_json(401, {"error": "Invalid username or password."})
            return
        _, candidate = hash_password(password, user["password_salt"])
        if not secrets.compare_digest(candidate, user["password_hash"]):
            self._send_json(401, {"error": "Invalid username or password."})
            return
        self._create_staff_session(user["id"])

    def _logout_staff(self) -> None:
        session_token = self._session_token()
        if session_token:
            with closing(connect_database()) as connection:
                connection.execute(
                    "DELETE FROM staff_sessions WHERE token_hash = ?",
                    (hashlib.sha256(session_token.encode("ascii")).hexdigest(),),
                )
                connection.commit()
        self._send_response_with_cookie(200, {"logged_out": True}, "")

    def _create_staff_session(self, user_id: int) -> None:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        expires_at = datetime.now(timezone.utc).timestamp() + SESSION_HOURS * 3600
        expires = datetime.fromtimestamp(expires_at, timezone.utc).isoformat(
            timespec="seconds"
        )
        with closing(connect_database()) as connection:
            connection.execute(
                "DELETE FROM staff_sessions WHERE expires_at <= ?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
            )
            connection.execute(
                "INSERT INTO staff_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash, user_id, expires),
            )
            connection.commit()
        self._send_response_with_cookie(
            200,
            {"authenticated": True, "expires_at": expires},
            f"attachment_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_HOURS * 3600}",
        )

    def _get_authenticated_staff(self) -> sqlite3.Row | None:
        token = self._session_token()
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(connect_database()) as connection:
            return connection.execute(
                """
                SELECT staff_users.id, staff_users.username
                FROM staff_sessions
                JOIN staff_users ON staff_users.id = staff_sessions.user_id
                WHERE staff_sessions.token_hash = ? AND staff_sessions.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()

    def _session_token(self) -> str | None:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get("attachment_session")
        if morsel and re.fullmatch(r"[A-Za-z0-9_-]{20,100}", morsel.value):
            return morsel.value
        return None

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if not origin or not host:
            return False
        parsed_origin = urlsplit(origin)
        return parsed_origin.scheme == "http" and parsed_origin.netloc == host

    def _list_applications(self) -> None:
        if not self._get_authenticated_staff():
            self._send_json(401, {"error": "Staff sign-in required."})
            return
        with closing(connect_database()) as connection:
            rows = connection.execute(
                """
                SELECT id, full_name, email, phone, institution, course,
                       start_date, end_date, status, created_at, entry_type
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
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _send_response_with_cookie(
        self, status_code: int, payload: object, cookie_header: str
    ) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        if cookie_header:
            self.send_header("Set-Cookie", cookie_header)
        else:
            self.send_header(
                "Set-Cookie",
                "attachment_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0",
            )
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    initialize_database()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), AttachmentRequestHandler)
    print(f"Attachment tracker available at http://127.0.0.1:{port}")
    print("Local prototype only; do not expose this server directly to a network.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping attachment tracker.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
