"""Stand-in for jarvisd's policy gate: a loopback HTTP endpoint that allows or denies a tool call.

Denies any Bash command containing DENYME; allows everything else. Logs nothing sensitive.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        command = str(body.get("tool_input", {}).get("command", ""))
        decision = "deny" if "DENYME" in command else "allow"
        payload = json.dumps({"decision": decision}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:  # keep the console quiet
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
