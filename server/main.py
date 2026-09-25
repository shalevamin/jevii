"""jevii FastAPI — UI, chat, OAuth, Telegram, local models, desktop tools."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import browser as browser_mod
from . import chat as chat_mod
from . import desktop as desktop_mod
from . import local_models
from . import oauth_anthropic
from . import oauth_openai
from . import oauth_xai
from . import telegram_bridge
from .doctor import open_all_required, open_settings, run_doctor
from .keys import ensure_keys_loaded, key_status, save_provider_key

ROOT = Path(os.environ.get("JEVII_ROOT", Path.home() / "jevii")).resolve()
APP_DIR = ROOT / "app"

ensure_keys_loaded()

app = FastAPI(title="jevii", version="0.2.1", docs_url="/api/docs")


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
    provider: str = "auto"
    model: Optional[str] = None
    temperature: float = 0.4


class GoalRequest(BaseModel):
    goal: str
    app: Optional[str] = None
    dry_run: bool = True
    max_steps: int = Field(default=5, ge=1, le=25)


class ClickRequest(BaseModel):
    x: int
    y: int
    button: str = "left"


class MoveRequest(BaseModel):
    x: int
    y: int
    steps: int = 14


class TypeRequest(BaseModel):
    text: str


class KeyRequest(BaseModel):
    key: str


class NavigateRequest(BaseModel):
    url: str


class OpenSettingsRequest(BaseModel):
    pane: str = "accessibility"


class SaveKeyRequest(BaseModel):
    provider: str
    key: str


class OAuthCompleteRequest(BaseModel):
    code_or_url: str = ""


class LocalSettingsRequest(BaseModel):
    provider: str
    base_url: Optional[str] = None
    model: Optional[str] = None


class TelegramConfigRequest(BaseModel):
    token: Optional[str] = None
    allowed_chat_ids: Optional[str] = None


def _oauth_bundle() -> dict[str, Any]:
    return {
        "chatgpt": oauth_openai.status(),
        "claude": oauth_anthropic.status(),
        "grok": oauth_xai.status(),
    }



@app.on_event("startup")
def _auto_start_telegram() -> None:
    """Start Telegram channel with the gateway when a bot token is configured."""
    import os
    if os.environ.get("JEVII_NO_TELEGRAM") == "1":
        return
    try:
        st = telegram_bridge.status()
        if st.get("configured") and not st.get("running"):
            telegram_bridge.start()
    except Exception:
        pass

@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "app": "jevii", "version": "0.2.1"}


@app.get("/api/doctor")
def api_doctor() -> dict:
    info = run_doctor(as_json=False, print_out=False)
    info["oauth"] = _oauth_bundle()
    info["local"] = local_models.probe_all()
    info["telegram"] = {k: v for k, v in telegram_bridge.status().items() if k != "guide"}
    info["providers"] = chat_mod.list_providers()
    keys = info.get("keys") or {}
    oauth_ok = any(bool(v.get("connected")) for v in info["oauth"].values() if isinstance(v, dict))
    local_ok = any(bool((info["local"].get(p) or {}).get("reachable")) for p in ("ollama", "lmstudio"))
    info["any_chat_backend"] = bool(keys.get("any_provider") or oauth_ok or local_ok)
    return info


@app.get("/api/keys")
def api_keys() -> dict:
    return {"ok": True, "keys": key_status(), "oauth": _oauth_bundle()}


@app.post("/api/keys/save")
def api_keys_save(body: SaveKeyRequest) -> dict:
    result = save_provider_key(body.provider, body.key)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Save failed")
    return {"ok": True, "provider": result.get("provider"), "keys": result.get("keys") or key_status()}


@app.get("/api/providers")
def api_providers() -> dict:
    return {"ok": True, "providers": chat_mod.list_providers()}


@app.post("/api/oauth/openai/start")
def api_oauth_openai_start() -> dict:
    return oauth_openai.start_login(open_browser=True)


@app.get("/api/oauth/openai/status")
def api_oauth_openai_status() -> dict:
    st = dict(oauth_openai.status())
    poll = oauth_openai.pending_poll()
    for k in ("pending", "timed_out", "error"):
        if k in poll:
            st[k] = poll[k]
    return st


@app.post("/api/oauth/openai/complete")
def api_oauth_openai_complete(body: OAuthCompleteRequest) -> dict:
    return oauth_openai.complete_login(body.code_or_url)


@app.post("/api/oauth/openai/logout")
def api_oauth_openai_logout() -> dict:
    return oauth_openai.logout()


@app.post("/api/oauth/anthropic/start")
def api_oauth_anthropic_start() -> dict:
    return oauth_anthropic.start_login(open_browser=True)


@app.get("/api/oauth/anthropic/status")
def api_oauth_anthropic_status() -> dict:
    st = dict(oauth_anthropic.status())
    poll = oauth_anthropic.pending_poll()
    for k in ("pending", "timed_out", "error"):
        if k in poll:
            st[k] = poll[k]
    return st


@app.post("/api/oauth/anthropic/complete")
def api_oauth_anthropic_complete(body: OAuthCompleteRequest) -> dict:
    return oauth_anthropic.complete_login(body.code_or_url)


@app.post("/api/oauth/anthropic/import-claude-code")
def api_oauth_anthropic_import() -> dict:
    return oauth_anthropic.import_claude_code()


@app.post("/api/oauth/anthropic/logout")
def api_oauth_anthropic_logout() -> dict:
    return oauth_anthropic.logout()


@app.post("/api/oauth/xai/start")
def api_oauth_xai_start() -> dict:
    return oauth_xai.start_login(open_browser=True)


@app.get("/api/oauth/xai/status")
def api_oauth_xai_status() -> dict:
    return oauth_xai.pending_poll()


@app.post("/api/oauth/xai/logout")
def api_oauth_xai_logout() -> dict:
    return oauth_xai.logout()


@app.get("/api/local/status")
def api_local_status() -> dict:
    return local_models.probe_all()


@app.get("/api/local/settings")
def api_local_settings() -> dict:
    return local_models.get_settings()


@app.post("/api/local/settings")
def api_local_settings_save(body: LocalSettingsRequest) -> dict:
    return local_models.save_settings(body.provider, base_url=body.base_url, model=body.model)


@app.post("/api/local/probe/{provider}")
def api_local_probe(provider: str) -> dict:
    return local_models.probe(provider)


@app.get("/api/telegram/status")
def api_telegram_status() -> dict:
    return telegram_bridge.status()


@app.post("/api/telegram/config")
def api_telegram_config(body: TelegramConfigRequest) -> dict:
    return telegram_bridge.save_config(token=body.token, allowed_chat_ids=body.allowed_chat_ids)


@app.post("/api/telegram/start")
def api_telegram_start() -> dict:
    return telegram_bridge.start()


@app.post("/api/telegram/stop")
def api_telegram_stop() -> dict:
    return telegram_bridge.stop()


@app.post("/api/telegram/clear")
def api_telegram_clear() -> dict:
    return telegram_bridge.clear_token()


@app.post("/api/settings/open")
def api_open_settings(body: OpenSettingsRequest) -> dict:
    return open_settings(body.pane)


@app.post("/api/settings/open-all")
def api_open_all() -> dict:
    return {"ok": True, "results": open_all_required()}


@app.post("/api/chat")
async def api_chat(body: ChatRequest) -> Any:
    result = await chat_mod.chat_completion(
        provider=body.provider,
        messages=body.messages,
        model=body.model,
        temperature=body.temperature,
    )
    if not result.get("ok"):
        code = 400 if (result.get("need_key") or result.get("need_oauth") or result.get("need_local")) else 502
        return JSONResponse(result, status_code=code)
    return result


@app.post("/api/desktop/screenshot")
def api_screenshot() -> dict:
    return desktop_mod.screenshot_b64()


@app.post("/api/desktop/click")
def api_click(body: ClickRequest) -> dict:
    return desktop_mod.click_xy(body.x, body.y, button=body.button)


@app.post("/api/desktop/move")
def api_move(body: MoveRequest) -> dict:
    return desktop_mod.move_xy(body.x, body.y, steps=body.steps)


@app.post("/api/desktop/type")
def api_type(body: TypeRequest) -> dict:
    return desktop_mod.type_text(body.text)


@app.post("/api/desktop/key")
def api_key(body: KeyRequest) -> dict:
    return desktop_mod.key_press(body.key)


@app.post("/api/desktop/goal")
def api_goal(body: GoalRequest) -> dict:
    return desktop_mod.run_goal(body.goal, app=body.app, dry_run=body.dry_run, max_steps=body.max_steps)


@app.get("/api/browser/status")
def api_browser_status() -> dict:
    return browser_mod.cdp_status()


@app.post("/api/browser/ensure")
def api_browser_ensure() -> dict:
    return browser_mod.ensure_cdp()


@app.get("/api/browser/tabs")
def api_browser_tabs() -> dict:
    return browser_mod.list_tabs()


@app.post("/api/browser/navigate")
def api_browser_navigate(body: NavigateRequest) -> dict:
    return browser_mod.navigate(body.url)


@app.get("/")
def index() -> FileResponse:
    index_path = APP_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "UI missing — re-run install.sh")
    return FileResponse(index_path)


if APP_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(APP_DIR)), name="static")
