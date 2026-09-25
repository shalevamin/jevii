#!/bin/bash
# jevii idempotent installer — safe to run twice
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/venv"
PY="${JEVII_PYTHON:-}"
LOCAL_BIN="$HOME/.local/bin"
OPEN_SETTINGS="${JEVII_OPEN_SETTINGS:-0}"

echo "==> jevii install"
echo "    root: $ROOT"

pick_python() {
  if [ -n "$PY" ] && command -v "$PY" >/dev/null 2>&1; then
    return 0
  fi
  for c in python3.12 python3.11 python3.13 python3.14 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      PY="$(command -v "$c")"
      return 0
    fi
  done
  echo "ERROR: python3 not found" >&2
  exit 1
}

pick_python
echo "    python: $PY ($("$PY" --version 2>&1))"

if [ ! -d "$VENV" ]; then
  echo "==> Creating venv"
  "$PY" -m venv "$VENV"
else
  echo "==> Reusing venv"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip wheel >/dev/null
echo "==> Installing requirements"
pip install -r "$ROOT/requirements.txt"

# Playwright browsers optional — CDP attach often enough; install chromium quietly if possible
if python -c "import playwright" 2>/dev/null; then
  echo "==> Ensuring Playwright Chromium (for CDP connect helpers)"
  python -m playwright install chromium >/dev/null 2>&1 || echo "    (playwright install skipped / partial — CDP attach still works)"
fi

mkdir -p "$LOCAL_BIN"
ln -sfn "$ROOT/jevii" "$LOCAL_BIN/jevii"
chmod +x "$ROOT/jevii" "$ROOT/install.sh"
if [ -f "$ROOT/jevii.command" ]; then
  chmod +x "$ROOT/jevii.command"
fi

# env.sh already present; ensure .env exists as a template without secrets
if [ ! -f "$ROOT/.env" ]; then
  cat > "$ROOT/.env" <<'ENV'
# jevii local secrets — chmod 600; never commit
# OPENAI_API_KEY=
# ANTHROPIC_API_KEY=
# XAI_API_KEY=
ENV
  chmod 600 "$ROOT/.env" || true
  echo "==> Wrote $ROOT/.env template (empty)"
fi

# Seed OPENAI from watch .env if jevii .env has none (presence only)
if ! grep -q '^OPENAI_API_KEY=.' "$ROOT/.env" 2>/dev/null; then
  if [ -f "$HOME/.config/watch/.env" ] && grep -q '^OPENAI_API_KEY=.' "$HOME/.config/watch/.env"; then
    echo "==> OPENAI_API_KEY available via ~/.config/watch/.env (loaded at runtime; not copied)"
  fi
fi

# PATH hint
case ":$PATH:" in
  *":$LOCAL_BIN:"*) ;;
  *)
    echo "==> NOTE: add to PATH: export PATH=\"$LOCAL_BIN:\$PATH\""
    ;;
esac

# shellcheck disable=SC1091
source "$ROOT/env.sh"

echo "==> Running doctor"
set +e
"$LOCAL_BIN/jevii" doctor
DOC_RC=$?
set -e

if [ "$OPEN_SETTINGS" = "1" ] || [ "${1:-}" = "--open-settings" ]; then
  echo "==> Opening Privacy panes"
  "$LOCAL_BIN/jevii" open-settings --all || true
fi

echo ""
echo "Install complete (exit doctor=$DOC_RC)."
echo "Start:   jevii serve"
echo "Or:      open $ROOT/jevii.command"
echo "URL:     http://127.0.0.1:8765"
echo "Doctor:  jevii doctor"
echo "Re-run:  bash $ROOT/install.sh"
exit 0
