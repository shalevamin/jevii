# jevii env — source before running (never commit secrets; never echo key values)
export JEVII_ROOT="${JEVII_ROOT:-$HOME/jevii}"
export JEVII_HOST="${JEVII_HOST:-127.0.0.1}"
export JEVII_PORT="${JEVII_PORT:-8765}"

# Prefer existing TypeSafe key files (chmod 600). Values are never printed.
if [ -z "${TYPESAFE_API_KEY:-}" ]; then
  for _k in \
    "$HOME/.jev-ultrafast-mcp/TYPESAFE_API_KEY" \
    "$HOME/.config/typesafe/api_key" \
    "$HOME/.jev-desktop/TYPESAFE_API_KEY"
  do
    if [ -f "$_k" ]; then
      export TYPESAFE_API_KEY="$(tr -d '[:space:]' < "$_k")"
      break
    fi
  done
  unset _k
fi

# Optional provider keys from local .env only (never echo values)
_load_dotenv() {
  local f="$1"
  [ -f "$f" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|\#*) continue ;;
      OPENAI_API_KEY=*|ANTHROPIC_API_KEY=*|XAI_API_KEY=*|GROQ_API_KEY=*|TELEGRAM_BOT_TOKEN=*|JEVII_TOKEN=*)
        key="${line%%=*}"
        val="${line#*=}"
        val="${val%\"}"; val="${val#\"}"
        val="${val%\'}"; val="${val#\'}"
        if [ -z "${!key:-}" ] && [ -n "$val" ]; then
          export "$key=$val"
        fi
        ;;
    esac
  done < "$f"
}
_load_dotenv "$JEVII_ROOT/.env"
unset -f _load_dotenv

export PATH="$JEVII_ROOT/venv/bin:$HOME/.local/bin:$PATH"
export JEV_DESKTOP_ROOT="${JEV_DESKTOP_ROOT:-$HOME/.jev-desktop}"
