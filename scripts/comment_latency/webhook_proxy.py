"""Expose test webhooks and authenticated job APIs, keeping UI/pprof local."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def forward(self):
        path = unquote(urlsplit(self.path).path)
        if ".." in path.split("/") or not (
            path == "/github/webhook" or path.startswith(("/repos/", "/orgs/"))
        ):
            self.send_error(404)
            return
        if self.headers.get("Transfer-Encoding"):
            self.send_error(411)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 5 * 1024 * 1024:
            self.send_error(413)
            return
        body = self.rfile.read(length)
        excluded = {"host", "connection", "transfer-encoding", "content-length"}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in excluded}
        upstream = http.client.HTTPConnection("127.0.0.1", 3101, timeout=60)
        try:
            upstream.request(self.command, self.path, body=body, headers=headers)
            response = upstream.getresponse()
            data = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in excluded:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        finally:
            upstream.close()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 3102), Handler).serve_forever()
