"""Permission / environment doctor for jevii."""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .keys import ensure_keys_loaded, key_status

ROOT = Path.home() / "jevii"
SETTINGS_LINKS = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "screen_recording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "full_disk": "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
}


def _perms() -> dict:
    try:
        from macos_computer_use import darwin

        return dict(darwin.permissions())
    except Exception as exc:
        return {"accessibility": False, "screen_recording": False, "error": str(exc)}


def _kit() -> dict:
    try:
        import macos_computer_use as mcu

        return {"ok": True, "version": getattr(mcu, "__version__", "installed")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _cdp_ok(port: int = 9222) -> dict:
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as resp:
            return {"ok": True, "port": port, "status": resp.status}
    except Exception as exc:
        # Chrome 144+ may 404 version but still listen
        try:
            import socket

            s = socket.create_connection(("127.0.0.1", port), timeout=0.8)
            s.close()
            return {"ok": True, "port": port, "note": "port open"}
        except Exception:
            return {"ok": False, "port": port, "error": str(exc)}


def process_hint() -> str:
    """Which binary the user should enable in TCC panes."""
    exe = Path(sys.executable).resolve()
    return (
        f"Enable Accessibility + Screen Recording for this Python: {exe}\n"
        "Also enable: Terminal (if you launch from Terminal), "
        "Grok Bot / com.anysphere.sand (if agents drive jevii), "
        "and Google Chrome (for CDP browser attach)."
    )


def run_doctor(*, as_json: bool = False, print_out: bool | None = None) -> dict:
    ensure_keys_loaded()
    perms = _perms()
    kit = _kit()
    keys = key_status()
    cdp = _cdp_ok()
    ok = bool(perms.get("accessibility")) and kit.get("ok") and keys.get("typesafe")
    info = {
        "ok": ok,
        "app": "jevii",
        "version": "0.1.0",
        "python": sys.executable,
        "platform": platform.platform(),
        "macos": platform.mac_ver()[0],
        "permissions": {
            "accessibility": bool(perms.get("accessibility")),
            "screen_recording": bool(perms.get("screen_recording")),
            "full_disk": None,  # no reliable probe without touching protected paths
        },
        "kit": kit,
        "keys": {k: v for k, v in keys.items() if k != "typesafe_path"},
        "typesafe_path": keys.get("typesafe_path"),
        "cdp": cdp,
        "jev_desktop": str(Path.home() / ".jev-desktop"),
        "jevii_root": str(ROOT),
        "settings_links": SETTINGS_LINKS,
        "enable_binary": str(Path(sys.executable).resolve()),
        "process_hint": process_hint(),
        "hints": [],
    }
    if not info["permissions"]["accessibility"]:
        info["hints"].append("Grant Accessibility, then quit & reopen the Terminal/Python process.")
    if not info["permissions"]["screen_recording"]:
        info["hints"].append("Grant Screen Recording for screenshots / vision mouse control.")
    if not keys.get("typesafe"):
        info["hints"].append("Missing TypeSafe key at ~/.jev-ultrafast-mcp/TYPESAFE_API_KEY")
    if not keys.get("openai") and not keys.get("anthropic") and not keys.get("xai"):
        info["hints"].append("Add OPENAI_API_KEY / ANTHROPIC_API_KEY / XAI_API_KEY to ~/jevii/.env for chat.")
    if not info["hints"]:
        info["hints"].append("All critical checks passed. Open http://127.0.0.1:8765")

    if print_out is None:
        print_out = True  # CLI default
    if print_out:
        if as_json:
            print(json.dumps(info, indent=2))
        else:
            print("jevii doctor")
            print(f"  python:           {info['python']}")
            print(f"  kit:              {kit}")
            print(f"  accessibility:    {info['permissions']['accessibility']}")
            print(f"  screen_recording: {info['permissions']['screen_recording']}")
            print(f"  typesafe:         {keys.get('typesafe')}")
            print(f"  openai:           {keys.get('openai')}")
            print(f"  anthropic:        {keys.get('anthropic')}")
            print(f"  xai:              {keys.get('xai')}")
            print(f"  cdp_9222:         {cdp.get('ok')}")
            print(f"  enable_binary:    {info['enable_binary']}")
            print("hints:")
            for h in info["hints"]:
                print(f"  - {h}")

    return info


def open_settings(pane: str) -> dict:
    url = SETTINGS_LINKS.get(pane)
    if not url:
        return {"ok": False, "error": f"unknown pane {pane!r}", "known": list(SETTINGS_LINKS)}
    try:
        subprocess.run(["open", url], check=False)
        return {"ok": True, "pane": pane, "url": url}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": url}


def open_all_required() -> list[dict]:
    return [open_settings(p) for p in ("accessibility", "screen_recording", "full_disk")]
