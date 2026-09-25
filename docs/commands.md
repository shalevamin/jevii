# jevii — Jevi the SGI (Super Intelligence)

Local macOS AI agent: vision-first mouse/keyboard, TypeSafe decision engine, Chrome CDP, multi-provider chat, Telegram channel.

**English UI only.** Inspired by OpenClaw’s install/gateway shape — not a fork.

## Quick start

```bash
bash install.sh
jevii doctor
jevii start
```

Open **http://127.0.0.1:8765**

`jevii start` (alias of `serve`) starts the local gateway + Control UI. If `TELEGRAM_BOT_TOKEN` is saved, the Telegram bridge starts automatically with the gateway.

## Commands

| Command | Purpose |
| --- | --- |
| `bash install.sh` | One-shot local install (venv, CLI on PATH) |
| `jevii doctor` | Permissions, keys, CDP, TypeSafe |
| `jevii serve` | Start gateway + UI |
| `jevii start` | Same as `serve` (Telegram auto-starts if token configured) |
| `jevii start --no-telegram` | Skip Telegram auto-start |
| `jevii url` | Print UI URL |
| `jevii open-settings` | Open a macOS Privacy pane |
| `jevii open-settings --all` | Accessibility + Screen Recording + Full Disk |

### Flags

| Flag | Purpose |
| --- | --- |
| `--host` | Bind host (default `127.0.0.1`) |
| `--port` | Port (default `8765`) |
| `--no-browser` | Do not open the browser |
| `--no-telegram` | Do not auto-start Telegram |

Short alias: `jevi` (same CLI). Double-click launcher: `Jevii.command`.

## Architecture (brain vs hands)

- **TypeSafe** — decision model for browser/desktop goals (`~/.jev-ultrafast-mcp/TYPESAFE_API_KEY`). Never commit or print the key.
- **Local tools** — mouse/keyboard (vision-first), Chrome CDP, Accessibility helpers.
- **Channels** — Telegram long-poll starts with the gateway when a bot token is configured.

## Security

Do not commit `.env`, OAuth cookies, or API keys. Secrets stay on your Mac.

## License

MIT
