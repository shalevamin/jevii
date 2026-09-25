"""Load provider / TypeSafe keys from env and known files. Never log values."""
from __future__ import annotations

import os
import re
from pathlib import Path

HOME = Path.home()
TYPESAFE_CANDIDATES = [
    HOME / ".jev-ultrafast-mcp" / "TYPESAFE_API_KEY",
    HOME / ".config" / "typesafe" / "api_key",
    HOME / ".jev-desktop" / "TYPESAFE_API_KEY",
]
DOTENV_CANDIDATES = [
    HOME / "jevii" / ".env",
    HOME / ".config" / "watch" / ".env",
]
PROVIDER_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY", "GROQ_API_KEY")
PROVIDER_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai": "XAI_API_KEY",
}
JEVII_ENV = HOME / "jevii" / ".env"
_loaded = False
_sources: dict[str, str] = {}


def _read_secret_file(path: Path) -> str | None:
    try:
        if path.is_file() and path.stat().st_size > 0:
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return None


def _parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key not in PROVIDER_KEYS:
            continue
        val = val.strip().strip('"').strip("'")
        if val:
            out[key] = val
    return out


def ensure_keys_loaded(*, force: bool = False) -> None:
    """Prefer ~/jevii/.env, then ~/.config/watch/.env, then process env."""
    global _loaded
    if _loaded and not force:
        return
    _sources.clear()
    file_vals: dict[str, str] = {}
    file_src: dict[str, str] = {}
    for path in DOTENV_CANDIDATES:  # jevii first in list — apply last so it wins
        parsed = _parse_dotenv(path)
        for k, v in parsed.items():
            file_vals[k] = v
            file_src[k] = str(path)
    # jevii path is first in candidates — re-apply to win
    desk = _parse_dotenv(HOME / "jevii" / ".env")
    for k, v in desk.items():
        file_vals[k] = v
        file_src[k] = str(HOME / "jevii" / ".env")

    for key in PROVIDER_KEYS:
        if key in file_vals:
            os.environ[key] = file_vals[key]
            _sources[key] = file_src[key]
        else:
            # Do not inherit agent/sandbox process env (often invalid for api.openai.com).
            # User must put keys in ~/jevii/.env
            os.environ.pop(key, None)

    if not os.environ.get("TYPESAFE_API_KEY"):
        for p in TYPESAFE_CANDIDATES:
            secret = _read_secret_file(p)
            if secret:
                os.environ["TYPESAFE_API_KEY"] = secret
                _sources["TYPESAFE_API_KEY"] = str(p)
                break
    elif "TYPESAFE_API_KEY" not in _sources:
        _sources["TYPESAFE_API_KEY"] = "process-env"
    _loaded = True


def key_status() -> dict:
    ensure_keys_loaded(force=True)
    typesafe_path = next((str(p) for p in TYPESAFE_CANDIDATES if p.is_file()), None)
    return {
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "xai": bool(os.environ.get("XAI_API_KEY")),
        "groq": bool(os.environ.get("GROQ_API_KEY")),
        "typesafe": bool(os.environ.get("TYPESAFE_API_KEY")),
        "typesafe_path": typesafe_path,
        "sources": {k: ("file" if "env" not in v.lower() or v.endswith(".env") or "API_KEY" in v else v) for k, v in _sources.items()},
        "any_provider": bool(
            os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("XAI_API_KEY")
        ),
    }



def save_typesafe_key(value: str) -> dict:
    """Write TypeSafe key to ~/.jev-ultrafast-mcp/TYPESAFE_API_KEY (chmod 600)."""
    key_value = (value or "").strip()
    if not key_value:
        return {"ok": False, "error": "Key cannot be empty."}
    path = TYPESAFE_CANDIDATES[0]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key_value + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError as exc:
        return {"ok": False, "error": f"Could not write TypeSafe key file: {exc}"}
    os.environ["TYPESAFE_API_KEY"] = key_value
    _sources["TYPESAFE_API_KEY"] = str(path)
    ensure_keys_loaded(force=True)
    return {"ok": True, "provider": "typesafe", "keys": key_status(), "typesafe_path": str(path)}


def get_provider_key(provider: str) -> str | None:
    ensure_keys_loaded(force=True)
    mapping = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "xai": "XAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "typesafe": "TYPESAFE_API_KEY",
    }
    env_name = mapping.get(provider.lower())
    if not env_name:
        return None
    return os.environ.get(env_name) or None


def save_provider_key(provider: str, value: str) -> dict:
    """Write/update a provider key. TypeSafe -> ~/.jev-ultrafast-mcp/TYPESAFE_API_KEY; chat providers -> ~/jevii/.env."""
    prov = (provider or "").strip().lower()
    if prov == "typesafe":
        return save_typesafe_key(value)
    env_name = PROVIDER_ENV.get(prov)
    if not env_name:
        return {"ok": False, "error": f"Unknown provider: {provider!r}. Use openai, anthropic, xai, or typesafe."}
    key_value = (value or "").strip()
    if not key_value:
        return {"ok": False, "error": "Key cannot be empty."}

    JEVII_ENV.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if JEVII_ENV.is_file():
        try:
            lines = JEVII_ENV.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return {"ok": False, "error": f"Could not read .env: {exc}"}

    replaced = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        k, _, _ = stripped.partition("=")
        if k.strip() == env_name:
            new_lines.append(f"{env_name}={key_value}")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append(f"{env_name}={key_value}")

    try:
        JEVII_ENV.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        os.chmod(JEVII_ENV, 0o600)
    except OSError as exc:
        return {"ok": False, "error": f"Could not write .env: {exc}"}

    # Apply immediately without logging the secret
    os.environ[env_name] = key_value
    ensure_keys_loaded(force=True)
    return {"ok": True, "provider": prov, "keys": key_status()}


def get_env_value(name: str) -> str | None:
    """Read a single key from ~/jevii/.env without logging values."""
    ensure_keys_loaded(force=True)
    if name in os.environ and os.environ.get(name):
        return os.environ.get(name)
    if not JEVII_ENV.is_file():
        return None
    try:
        for line in JEVII_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == name:
                val = v.strip().strip('"').strip("'")
                return val or None
    except OSError:
        return None
    return None


def save_env_value(name: str, value: str) -> dict:
    """Write/update arbitrary KEY=value in ~/jevii/.env (chmod 600). Never logs value."""
    key = (name or "").strip()
    if not key or not re.match(r"^[A-Z][A-Z0-9_]*$", key):
        return {"ok": False, "error": "Invalid env key name."}
    JEVII_ENV.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if JEVII_ENV.is_file():
        try:
            lines = JEVII_ENV.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return {"ok": False, "error": f"Could not read .env: {exc}"}
    replaced = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        k, _, _ = stripped.partition("=")
        if k.strip() == key:
            if value:
                new_lines.append(f"{key}={value}")
            # empty value => remove line
            replaced = True
        else:
            new_lines.append(line)
    if not replaced and value:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append(f"{key}={value}")
    try:
        JEVII_ENV.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        os.chmod(JEVII_ENV, 0o600)
    except OSError as exc:
        return {"ok": False, "error": f"Could not write .env: {exc}"}
    if value:
        os.environ[key] = value
    else:
        os.environ.pop(key, None)
    return {"ok": True}

