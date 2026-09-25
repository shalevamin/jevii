# jevii STATUS — 0.2.1 — Fri 2026-09-25 ~04:10 IDT

Local MVP (no cloud Tauri). English product UI. Workspace soul at `~/jevii/workspace/`.

## 0.2.1 fixes (this pass)

| Area | Fix |
| --- | --- |
| Claude OAuth / Claude Code import | `is_connected()` / `status()` require **usable** creds via `get_valid_credentials()`. Refresh failure → `needs_reauth=true` + clear error (file kept). Auto re-import from `~/.claude/.credentials.json` when store expired and Claude Code is newer. `_claude_oauth_chat` surfaces refresh error text (not only “not connected”). Never logs token values. |
| Chrome CDP (144+) | `browser.py` probes `/json/version`, `/json/list`, `/json`, `/json/new`. Port open + any working JSON endpoint = ok. Chrome 144+ quirk documented: `/json/*` may 404 while port listens. `ensure_cdp` launches dedicated Chrome with `~/jevii/.chrome-cdp` (does not touch main profile). |
| Agent system prompt | `workspace_prompt.BASE_OPERATOR_LINE` + `SOUL.md` / UI welcome: mouse + keyboard like a human (vision + AX), open apps, click, type; act autonomously for local UI. Injected for all providers. |

## What works
| Item | Result |
| --- | --- |
| `bash ~/jevii/install.sh` | **OK** (idempotent) |
| `~/.local/bin/jevii` | **OK** |
| UI `http://127.0.0.1:8765` | **OK** after serve |
| Workspace prompt (`SOUL`/`IDENTITY`/…) | **OK** — `server/workspace_prompt.py` |
| Claude Code import path | **OK** modules; usable-creds gate in 0.2.1 |
| Chrome CDP status | **OK** — no hard-fail solely on `/json/version` 404 |
| Desktop screenshot / goal hooks | **OK** (permissions permitting) |
| OAuth Connect UI (ChatGPT / Claude / Grok) | **OK** on disk |
| Telegram / local models routes | **OK** |

## Needs your click / key
| Item | State |
| --- | --- |
| Claude subscription usable token | Store may be expired — reconnect Claude or refresh Claude Code login, then Import |
| API keys | Optional — `~/jevii/.env` (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `XAI_API_KEY`) |
| Chrome dedicated CDP | Main Chrome may hold :9222 with 404 JSON quirk — Settings → Attach/launch CDP uses `~/jevii/.chrome-cdp` |

## How to open
```bash
bash ~/jevii/install.sh
jevii doctor
jevii serve
# or: open ~/jevii/jevii.command
```
URL: **http://127.0.0.1:8765**

## Paths
```
~/jevii/
  STATUS.md / README.md
  .env / .auth/                 ← secrets (chmod 600); never logged
  .chrome-cdp/                  ← dedicated CDP profile (0.2.1)
  workspace/                    ← SOUL IDENTITY USER AGENTS MEMORY TOOLS
  app/  server/  venv/
```

## Verify notes (0.2.1)
- Module import + `get_valid_credentials` with expired jevii store + present Claude Code file (no secrets printed).
- `cdp_status` / `ensure_cdp` do not hard-fail solely on `/json/version` 404.
- Single restart of jevii on `127.0.0.1:8765` after fixes.

## Live verify (2026-09-25 ~04:10 IDT)
- `get_valid_credentials()` with expired store + present Claude Code (same expired tokens): returns `None`; `connected=false`, `needs_reauth=true`, error `Claude session expired…`; no token leakage.
- `cdp_status`: `ok=true` with `chrome144_quirk` despite all `/json/*` 404.
- `ensure_cdp`: `ok=true` (partial/launched path; dedicated `~/jevii/.chrome-cdp`).
- Restart once: `http://127.0.0.1:8765` health **0.2.1** 200; anthropic status + browser status OK.
