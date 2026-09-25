# CLI reference

## Install

```bash
bash install.sh
```

## Core

```bash
jevii doctor
jevii start          # alias: jevii serve
jevii url
jevii open-settings
jevii open-settings --all
```

## Start / serve flags

```bash
jevii start --host 127.0.0.1 --port 8765
jevii start --no-browser
jevii start --no-telegram
```

When `TELEGRAM_BOT_TOKEN` is configured locally, Telegram starts with the Gateway unless `--no-telegram` is set.

## Environment (names only — never commit values)

| Variable | Purpose |
| --- | --- |
| `JEVII_ROOT` | Install / data root (default `~/jevii`) |
| `JEVII_HOST` / `JEVII_PORT` | Bind defaults |
| `TELEGRAM_BOT_TOKEN` | Telegram channel |
| `TELEGRAM_ALLOWED_CHAT_IDS` | Optional allowlist |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `XAI_API_KEY` | Provider API keys |
| TypeSafe file | `~/.jev-ultrafast-mcp/TYPESAFE_API_KEY` |

Short alias: `jevi`. Launcher: `Jevii.command`.
