"""Local inference helpers — Ollama and LM Studio (OpenAI-compatible)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("jevii.local")

ROOT = Path.home() / "jevii"
CONFIG_FILE = ROOT / ".auth" / "local-models.json"

DEFAULTS = {
    "ollama": {"base_url": "http://127.0.0.1:11434", "model": ""},
    "lmstudio": {"base_url": "http://127.0.0.1:1234/v1", "model": ""},
}


def _load_config() -> dict[str, Any]:
    if CONFIG_FILE.is_file():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"ollama": dict(DEFAULTS["ollama"]), "lmstudio": dict(DEFAULTS["lmstudio"])}


def _save_config(cfg: dict[str, Any]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    CONFIG_FILE.chmod(0o600)


def get_settings() -> dict[str, Any]:
    cfg = _load_config()
    return {
        "ok": True,
        "ollama": {**DEFAULTS["ollama"], **(cfg.get("ollama") or {})},
        "lmstudio": {**DEFAULTS["lmstudio"], **(cfg.get("lmstudio") or {})},
    }


def save_settings(provider: str, *, base_url: str | None = None, model: str | None = None) -> dict[str, Any]:
    prov = (provider or "").strip().lower()
    if prov not in ("ollama", "lmstudio"):
        return {"ok": False, "error": "provider must be ollama or lmstudio"}
    cfg = _load_config()
    entry = {**DEFAULTS[prov], **(cfg.get(prov) or {})}
    if base_url is not None:
        entry["base_url"] = (base_url or DEFAULTS[prov]["base_url"]).rstrip("/")
    if model is not None:
        entry["model"] = (model or "").strip()
    cfg[prov] = entry
    _save_config(cfg)
    return {"ok": True, **get_settings()}


def probe(provider: str) -> dict[str, Any]:
    prov = (provider or "").strip().lower()
    if prov in ("lm_studio", "lm-studio"):
        prov = "lmstudio"
    settings = get_settings()
    if prov not in ("ollama", "lmstudio"):
        return {"ok": False, "reachable": False, "error": "unknown provider"}
    base = (settings[prov].get("base_url") or DEFAULTS[prov]["base_url"]).rstrip("/")
    models: list[str] = []
    try:
        with httpx.Client(timeout=2.5) as client:
            if prov == "ollama":
                # Ollama native tags + OpenAI-compat
                r = client.get(f"{base}/api/tags")
                if r.status_code < 400:
                    data = r.json()
                    for m in data.get("models") or []:
                        name = m.get("name") if isinstance(m, dict) else None
                        if name:
                            models.append(name)
                    return {
                        "ok": True,
                        "reachable": True,
                        "base_url": base,
                        "models": models,
                        "saved_model": settings[prov].get("model") or "",
                    }
                # fallback openai compat
                r2 = client.get(f"{base}/v1/models")
                if r2.status_code < 400:
                    data = r2.json()
                    for m in data.get("data") or []:
                        mid = m.get("id") if isinstance(m, dict) else None
                        if mid:
                            models.append(mid)
                    return {
                        "ok": True,
                        "reachable": True,
                        "base_url": base,
                        "models": models,
                        "saved_model": settings[prov].get("model") or "",
                    }
                return {
                    "ok": True,
                    "reachable": False,
                    "base_url": base,
                    "error": f"Ollama HTTP {r.status_code}",
                    "models": [],
                }
            # lmstudio — openai compatible
            url = base if base.endswith("/v1") else f"{base}/v1"
            r = client.get(f"{url}/models")
            if r.status_code < 400:
                data = r.json()
                for m in data.get("data") or []:
                    mid = m.get("id") if isinstance(m, dict) else None
                    if mid:
                        models.append(mid)
                return {
                    "ok": True,
                    "reachable": True,
                    "base_url": url,
                    "models": models,
                    "saved_model": settings[prov].get("model") or "",
                }
            return {
                "ok": True,
                "reachable": False,
                "base_url": url,
                "error": f"LM Studio HTTP {r.status_code}",
                "models": [],
            }
    except Exception as exc:
        return {
            "ok": True,
            "reachable": False,
            "base_url": base,
            "error": f"Offline ({type(exc).__name__}). Start {prov} and try again.",
            "models": [],
        }


def probe_all() -> dict[str, Any]:
    return {"ok": True, "ollama": probe("ollama"), "lmstudio": probe("lmstudio")}


def chat_completions_url(provider: str) -> tuple[str, str, str]:
    """Return (url, model, error)."""
    settings = get_settings()
    prov = provider.lower()
    entry = settings.get(prov) or DEFAULTS.get(prov) or {}
    base = (entry.get("base_url") or "").rstrip("/")
    model = (entry.get("model") or "").strip()
    if not base:
        return "", "", f"No base URL configured for {prov}"
    if prov == "ollama":
        # prefer openai-compat path
        if base.endswith("/v1"):
            url = f"{base}/chat/completions"
        else:
            url = f"{base}/v1/chat/completions"
        if not model:
            # try first available
            p = probe("ollama")
            models = p.get("models") or []
            model = models[0] if models else ""
        if not model:
            return url, "", "No Ollama model selected. Pull a model (e.g. llama3.2) and save it in Settings."
        return url, model, ""
    # lmstudio
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    url = f"{base}/chat/completions"
    if not model:
        p = probe("lmstudio")
        models = p.get("models") or []
        model = models[0] if models else ""
    if not model:
        return url, "", "No LM Studio model loaded. Load a model in LM Studio, then save it in Settings."
    return url, model, ""
