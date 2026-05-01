from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from homewiki.config import load_settings  # noqa: E402


class UiHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/ui/")
            self.end_headers()
            return
        if path == "/ui-config.json":
            self._send_ui_config()
            return
        super().do_GET()

    def _send_ui_config(self):
        settings = load_settings(project_root=PROJECT_ROOT)
        payload = {
            "apiBase": settings.api.ui_api_base,
        }
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    host = os.environ.get("UI_HOST", "127.0.0.1")
    port = int(os.environ.get("UI_PORT", "5173"))
    server = ThreadingHTTPServer((host, port), UiHandler)
    print(f"Serving Home Wiki UI at http://{host}:{port}/ui/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
