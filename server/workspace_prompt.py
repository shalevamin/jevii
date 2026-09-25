"""jevii system prompt: operator capability + soul + memory.

Only SOUL.md and MEMORY.md from workspace/. Never logs secrets.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

MAX_CHARS_PER_FILE = 20_000
MAX_CHARS_TOTAL = 40_000

WORKSPACE_FILES: tuple[str, ...] = (
    "SOUL.md",
    "MEMORY.md",
)

# High-priority system layer: capabilities first, then soul/memory files.
SYSTEM_PROMPT = """You are jevii, a local AI agent on the user's Mac.

You are not limited to chat. You can operate the entire Mac with mouse and keyboard like a human: see the screen, move the pointer, click, double-click, drag, scroll, type, and press keys. Open any app. Drive any window. Use the browser, Finder, creative tools, Telegram, settings — whatever the task needs. Prefer acting on the desktop over asking the user to click for you.

When a tool or desktop API is available, use it. Screenshot to see, then click and type to change things. Keep going until the goal is done or you hit a hard blocker (destructive action the user did not ask for, or an Apple permission only they can toggle).

Never invent that you lack a body on this Mac. You have mouse and keyboard. Use them.

English for product/UI voice. Match the user's language in conversation when they write Hebrew or another language.

Never print secrets (API keys, OAuth tokens, Telegram tokens, passwords).
""".strip()

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = ROOT / "workspace"


def workspace_dir() -> Path:
    return WORKSPACE_DIR


def _read_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    text = text.strip()
    if not text:
        return ""
    if len(text) > MAX_CHARS_PER_FILE:
        text = text[:MAX_CHARS_PER_FILE].rstrip() + "\n\n[…truncated to cap]"
    return text


def load_workspace_sections(
    names: Iterable[str] | None = None,
    *,
    directory: Path | None = None,
) -> list[tuple[str, str]]:
    directory = directory or WORKSPACE_DIR
    order = tuple(names) if names is not None else WORKSPACE_FILES
    sections: list[tuple[str, str]] = []
    used = 0
    for name in order:
        path = directory / name
        if not path.is_file():
            continue
        body = _read_file(path)
        if not body:
            continue
        remaining = MAX_CHARS_TOTAL - used
        if remaining <= 0:
            break
        if len(body) > remaining:
            body = body[:remaining].rstrip() + "\n\n[…truncated; total workspace cap]"
        sections.append((name, body))
        used += len(body)
    return sections


def build_system_prompt(*, directory: Path | None = None) -> str:
    parts: list[str] = [SYSTEM_PROMPT]
    for name, body in load_workspace_sections(directory=directory):
        label = name.removesuffix(".md")
        parts.append(f"## {label}\n\n{body}")
    return "\n\n".join(parts).strip() + "\n"


def inject_system_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure the assembled jevii system prompt is the first system message."""
    system = build_system_prompt()
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        role = (m.get("role") or "").lower()
        if role == "system":
            # Drop caller system; server owns the operator + soul + memory prompt.
            continue
        out.append(m)
    return out
