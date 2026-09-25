"""ChatGPT / Codex subscription OAuth (PKCE) — same path as OpenClaw/Hermes.

Public client_id app_EMoamEEZ73f0CkXaXp7hrann. Never log token values.
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

log = logging.getLogger("jevii.oauth")

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 1455
CALLBACK_PATH = "/auth/callback"
SCOPE = "openid profile email offline_access"
ORIGINATOR = "jevii"
AUTH_CLAIM = "https://api.openai.com/auth"
REFRESH_SKEW_MS = 60_000

ROOT = Path.home() / "jevii"
AUTH_DIR = ROOT / ".auth"
AUTH_FILE = AUTH_DIR / "openai-oauth.json"

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


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        pad = "=" * ((4 - len(payload) % 4) % 4)
        raw = base64.urlsafe_b64decode(payload + pad)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def extract_account_id(*tokens: str | None) -> str | None:
    """chatgpt_account_id from id_token or access token under OpenAI auth claim."""
    for tok in tokens:
        if not tok:
            continue
        claims = _decode_jwt_payload(tok)
        if not claims:
            continue
        auth = claims.get(AUTH_CLAIM)
        if isinstance(auth, dict):
            for key in ("chatgpt_account_id", "account_id", "organization_id"):
                val = auth.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return None


def _success_html() -> bytes:
    html = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>jevii - Connected</title>
<style>body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#fff5f8;color:#1f1220}
.card{padding:32px 40px;border-radius:20px;background:#fff;box-shadow:0 16px 48px rgba(225,29,72,.18);text-align:center}
h1{margin:0 0 8px;font-size:1.4rem}p{margin:0;color:#6b5560}</style>
</head><body><div class="card"><h1>ChatGPT connected</h1>
<p>Authentication completed. You can close this window and return to jevii.</p>
</div></body></html>"""
    return html.encode("utf-8")


def _error_html(message: str) -> bytes:
    safe = (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>jevii - Auth error</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#fff1f2;color:#9f1239}}
.card{{padding:32px 40px;border-radius:20px;background:#fff;box-shadow:0 16px 48px rgba(159,18,57,.12);text-align:center;max-width:480px}}
h1{{margin:0 0 8px;font-size:1.3rem}}p{{margin:0;color:#6b5560}}</style>
</head><body><div class="card"><h1>Sign-in failed</h1><p>{safe}</p>
<p style="margin-top:12px">You can paste the redirect URL in jevii as a fallback.</p>
</div></body></html>"""
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


def _finish_with_code(code: str, expected_state: str) -> None:
    with _lock:
        pending = _pending
        if not pending or pending.get("state") != expected_state:
            return
        if pending.get("done"):
            return
        verifier = pending.get("verifier")
        if not verifier:
            return
        result = _exchange_code(code, verifier)
        pending["done"] = True
        pending["result"] = result
        pending["connected"] = bool(result.get("ok"))

    def _later() -> None:
        time.sleep(0.5)
        _stop_callback_server()

    threading.Thread(target=_later, daemon=True).start()


def _start_callback_server(expected_state: str) -> bool:
    """Bind 127.0.0.1:1455 /auth/callback. Returns False if port busy."""
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
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
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
                    args=(code, expected_state),
                    daemon=True,
                ).start()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    try:
        httpd = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), Handler)
    except OSError as exc:
        log.warning("OAuth callback port %s busy: %s", CALLBACK_PORT, exc)
        return False

    _httpd = httpd

    def _serve() -> None:
        try:
            httpd.serve_forever(poll_interval=0.3)
        except Exception:
            pass

    _httpd_thread = threading.Thread(target=_serve, daemon=True, name="oauth-callback")
    _httpd_thread.start()
    return True


def _store_tokens(access: str, refresh: str, expires: int, account_id: str) -> None:
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "access": access,
        "refresh": refresh,
        "expires": expires,
        "accountId": account_id,
    }
    AUTH_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    AUTH_FILE.chmod(0o600)


def load_stored() -> dict[str, Any] | None:
    if not AUTH_FILE.is_file():
        return None
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if not data.get("access") or not data.get("refresh") or not data.get("accountId"):
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
    if not data:
        return {"ok": True, "connected": False}
    out: dict[str, Any] = {"ok": True, "connected": True}
    exp = data.get("expires")
    if isinstance(exp, (int, float)):
        out["expires_at"] = int(exp)
    return out


def _exchange_code(code: str, verifier: str) -> dict[str, Any]:
    body = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT_URI,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code >= 400:
        return {
            "ok": False,
            "error": f"Token exchange failed (HTTP {resp.status_code}). Try Connect again.",
        }
    try:
        js = resp.json()
    except Exception:
        return {"ok": False, "error": "Token exchange returned invalid JSON."}
    access = js.get("access_token")
    refresh = js.get("refresh_token")
    expires_in = js.get("expires_in")
    id_token = js.get("id_token")
    if not access or not refresh or not isinstance(expires_in, (int, float)):
        return {"ok": False, "error": "Token exchange missing required fields."}
    expires = int(time.time() * 1000) + int(expires_in) * 1000
    account_id = extract_account_id(id_token, access)
    if not account_id:
        return {
            "ok": False,
            "error": "Could not extract ChatGPT account id from token. Reconnect ChatGPT.",
        }
    _store_tokens(access, refresh, expires, account_id)
    log.info("ChatGPT OAuth connected (tokens stored under .auth)")
    return {"ok": True, "connected": True}


def _refresh(refresh_token: str, previous_account: str | None = None) -> dict[str, Any]:
    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code >= 400:
        return {
            "ok": False,
            "error": "ChatGPT session expired. Reconnect ChatGPT (subscription).",
            "need_reconnect": True,
        }
    try:
        js = resp.json()
    except Exception:
        return {"ok": False, "error": "Token refresh returned invalid JSON.", "need_reconnect": True}
    access = js.get("access_token")
    refresh = js.get("refresh_token") or refresh_token
    expires_in = js.get("expires_in")
    id_token = js.get("id_token")
    if not access or not isinstance(expires_in, (int, float)):
        return {"ok": False, "error": "Token refresh missing fields.", "need_reconnect": True}
    expires = int(time.time() * 1000) + int(expires_in) * 1000
    account_id = extract_account_id(id_token, access) or previous_account
    if not account_id:
        return {
            "ok": False,
            "error": "Could not resolve ChatGPT account id after refresh. Reconnect.",
            "need_reconnect": True,
        }
    _store_tokens(access, refresh, expires, account_id)
    return {"ok": True, "access": access, "accountId": account_id, "expires": expires}


def get_valid_credentials() -> dict[str, Any] | None:
    """Return {access, accountId}, refreshing near expiry. Never logs secrets."""
    with _lock:
        data = load_stored()
        if not data:
            return None
        now = int(time.time() * 1000)
        expires = int(data.get("expires") or 0)
        if expires and now < (expires - REFRESH_SKEW_MS):
            return {"access": data["access"], "accountId": data["accountId"]}
        result = _refresh(data["refresh"], previous_account=data.get("accountId"))
        if not result.get("ok"):
            return None
        return {"access": result["access"], "accountId": result["accountId"]}


def parse_code_or_url(raw: str, expected_state: str | None = None) -> tuple[str | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return None, "Paste the redirect URL or authorization code."
    if "://" in text or text.startswith("http"):
        try:
            parsed = urlparse(text)
            qs = parse_qs(parsed.query)
            code = (qs.get("code") or [None])[0]
            state = (qs.get("state") or [None])[0]
            if expected_state and state and state != expected_state:
                return None, "State mismatch — start Connect again, then paste the new redirect URL."
            if not code:
                return None, "No authorization code found in that URL."
            return code, None
        except Exception:
            return None, "Could not parse that redirect URL."
    return text, None


def build_authorize_url(state: str, challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": ORIGINATOR,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def start_login(*, open_browser: bool = True) -> dict[str, Any]:
    """Start PKCE flow + local callback listener. Opens browser via macOS `open`."""
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
                "Could not bind localhost:1455 — use the paste-redirect-URL fallback after signing in."
            )

    if open_browser:
        try:
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            out["browser_opened"] = True
        except Exception as exc:
            log.warning("Could not open browser: %s", type(exc).__name__)
            out["browser_opened"] = False
    return out


def complete_login(code_or_url: str) -> dict[str, Any]:
    """Paste-redirect-URL / code fallback."""
    with _lock:
        pending = dict(_pending)
        expected_state = pending.get("state")
        verifier = pending.get("verifier")
        if not verifier:
            return {
                "ok": False,
                "error": "No active sign-in. Click Connect ChatGPT first, then paste the redirect URL.",
            }
        if pending.get("done") and pending.get("connected"):
            return {"ok": True, "connected": True}
        code, err = parse_code_or_url(code_or_url, expected_state=expected_state)
        if err or not code:
            return {"ok": False, "error": err or "Missing code"}
        result = _exchange_code(code, verifier)
        _pending["done"] = True
        _pending["result"] = result
        _pending["connected"] = bool(result.get("ok"))
        _stop_callback_server()
        return result


def logout() -> dict[str, Any]:
    with _lock:
        clear_stored()
        _pending.clear()
        _stop_callback_server()
    return {"ok": True, "connected": False}


def pending_poll() -> dict[str, Any]:
    """UI poll helper — presence only, never tokens."""
    st = status()
    with _lock:
        pending = dict(_pending)
    if st.get("connected"):
        return {**st, "pending": False}
    if not pending:
        return {**st, "pending": False}
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
