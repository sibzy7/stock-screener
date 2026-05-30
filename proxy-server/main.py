"""
Lightweight HTTP/HTTPS forward proxy for routing yfinance requests
out of GCP IP ranges. Deployed on Render (non-GCP IPs).
"""
import select
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.request
import ssl
import os

PORT = int(os.environ.get("PORT", 8080))


class ProxyHandler(BaseHTTPRequestHandler):
    log_message = lambda self, *a: None  # silence per-request logs

    # ── Plain HTTP ────────────────────────────────────────────────────────────
    def do_GET(self):  self._forward()
    def do_POST(self): self._forward()
    def do_HEAD(self): self._forward()
    def do_PUT(self):  self._forward()
    def do_DELETE(self): self._forward()
    def do_OPTIONS(self): self._forward()

    def _forward(self):
        try:
            req = urllib.request.Request(self.path)
            for k, v in self.headers.items():
                if k.lower() not in ("host", "proxy-connection"):
                    req.add_header(k, v)
            body = None
            if self.command in ("POST", "PUT", "PATCH"):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else None
            if body:
                req.data = body

            ctx = ssl.create_default_context()
            resp = urllib.request.urlopen(req, context=ctx, timeout=30)
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                if k.lower() not in ("transfer-encoding",):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_error(502, str(e))

    # ── HTTPS CONNECT tunnel ──────────────────────────────────────────────────
    def do_CONNECT(self):
        host, port = self.path.split(":")
        port = int(port)
        try:
            remote = socket.create_connection((host, port), timeout=10)
            self.send_response(200, "Connection Established")
            self.end_headers()
            self._tunnel(self.connection, remote)
        except Exception as e:
            self.send_error(502, str(e))

    def _tunnel(self, client, remote):
        sockets = [client, remote]
        while True:
            readable, _, err = select.select(sockets, [], sockets, 10)
            if err:
                break
            for s in readable:
                other = remote if s is client else client
                try:
                    data = s.recv(4096)
                    if not data:
                        return
                    other.sendall(data)
                except Exception:
                    return


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), ProxyHandler)
    print(f"Proxy listening on port {PORT}")
    server.serve_forever()
