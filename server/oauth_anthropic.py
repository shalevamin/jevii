"""Claude Pro/Max OAuth (PKCE) — same path as OpenClaw/Hermes.

Public client_id 9d1c250a-e61b-44d9-88ed-5944d1962f5e. Never log token values.
Also supports reusing ~/.claude/.credentials.json (Claude Code login).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

log = logging.getLogger("jevii.oauth.anthropic")

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
REDIRECT_URI = "http://localhost:53692/callback"
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 53692
CALLBACK_PATH = "/callback"
SCOPES = (
    "org:create_api_key user:profile user:inference "
    "user:sessions:claude_code user:mcp_servers user:file_upload"
)
REFRESH_SKEW_MS = 60_000

ROOT = Path.home() / "jevii"
AUTH_DIR = ROOT / ".auth"
AUTH_FILE = AUTH_DIR / "anthropic-oauth.json"
CLAUDE_CODE_CREDS = Path.home() / ".claude" / ".credentials.json"

_lock = threading.Lock()
_pending: dict[str, Any] = {}
_httpd: Optional[HTTPServer] = None
_httpd_thread: Optional[threading.Thread] = None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _success_html() -> bytes:
    return (
        b"<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        b"<title>jevii - Connected</title></head><body style=\"font-family:system-ui;"
        b"display:grid;place-items:center;min-height:100vh;background:#fff5f8\">"
        b"<div style=\"text-align:center;padding:32px;background:#fff;border-radius:20px;"
        b"box-shadow:0 16px 48px rgba(225,29,72,.18)\"><h1>Claude connected</h1>"
        b"<p>You can close this window and return to jevii.</p></div></body></html>"
    )


def _error_html(message: str) -> bytes:
    safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>jevii - Auth error</title></head><body style=\"font-family:system-ui;"
        "display:grid;place-items:center;min-height:100vh\"><div style=\"text-align:center;"
        f"max-width:480px\"><h1>Sign-in failed</h1><p>{safe}</p>"
        "<p>Paste the redirect URL or code#state in jevii as a fallback.</p>"
        "</div></body></html>"
    )
    return html.encode("utf-8")


def _stop_callback_server() -> None:
    global _httpd, _httpd_thread
    if _httpd is not None:
        try:
            _httpd.shutdown()
        except Exception:
            pass
        try:
            _httpd.server_close()
        except Exception:
            pass
    _httpd = None
    _httpd_thread = None


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


def claude_code_available() -> dict[str, Any]:
    if not CLAUDE_CODE_CREDS.is_file():
        return {"ok": True, "available": False}
    try:
        data = json.loads(CLAUDE_CODE_CREDS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": True, "available": False}
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict):
        return {"ok": True, "available": False}
    has = bool(oauth.get("accessToken") and oauth.get("refreshToken"))
    return {"ok": True, "available": has, "path": str(CLAUDE_CODE_CREDS) if has else None}


def import_claude_code() -> dict[str, Any]:
    info = claude_code_available()
    if not info.get("available"):
        return {"ok": False, "error": "No Claude Code login found at ~/.claude/.credentials.json"}
    try:
        data = json.loads(CLAUDE_CODE_CREDS.read_text(encoding="utf-8"))
        oauth = data["claudeAiOauth"]
        access = oauth["accessToken"]
        refresh = oauth["refreshToken"]
        expires = _normalize_expires(oauth.get("expiresAt"))
        _store_tokens(access, refresh, expires)
        _mark_usable()
        log.info("Imported Claude Code credentials into jevii .auth")
        return {"ok": True, "connected": True, "source": "claude-code"}
    except Exception as exc:
        return {"ok": False, "error": f"Could not import Claude Code login: {type(exc).__name__}"}


# Last refresh / usability error (never contains token values).
_last_error: Optional[str] = None
_needs_reauth: bool = False


def last_error() -> Optional[str]:
    return _last_error


def needs_reauth() -> bool:
    return _needs_reauth


def _normalize_expires(expires_at: Any) -> int:
    if isinstance(expires_at, (int, float)) and expires_at < 10_000_000_000:
        return int(expires_at * 1000)
    if isinstance(expires_at, (int, float)):
        return int(expires_at)
    return int(time.time() * 1000) + 3600_000


def _read_claude_code_tokens() -> dict[str, Any] | None:
    """Read live Claude Code tokens without logging secrets."""
    if not CLAUDE_CODE_CREDS.is_file():
        return None
    try:
        data = json.loads(CLAUDE_CODE_CREDS.read_text(encoding="utf-8"))
        oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
        if not isinstance(oauth, dict):
            return None
        access = oauth.get("accessToken")
        refresh = oauth.get("refreshToken")
        if not access or not refresh:
            return None
        return {
            "access": access,
            "refresh": refresh,
            "expires": _normalize_expires(oauth.get("expiresAt")),
        }
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        return None


def _mark_unusable(error: str, *, clear_file: bool = False) -> None:
    global _last_error, _needs_reauth
    _last_error = error
    _needs_reauth = True
    if clear_file:
        clear_stored()
        log.info("Cleared unusable Anthropic OAuth store (no token values logged)")
    else:
        log.info("Anthropic OAuth marked needs_reauth (no token values logged)")


def _mark_usable() -> None:
    global _last_error, _needs_reauth
    _last_error = None
    _needs_reauth = False


def is_connected() -> bool:
    """True only when credentials are usable (valid or successfully refreshed)."""
    return get_valid_credentials() is not None


def status() -> dict[str, Any]:
    creds = get_valid_credentials()
    data = load_stored()
    out: dict[str, Any] = {
        "ok": True,
        "connected": creds is not None,
        "needs_reauth": bool(_needs_reauth and creds is None),
        "claude_code_available": bool(claude_code_available().get("available")),
    }
    if creds is None and _last_error:
        out["error"] = _last_error
    if data and isinstance(data.get("expires"), (int, float)):
        out["expires_at"] = int(data["expires"])
    return out


def _exchange_code(code: str, verifier: str, state: str) -> dict[str, Any]:
    body = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "state": state,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            TOKEN_URL,
            json=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    if resp.status_code >= 400:
        return {"ok": False, "error": f"Token exchange failed (HTTP {resp.status_code}). Try again."}
    try:
        js = resp.json()
    except Exception:
        return {"ok": False, "error": "Token exchange returned invalid JSON."}
    access = js.get("access_token")
    refresh = js.get("refresh_token")
    expires_in = js.get("expires_in")
    if not access or not refresh or not isinstance(expires_in, (int, float)):
        return {"ok": False, "error": "Token exchange missing required fields."}
    expires = int(time.time() * 1000) + int(expires_in) * 1000
    _store_tokens(access, refresh, expires)
    _mark_usable()
    log.info("Claude OAuth connected (tokens stored under .auth)")
    return {"ok": True, "connected": True}


def _refresh(refresh_token: str) -> dict[str, Any]:
    body = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            TOKEN_URL,
            json=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    if resp.status_code >= 400:
        return {
            "ok": False,
            "error": "Claude session expired. Reconnect Claude (subscription).",
            "need_reconnect": True,
        }
    try:
        js = resp.json()
    except Exception:
        return {"ok": False, "error": "Token refresh returned invalid JSON.", "need_reconnect": True}
    access = js.get("access_token")
    refresh = js.get("refresh_token") or refresh_token
    expires_in = js.get("expires_in")
    if not access or not isinstance(expires_in, (int, float)):
        return {"ok": False, "error": "Token refresh missing fields.", "need_reconnect": True}
    expires = int(time.time() * 1000) + int(expires_in) * 1000
    _store_tokens(access, refresh, expires)
    return {"ok": True, "access": access, "expires": expires}


def get_valid_credentials() -> dict[str, Any] | None:
    """Return usable access creds, refreshing or re-importing Claude Code as needed.

    Never logs token values. On hard failure sets needs_reauth and last_error.
    """
    with _lock:
        data = load_stored()
        now = int(time.time() * 1000)

        # Prefer live Claude Code tokens when jevii store is missing or expired.
        cc = _read_claude_code_tokens()
        if cc is not None:
            store_exp = int((data or {}).get("expires") or 0)
            store_expired = (not data) or (store_exp and now >= (store_exp - REFRESH_SKEW_MS))
            newer = (not data) or (cc["expires"] > store_exp)
            # Also treat Claude Code file mtime newer than jevii store as a signal to re-import.
            try:
                cc_mtime = CLAUDE_CODE_CREDS.stat().st_mtime
                store_mtime = AUTH_FILE.stat().st_mtime if AUTH_FILE.is_file() else 0.0
                newer = newer or (store_expired and cc_mtime > store_mtime)
            except OSError:
                pass
            if store_expired and newer:
                _store_tokens(cc["access"], cc["refresh"], cc["expires"])
                data = {"access": cc["access"], "refresh": cc["refresh"], "expires": cc["expires"]}
                _mark_usable()
                log.info("Re-imported Claude Code credentials into jevii .auth")
            elif data is None:
                _store_tokens(cc["access"], cc["refresh"], cc["expires"])
                data = {"access": cc["access"], "refresh": cc["refresh"], "expires": cc["expires"]}
                _mark_usable()
                log.info("Imported Claude Code credentials into jevii .auth")

        if not data:
            _mark_unusable(
                "Claude subscription not connected. Open Connect and sign in with Claude, "
                "or use Claude Code login.",
                clear_file=False,
            )
            return None

        expires = int(data.get("expires") or 0)
        if expires and now < (expires - REFRESH_SKEW_MS):
            _mark_usable()
            return {"access": data["access"]}

        # Already failed refresh for this store and Claude Code has nothing newer — don't hammer.
        if _needs_reauth and cc is not None:
            store_exp = int(data.get("expires") or 0)
            if cc["expires"] <= store_exp and cc.get("refresh") == data.get("refresh"):
                return None
        elif _needs_reauth and cc is None:
            return None

        # Access expired — refresh jevii store token.
        result = _refresh(data["refresh"])
        if result.get("ok"):
            _mark_usable()
            return {"access": result["access"]}

        refresh_err = result.get("error") or "Claude session expired. Reconnect Claude (subscription)."

        # Refresh failed — try live Claude Code once more if tokens differ.
        cc = _read_claude_code_tokens()
        if cc is not None and cc.get("refresh") and cc.get("refresh") != data.get("refresh"):
            _store_tokens(cc["access"], cc["refresh"], cc["expires"])
            if cc["expires"] and now < (cc["expires"] - REFRESH_SKEW_MS):
                _mark_usable()
                return {"access": cc["access"]}
            result2 = _refresh(cc["refresh"])
            if result2.get("ok"):
                _mark_usable()
                return {"access": result2["access"]}
            refresh_err = result2.get("error") or refresh_err

        # Keep file but mark unusable so status/is_connected do not claim connected.
        _mark_unusable(refresh_err, clear_file=False)
        return None


def _finish_with_code(code: str, state: str, expected_state: str) -> None:
    with _lock:
        if not _pending or _pending.get("state") != expected_state:
            return
        if _pending.get("done"):
            return
        verifier = _pending.get("verifier")
        if not verifier:
            return
        result = _exchange_code(code, verifier, state or expected_state)
        _pending["done"] = True
        _pending["result"] = result
        _pending["connected"] = bool(result.get("ok"))

    def _later() -> None:
        time.sleep(0.5)
        _stop_callback_server()

    threading.Thread(target=_later, daemon=True).start()


def _start_callback_server(expected_state: str) -> bool:
    global _httpd, _httpd_thread
    _stop_callback_server()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                body = _error_html("Callback route not found.")
                self.send_response(404)
            else:
                qs = parse_qs(parsed.query)
                state = (qs.get("state") or [None])[0]
                code = (qs.get("code") or [None])[0]
                err = (qs.get("error") or [None])[0]
                if err:
                    body = _error_html(f"Provider error: {err}")
                    self.send_response(400)
                elif state != expected_state:
                    body = _error_html("State mismatch.")
                    self.send_response(400)
                elif not code:
                    body = _error_html("Missing authorization code.")
                    self.send_response(400)
                else:
                    body = _success_html()
                    self.send_response(200)
                    threading.Thread(
                        target=_finish_with_code,
                        args=(code, state or expected_state, expected_state),
                        daemon=True,
                    ).start()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    try:
        httpd = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), Handler)
    except OSError as exc:
        log.warning("Claude OAuth callback port %s busy: %s", CALLBACK_PORT, exc)
        return False
    _httpd = httpd

    def _serve() -> None:
        try:
            httpd.serve_forever(poll_interval=0.3)
        except Exception:
            pass

    _httpd_thread = threading.Thread(target=_serve, daemon=True, name="claude-oauth-cb")
    _httpd_thread.start()
    return True


def parse_code_or_url(
    raw: str, expected_state: str | None = None
) -> tuple[str | None, str | None, str | None]:
    """Return (code, state, error). Supports URL, bare code, or code#state."""
    text = (raw or "").strip()
    if not text:
        return None, None, "Paste the redirect URL, authorization code, or code#state."
    if "#" in text and "://" not in text:
        code, _, st = text.partition("#")
        code, st = code.strip(), st.strip()
        if expected_state and st and st != expected_state:
            return None, None, "State mismatch — start Connect again."
        if not code:
            return None, None, "Missing code before #."
        return code, st or expected_state, None
    if "://" in text or text.startswith("http"):
        try:
            parsed = urlparse(text)
            qs = parse_qs(parsed.query)
            code = (qs.get("code") or [None])[0]
            state = (qs.get("state") or [None])[0]
            if not code and parsed.fragment:
                frag = parsed.fragment
                if "code=" in frag:
                    fqs = parse_qs(frag)
                    code = (fqs.get("code") or [None])[0]
                    state = state or (fqs.get("state") or [None])[0]
                elif frag:
                    code = frag
            if expected_state and state and state != expected_state:
                return None, None, "State mismatch — start Connect again."
            if not code:
                return None, None, "No authorization code found."
            return code, state or expected_state, None
        except Exception:
            return None, None, "Could not parse that redirect URL."
    return text, expected_state, None


def build_authorize_url(state: str, challenge: str) -> str:
    params = {
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def start_login(*, open_browser: bool = True) -> dict[str, Any]:
    with _lock:
        verifier, challenge = _pkce_pair()
        state = secrets.token_hex(16)
        url = build_authorize_url(state, challenge)
        _pending.clear()
        _pending.update(
            {
                "verifier": verifier,
                "state": state,
                "url": url,
                "started_at": time.time(),
                "done": False,
                "connected": False,
            }
        )
        bound = _start_callback_server(state)
        out: dict[str, Any] = {
            "ok": True,
            "url": url,
            "state": state,
            "callback_listening": bound,
        }
        if not bound:
            out["warning"] = (
                "Could not bind localhost:53692 — paste the redirect URL or code#state after signing in."
            )
    if open_browser:
        try:
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            out["browser_opened"] = True
        except Exception:
            out["browser_opened"] = False
    return out


def complete_login(code_or_url: str) -> dict[str, Any]:
    with _lock:
        pending = dict(_pending)
        expected_state = pending.get("state")
        verifier = pending.get("verifier")
        if not verifier:
            return {
                "ok": False,
                "error": "No active sign-in. Click Connect Claude first, then paste the code.",
            }
        if pending.get("done") and pending.get("connected"):
            return {"ok": True, "connected": True}
        code, state, err = parse_code_or_url(code_or_url, expected_state=expected_state)
        if err or not code:
            return {"ok": False, "error": err or "Missing code"}
        result = _exchange_code(code, verifier, state or expected_state)
        _pending["done"] = True
        _pending["result"] = result
        _pending["connected"] = bool(result.get("ok"))
        _stop_callback_server()
        return result


def logout() -> dict[str, Any]:
    global _last_error, _needs_reauth
    with _lock:
        clear_stored()
        _pending.clear()
        _stop_callback_server()
        _last_error = None
        _needs_reauth = False
    return {"ok": True, "connected": False}


def pending_poll() -> dict[str, Any]:
    if load_stored():
        with _lock:
            pending = dict(_pending)
        if not pending or pending.get("connected") or pending.get("done"):
            return {"ok": True, "connected": True, "pending": False}
    with _lock:
        pending = dict(_pending)
    if not pending:
        return {"ok": True, "connected": False, "pending": False}
    age = time.time() - float(pending.get("started_at") or time.time())
    timed_out = age > 180
    result = pending.get("result") if pending.get("done") else None
    out: dict[str, Any] = {
        "ok": True,
        "connected": False,
        "pending": not timed_out and not pending.get("done"),
        "timed_out": timed_out,
    }
    if isinstance(result, dict) and not result.get("ok"):
        out["error"] = result.get("error")
    return out
