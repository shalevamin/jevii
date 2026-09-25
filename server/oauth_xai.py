"""xAI Grok subscription OAuth — device-code flow (no localhost callback).

Public client_id b1a00492-073a-47ea-816f-4c329264a828. Never log token values.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

import httpx

log = logging.getLogger("jevii.oauth.xai")

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
DEVICE_URL = "https://auth.x.ai/oauth2/device/code"
TOKEN_URL = "https://auth.x.ai/oauth2/token"
SCOPE = (
    "openid profile email offline_access grok-cli:access api:access "
    "conversations:read conversations:write"
)
REFRESH_SKEW_MS = 60_000

ROOT = Path.home() / "jevii"
AUTH_DIR = ROOT / ".auth"
AUTH_FILE = AUTH_DIR / "xai-oauth.json"

_lock = threading.Lock()
_pending: dict[str, Any] = {}
_poll_thread: Optional[threading.Thread] = None
_poll_stop = threading.Event()


def _store_tokens(access: str, refresh: str, expires: int) -> None:
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"access": access, "refresh": refresh, "expires": expires}
    AUTH_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    AUTH_FILE.chmod(0o600)


def load_stored() -> dict[str, Any] | None:
    if not AUTH_FILE.is_file():
        return None
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("access") or not data.get("refresh"):
        return None
    return data


def clear_stored() -> None:
    try:
        if AUTH_FILE.is_file():
            AUTH_FILE.unlink()
    except OSError:
        pass


def is_connected() -> bool:
    return load_stored() is not None


def status() -> dict[str, Any]:
    data = load_stored()
    out: dict[str, Any] = {"ok": True, "connected": bool(data)}
    if data and isinstance(data.get("expires"), (int, float)):
        out["expires_at"] = int(data["expires"])
    with _lock:
        pending = dict(_pending)
    if pending and not out["connected"]:
        out["pending"] = not pending.get("done") and not pending.get("timed_out")
        out["user_code"] = pending.get("user_code")
        out["verification_url"] = pending.get("verification_url")
        if pending.get("error"):
            out["error"] = pending["error"]
    return out


def _save_from_token_response(js: dict[str, Any]) -> dict[str, Any]:
    access = js.get("access_token")
    refresh = js.get("refresh_token")
    expires_in = js.get("expires_in")
    if not access or not refresh or not isinstance(expires_in, (int, float)):
        return {"ok": False, "error": "Token response missing required fields."}
    expires = int(time.time() * 1000) + int(expires_in) * 1000
    _store_tokens(access, refresh, expires)
    log.info("Grok OAuth connected (tokens stored under .auth)")
    return {"ok": True, "connected": True}


def _refresh(refresh_token: str) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": refresh_token,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
    if resp.status_code >= 400:
        return {
            "ok": False,
            "error": "Grok session expired. Reconnect Grok (subscription).",
            "need_reconnect": True,
        }
    try:
        js = resp.json()
    except Exception:
        return {"ok": False, "error": "Token refresh returned invalid JSON.", "need_reconnect": True}
    result = _save_from_token_response(js)
    if not result.get("ok"):
        result["need_reconnect"] = True
    if result.get("ok"):
        data = load_stored()
        return {"ok": True, "access": data["access"], "expires": data["expires"]}
    return result


def get_valid_credentials() -> dict[str, Any] | None:
    with _lock:
        data = load_stored()
        if not data:
            return None
        now = int(time.time() * 1000)
        expires = int(data.get("expires") or 0)
        if expires and now < (expires - REFRESH_SKEW_MS):
            return {"access": data["access"]}
        result = _refresh(data["refresh"])
        if not result.get("ok"):
            return None
        return {"access": result["access"]}


def _poll_loop(device_code: str, interval: int, expires_in: int) -> None:
    deadline = time.time() + max(30, int(expires_in))
    wait = max(3, int(interval or 5))
    while not _poll_stop.is_set() and time.time() < deadline:
        if _poll_stop.wait(wait):
            break
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "client_id": CLIENT_ID,
                        "device_code": device_code,
                    },
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                )
        except Exception as exc:
            log.warning("Grok device poll transport error: %s", type(exc).__name__)
            continue
        if resp.status_code == 200:
            try:
                js = resp.json()
            except Exception:
                with _lock:
                    _pending["done"] = True
                    _pending["error"] = "Invalid token JSON from xAI."
                return
            result = _save_from_token_response(js)
            with _lock:
                _pending["done"] = True
                _pending["result"] = result
                _pending["connected"] = bool(result.get("ok"))
                if not result.get("ok"):
                    _pending["error"] = result.get("error")
            return
        try:
            err_body = resp.json()
        except Exception:
            err_body = {}
        err = (err_body.get("error") if isinstance(err_body, dict) else None) or ""
        if err in ("authorization_pending", "slow_down"):
            if err == "slow_down":
                wait = min(wait + 2, 15)
            continue
        if err == "expired_token":
            with _lock:
                _pending["done"] = True
                _pending["timed_out"] = True
                _pending["error"] = "Device code expired. Start Sign in with Grok again."
            return
        if err == "access_denied":
            with _lock:
                _pending["done"] = True
                _pending["error"] = "Access denied in browser. Try again or use an API key."
            return
        # other errors
        with _lock:
            _pending["done"] = True
            _pending["error"] = f"Device login failed ({resp.status_code}). Try again."
        return
    with _lock:
        if not _pending.get("done"):
            _pending["done"] = True
            _pending["timed_out"] = True
            _pending["error"] = "Timed out waiting for browser approval."


def start_login(*, open_browser: bool = True) -> dict[str, Any]:
    global _poll_thread
    _poll_stop.set()
    if _poll_thread and _poll_thread.is_alive():
        _poll_thread.join(timeout=2)
    _poll_stop.clear()

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                DEVICE_URL,
                data={"client_id": CLIENT_ID, "scope": SCOPE},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
    except Exception as exc:
        return {"ok": False, "error": f"Could not reach xAI auth: {type(exc).__name__}"}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"Device code request failed (HTTP {resp.status_code})."}
    try:
        js = resp.json()
    except Exception:
        return {"ok": False, "error": "Device code response was not JSON."}
    device_code = js.get("device_code")
    user_code = js.get("user_code")
    ver_uri = js.get("verification_uri_complete") or js.get("verification_uri")
    if not device_code or not user_code or not ver_uri:
        return {"ok": False, "error": "Device code response missing fields."}
    interval = int(js.get("interval") or 5)
    expires_in = int(js.get("expires_in") or 1800)

    with _lock:
        _pending.clear()
        _pending.update(
            {
                "device_code": device_code,
                "user_code": user_code,
                "verification_url": ver_uri,
                "started_at": time.time(),
                "done": False,
                "connected": False,
                "timed_out": False,
            }
        )

    _poll_thread = threading.Thread(
        target=_poll_loop,
        args=(device_code, interval, expires_in),
        daemon=True,
        name="xai-device-poll",
    )
    _poll_thread.start()

    out: dict[str, Any] = {
        "ok": True,
        "user_code": user_code,
        "verification_url": ver_uri,
        "expires_in": expires_in,
        "interval": interval,
    }
    if open_browser:
        try:
            subprocess.Popen(["open", ver_uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            out["browser_opened"] = True
        except Exception:
            out["browser_opened"] = False
    return out


def pending_poll() -> dict[str, Any]:
    if load_stored():
        return {"ok": True, "connected": True, "pending": False}
    with _lock:
        pending = dict(_pending)
    if not pending:
        return {"ok": True, "connected": False, "pending": False}
    out: dict[str, Any] = {
        "ok": True,
        "connected": bool(pending.get("connected")),
        "pending": not pending.get("done") and not pending.get("timed_out"),
        "timed_out": bool(pending.get("timed_out")),
        "user_code": pending.get("user_code"),
        "verification_url": pending.get("verification_url"),
    }
    if pending.get("error"):
        out["error"] = pending["error"]
    return out


def logout() -> dict[str, Any]:
    global _poll_thread
    _poll_stop.set()
    with _lock:
        clear_stored()
        _pending.clear()
    return {"ok": True, "connected": False}
