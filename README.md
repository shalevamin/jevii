# jevii — Jevi the SGI (Super Intelligence)

**Your AI assistant, on your Mac, in your chats.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/platform-macOS-black.svg)](docs/platforms/macos.md)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](requirements.txt)

jevii is an open-source AI agent that runs on **your Mac**. It meets you in a local Control UI and in channels you already use (Telegram first), with a single **Gateway** that owns sessions, tools, and channel connections.

**Yours, with no catch.** State, memory, and credentials live on your hardware. Models (ChatGPT, Claude, Grok, local Ollama/LM Studio) are swappable. By default jevii does not phone home; your prompts go only to the providers and channels you configure.

Website-style docs live in [`docs/`](docs/). This README is the front door.

---

## Install

The installer targets **macOS**. It creates a local venv and puts `jevii` on your PATH.

```bash
git clone https://github.com/shalevamin/jevii.git
cd jevii
bash install.sh
```

Already have a checkout? Re-run `bash install.sh` anytime — it is idempotent.

---

## Quick start

```bash
jevii doctor
jevii start
```

`start` is an alias for `serve`. It starts the local **Gateway** + Control UI at [http://127.0.0.1:8765](http://127.0.0.1:8765).

If `TELEGRAM_BOT_TOKEN` is saved in your local `.env`, the **Telegram channel starts with the Gateway** (no separate “Start bridge” step). Use `--no-telegram` to skip.

Onboarding tips:

1. Grant **Accessibility** and **Screen Recording** when prompted (`jevii open-settings --all`).
2. Connect a model in the Control UI (OAuth and/or API keys) — values stay on disk, never in this repo.
3. Optional: save a TypeSafe key at `~/.jev-ultrafast-mcp/TYPESAFE_API_KEY` for goal-driven browser/desktop decisions.
4. Send a message in the Control UI (or Telegram) to confirm Jevi is alive.

Double-click launcher: `Jevii.command`.

---

## How it fits together

- The **Gateway** is the local control plane for sessions, tools, events, and channel connections (`jevii start`).
- The **Control UI** and **CLI** connect to the Gateway.
- **Channels** bring the assistant to messaging apps (Telegram today; more can plug into the same start path).
- **Desktop + browser tools** act on your Mac: vision-first mouse/keyboard, Chrome CDP, and Accessibility helpers when labels exist.
- **TypeSafe** is the decision engine for goal loops (what to click next). Local tools are the hands. TypeSafe does not move the mouse by itself.

jevii works with hosted and local model providers. Tools and channels extend what Jevi the SGI can do.

---

## Commands

| Command | Purpose |
| --- | --- |
| `bash install.sh` | One-shot local install |
| `jevii doctor` | Permissions, keys present?, CDP, TypeSafe |
| `jevii start` / `jevii serve` | Start Gateway + Control UI (+ Telegram if configured) |
| `jevii start --no-telegram` | Skip Telegram auto-start |
| `jevii url` | Print Control UI URL |
| `jevii open-settings` | Open a macOS Privacy pane |
| `jevii open-settings --all` | Accessibility + Screen Recording + Full Disk |

### Flags

| Flag | Purpose |
| --- | --- |
| `--host` | Bind host (default `127.0.0.1`) |
| `--port` | Port (default `8765`) |
| `--no-browser` | Do not open a browser tab |
| `--no-telegram` | Do not auto-start Telegram |

Short alias: `jevi` (same CLI).

Full reference: [`docs/commands.md`](docs/commands.md).

---

## Security

Treat inbound channel messages as **untrusted input**. Prefer allowlisting Telegram chat IDs.

Tools (desktop control, browser, shell-adjacent actions) run on **your Mac** for the main session. Do not expose the Gateway to the public internet without authentication. Keep secrets in `~/jevii/.env` (chmod `600`) and TypeSafe keys in their local key files — **never commit them**.

This repository is audited to contain **no API keys, tokens, or `.env` files**. Variable *names* appear in docs and loaders; values never do.

Read [`SECURITY.md`](SECURITY.md) before sharing access or binding beyond localhost.

---

## Documentation

| Goal | Start here |
| --- | --- |
| Install and first run | [`docs/install.md`](docs/install.md) |
| All CLI commands | [`docs/commands.md`](docs/commands.md) |
| Architecture (Gateway, brain vs hands) | [`docs/architecture.md`](docs/architecture.md) |
| macOS permissions | [`docs/platforms/macos.md`](docs/platforms/macos.md) |
| Telegram channel | [`docs/channels/telegram.md`](docs/channels/telegram.md) |
| Desktop tools | [`docs/tools/desktop.md`](docs/tools/desktop.md) |
| Browser / CDP | [`docs/tools/browser.md`](docs/tools/browser.md) |
| Security | [`SECURITY.md`](SECURITY.md) |

---

## Development

```bash
git clone https://github.com/shalevamin/jevii.git
cd jevii
bash install.sh
jevii doctor
jevii start --no-browser
```

Python package layout: `server/` (Gateway + tools), `app/` (Control UI), `install.sh` + `jevii` CLI entrypoint.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for contribution workflow.

---

## Community

- Bugs and feature requests: GitHub Issues
- Security reports: [`SECURITY.md`](SECURITY.md)
- AI-assisted PRs welcome

jevii is built for **Jevi the SGI (Super Intelligence)** — a local Mac agent that can actually use the computer.

---

## License

MIT © shalevamin. See [LICENSE](LICENSE).
