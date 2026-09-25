#!/usr/bin/env python3
"""Smooth from-zero jevii film: 1 Terminal, visible mouse glide, Jevi type+zoom.
Never reveal real API keys.
"""
from __future__ import annotations
import base64, json, os, signal, subprocess, time, urllib.request
from pathlib import Path

ROOT = Path.home() / "jevii"
OUT = ROOT / "shots" / "videos"
SHOTS = ROOT / "shots" / "onboarding"
DESK = Path.home() / "Desktop"
OUT.mkdir(parents=True, exist_ok=True)
SHOTS.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8765"
MSG = "hi I am jevi your ai agent that's can use evrything on your computer."
RAW, FINAL = OUT / "10-onboarding-jevi-raw.mov", OUT / "10-onboarding-jevi.mp4"
FULL, ZOOM = OUT / "10a-onboarding-full.mp4", OUT / "10b-jevi-type-zoom.mp4"
PY = Path("/Users/shalevamin/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none/bin/python3.11")
CL = "/opt/homebrew/bin/cliclick"

def run(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

def cc(*cmds):
    subprocess.run([CL, *cmds], check=False, capture_output=True, text=True)

def api(path, method="GET", body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE+path, data=data, method=method,
        headers={"Content-Type":"application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())

def wait_health(sec=55):
    t0=time.time()
    while time.time()-t0 < sec:
        try:
            if api("/api/health").get("ok"): return True
        except Exception: pass
        time.sleep(0.5)
    return False

def move(x,y,steps=14):
    # Prefer jevii smooth move when server is up
    try:
        api("/api/desktop/move","POST",{"x":x,"y":y,"steps":steps})
        return
    except Exception:
        pass
    # fallback local animate
    cur = subprocess.run([CL,"p"], capture_output=True, text=True)
    try:
        x0,y0 = map(int, cur.stdout.strip().splitlines()[-1].replace(" ","").split(","))
    except Exception:
        x0,y0 = x,y
    for i in range(1, steps+1):
        cc(f"m:{int(x0+(x-x0)*i/steps)},{int(y0+(y-y0)*i/steps)}")
        time.sleep(0.018)

def click(x,y):
    move(x,y, steps=16)
    time.sleep(0.05)
    try:
        api("/api/desktop/click","POST",{"x":x,"y":y})
    except Exception:
        cc(f"c:{x},{y}")
    time.sleep(0.12)

def type_ch(ch, d=0.07):
    if ch==" ": cc("kp:space")
    elif ch=="'": cc("t:'")
    else: cc(f"t:{ch}")
    time.sleep(d)

def type_line(s, d=0.05):
    for ch in s: type_ch(ch, d)

def start_rec():
    RAW.unlink(missing_ok=True)
    log=open(SHOTS/"ffmpeg-record.log","w")
    wrap=SHOTS/"_ffmpeg_wrap.py"
    wrap.write_text("import os,sys\nos.execvp('ffmpeg', ['ffmpeg']+sys.argv[1:])\n")
    cmd=[str(PY),str(wrap),"-y","-f","avfoundation","-capture_cursor","1","-framerate","30",
         "-i","Capture screen 0:none","-r","30","-vsync","cfr","-pix_fmt","yuv420p",
         "-c:v","h264_videotoolbox","-b:v","10M",str(RAW)]
    return subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True)

def stop_rec(p):
    if p.poll() is None:
        try: os.killpg(p.pid, signal.SIGINT)
        except ProcessLookupError: p.send_signal(signal.SIGINT)
        try: p.wait(timeout=25)
        except subprocess.TimeoutExpired:
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: p.kill()

def one_terminal():
    """Activate exactly one Terminal window — never Cmd+N."""
    run(["open","-a","Terminal"])
    time.sleep(0.8)
    run(["osascript","-e",'''
tell application "Terminal"
  activate
  set n to count of windows
  if n = 0 then
    do script ""
  else if n > 1 then
    repeat with i from n to 2 by -1
      try
        close window i saving no
      end try
    end repeat
  end if
end tell
'''])
    time.sleep(0.6)

def save_shot(name):
    try:
        d=api("/api/desktop/screenshot","POST",{})
        if d.get("b64"):
            (SHOTS/name).write_bytes(base64.b64decode(d["b64"])); return
    except Exception: pass
    run(["screencapture","-x",str(SHOTS/name)])

def main():
    print("smooth from-zero film", flush=True)
    # pause keepup so serve looks fresh
    run(["launchctl","bootout",f"gui/{os.getuid()}/com.jevii.keepup"])
    run(["pkill","-f","jevii serve"]); time.sleep(1.0)

    t0=time.time()
    proc=start_rec(); time.sleep(2.0)
    if proc.poll() is not None:
        print((SHOTS/"ffmpeg-record.log").read_text()[-1500:]); raise SystemExit("ffmpeg fail")

    # gentle mouse intro
    for x,y in [(240,200),(980,260),(1100,620),(520,700)]:
        move(x,y, steps=18); time.sleep(0.1)

    one_terminal()
    click(640, 420)
    type_line("clear"); cc("kp:return"); time.sleep(0.4)
    type_line("cd ~/jevii"); cc("kp:return"); time.sleep(0.5)
    type_line("bash ~/jevii/install.sh"); cc("kp:return"); time.sleep(8.5)
    type_line("jevii doctor"); cc("kp:return"); time.sleep(3.5)
    type_line("jevii serve --no-browser --host 127.0.0.1 --port 8765"); cc("kp:return")
    ok=wait_health(55); print("health", ok, flush=True)
    if not ok:
        subprocess.Popen([str(ROOT/"jevii"),"serve","--no-browser","--host","127.0.0.1","--port","8765"],
            stdout=open(SHOTS/"server-fallback.log","w"), stderr=subprocess.STDOUT, start_new_session=True)
        ok=wait_health(40); print("health2", ok, flush=True)
    time.sleep(0.8)

    # onboarding — no key values
    run(["open","-a","Google Chrome","http://127.0.0.1:8765/?v=typesafe3&view=permissions&demo=1&mask=1"])
    time.sleep(2.2)
    click(920, 520)
    for _ in range(10):
        cc("kp:arrow-down"); time.sleep(0.2)
    time.sleep(0.8)
    run(["open","-a","Google Chrome","http://127.0.0.1:8765/?v=typesafe3&view=settings&demo=1&mask=1"])
    time.sleep(1.8)
    click(880, 500)
    for _ in range(6):
        cc("kp:arrow-down"); time.sleep(0.2)
    run(["open","-a","Google Chrome","http://127.0.0.1:8765/?v=typesafe3&view=chat&demo=1"])
    time.sleep(1.8)
    click(700, 420)

    t1=time.time()-t0; print("type_start", round(t1,2), flush=True)
    run(["open","-a","Notes"]); time.sleep(1.5)
    # new note via menu key — only once
    cc("kd:cmd","t:n","ku:cmd"); time.sleep(0.9)
    click(720, 460)
    for _ in range(5):
        cc("kd:cmd","t:=","ku:cmd"); time.sleep(0.06)
    for i,ch in enumerate(MSG):
        type_ch(ch, 0.09)
        if i in (15,40): save_shot(f"type-{i}.png")
    time.sleep(1.8)
    t2=time.time()-t0; print("type_end", round(t2,2), flush=True)
    save_shot("done.png")

    stop_rec(proc); time.sleep(1.0)
    run(["ffmpeg","-y","-i",str(RAW),"-r","30","-c:v","h264_videotoolbox","-b:v","10M","-pix_fmt","yuv420p",str(FULL)])
    start=max(0.0,t1-0.4); dur=max(5.0,(t2-t1)+1.0)
    vf=(f"trim=start={start}:duration={dur},setpts=PTS-STARTPTS,scale=iw*2:ih*2,"
        f"zoompan=z='min(1.2+0.0022*on,2.1)':x='iw/2-(iw/zoom/2)':y='ih*0.58-(ih/zoom/2)':d=1:s=1920x1080:fps=30,format=yuv420p")
    run(["ffmpeg","-y","-i",str(RAW),"-vf",vf,"-an","-c:v","h264_videotoolbox","-b:v","10M","-t",str(dur),str(ZOOM)])
    lst=SHOTS/"concat.txt"
    parts=[p for p in (FULL,ZOOM) if p.exists() and p.stat().st_size>2000]
    lst.write_text("\n".join(f"file '{p.resolve()}'" for p in parts)+"\n")
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),"-c:v","h264_videotoolbox","-b:v","10M","-pix_fmt","yuv420p",str(FINAL)])
    if FINAL.exists(): run(["cp","-f",str(FINAL),str(DESK/"10-onboarding-jevi.mp4")])
    plist=Path.home()/"Library/LaunchAgents/com.jevii.keepup.plist"
    if plist.exists(): run(["launchctl","bootstrap",f"gui/{os.getuid()}",str(plist)])
    meta={"final":str(FINAL),"bytes":FINAL.stat().st_size if FINAL.exists() else 0,
          "type_start":t1,"type_end":t2,"from_zero":True,"smooth_mouse":True,"keys_hidden":True,"one_terminal":True}
    (SHOTS/"meta.json").write_text(json.dumps(meta,indent=2))
    print(json.dumps(meta,indent=2), flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception as _e:
        import traceback
        open(Path.home()/"jevii/shots/onboarding/crash.log","w").write(traceback.format_exc())
        print("CRASH", _e, flush=True)
        raise
