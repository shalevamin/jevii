"""Multi-provider chat: API keys, subscription OAuth, and local models.

Never log secrets or OAuth tokens.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from . import local_models
from . import oauth_anthropic
from . import oauth_openai
from . import oauth_xai
from .keys import get_provider_key
from .workspace_prompt import build_system_prompt, inject_system_messages

log = logging.getLogger("jevii.chat")

CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_DEFAULT_MODEL = "gpt-6-luna"
CLAUDE_DEFAULT = "claude-sonnet-4-20250514"
GROK_DEFAULT = "grok-4"

API_PROVIDERS = {
    "openai": {
        "base": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "style": "openai",
    },
    "xai": {
        "base": "https://api.x.ai/v1",
        "default_model": "grok-2-latest",
        "style": "openai",
    },
    "anthropic": {
        "base": "https://api.anthropic.com/v1",
        "default_model": "claude-3-5-haiku-latest",
        "style": "anthropic",
    },
}

OAUTH_ALIASES = {
    "chatgpt": "chatgpt-oauth",
    "chatgpt-oauth": "chatgpt-oauth",
    "openai-oauth": "chatgpt-oauth",
    "claude-oauth": "claude-oauth",
    "anthropic-oauth": "claude-oauth",
    "grok-oauth": "grok-oauth",
    "xai-oauth": "grok-oauth",
}


def list_providers() -> list[dict[str, Any]]:
    """UI/provider catalog with connection presence only."""
    keys_openai = bool(get_provider_key("openai"))
    keys_ant = bool(get_provider_key("anthropic"))
    keys_xai = bool(get_provider_key("xai"))
    return [
        {"id": "chatgpt-oauth", "label": "ChatGPT (subscription)", "kind": "oauth", "connected": oauth_openai.is_connected()},
        {"id": "claude-oauth", "label": "Claude (subscription)", "kind": "oauth", "connected": oauth_anthropic.is_connected()},
        {"id": "grok-oauth", "label": "Grok (subscription)", "kind": "oauth", "connected": oauth_xai.is_connected()},
        {"id": "openai", "label": "OpenAI (API key)", "kind": "api_key", "connected": keys_openai},
        {"id": "anthropic", "label": "Anthropic (API key)", "kind": "api_key", "connected": keys_ant},
        {"id": "xai", "label": "xAI (API key)", "kind": "api_key", "connected": keys_xai},
        {"id": "ollama", "label": "Ollama (local)", "kind": "local", "connected": bool(local_models.probe("ollama").get("reachable"))},
        {"id": "lmstudio", "label": "LM Studio (local)", "kind": "local", "connected": bool(local_models.probe("lmstudio").get("reachable"))},
    ]


def _messages_to_codex_input(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    instructions = build_system_prompt()
    input_items: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            instructions = content if not instructions else f"{instructions}\n{content}"
            continue
        if role not in ("user", "assistant"):
            continue
        input_items.append(
            {
                "type": "message",
                "role": "user" if role == "user" else "assistant",
                "content": [{"type": "input_text" if role == "user" else "output_text", "text": content}],
            }
        )
    if not input_items:
        input_items = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hello"}]}]
    return instructions, input_items


def _parse_sse_text(body: str) -> str:
    texts: list[str] = []
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(evt, dict):
            continue
        et = evt.get("type") or ""
        if et in ("response.output_text.delta", "response.text.delta"):
            delta = evt.get("delta")
            if isinstance(delta, str):
                texts.append(delta)
        elif et == "response.output_text.done":
            t = evt.get("text")
            if isinstance(t, str) and t and not texts:
                texts.append(t)
        elif et == "response.completed":
            resp = evt.get("response") or {}
            out = resp.get("output_text")
            if isinstance(out, str) and out and not texts:
                texts.append(out)
        # non-stream shaped
        if "output_text" in evt and isinstance(evt["output_text"], str) and not texts:
            texts.append(evt["output_text"])
    return "".join(texts)


async def _chatgpt_oauth_chat(messages: list[dict[str, Any]], model: str | None) -> dict[str, Any]:
    creds = oauth_openai.get_valid_credentials()
    if not creds:
        return {
            "ok": False,
            "error": "ChatGPT subscription not connected. Open Connect and sign in with ChatGPT.",
            "need_oauth": "chatgpt",
        }
    access = creds["access"]
    account_id = creds["accountId"]
    model = model or CODEX_DEFAULT_MODEL
    instructions, input_items = _messages_to_codex_input(messages)
    headers = {
        "Authorization": f"Bearer {access}",
        "chatgpt-account-id": account_id,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "OpenAI-Beta": "responses=experimental",
        "originator": "codex_cli_rs",
        "User-Agent": "codex_cli_rs/0.58.0",
    }
    payload = {
        "model": model,
        "instructions": instructions,
        "input": input_items,
        "store": False,
        "stream": True,
        "reasoning": {"effort": "medium"},
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(CODEX_RESPONSES_URL, headers=headers, json=payload)
    except Exception as exc:
        return {"ok": False, "error": f"ChatGPT Responses request failed: {type(exc).__name__}"}
    if resp.status_code in (401, 403):
        return {
            "ok": False,
            "error": "ChatGPT auth failed. Reconnect ChatGPT (subscription) in Connect.",
            "need_oauth": "chatgpt",
        }
    if resp.status_code >= 400:
        # try non-stream once
        payload["stream"] = False
        headers["Accept"] = "application/json"
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp2 = await client.post(CODEX_RESPONSES_URL, headers=headers, json=payload)
        if resp2.status_code >= 400:
            return {
                "ok": False,
                "error": f"ChatGPT Responses HTTP {resp.status_code}",
                "detail": (resp.text or "")[:400],
            }
        data = resp2.json()
        text = data.get("output_text") or ""
        if not text and isinstance(data.get("output"), list):
            parts = []
            for item in data["output"]:
                if isinstance(item, dict):
                    for c in item.get("content") or []:
                        if isinstance(c, dict) and c.get("text"):
                            parts.append(c["text"])
            text = "".join(parts)
        return {"ok": True, "provider": "chatgpt-oauth", "model": model, "content": text}
    text = _parse_sse_text(resp.text)
    if not text:
        # last resort: try parse json
        try:
            data = resp.json()
            text = data.get("output_text") or ""
        except Exception:
            text = ""
    return {"ok": True, "provider": "chatgpt-oauth", "model": model, "content": text or "(empty reply)"}


async def _claude_oauth_chat(messages: list[dict[str, Any]], model: str | None, temperature: float) -> dict[str, Any]:
    creds = oauth_anthropic.get_valid_credentials()
    if not creds:
        detail = oauth_anthropic.last_error() or (
            "Claude subscription not connected. Open Connect and sign in with Claude."
        )
        return {
            "ok": False,
            "error": detail,
            "need_oauth": "claude",
            "needs_reauth": bool(oauth_anthropic.needs_reauth()),
        }
    access = creds["access"]
    model = model or CLAUDE_DEFAULT
    system = None
    converted = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            system = content if system is None else f"{system}\n{content}"
            continue
        converted.append({"role": "assistant" if role == "assistant" else "user", "content": content})
    headers = {
        "x-api-key": access,
        "Authorization": f"Bearer {access}",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 2048,
        "temperature": temperature,
        "messages": converted or [{"role": "user", "content": "Hello"}],
    }
    if system:
        payload["system"] = system
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
    if resp.status_code in (401, 403):
        return {
            "ok": False,
            "error": "Claude auth failed. Reconnect Claude or use an API key. Pro alone may not work; Max + eligible credits is typical.",
            "need_oauth": "claude",
        }
    if resp.status_code >= 400:
        return {"ok": False, "error": f"Claude OAuth HTTP {resp.status_code}", "detail": resp.text[:500]}
    data = resp.json()
    blocks = data.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
    return {"ok": True, "provider": "claude-oauth", "model": model, "content": text, "usage": data.get("usage")}


async def _grok_oauth_chat(messages: list[dict[str, Any]], model: str | None, temperature: float) -> dict[str, Any]:
    creds = oauth_xai.get_valid_credentials()
    if not creds:
        return {
            "ok": False,
            "error": "Grok subscription not connected. Open Connect and sign in with Grok.",
            "need_oauth": "grok",
        }
    access = creds["access"]
    model = model or GROK_DEFAULT
    headers = {
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages, "temperature": temperature}
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload)
    if resp.status_code in (401, 403):
        return {
            "ok": False,
            "error": "Grok OAuth rejected (tier/entitlement). Try reconnecting or use an XAI_API_KEY.",
            "need_oauth": "grok",
        }
    if resp.status_code >= 400:
        return {"ok": False, "error": f"Grok OAuth HTTP {resp.status_code}", "detail": resp.text[:500]}
    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""
    return {"ok": True, "provider": "grok-oauth", "model": model, "content": content, "usage": data.get("usage")}


async def _local_chat(provider: str, messages: list[dict[str, Any]], model: str | None, temperature: float) -> dict[str, Any]:
    url, resolved_model, err = local_models.chat_completions_url(provider)
    if err:
        return {"ok": False, "error": err, "need_local": provider}
    model = model or resolved_model
    payload = {"model": model, "messages": messages, "temperature": temperature}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{provider} unreachable ({type(exc).__name__}). Is it running?",
            "need_local": provider,
        }
    if resp.status_code >= 400:
        return {"ok": False, "error": f"{provider} HTTP {resp.status_code}", "detail": resp.text[:400]}
    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""
    return {"ok": True, "provider": provider, "model": model, "content": content, "usage": data.get("usage")}


async def _api_key_chat(provider: str, messages: list[dict[str, Any]], model: str | None, temperature: float) -> dict[str, Any]:
    cfg = API_PROVIDERS[provider]
    key = get_provider_key(provider)
    if not key:
        return {
            "ok": False,
            "error": f"Missing API key for {provider}. Add it in Settings or ~/jevii/.env",
            "need_key": provider,
        }
    model = model or cfg["default_model"]
    if cfg["style"] == "openai":
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": messages, "temperature": temperature}
        url = f"{cfg['base']}/chat/completions"
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                msg = f"{provider} HTTP {resp.status_code}"
                if resp.status_code == 401:
                    msg += " — invalid key."
                return {"ok": False, "error": msg, "detail": resp.text[:800]}
            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            return {"ok": True, "provider": provider, "model": model, "content": content, "usage": data.get("usage")}

    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    system = None
    converted = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            system = content if system is None else f"{system}\n{content}"
            continue
        converted.append({"role": "assistant" if role == "assistant" else "user", "content": content})
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 2048,
        "temperature": temperature,
        "messages": converted or [{"role": "user", "content": "Hello"}],
    }
    if system:
        payload["system"] = system
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(f"{cfg['base']}/messages", headers=headers, json=payload)
        if resp.status_code >= 400:
            return {"ok": False, "error": f"anthropic HTTP {resp.status_code}", "detail": resp.text[:800]}
        data = resp.json()
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
        return {"ok": True, "provider": "anthropic", "model": model, "content": text, "usage": data.get("usage")}


def resolve_provider(provider: str | None) -> str:
    p = (provider or "").strip().lower()
    if not p or p == "auto":
        # prefer oauth then keys then local
        if oauth_openai.is_connected():
            return "chatgpt-oauth"
        if oauth_anthropic.is_connected():
            return "claude-oauth"
        if oauth_xai.is_connected():
            return "grok-oauth"
        if get_provider_key("openai"):
            return "openai"
        if get_provider_key("anthropic"):
            return "anthropic"
        if get_provider_key("xai"):
            return "xai"
        if local_models.probe("ollama").get("reachable"):
            return "ollama"
        if local_models.probe("lmstudio").get("reachable"):
            return "lmstudio"
        return "openai"
    return OAUTH_ALIASES.get(p, p)


async def chat_completion(
    *,
    provider: str,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.4,
) -> dict[str, Any]:
    # All providers (API / OAuth / local): workspace SOUL+IDENTITY+… as system.
    # Replaces any UI short system string with build_system_prompt().
    messages = inject_system_messages(messages)
    provider = resolve_provider(provider)
    if provider == "chatgpt-oauth":
        return await _chatgpt_oauth_chat(messages, model)
    if provider == "claude-oauth":
        return await _claude_oauth_chat(messages, model, temperature)
    if provider == "grok-oauth":
        return await _grok_oauth_chat(messages, model, temperature)
    if provider in ("ollama", "lmstudio"):
        return await _local_chat(provider, messages, model, temperature)
    if provider in API_PROVIDERS:
        return await _api_key_chat(provider, messages, model, temperature)
    return {"ok": False, "error": f"unknown provider {provider}"}
