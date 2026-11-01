"""Local web app: the morning dashboard plus a chat panel for the Claude agent.

    python -m hedis_agent serve            # http://localhost:8000

Standard library only. The chat panel needs the `anthropic` package and an
API key; the dashboard works without either. Binds to localhost by default.
"""
from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .analytics import PublicAnalyzer
from .config import OUTPUT_DIR

WEB_DIR = Path(__file__).parent / "web"
_state = {"payload": None, "analyzer": None, "sessions": {}}
_lock = threading.Lock()


def build_payload() -> dict:
    a = PublicAnalyzer()
    _state["analyzer"] = a
    _state["payload"] = a.payload()
    return _state["payload"]


def render_static(payload: dict) -> str:
    """Dashboard HTML with the data embedded (no server needed; chat disabled)."""
    html = (WEB_DIR / "dashboard.html").read_text()
    data = json.dumps(payload, default=str).replace("</", "<\\/")
    return html.replace("<!--DATA-->", f"<script>window.__HEDIS_DATA__ = {data};</script>")


def write_static_site() -> dict:
    """Write docs/index.html: a self-contained copy of the dashboard (chat off) for GitHub Pages."""
    payload = _state["payload"] or build_payload()
    page = render_static(payload)
    docs = OUTPUT_DIR.parent / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "index.html").write_text(page)
    (docs / ".nojekyll").write_text("")
    return {"static_dashboard": str(docs / "index.html")}


def _agent_for(sid: str):
    from .agent import HedisAgent  # needs the anthropic package
    with _lock:
        ag = _state["sessions"].get(sid)
        if ag is None:
            ag = HedisAgent(analyzer=_state["analyzer"], verbose=False)
            _state["sessions"][sid] = ag
        return ag


def _agent_status() -> dict:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return {"available": False, "reason": "Install the SDK: pip install -r requirements.txt"}
    import os
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return {"available": False, "reason": "Set ANTHROPIC_API_KEY and restart the server to enable chat."}
    return {"available": True}


class Handler(BaseHTTPRequestHandler):
    server_version = "HedisAgent/0.2"

    def log_message(self, fmt, *args):  # quieter console
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, default=str).encode(), "application/json")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (WEB_DIR / "dashboard.html").read_text().replace("<!--DATA-->", "")
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        if self.path == "/api/dashboard":
            return self._json(200, _state["payload"] or build_payload())
        if self.path == "/api/status":
            return self._json(200, _agent_status())
        self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(min(length, 20_000)) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "Bad JSON"})
        if self.path == "/api/refresh":
            from .facts import build
            build()
            build_payload()
            return self._json(200, {"ok": True, "as_of": _state["payload"]["as_of"]})
        if self.path == "/api/ask":
            status = _agent_status()
            if not status["available"]:
                return self._json(503, {"error": status["reason"]})
            q = str(body.get("question", "")).strip()[:2000]
            sid = str(body.get("session") or secrets.token_hex(8))
            if not q:
                return self._json(400, {"error": "Empty question"})
            ag = _agent_for(sid)
            api = ag.anthropic
            try:
                answer = ag.ask(q)
                return self._json(200, {"answer": answer, "session": sid})
            except api.AuthenticationError:
                return self._json(401, {"error": "The API key was rejected."})
            except api.RateLimitError:
                return self._json(429, {"error": "Rate limited — try again in a moment."})
            except api.APIStatusError as e:
                ag.messages.clear()
                return self._json(502, {"error": f"API error {e.status_code}: {e.message}"})
            except api.APIConnectionError:
                return self._json(502, {"error": "Could not reach the Anthropic API."})
        self._send(404, b"Not found", "text/plain")


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    build_payload()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"HEDIS dashboard running at http://{host}:{port}  (Ctrl-C to stop)")
    print("Agent chat:", "enabled" if _agent_status()["available"] else _agent_status()["reason"])
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
