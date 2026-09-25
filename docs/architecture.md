# Architecture

## Gateway

`jevii start` runs the local Gateway (HTTP API + Control UI). It owns sessions, tool routes, and channel connections.

## Control plane pieces

| Piece | Role |
| --- | --- |
| Control UI (`app/`) | Chat, connect models, permissions, TypeSafe panel |
| CLI (`jevii`) | doctor / start / settings |
| Channels | e.g. Telegram long-poll — auto-started with Gateway when configured |
| Desktop tools | Vision-first mouse/keyboard on macOS |
| Browser tools | Chrome CDP |
| TypeSafe | Decision model for goal loops (browser + desktop) |

## Brain vs hands

**TypeSafe** decides the next step from structured state (element tables / AX). **Local executors** click, type, and drive CDP. Same principle for browser and desktop goals.
