# Telegram

## With the Gateway

If `TELEGRAM_BOT_TOKEN` is present in your local env, `jevii start` auto-starts the Telegram bridge.

```bash
jevii start                 # Telegram on (if token saved)
jevii start --no-telegram   # UI/Gateway only
```

## Setup

1. Create a bot with BotFather; copy the token into `~/jevii/.env` (chmod 600).
2. Optional: `TELEGRAM_ALLOWED_CHAT_IDS` allowlist.
3. `jevii start`, then message the bot.

Treat inbound DMs as untrusted; prefer an allowlist.
