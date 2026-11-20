from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .orchestrator import ChallengeOrchestrator


ROOT = Path(__file__).resolve().parents[2]
MOCK_PAGE = ROOT / "mock_page.html"


class ProposalHandler(BaseHTTPRequestHandler):
    orchestrator = ChallengeOrchestrator()
    payload = orchestrator.generate_proposals(limit=5)

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/mock", "/mock_page.html"):
            if not MOCK_PAGE.exists():
                self.send_error(404, "mock_page.html not found")
                return
            body = MOCK_PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/api/proposals", "/api/proposals.json"):
            self.send_json(200, self.payload)
            return
        if path == "/api/health":
            self.send_json(200, {"status": "ok", "person": "A", "handoff": "proposals"})
            return
        self.send_error(404)

    def log_message(self, format: str, *args) -> None:
        return


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), ProposalHandler)
    print(f"Person A proposal backend running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
