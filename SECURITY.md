# Security

## Secrets

- Never commit `.env`, OAuth stores, bot tokens, or API keys.
- Store secrets only on the machine that runs jevii (`~/jevii/.env`, TypeSafe key files).
- Loaders may read key *files*; they must never log or print values.

## Channels

Inbound messages are untrusted. Allowlist Telegram chat IDs when possible.

## Exposure

Default bind is `127.0.0.1`. Do not bind to `0.0.0.0` or share the Gateway without authentication — desktop control APIs can drive the Mac.

## Reports

Report vulnerabilities privately via GitHub Security Advisories on this repository when available, or contact the maintainer.
