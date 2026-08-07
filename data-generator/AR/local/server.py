import base64
import json
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
HOST = "0.0.0.0"
PORT = 5555
DITTO_FEATURES_URL = "http://localhost:30525/api/2/things/summerschool:lightbulb-01/features"
DITTO_AUTH = base64.b64encode(b"ditto:ditto").decode("ascii")

ALIASES = {
    "/": "lampa (1).html",
    "/lampa.obj": "lampa (1).obj",
    "/lampa.patt": "lampa (1).patt",
}


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if urlparse(self.path).path == "/api/lightbulb":
            self.proxy_lightbulb_features()
            return

        super().do_GET()

    def proxy_lightbulb_features(self):
        request = urllib.request.Request(DITTO_FEATURES_URL)
        request.add_header("Authorization", f"Basic {DITTO_AUTH}")

        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read()
                status = 200
        except Exception as exc:
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            status = 502

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def translate_path(self, path):
        request_path = unquote(urlparse(path).path)
        local_name = ALIASES.get(request_path, request_path.lstrip("/"))
        return str((ROOT / local_name).resolve())

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Server running on all interfaces: http://{HOST}:{PORT}")
    print("Open it from the host browser as: http://<VM_IP>:5555")
    server.serve_forever()
