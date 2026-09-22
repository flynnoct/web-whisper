import json
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

import server


class MockWhisperHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        responses = {
            "/health": {
                "status": "ready",
                "uptime_seconds": 90,
                "device": "cuda",
                "default_model": "large-v3",
                "loaded_models": ["large-v3"],
                "model_unload_status": {"large-v3": {"unload_in_seconds": 1790}},
            },
            "/v1/models": {"available_models": ["tiny", "large-v3"]},
        }
        body = json.dumps(responses[self.path]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = HTTPServer(("127.0.0.1", 0), MockWhisperHandler)
        server.UPSTREAM = urlsplit(f"http://127.0.0.1:{cls.upstream.server_port}")
        cls.app = server.create_server(port=0)
        cls.threads = [
            threading.Thread(target=cls.upstream.serve_forever, daemon=True),
            threading.Thread(target=cls.app.serve_forever, daemon=True),
        ]
        for thread in cls.threads:
            thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.upstream.shutdown()

    def request(self, path):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.app.server_port}{path}")

    def test_serves_web_ui(self):
        with self.request("/") as response:
            self.assertIn("Web Whisper", response.read().decode())

    def test_proxies_status(self):
        with self.request("/api/health") as response:
            data = json.load(response)
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["device"], "cuda")
        self.assertEqual(data["backend_base_url"], f"http://127.0.0.1:{self.upstream.server_port}")


if __name__ == "__main__":
    unittest.main()
