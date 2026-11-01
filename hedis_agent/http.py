"""Tiny JSON-over-HTTP helper (stdlib only)."""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.parse
import urllib.request

USER_AGENT = "hedis-care-gap-agent-poc/0.1 (+https://github.com)"  # CMS blocks some bare custom agents


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS. Falls back to certifi or the macOS system bundle when
    Python ships without CA certificates (common with python.org installers)."""
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0):
        return ctx
    try:
        import certifi  # optional
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for path in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if os.path.exists(path):
            return ssl.create_default_context(cafile=path)
    return ctx


_CTX = _ssl_context()


def get_json(url: str, params: dict | None = None, timeout: int = 60, retries: int = 2) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # network errors, timeouts, bad JSON
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Request failed: {url} ({last_err})")
