"""Desktop control via macos-computer-use-kit + cliclick/osascript/pbcopy fallbacks."""
from __future__ import annotations

import base64
import ctypes
import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("jevii.desktop")

ROOT = Path.home() / "jevii"
JEV = Path.home() / ".jev-desktop"
CLICLICK = Path("/opt/homebrew/bin/cliclick")
if not CLICLICK.exists():
    CLICLICK = Path("/usr/local/bin/cliclick")


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def force_abc_keyboard() -> dict[str, Any]:
    """Select the ABC (Latin) keyboard layout so Latin typing is never via Hebrew IME."""
    try:
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        c_void_p = ctypes.c_void_p
        c_bool = ctypes.c_bool
        c_char_p = ctypes.c_char_p
        c_int32 = ctypes.c_int32
        c_long = ctypes.c_long
        c_uint32 = ctypes.c_uint32

        cf.CFStringCreateWithCString.restype = c_void_p
        cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_uint32]
        cf.CFArrayGetCount.restype = c_long
        cf.CFArrayGetCount.argtypes = [c_void_p]
        cf.CFArrayGetValueAtIndex.restype = c_void_p
        cf.CFArrayGetValueAtIndex.argtypes = [c_void_p, c_long]
        cf.CFRelease.argtypes = [c_void_p]
        cf.CFStringGetCString.restype = c_bool
        cf.CFStringGetCString.argtypes = [c_void_p, c_char_p, c_long, c_uint32]

        kCFStringEncodingUTF8 = 0x08000100
        carbon.TISCreateInputSourceList.restype = c_void_p
        carbon.TISCreateInputSourceList.argtypes = [c_void_p, c_bool]
        carbon.TISGetInputSourceProperty.restype = c_void_p
        carbon.TISGetInputSourceProperty.argtypes = [c_void_p, c_void_p]
        carbon.TISSelectInputSource.restype = c_int32
        carbon.TISSelectInputSource.argtypes = [c_void_p]
        prop_id = c_void_p.in_dll(carbon, "kTISPropertyInputSourceID")

        def cf_to_py(sref: int | None) -> str | None:
            if not sref:
                return None
            buf = ctypes.create_string_buffer(512)
            if cf.CFStringGetCString(sref, buf, 512, kCFStringEncodingUTF8):
                return buf.value.decode()
            return None

        lst = carbon.TISCreateInputSourceList(None, False)
        n = cf.CFArrayGetCount(lst)
        chosen = None
        chosen_id = None
        for i in range(n):
            src = cf.CFArrayGetValueAtIndex(lst, i)
            sid = cf_to_py(carbon.TISGetInputSourceProperty(src, prop_id))
            if not sid:
                continue
            if sid == "com.apple.keylayout.ABC" or sid.endswith(".ABC"):
                chosen, chosen_id = src, sid
                break
            if chosen is None and ("ABC" in sid or sid.endswith(".US")):
                chosen, chosen_id = src, sid
        if chosen is None:
            return {"ok": False, "error": "ABC input source not found"}
        rc = carbon.TISSelectInputSource(chosen)
        return {"ok": rc == 0, "source": chosen_id, "rc": rc}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _cliclick(*cmds: str) -> dict[str, Any]:
    exe = str(CLICLICK) if CLICLICK.exists() else (_which("cliclick") or "")
    if not exe:
        return {"ok": False, "error": "cliclick not found"}
    try:
        proc = subprocess.run([exe, *cmds], capture_output=True, text=True, timeout=30)
        return {
            "ok": proc.returncode == 0,
            "via": "cliclick",
            "stdout": (proc.stdout or "")[-2000:],
            "stderr": (proc.stderr or "")[-1000:],
            "rc": proc.returncode,
            "cmds": list(cmds),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "via": "cliclick"}


def _pbcopy(text: str) -> bool:
    try:
        proc = subprocess.run(["pbcopy"], input=text.encode("utf-8"), capture_output=True, timeout=10)
        return proc.returncode == 0
    except Exception:
        return False


def _osascript_keystroke_paste() -> dict[str, Any]:
    script = 'tell application "System Events" to keystroke "v" using command down'
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
        return {"ok": proc.returncode == 0, "via": "osascript-paste", "stderr": (proc.stderr or "")[-500:]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _osascript_key(key: str) -> dict[str, Any]:
    """Map common key names to osascript key codes / keystrokes."""
    aliases = {
        "return": 36,
        "enter": 76,
        "tab": 48,
        "escape": 53,
        "esc": 53,
        "delete": 51,
        "backspace": 51,
        "space": 49,
        "up": 126,
        "down": 125,
        "left": 123,
        "right": 124,
    }
    k = (key or "").strip().lower()
    # chords like cmd+v / command+c
    if "+" in k or " " in k:
        parts = re.split(r"[+\s]+", k)
        parts = [p for p in parts if p]
        mods = []
        main = None
        for p in parts:
            if p in ("cmd", "command", "meta"):
                mods.append("command down")
            elif p in ("alt", "option", "opt"):
                mods.append("option down")
            elif p in ("ctrl", "control"):
                mods.append("control down")
            elif p == "shift":
                mods.append("shift down")
            else:
                main = p
        if main is None:
            return {"ok": False, "error": f"bad chord: {key}"}
        if main in aliases:
            using = f" using {{{', '.join(mods)}}}" if mods else ""
            script = f'tell application "System Events" to key code {aliases[main]}{using}'
        else:
            using = f" using {{{', '.join(mods)}}}" if mods else ""
            safe = main.replace("\\", "\\\\").replace('"', '\\"')
            script = f'tell application "System Events" to keystroke "{safe}"{using}'
    elif k in aliases:
        script = f'tell application "System Events" to key code {aliases[k]}'
    else:
        safe = k.replace("\\", "\\\\").replace('"', '\\"')
        script = f'tell application "System Events" to keystroke "{safe}"'
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
        return {
            "ok": proc.returncode == 0,
            "via": "osascript-key",
            "stderr": (proc.stderr or "")[-500:],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def screenshot_b64(*, max_width: int = 1280) -> dict[str, Any]:
    """Capture primary display; return base64 PNG + size hints."""
    try:
        from macos_computer_use import shot

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "shot.png"
            result = None
            for kwargs in (
                {"path": str(out)},
                {"output": str(out)},
                {},
            ):
                try:
                    result = shot.capture(**kwargs) if kwargs else shot.capture()
                    break
                except TypeError:
                    continue
                except Exception as exc:
                    return {"ok": False, "error": f"shot.capture: {exc}"}
            data = None
            if isinstance(result, dict):
                path = result.get("path") or result.get("file") or (str(out) if out.exists() else None)
                if path and Path(path).exists():
                    data = Path(path).read_bytes()
                elif result.get("png") or result.get("bytes"):
                    raw = result.get("png") or result.get("bytes")
                    data = raw if isinstance(raw, (bytes, bytearray)) else base64.b64decode(raw)
            elif out.exists():
                data = out.read_bytes()
            if not data:
                out2 = Path(td) / "fallback.png"
                subprocess.run(["screencapture", "-x", "-C", str(out2)], check=False)
                if out2.exists():
                    data = out2.read_bytes()
            if not data:
                return {"ok": False, "error": "screenshot failed"}
            return {
                "ok": True,
                "mime": "image/png",
                "b64": base64.b64encode(data).decode("ascii"),
                "bytes": len(data),
            }
    except Exception as exc:
        try:
            with tempfile.TemporaryDirectory() as td:
                out = Path(td) / "shot.png"
                r = subprocess.run(["screencapture", "-x", "-C", str(out)], capture_output=True)
                if out.exists() and out.stat().st_size > 0:
                    data = out.read_bytes()
                    return {
                        "ok": True,
                        "mime": "image/png",
                        "b64": base64.b64encode(data).decode("ascii"),
                        "bytes": len(data),
                        "via": "screencapture",
                    }
                return {"ok": False, "error": f"{exc}; screencapture rc={r.returncode}"}
        except Exception as exc2:
            return {"ok": False, "error": f"{exc}; {exc2}"}



def _cursor_pos() -> tuple[int, int] | None:
    r = _cliclick("p")
    if not r.get("ok"):
        return None
    raw = (r.get("stdout") or "").strip().splitlines()
    if not raw:
        return None
    try:
        a, b = raw[-1].replace(" ", "").split(",", 1)
        return int(a), int(b)
    except Exception:
        return None


def move_xy(x: int, y: int, *, steps: int = 14, step_delay: float = 0.018) -> dict[str, Any]:
    """Animate the cursor to (x,y) so viewers see real mouse movement."""
    import time as _time
    x, y = int(x), int(y)
    steps = max(3, min(int(steps), 40))
    cur = _cursor_pos() or (x, y)
    x0, y0 = cur
    for i in range(1, steps + 1):
        xi = int(x0 + (x - x0) * i / steps)
        yi = int(y0 + (y - y0) * i / steps)
        r = _cliclick(f"m:{xi},{yi}")
        if not r.get("ok"):
            return {"ok": False, "error": "move failed", "step": i, "cliclick": r}
        _time.sleep(step_delay)
    return {"ok": True, "via": "cliclick-move", "x": x, "y": y, "steps": steps}


def click_xy(x: int, y: int, *, button: str = "left") -> dict[str, Any]:
    # Always glide the cursor first so control looks human / filmable.
    move_xy(int(x), int(y))
    # Prefer kit when import works; fallback to cliclick / osascript.
    try:
        from macos_computer_use import input_events as mcu_input

        for call in (
            lambda: mcu_input.do_click(x=int(x), y=int(y), button=button),
            lambda: mcu_input.do_click(int(x), int(y)),
        ):
            try:
                result = call()
                return {
                    "ok": True,
                    "via": "macos_computer_use.input_events",
                    "result": result if isinstance(result, dict) else {"raw": str(result)},
                }
            except TypeError:
                continue
            except Exception:
                break
    except Exception:
        pass

    try:
        from macos_computer_use import input as mcu_input  # type: ignore

        for call in (
            lambda: mcu_input.click(x=x, y=y, button=button),
            lambda: mcu_input.click(int(x), int(y)),
        ):
            try:
                result = call()
                return {
                    "ok": True,
                    "via": "macos_computer_use.input",
                    "result": result if isinstance(result, dict) else {"raw": str(result)},
                }
            except TypeError:
                continue
    except Exception:
        pass

    btn = (button or "left").lower()
    cmd = "rc" if btn in ("right", "r") else "c"
    fb = _cliclick(f"{cmd}:{int(x)},{int(y)}")
    if fb.get("ok"):
        return fb

    script = (
        f'tell application "System Events" to click at {{{int(x)}, {int(y)}}}'
        if btn == "left"
        else f'tell application "System Events" to right click at {{{int(x)}, {int(y)}}}'
    )
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
        return {
            "ok": proc.returncode == 0,
            "via": "osascript-click",
            "stderr": (proc.stderr or "")[-500:],
            "cliclick": fb,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "cliclick": fb}


def type_text(text: str) -> dict[str, Any]:
    """Prefer ABC + clipboard paste for ASCII; never rely on Hebrew IME for Latin."""
    force = force_abc_keyboard()

    # Try kit paste first (still after forcing ABC).
    try:
        from macos_computer_use import paste as mcu_paste

        try:
            result = mcu_paste.run  # noqa: B018 — probe
        except Exception:
            result = None
        # Public helpers: write_text + post_paste if available
        try:
            if hasattr(mcu_paste, "write_text") and hasattr(mcu_paste, "post_paste"):
                prev_ok = mcu_paste.write_text(text)
                mcu_paste.post_paste(None, "global")
                return {"ok": bool(prev_ok), "via": "macos_computer_use.paste", "abc": force}
        except Exception:
            pass
        try:
            result = mcu_paste.paste(text)  # type: ignore[attr-defined]
            return {
                "ok": True,
                "via": "macos_computer_use.paste.paste",
                "result": result if isinstance(result, dict) else {"raw": str(result)},
                "abc": force,
            }
        except Exception:
            pass
    except Exception:
        pass

    # Prefer pbcopy + Cmd+V (ASCII-safe).
    if _pbcopy(text):
        # cliclick: hold cmd, type v, release — or osascript
        ck = _cliclick("kd:cmd", "t:v", "ku:cmd")
        if ck.get("ok"):
            return {"ok": True, "via": "pbcopy+cliclick", "abc": force}
        osa = _osascript_keystroke_paste()
        if osa.get("ok"):
            return {"ok": True, "via": "pbcopy+osascript", "abc": force, "cliclick": ck}
        return {"ok": False, "error": "paste failed after pbcopy", "abc": force, "cliclick": ck, "osascript": osa}

    # Last resort: cliclick type (after ABC)
    ck = _cliclick(f"t:{text}")
    if ck.get("ok"):
        return {**ck, "abc": force}
    return {"ok": False, "error": "type_text failed", "abc": force, "cliclick": ck}


def key_press(key: str) -> dict[str, Any]:
    force_abc_keyboard()
    try:
        from macos_computer_use import input_events as mcu_input

        for call in (
            lambda: mcu_input.do_key(key),
            lambda: mcu_input.do_key(key=key),
        ):
            try:
                result = call()
                return {
                    "ok": True,
                    "via": "macos_computer_use.input_events",
                    "result": result if isinstance(result, dict) else {"raw": str(result)},
                }
            except TypeError:
                continue
            except Exception:
                break
    except Exception:
        pass

    try:
        from macos_computer_use import input as mcu_input  # type: ignore

        for call in (
            lambda: mcu_input.key(key),
            lambda: mcu_input.hotkey(key),
            lambda: mcu_input.press(key),
        ):
            try:
                result = call()
                return {
                    "ok": True,
                    "via": "macos_computer_use.input",
                    "result": result if isinstance(result, dict) else {"raw": str(result)},
                }
            except (TypeError, AttributeError):
                continue
    except Exception:
        pass

    k = (key or "").strip()
    kl = k.lower()
    # cliclick kp: supports return, tab, space, escape, delete, ...
    cliclick_keys = {
        "return": "return",
        "enter": "return",
        "tab": "tab",
        "escape": "escape",
        "esc": "escape",
        "delete": "delete",
        "backspace": "delete",
        "space": "space",
        "up": "arrow-up",
        "down": "arrow-down",
        "left": "arrow-left",
        "right": "arrow-right",
    }
    if "+" in kl or kl.startswith("cmd") or kl.startswith("command"):
        # Use osascript for chords
        osa = _osascript_key(k)
        if osa.get("ok"):
            return osa
    if kl in cliclick_keys:
        ck = _cliclick(f"kp:{cliclick_keys[kl]}")
        if ck.get("ok"):
            return ck
    elif len(k) == 1:
        ck = _cliclick(f"t:{k}")
        if ck.get("ok"):
            return ck
    else:
        ck = _cliclick(f"kp:{kl}")
        if ck.get("ok"):
            return ck

    osa = _osascript_key(k)
    if osa.get("ok"):
        return osa
    return {"ok": False, "error": f"key_press failed for {key!r}", "cliclick": ck if "ck" in dir() else None, "osascript": osa}


def run_goal(goal: str, *, app: str | None = None, dry_run: bool = True, max_steps: int = 5) -> dict[str, Any]:
    """Wrap jev-desktop CLI for vision/AX goal loops."""
    cli = Path.home() / ".local" / "bin" / "jev-desktop"
    if not cli.exists():
        cli = JEV / "jev-desktop"
    if not cli.exists():
        return {"ok": False, "error": "jev-desktop not found"}
    cmd = [str(cli), "goal", goal, "--max-steps", str(max_steps)]
    if dry_run:
        cmd.append("--dry-run")
    if app:
        cmd.extend(["--app", app, "--launch"])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-2000:],
            "dry_run": dry_run,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _ax_calculator_read() -> dict[str, Any]:
    """Read Calculator display via macos-cu AX find (Edit field / Last Expression)."""
    try:
        proc = subprocess.run(
            [
                str(Path.home() / "jevii" / "venv" / "bin" / "python"),
                "-m",
                "macos_computer_use",
                "ax",
                "find",
                "--app",
                "Calculator",
                "--role",
                "AXStaticText",
                "--max",
                "20",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        import json

        data = json.loads(proc.stdout or "{}")
        result_val = None
        expr_val = None
        for el in data.get("elements") or []:
            desc = (el.get("desc") or "").lower()
            val = el.get("value")
            if desc == "edit field" and val is not None:
                result_val = str(val).strip()
            if desc == "last expression" and val is not None:
                expr_val = str(val).strip()
        return {
            "ok": result_val is not None,
            "result": result_val,
            "expression": expr_val,
            "raw_count": data.get("count"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _ax_calculator_press(title: str) -> dict[str, Any]:
    """Click a Calculator button whose AX title/desc equals `title` exactly."""
    try:
        import json

        proc = subprocess.run(
            [
                str(Path.home() / "jevii" / "venv" / "bin" / "python"),
                "-m",
                "macos_computer_use",
                "ax",
                "find",
                "--app",
                "Calculator",
                "--role",
                "AXButton",
                "--title",
                title,
                "--max",
                "30",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        data = json.loads(proc.stdout or "{}")
        els = data.get("elements") or []
        exact = []
        for el in els:
            t = (el.get("title") or el.get("desc") or "").strip()
            if t == title:
                exact.append(el)
        el = exact[0] if exact else None
        if el is None:
            # Also try checkboxes (e.g. Secondary Functions) — skip; require exact.
            return {"ok": False, "error": f"exact button {title!r} not found", "candidates": [
                (e.get("title") or e.get("desc")) for e in els[:8]
            ]}
        center = el.get("center_screen") or []
        if len(center) >= 2:
            return click_xy(int(center[0]), int(center[1]))
        ref = el.get("ref")
        if ref:
            p2 = subprocess.run(
                [
                    str(Path.home() / "jevii" / "venv" / "bin" / "python"),
                    "-m",
                    "macos_computer_use",
                    "ax",
                    "press",
                    "--app",
                    "Calculator",
                    "--ref",
                    str(ref),
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            return {"ok": p2.returncode == 0, "via": "ax-press", "stderr": (p2.stderr or "")[-500:]}
        return {"ok": False, "error": "no center/ref"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def calculator_compute(expression: str = "1+1") -> dict[str, Any]:
    """Reliable Calculator path: open app, clear, type expression=, read AX/OCR result."""
    steps: list[dict[str, Any]] = []
    force_abc_keyboard()
    launched = subprocess.run(["open", "-a", "Calculator"], capture_output=True, text=True)
    steps.append({"open": launched.returncode == 0})
    time.sleep(0.8)
    try:
        from macos_computer_use import apps

        apps.activate("Calculator", None)
    except Exception as exc:
        steps.append({"activate_error": str(exc)})
        subprocess.run(
            ["osascript", "-e", 'tell application "Calculator" to activate'],
            capture_output=True,
        )
    time.sleep(0.35)

    # Clear
    cleared = _ax_calculator_press("All Clear")
    steps.append({"clear": cleared})
    if not cleared.get("ok"):
        steps.append({"clear_key": key_press("escape")})
    time.sleep(0.2)

    expr = re.sub(r"\s+", "", expression or "1+1")
    if expr.endswith("="):
        expr = expr[:-1]

    # Prefer AX button presses for simple 1+1 (true mouse path).
    if expr == "1+1":
        for title in ("1", "Add", "1", "Equals"):
            steps.append({f"btn_{title}": _ax_calculator_press(title)})
            time.sleep(0.12)
    else:
        # Type via cliclick (not clipboard paste — Calculator prefers key events).
        ck = _cliclick(f"t:{expr}")
        steps.append({"type_cliclick": ck})
        if not ck.get("ok"):
            for ch in expr:
                steps.append({f"key_{ch}": _osascript_key(ch)})
                time.sleep(0.05)
        time.sleep(0.15)
        eq = key_press("return")
        if not eq.get("ok"):
            eq = _ax_calculator_press("Equals")
        steps.append({"equals": eq})

    time.sleep(0.35)

    read = _ax_calculator_read()
    steps.append({"ax_read": read})
    if read.get("ok") and read.get("result") is not None:
        return {
            "ok": True,
            "result": str(read["result"]).strip(),
            "expression": read.get("expression") or expr,
            "via": "calculator-ax",
            "steps": steps,
        }

    # OCR fallback on Calculator window
    try:
        r = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to tell process "Calculator" to get {position, size} of window 1',
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        nums = [int(x) for x in re.findall(r"-?\d+", r.stdout or "")]
        ocr_text = ""
        if len(nums) >= 4:
            x, y, w, h = nums[:4]
            with tempfile.TemporaryDirectory() as td:
                out = Path(td) / "calc.png"
                subprocess.run(["screencapture", "-x", "-R", f"{x},{y},{w},{h}", str(out)], check=False)
                tess = _which("tesseract")
                if tess and out.exists():
                    ocr = subprocess.run(
                        [tess, str(out), "stdout", "--psm", "6"],
                        capture_output=True,
                        timeout=30,
                    )
                    ocr_text = (ocr.stdout or b"").decode("utf-8", errors="replace")
        steps.append({"ocr": ocr_text[:500]})
        # Heuristic: last standalone number
        nums2 = re.findall(r"(?m)^\s*(-?\d+(?:\.\d+)?)\s*$", ocr_text)
        if not nums2:
            nums2 = re.findall(r"-?\d+(?:\.\d+)?", ocr_text)
        if nums2:
            return {
                "ok": True,
                "result": nums2[-1],
                "expression": expr,
                "via": "calculator-ocr",
                "steps": steps,
            }
    except Exception as exc:
        steps.append({"ocr_error": str(exc)})

    return {"ok": False, "error": "could not read Calculator result", "steps": steps}
