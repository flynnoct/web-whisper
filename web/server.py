#!/usr/bin/env python3
"""Dependency-free web UI and reverse proxy for the Whisper HTTP API."""

from __future__ import annotations

import http.client
import json
import mimetypes
import os
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, HTTPServer


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
UPSTREAM = urlsplit(os.getenv("WHISPER_API_BASE_URL", "http://127.0.0.1:8001"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(1024 * 1024 * 1024)))

PROXY_ROUTES = {
    "/api/health": "/health",
    "/api/models": "/v1/models",
    "/api/transcriptions": "/v1/audio/transcriptions",
}


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class WebWhisperHandler(BaseHTTPRequestHandler):
    server_version = "WebWhisper/1.0"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self._proxy_health()
            return
        if path in PROXY_ROUTES:
            self._proxy("GET", PROXY_ROUTES[path])
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/api/transcriptions":
            self.send_error(404)
            return
        content_length = self._content_length()
        if content_length is None:
            self._json_error(411, "请求缺少 Content-Length")
            return
        if content_length > MAX_UPLOAD_BYTES:
            self._json_error(413, "文件过大")
            return
        self._proxy("POST", PROXY_ROUTES[path], content_length)

    def _proxy(self, method: str, upstream_path: str, content_length: int = 0) -> None:
        connection_class = http.client.HTTPSConnection if UPSTREAM.scheme == "https" else http.client.HTTPConnection
        base_path = UPSTREAM.path.rstrip("/")
        # Status checks should fail fast; transcription may legitimately take a long time.
        timeout = 3600 if method == "POST" else 8
        connection = connection_class(UPSTREAM.hostname, UPSTREAM.port, timeout=timeout)
        try:
            connection.putrequest(method, f"{base_path}{upstream_path}")
            for header in ("Content-Type", "Accept"):
                value = self.headers.get(header)
                if value:
                    connection.putheader(header, value)
            if method == "POST":
                connection.putheader("Content-Length", str(content_length))
            connection.endheaders()

            remaining = content_length
            while remaining:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                connection.send(chunk)
                remaining -= len(chunk)

            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status)
            self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
        except (OSError, http.client.HTTPException) as exc:
            self._json_error(502, f"无法连接 Whisper 后端：{exc}")
        finally:
            connection.close()

    def _proxy_health(self) -> None:
        """Proxy health data and expose the configured upstream address to the UI."""
        connection_class = http.client.HTTPSConnection if UPSTREAM.scheme == "https" else http.client.HTTPConnection
        base_path = UPSTREAM.path.rstrip("/")
        connection = connection_class(UPSTREAM.hostname, UPSTREAM.port, timeout=8)
        try:
            connection.request("GET", f"{base_path}/health", headers={"Accept": "application/json"})
            response = connection.getresponse()
            payload = response.read()
            if response.status < 200 or response.status >= 300:
                self.send_response(response.status)
                self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            data = json.loads(payload)
            data["backend_base_url"] = UPSTREAM.geturl()
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
            self._json_error(502, f"无法连接 Whisper 后端：{exc}")
        finally:
            connection.close()

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path == "/" else request_path.lstrip("/")
        candidate = (PUBLIC_DIR / relative).resolve()
        if PUBLIC_DIR not in candidate.parents and candidate != PUBLIC_DIR:
            self.send_error(403)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        content = candidate.read_bytes()
        mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{mime_type}; charset=utf-8" if mime_type.startswith("text/") else mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _content_length(self) -> int | None:
        try:
            return int(self.headers["Content-Length"])
        except (KeyError, TypeError, ValueError):
            return None

    def _json_error(self, status: int, message: str) -> None:
        body = json.dumps({"detail": message}, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def create_server(host: str = "0.0.0.0", port: int = 3000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), WebWhisperHandler)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "3000"))
    server = create_server(host, port)
    print(f"Web Whisper: http://{host}:{server.server_port}")
    print(f"Whisper API: {UPSTREAM.geturl()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
