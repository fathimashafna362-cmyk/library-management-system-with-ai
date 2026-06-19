from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen
import json
import mimetypes
import os
import threading
import webbrowser


ROOT = Path(__file__).resolve().parent
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://hzfwsaxervmxjkjojigs.supabase.co").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_P6FIQVEc08grizb3RpDwlA_R-5IeHIV")
BOOKS_TABLE = os.getenv("SUPABASE_BOOKS_TABLE", "library_books")


class SupabaseError(Exception):
    def __init__(self, message, status_code=500):
        super().__init__(message)
        self.status_code = status_code


def supabase_headers(extra_headers=None):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    if extra_headers:
        headers.update(extra_headers)

    return headers


def supabase_request(method, path, payload=None, extra_headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        data=data,
        method=method,
        headers=supabase_headers(extra_headers),
    )

    try:
        with urlopen(req, timeout=15) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except HTTPError as error:
        body = error.read().decode("utf-8")
        try:
            details = json.loads(body)
            message = details.get("message") or details.get("hint") or body
        except json.JSONDecodeError:
            message = body or error.reason
        raise SupabaseError(message, error.code) from error
    except URLError as error:
        raise SupabaseError(f"Could not reach Supabase: {error.reason}") from error


def validate_title(title):
    clean_title = str(title or "").strip()

    if not clean_title:
        raise SupabaseError("Book title is required.", 400)

    return clean_title


def validate_status(status):
    clean_status = str(status or "available").strip().lower()

    if clean_status not in {"available", "borrowed"}:
        raise SupabaseError("Book status must be available or borrowed.", 400)

    return clean_status


def title_filter(title):
    return f"title=eq.{quote(title, safe='')}"


class LibraryHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_empty(self, status=204):
        self.send_response(status)
        self.send_cors_headers()
        self.end_headers()

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, apikey")

    def do_OPTIONS(self):
        self.send_empty()

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}

        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body) if body else {}

    def handle_error(self, error):
        if isinstance(error, SupabaseError):
            self.send_json({"error": str(error)}, error.status_code)
            return

        self.send_json({"error": str(error)}, 500)

    def do_GET(self):
        path = urlparse(self.path).path

        try:
            if path == "/api/health":
                self.send_json(
                    {
                        "ok": True,
                        "supabaseUrl": SUPABASE_URL,
                        "table": BOOKS_TABLE,
                    }
                )
                return

            if path == "/api/books":
                rows = supabase_request(
                    "GET",
                    f"{BOOKS_TABLE}?select=title,status&order=created_at.desc",
                )
                self.send_json(rows or [])
                return

            self.serve_file("index.html" if path == "/" else path.lstrip("/"))
        except Exception as error:
            self.handle_error(error)

    def do_POST(self):
        path = urlparse(self.path).path

        try:
            if path != "/api/books":
                self.send_json({"error": "Not found"}, 404)
                return

            payload = self.read_json()
            title = validate_title(payload.get("title"))
            status = validate_status(payload.get("status", "available"))
            supabase_request(
                "POST",
                BOOKS_TABLE,
                [{"title": title, "status": status}],
                {"Prefer": "return=minimal"},
            )
            self.send_json({"title": title, "status": status}, 201)
        except Exception as error:
            self.handle_error(error)

    def do_PATCH(self):
        path = urlparse(self.path).path

        try:
            prefix = "/api/books/"
            if not path.startswith(prefix):
                self.send_json({"error": "Not found"}, 404)
                return

            title = validate_title(unquote(path[len(prefix) :]))
            status = validate_status(self.read_json().get("status"))
            supabase_request(
                "PATCH",
                f"{BOOKS_TABLE}?{title_filter(title)}",
                {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()},
                {"Prefer": "return=minimal"},
            )
            self.send_json({"title": title, "status": status})
        except Exception as error:
            self.handle_error(error)

    def do_DELETE(self):
        path = urlparse(self.path).path

        try:
            prefix = "/api/books/"
            if not path.startswith(prefix):
                self.send_json({"error": "Not found"}, 404)
                return

            title = validate_title(unquote(path[len(prefix) :]))
            supabase_request(
                "DELETE",
                f"{BOOKS_TABLE}?{title_filter(title)}",
                extra_headers={"Prefer": "return=minimal"},
            )
            self.send_empty()
        except Exception as error:
            self.handle_error(error)

    def do_PUT(self):
        path = urlparse(self.path).path

        try:
            if path != "/api/books":
                self.send_json({"error": "Not found"}, 404)
                return

            payload = self.read_json()
            books = [validate_title(title) for title in payload.get("books", [])]
            borrowed_books = [validate_title(title) for title in payload.get("borrowedBooks", [])]
            supabase_request(
                "DELETE",
                f"{BOOKS_TABLE}?title=neq.",
                extra_headers={"Prefer": "return=minimal"},
            )

            rows = [
                *[{"title": title, "status": "available"} for title in books],
                *[{"title": title, "status": "borrowed"} for title in borrowed_books],
            ]

            if rows:
                supabase_request("POST", BOOKS_TABLE, rows, {"Prefer": "return=minimal"})

            self.send_json({"books": books, "borrowedBooks": borrowed_books})
        except Exception as error:
            self.handle_error(error)

    def serve_file(self, relative_path):
        file_path = (ROOT / relative_path).resolve()

        if not file_path.is_file() or ROOT not in file_path.parents and file_path != ROOT:
            self.send_json({"error": "Not found"}, 404)
            return

        content = file_path.read_bytes()
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 5000), LibraryHandler)
    site_url = "http://127.0.0.1:5000"
    print(f"Library server running at {site_url}")
    print("Keep this window open while using the website.")
    if os.getenv("NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(site_url)).start()
    server.serve_forever()
