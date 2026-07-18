#!/usr/bin/env python3
"""Local brain server: serves brain.html and proxies questions to Cognee Cloud.

Stdlib only (no FastAPI dependency). The browser never sees the Cognee API key;
this server reads it from .env and forwards questions to
POST {COGNEE_BASE_URL}/api/v1/recall against the muster_verpackungen_2025
dataset. Deterministic findings (build/findings.json) are served alongside so
the UI cross-checks graph answers against the books.

Run: python3 app.py   ->  http://127.0.0.1:8600
"""
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DATASET = "muster_verpackungen_2025"
PORT = 8600


def load_env():
    env = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"')
    base = os.environ.get("COGNEE_BASE_URL") or env.get("COGNEE_BASE_URL")
    key = os.environ.get("COGNEE_API_KEY") or env.get("COGNEE_API_KEY")
    if not base or not key:
        raise SystemExit("COGNEE_BASE_URL / COGNEE_API_KEY missing (.env or env)")
    return base.rstrip("/"), key


COGNEE_URL, COGNEE_KEY = load_env()


def cognee_recall(question):
    req = urllib.request.Request(
        f"{COGNEE_URL}/api/v1/recall",
        data=json.dumps({"query": question, "datasets": [DATASET]}).encode(),
        headers={"X-Api-Key": COGNEE_KEY, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


def related_findings(question):
    words = {w.lower().strip("?.,") for w in question.split() if len(w) > 3}
    hits = []
    for f in json.loads((ROOT / "build" / "findings.json").read_text()):
        hay = (f["title"] + " " + f["explanation"]).lower()
        if sum(1 for w in words if w in hay) >= 2:
            hits.append({"id": f["id"], "tier": f["tier"], "title": f["title"],
                         "provenance": f["provenance"][:4]})
    return hits[:5]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/brain.html"):
            self._send(200, (ROOT / "brain.html").read_bytes(),
                       "text/html; charset=utf-8")
        elif self.path == "/api/findings":
            self._send(200, (ROOT / "build" / "findings.json").read_bytes())
        else:
            self._send(404, {"detail": "not found"})

    def do_POST(self):
        if self.path != "/api/ask":
            self._send(404, {"detail": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            q = str(body.get("question", "")).strip()
            if not q:
                self._send(400, {"detail": "empty question"})
                return
            results = cognee_recall(q)
            answers = [{"text": item.get("text", ""),
                        "source": item.get("source", ""),
                        "dataset": item.get("dataset_name", "")}
                       for item in results if item.get("text")]
            self._send(200, {"answers": answers,
                             "related_findings": related_findings(q)})
        except urllib.error.URLError as e:
            self._send(502, {"detail": f"Cognee unreachable: {e}"})
        except Exception as e:  # surface any handler error to the UI
            self._send(500, {"detail": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}")


if __name__ == "__main__":
    print(f"Fraud Brain on http://127.0.0.1:{PORT}  (Cognee: {COGNEE_URL})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
