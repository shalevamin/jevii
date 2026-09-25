# Install

## macOS

```bash
git clone https://github.com/shalevamin/jevii.git
cd jevii
bash install.sh
```

Then:

```bash
jevii doctor
jevii start
```

Control UI: http://127.0.0.1:8765

## Permissions

```bash
jevii open-settings --all
```

Grant **Accessibility** and **Screen Recording** to the process that runs jevii (Terminal / your launcher).

## Secrets (local only)

Create `~/jevii/.env` (chmod 600) for optional keys such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `XAI_API_KEY`, `TELEGRAM_BOT_TOKEN`. Never commit this file.

TypeSafe: `~/.jev-ultrafast-mcp/TYPESAFE_API_KEY` (chmod 600).

Next: [Commands](commands.md) · [macOS](platforms/macos.md)
