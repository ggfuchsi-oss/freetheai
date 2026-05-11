from http.server import HTTPServer, BaseHTTPRequestHandler
import threading, os

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *args):
        pass

def start():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"[keep_alive] HTTP Server auf Port {port}", flush=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
