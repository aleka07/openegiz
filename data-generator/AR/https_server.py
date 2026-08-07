import base64
import http.server
import json
import ssl
import urllib.request

PORT = 30001
DITTO_FEATURES_URL = "http://localhost:30525/api/2/things/summerschool:lightbulb-01/features"
DITTO_AUTH = base64.b64encode(b"ditto:ditto").decode("ascii")

class ARRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/lightbulb":
            self.proxy_lightbulb_features()
            return

        super().do_GET()

    def proxy_lightbulb_features(self):
        request = urllib.request.Request(DITTO_FEATURES_URL)
        request.add_header("Authorization", f"Basic {DITTO_AUTH}")

        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read()
        except Exception as exc:
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

handler = ARRequestHandler
server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), handler)

context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

server.socket = context.wrap_socket(server.socket, server_side=True)

print(f"Serving HTTPS on 0.0.0.0:{PORT}")
server.serve_forever()
