"""Built-in Chrome CDP attach (no MCP). Prefer existing debug Chrome on :9222.

Chrome 144+ quirk: /json/version and /json/list may return HTTP 404 while the
remote-debugging port is still open. Probe several /json/* endpoints and treat
"port open + any working JSON endpoint" as healthy; if attach is unusable,
launch a dedicated Chrome with its own user-data-dir (never the main profile).
"""
from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

CDP_PORT = 9222
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT = Path.home() / "jevii"
PROFILE = str(ROOT / ".chrome-cdp")

# Prefer discovery endpoints first; /json/new is last (may create a tab).
_JSON_ENDPOINTS = ("/json/version", "/json/list", "/json", "/json/new")


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_json(url: str, *, method: str = "GET", timeout: float = 1.5) -> tuple[int, Any]:
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, {"raw": raw[:500]}
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read() or b""
        except Exception:
            pass
        raw = body.decode("utf-8", errors="replace")
        data: Any
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            data = {"raw": raw[:500]} if raw else None
        return int(exc.code), data
    except Exception as exc:
        raise exc


def _probe_endpoints(port: int) -> dict[str, Any]:
    """Return first working JSON CDP endpoint, or empty result."""
    errors: list[str] = []
    for path in _JSON_ENDPOINTS:
        url = f"http://127.0.0.1:{port}{path}"
        try:
            # /json/new creates a tab on some Chrome builds — prefer GET; skip PUT here.
            if path == "/json/new":
                status, data = _http_json(url, method="GET", timeout=1.5)
            else:
                status, data = _http_json(url, method="GET", timeout=1.5)
            if status == 200 and data is not None:
                return {"ok": True, "endpoint": path, "status_code": status, "data": data}
            errors.append(f"{path}:{status}")
        except Exception as exc:
            errors.append(f"{path}:{type(exc).__name__}")
    return {"ok": False, "errors": errors}


def _devtools_active_port(user_data_dir: str | Path) -> Optional[int]:
    path = Path(user_data_dir) / "DevToolsActivePort"
    if not path.is_file():
        return None
    try:
        first = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        return int(first)
    except (OSError, ValueError, IndexError):
        return None


def cdp_status(port: int = CDP_PORT) -> dict[str, Any]:
    probe = _probe_endpoints(port)
    if probe.get("ok"):
        data = probe.get("data")
        out: dict[str, Any] = {
            "ok": True,
            "port": port,
            "endpoint": probe.get("endpoint"),
        }
        if probe.get("endpoint") == "/json/version" and isinstance(data, dict):
            out["version"] = data
        elif probe.get("endpoint") in ("/json/list", "/json") and isinstance(data, list):
            out["tabs"] = len(data)
        else:
            out["data_type"] = type(data).__name__
        return out

    # Chrome 144+: port may listen while every /json/* returns 404.
    if _port_open(port):
        return {
            "ok": True,
            "port": port,
            "endpoint": None,
            "chrome144_quirk": True,
            "note": (
                "Port open but /json/version|/json/list|/json returned 404 "
                "(Chrome 144+ quirk). Dedicated profile may still be launched."
            ),
            "probe_errors": probe.get("errors"),
        }

    return {
        "ok": False,
        "port": port,
        "error": "CDP port closed and no JSON endpoint responded",
        "probe_errors": probe.get("errors"),
    }


def _fetch_tab_list(port: int) -> list[dict[str, Any]]:
    for path in ("/json/list", "/json"):
        try:
            status, data = _http_json(f"http://127.0.0.1:{port}{path}", timeout=2.0)
            if status == 200 and isinstance(data, list):
                return data
        except Exception:
            continue
    return []


def list_tabs(port: int = CDP_PORT) -> dict[str, Any]:
    tabs_raw = _fetch_tab_list(port)
    if tabs_raw:
        slim = [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "url": t.get("url"),
                "type": t.get("type"),
            }
            for t in tabs_raw
            if isinstance(t, dict) and t.get("type") in (None, "page")
        ]
        return {"ok": True, "tabs": slim, "port": port}

    st = cdp_status(port)
    if st.get("ok") and st.get("chrome144_quirk"):
        return {
            "ok": True,
            "tabs": [],
            "port": port,
            "note": st.get("note"),
            "chrome144_quirk": True,
        }
    if st.get("ok") and st.get("endpoint") == "/json/version":
        # Version worked but list empty/unavailable
        return {"ok": True, "tabs": [], "port": port, "endpoint": st.get("endpoint")}
    return {"ok": False, "error": st.get("error") or "No CDP tab list endpoint available", "status": st}


def _launch_debug_chrome(port: int) -> None:
    Path(PROFILE).mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            CHROME,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _usable_json(port: int) -> bool:
    probe = _probe_endpoints(port)
    return bool(probe.get("ok"))


def ensure_cdp(*, port: int = CDP_PORT) -> dict[str, Any]:
    st = cdp_status(port)
    if st.get("ok") and _usable_json(port):
        return {"ok": True, "already": True, "status": st, "port": port}

    # Attach insufficient (closed, or Chrome 144+ 404-only) — launch dedicated profile.
    try:
        _launch_debug_chrome(port)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "last": st}

    last: dict[str, Any] = st
    for _ in range(30):
        time.sleep(0.5)
        # Preferred port
        if _usable_json(port):
            return {"ok": True, "launched": True, "status": cdp_status(port), "port": port}
        # Chrome may pick another port when 9222 is taken — read DevToolsActivePort.
        alt = _devtools_active_port(PROFILE)
        if alt and alt != port and _usable_json(alt):
            return {
                "ok": True,
                "launched": True,
                "status": cdp_status(alt),
                "port": alt,
                "note": f"Bound alternate debug port {alt} (requested {port} busy)",
            }
        last = cdp_status(port)

    # Port open with quirk still counts as partial success for status callers.
    if last.get("ok"):
        return {
            "ok": True,
            "launched": True,
            "partial": True,
            "status": last,
            "port": port,
            "note": last.get("note")
            or "Chrome launched but JSON endpoints still 404 (Chrome 144+ quirk)",
        }
    return {"ok": False, "error": "Chrome CDP did not become ready", "last": last}


def navigate(url: str, *, port: int = CDP_PORT) -> dict[str, Any]:
    """Navigate via Playwright CDP attach, else /json/new on a working endpoint."""
    ensure = ensure_cdp(port=port)
    if not ensure.get("ok"):
        return ensure
    use_port = int(ensure.get("port") or port)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{use_port}")
            contexts = browser.contexts
            context = contexts[0] if contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return {"ok": True, "url": page.url, "title": page.title(), "port": use_port}
    except Exception as exc:
        # Fallback: open via /json/new (PUT) when that endpoint works.
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{use_port}/json/new?{quote(url, safe='')}",
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            return {"ok": True, "via": "json/new", "tab": data, "port": use_port}
        except Exception as exc2:
            # Last resort: GET /json/new?url= on builds that accept it
            try:
                status, data = _http_json(
                    f"http://127.0.0.1:{use_port}/json/new?{quote(url, safe='')}",
                    method="GET",
                    timeout=5.0,
                )
                if status == 200:
                    return {"ok": True, "via": "json/new-get", "tab": data, "port": use_port}
            except Exception as exc3:
                return {
                    "ok": False,
                    "error": f"{exc}; fallback: {exc2}; get: {exc3}",
                    "port": use_port,
                    "ensure": ensure,
                }
            return {"ok": False, "error": f"{exc}; fallback: {exc2}", "port": use_port, "ensure": ensure}
