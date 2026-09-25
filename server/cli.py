"""jevii CLI: serve | doctor | open-settings | install-hint"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def _root() -> Path:
    return Path(os.environ.get("JEVII_ROOT", Path.home() / "jevii")).resolve()


def cmd_doctor(_: argparse.Namespace) -> int:
    from .doctor import run_doctor

    info = run_doctor(as_json=False)
    return 0 if info.get("ok") else 2


def cmd_open_settings(args: argparse.Namespace) -> int:
    from .doctor import open_all_required, open_settings

    if args.all:
        open_all_required()
        print("Opened Accessibility, Screen Recording, and Full Disk Access panes.")
        return 0
    r = open_settings(args.pane)
    print(r)
    return 0 if r.get("ok") else 1


def cmd_serve(args: argparse.Namespace) -> int:
    host = args.host or os.environ.get("JEVII_HOST", "127.0.0.1")
    port = int(args.port or os.environ.get("JEVII_PORT", "8765"))
    root = _root()
    os.environ["JEVII_ROOT"] = str(root)
    url = f"http://{host}:{port}"

    if args.open_settings:
        from .doctor import open_all_required

        open_all_required()

    if not args.no_browser:
        # delay open slightly so server is up
        def _open() -> None:
            time.sleep(0.8)
            webbrowser.open(url)

        import threading

        threading.Thread(target=_open, daemon=True).start()

    import uvicorn

    print(f"jevii → {url}")
    print(f"UI: {root / 'app'}")
    print("Stop with Ctrl+C")
    from server.main import app as fastapi_app
    uvicorn.run(fastapi_app, host=host, port=port, reload=False)
    return 0


def cmd_url(_: argparse.Namespace) -> int:
    host = os.environ.get("JEVII_HOST", "127.0.0.1")
    port = os.environ.get("JEVII_PORT", "8765")
    print(f"http://{host}:{port}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Ensure package import path
    root = _root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    parser = argparse.ArgumentParser(prog="jevii", description="jevii local MVP")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Start local UI + API server")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", default=None)
    p_serve.add_argument("--no-browser", action="store_true")
    p_serve.add_argument("--open-settings", action="store_true", help="Open TCC panes on start")
    p_serve.set_defaults(func=cmd_serve)

    p_start = sub.add_parser("start", help="Alias for serve; auto-starts Telegram if configured")
    p_start.add_argument("--host", default=None)
    p_start.add_argument("--port", default=None)
    p_start.add_argument("--no-browser", action="store_true")
    p_start.add_argument("--open-settings", action="store_true")
    p_start.add_argument("--no-telegram", action="store_true")
    p_start.set_defaults(func=cmd_serve)
    p_serve.add_argument("--no-telegram", action="store_true")


    p_doc = sub.add_parser("doctor", help="Permission / key / CDP status")
    p_doc.set_defaults(func=cmd_doctor)

    p_set = sub.add_parser("open-settings", help="Open macOS Privacy panes")
    p_set.add_argument(
        "--pane",
        default="accessibility",
        choices=["accessibility", "screen_recording", "full_disk"],
    )
    p_set.add_argument("--all", action="store_true")
    p_set.set_defaults(func=cmd_open_settings)

    p_url = sub.add_parser("url", help="Print local UI URL")
    p_url.set_defaults(func=cmd_url)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
