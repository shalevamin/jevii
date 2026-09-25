"""Telegram long-poll bridge into jevii chat pipeline. Never log bot tokens."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from typing import Any, Optional

import httpx

from .keys import ensure_keys_loaded, get_env_value, save_env_value

log = logging.getLogger("jevii.telegram")

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
ALLOWED_ENV = "TELEGRAM_ALLOWED_CHAT_IDS"

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_state: dict[str, Any] = {
    "running": False,
    "last_error": None,
    "last_update_id": 0,
    "started_at": None,
    "messages_handled": 0,
    "last_desktop": None,
}

GUIDE = (
    "1. Open Telegram and search for @BotFather.\n"
    "2. Send /newbot and follow the prompts (name + username ending in bot).\n"
    "3. BotFather replies with a token like 123456:ABC…. Copy it.\n"
    "4. Paste the token below and click Save token (stored only in ~/jevii/.env, chmod 600).\n"
    "5. Optional: limit who can talk to the bot by pasting your numeric chat id(s), comma-separated. "
    "Message @userinfobot to learn your chat id.\n"
    "6. Click Start bridge. jevii long-polls Telegram and replies with your connected model "
    "(ChatGPT/Claude/Grok OAuth, API key, or local Ollama/LM Studio).\n"
    "7. In Telegram, open your bot and send /start, then chat normally. "
    "Mac desktop tasks (Calculator, click, screenshot, open app) are handled with real mouse/keyboard."
)

_MAC_TASK_RE = re.compile(
    r"(?i)\b("
    r"calculator|mouse|keyboard|screenshot|desktop|mac\b|macos|"
    r"open\s+app|click|type\s+text|key\s*press|compute\s+on\s+this\s+mac|"
    r"use\s+mouse|use\s+keyboard|on\s+this\s+mac|screen\s*shot|"
    r"jev-?desktop|vision|ax\b"
    r")\b"
)

_CALC_EXPR_RE = re.compile(
    r"(?i)(?:calculator|compute|calculate|calc).*?(\d+\s*[\+\-\*/]\s*\d+)|"
    r"(\d+\s*[\+\-\*/]\s*\d+).*?(?:calculator|on\s+this\s+mac)|"
    r"\b(\d+\s*\+\s*\d+)\b"
)


def _token() -> str | None:
    ensure_keys_loaded(force=True)
    val = (os.environ.get(TOKEN_ENV) or get_env_value(TOKEN_ENV) or "").strip()
    return val or None


def _allowed_ids() -> set[str]:
    ensure_keys_loaded(force=True)
    raw = (os.environ.get(ALLOWED_ENV) or get_env_value(ALLOWED_ENV) or "").strip()
    if not raw:
        return set()
    return {p.strip() for p in raw.replace(";", ",").split(",") if p.strip()}


def validate_token_format(token: str) -> str | None:
    t = (token or "").strip()
    if not t:
        return "Bot token is required."
    if not re.match(r"^\d{6,}:[A-Za-z0-9_-]{20,}$", t):
        return "That does not look like a BotFather token (expected digits:secret)."
    return None


def status() -> dict[str, Any]:
    tok = _token()
    with _lock:
        st = dict(_state)
    return {
        "ok": True,
        "configured": bool(tok),
        "running": bool(st.get("running")),
        "allowed_chats_configured": bool(_allowed_ids()),
        "messages_handled": int(st.get("messages_handled") or 0),
        "last_error": st.get("last_error"),
        "started_at": st.get("started_at"),
        "last_desktop": st.get("last_desktop"),
        "guide": GUIDE,
    }


def save_config(*, token: str | None = None, allowed_chat_ids: str | None = None) -> dict[str, Any]:
    if token is not None:
        err = validate_token_format(token)
        if err:
            return {"ok": False, "error": err}
        save_env_value(TOKEN_ENV, token.strip())
        os.environ[TOKEN_ENV] = token.strip()
    if allowed_chat_ids is not None:
        save_env_value(ALLOWED_ENV, allowed_chat_ids.strip())
        os.environ[ALLOWED_ENV] = allowed_chat_ids.strip()
    return {"ok": True, **{k: v for k, v in status().items() if k != "guide"}}


def clear_token() -> dict[str, Any]:
    stop()
    save_env_value(TOKEN_ENV, "")
    os.environ.pop(TOKEN_ENV, None)
    return {"ok": True, **{k: v for k, v in status().items() if k != "guide"}}


def _tg_api(token: str, method: str, **params: Any) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    with httpx.Client(timeout=45.0) as client:
        resp = client.get(url, params=params)
    try:
        data = resp.json()
    except Exception:
        return {"ok": False, "description": f"Telegram HTTP {resp.status_code}"}
    return data if isinstance(data, dict) else {"ok": False}


def _send_message(token: str, chat_id: int | str, text: str) -> None:
    chunk = 3500
    for i in range(0, max(len(text), 1), chunk):
        part = text[i : i + chunk] or "(empty)"
        _tg_api(token, "sendMessage", chat_id=chat_id, text=part)


def _prefer_provider() -> str:
    from . import oauth_anthropic, oauth_openai, oauth_xai
    from . import local_models
    from .keys import get_provider_key

    if oauth_openai.is_connected():
        return "chatgpt-oauth"
    if oauth_anthropic.is_connected():
        return "claude-oauth"
    if oauth_xai.is_connected():
        return "grok-oauth"
    for p in ("openai", "anthropic", "xai"):
        if get_provider_key(p):
            return p
    if local_models.probe("ollama").get("reachable"):
        return "ollama"
    if local_models.probe("lmstudio").get("reachable"):
        return "lmstudio"
    return "openai"


def _looks_like_mac_task(text: str) -> bool:
    return bool(_MAC_TASK_RE.search(text or ""))


def _extract_calc_expr(text: str) -> str | None:
    m = _CALC_EXPR_RE.search(text or "")
    if not m:
        return None
    for g in m.groups():
        if g:
            return re.sub(r"\s+", "", g)
    return None


def _run_mac_desktop_task(text: str) -> dict[str, Any]:
    """Drive the Mac for Calculator / desktop goals; fall back to Calculator path."""
    from . import desktop as desktop_mod

    expr = _extract_calc_expr(text)
    is_calc = bool(re.search(r"(?i)calculator", text or "")) or bool(expr)
    goal_result: dict[str, Any] | None = None
    calc_result: dict[str, Any] | None = None

    # Calculator-specific tasks: prefer the reliable open+cliclick/AX path.
    if is_calc:
        try:
            calc_result = desktop_mod.calculator_compute(expr or "1+1")
        except Exception as exc:
            calc_result = {"ok": False, "error": str(exc)}
        if not (calc_result or {}).get("ok"):
            try:
                goal_result = desktop_mod.run_goal(text, dry_run=False, max_steps=12)
            except Exception as exc:
                goal_result = {"ok": False, "error": str(exc)}
            # If goal also fails / no numeric result, retry simple 1+1 when asked
            if re.search(r"(?i)1\s*\+\s*1", text or ""):
                try:
                    calc_result = desktop_mod.calculator_compute("1+1")
                except Exception as exc:
                    calc_result = {"ok": False, "error": str(exc)}
    else:
        try:
            goal_result = desktop_mod.run_goal(text, dry_run=False, max_steps=12)
        except Exception as exc:
            goal_result = {"ok": False, "error": str(exc)}
        # If goal fails and message still looks like 1+1 on Mac, try Calculator.
        if not (goal_result or {}).get("ok") and re.search(r"(?i)1\s*\+\s*1", text or ""):
            try:
                calc_result = desktop_mod.calculator_compute("1+1")
            except Exception as exc:
                calc_result = {"ok": False, "error": str(exc)}

    summary = {
        "ok": bool((calc_result and calc_result.get("ok")) or (goal_result and goal_result.get("ok"))),
        "goal": goal_result,
        "calculator": calc_result,
        "result": (calc_result or {}).get("result") if calc_result else None,
        "expression": (calc_result or {}).get("expression") if calc_result else None,
        "via": (calc_result or {}).get("via")
        if (calc_result and calc_result.get("ok"))
        else ("jev-desktop" if (goal_result and goal_result.get("ok")) else None),
    }
    with _lock:
        _state["last_desktop"] = {
            "ok": summary["ok"],
            "via": summary.get("via"),
            "result": summary.get("result"),
            "expression": summary.get("expression"),
            "ts": time.time(),
        }
    return summary


def _llm_summarize_desktop(provider: str, user_text: str, desktop_info: dict[str, Any]) -> str:
    from . import chat as chat_mod

    result_val = desktop_info.get("result")
    expr = desktop_info.get("expression")
    via = desktop_info.get("via")
    ok = desktop_info.get("ok")
    goal = desktop_info.get("goal") or {}
    calc = desktop_info.get("calculator") or {}

    facts = []
    if result_val is not None:
        facts.append(f"Calculator display result: {result_val}")
    if expr:
        facts.append(f"Expression seen: {expr}")
    if via:
        facts.append(f"Control path: {via}")
    facts.append(f"Desktop action ok: {ok}")
    if goal.get("stdout"):
        facts.append(f"Goal stdout (tail): {str(goal.get('stdout'))[-1200:]}")
    if goal.get("stderr"):
        facts.append(f"Goal stderr (tail): {str(goal.get('stderr'))[-400:]}")
    if calc.get("error"):
        facts.append(f"Calculator path error: {calc.get('error')}")

    # If we have a hard result, keep LLM brief — still require English.
    system = (
        "You are jevii on macOS. The Mac desktop was just controlled with real mouse/keyboard. "
        "Reply in concise English only. If a numeric Calculator result is provided, state it clearly "
        "(e.g. 'Result: 2'). Do not invent a result that contradicts the desktop facts."
    )
    user = (
        f"User asked:\n{user_text}\n\nDesktop facts:\n- "
        + "\n- ".join(facts)
        + "\n\nWrite a short Telegram reply."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        result = asyncio.run(chat_mod.chat_completion(provider=provider, messages=messages))
    except Exception as exc:
        if result_val is not None:
            return f"Done on this Mac. Calculator result: {result_val}"
        return f"jevii desktop error: {type(exc).__name__}"
    if not result.get("ok"):
        if result_val is not None:
            return f"Done on this Mac. Calculator result: {result_val}"
        return result.get("error") or "Chat failed"
    content = (result.get("content") or "").strip()
    if result_val is not None and str(result_val) not in content:
        content = (content + f"\n\nResult: {result_val}").strip()
    return content or (f"Result: {result_val}" if result_val is not None else "(empty reply)")


def _handle_text(token: str, chat_id: int, text: str, provider: str) -> None:
    from . import chat as chat_mod

    if _looks_like_mac_task(text):
        _send_message(token, chat_id, "Working on this Mac (mouse/keyboard)…")
        desktop_info = _run_mac_desktop_task(text)
        reply = _llm_summarize_desktop(provider, text, desktop_info)
        _send_message(token, chat_id, reply)
        return

    messages = [
        {
            "role": "system",
            "content": (
                "You are jevii, a helpful local macOS desktop assistant. "
                "The user is messaging via Telegram. Be concise. English only. "
                "You can control this Mac (apps, mouse, keyboard, Calculator) when asked."
            ),
        },
        {"role": "user", "content": text},
    ]
    try:
        result = asyncio.run(chat_mod.chat_completion(provider=provider, messages=messages))
    except Exception as exc:
        _send_message(token, chat_id, f"jevii error: {type(exc).__name__}")
        return
    if not result.get("ok"):
        _send_message(token, chat_id, result.get("error") or "Chat failed")
        return
    _send_message(token, chat_id, result.get("content") or "(empty reply)")


def _loop() -> None:
    token = _token()
    if not token:
        with _lock:
            _state["running"] = False
            _state["last_error"] = "No TELEGRAM_BOT_TOKEN configured."
        return
    allowed = _allowed_ids()
    with _lock:
        offset = int(_state.get("last_update_id") or 0) + 1
        _state["running"] = True
        _state["last_error"] = None
        _state["started_at"] = time.time()
    log.info("Telegram bridge started")
    while not _stop.is_set():
        token = _token()
        if not token:
            with _lock:
                _state["last_error"] = "Token cleared."
                _state["running"] = False
            break
        try:
            data = _tg_api(token, "getUpdates", timeout=25, offset=offset)
        except Exception as exc:
            with _lock:
                _state["last_error"] = f"poll {type(exc).__name__}"
            if _stop.wait(3):
                break
            continue
        if not data.get("ok"):
            with _lock:
                _state["last_error"] = "Telegram getUpdates failed (check token)."
            if _stop.wait(5):
                break
            continue
        for upd in data.get("result") or []:
            uid = upd.get("update_id")
            if isinstance(uid, int):
                offset = uid + 1
                with _lock:
                    _state["last_update_id"] = uid
            msg = upd.get("message") or upd.get("edited_message")
            if not isinstance(msg, dict):
                continue
            chat = msg.get("chat") or {}
            chat_id = chat.get("id")
            text = msg.get("text")
            if chat_id is None or not isinstance(text, str) or not text.strip():
                continue
            if allowed and str(chat_id) not in allowed:
                _send_message(token, chat_id, "This chat is not allowed for jevii.")
                continue
            if text.strip() in ("/start", "/help"):
                _send_message(
                    token,
                    chat_id,
                    "jevii Telegram bridge is online. Mac control is available "
                    "(open apps, mouse/keyboard, Calculator, screenshots). "
                    "Send any message and I will reply using your connected model.",
                )
                continue
            provider = _prefer_provider()
            try:
                _handle_text(token, chat_id, text.strip(), provider)
                with _lock:
                    _state["messages_handled"] = int(_state.get("messages_handled") or 0) + 1
            except Exception as exc:
                with _lock:
                    _state["last_error"] = type(exc).__name__
                _send_message(token, chat_id, f"Sorry — jevii hit an error ({type(exc).__name__}).")
    with _lock:
        _state["running"] = False
    log.info("Telegram bridge stopped")


def start() -> dict[str, Any]:
    global _thread
    if not _token():
        return {"ok": False, "error": "Save a BotFather token first.", **{k: v for k, v in status().items() if k != "guide"}}
    already = False
    with _lock:
        if _state.get("running") and _thread and _thread.is_alive():
            already = True
    if already:
        return {"ok": True, "already": True, **{k: v for k, v in status().items() if k != "guide"}}
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="telegram-bridge")
    _thread.start()
    time.sleep(0.2)
    return {"ok": True, **{k: v for k, v in status().items() if k != "guide"}}


def stop() -> dict[str, Any]:
    global _thread
    _stop.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=3)
    _thread = None
    with _lock:
        _state["running"] = False
    return {"ok": True, **{k: v for k, v in status().items() if k != "guide"}}
