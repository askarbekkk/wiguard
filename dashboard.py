"""Live web dashboard: WiFi CSI (motion + static fingerprint) and the LD2410C radar.

    python dashboard.py --csi COM5 --radar COM6     # either one can be left out
    then open http://localhost:8000
"""
import argparse
import json
import os
import threading
import time
import wave
import winsound
from collections import deque
from urllib.parse import urlencode
from urllib.request import urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import serial
from numpy.lib.stride_tricks import sliding_window_view

import radar

WINDOW = 60  # seconds shown on the charts
CALIBRATION = 20  # seconds of empty room
csi_points = deque(maxlen=WINDOW * 3)  # (time, motion, fingerprint)
radar_points = deque(maxlen=WINDOW * 12)  # (time, state, moving_cm, moving_energy, still_cm, still_energy)
calib = {"until": 0.0, "threshold": None, "fp_base": None}
events = deque(maxlen=50)  # (time, "entered" | "left")
lock = threading.Lock()

# everything shown on the dashboard is also saved, one file set per run
os.makedirs("data/live", exist_ok=True)
run = time.strftime("%Y%m%d_%H%M%S")
csi_log = open(f"data/live/{run}_csi.csv", "w", buffering=1)
csi_log.write("time,motion,fingerprint\n")
radar_log = open(f"data/live/{run}_radar.csv", "w", buffering=1)
radar_log.write("time,state,moving_cm,moving_energy,still_cm,still_energy\n")
event_log = open(f"data/live/{run}_events.csv", "w", buffering=1)
event_log.write("time,event\n")

LEAVE_AFTER, ENTER_AFTER = 5, 2  # seconds the radar must agree before the room changes state
MAX_CM = 450  # radar targets farther than this are outside the room (--max-cm); without it a person behind the wall showed up at 5.5 m
# alarm: no WiFi motion this long while the radar sees someone in the room -> countdown -> alert.
# A fall is not told apart from walking by motion size (fall peak 0.085, walking 0.08-0.088), so it is one
# "does not get up" timer. 30 s is a demo value; a real home needs minutes (--still) to avoid alarms while resting
STILL_LIMIT, COUNTDOWN = 30, 15
room = {"occupied": None}
alarm = {"state": None, "until": 0.0, "last_move": time.time()}


def tone(name, parts, rate=22050):
    """Write a WAV of (Hz, ms) parts. winsound.Beep is too quiet or silent on many laptops; a WAV follows the volume."""
    path = f"data/live/{name}.wav"
    with wave.open(path, "w") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        for hz, ms in parts:
            t = np.arange(rate * ms // 1000) / rate
            w.writeframes((30000 * np.sin(2 * np.pi * hz * t)).astype("<i2").tobytes())
    return path


SOUNDS = {"ok": tone("ok", [(600, 150), (800, 150)]), "tick": tone("tick", [(880, 200)]),
          "siren": tone("siren", [(1400, 400), (1000, 400)])}


def sound(kind):
    """Audible alarm states, so a person lying on the floor in a test knows what the system decided."""
    play_wav = lambda k: winsound.PlaySound(SOUNDS[k], winsound.SND_FILENAME)

    def play():
        if kind == "ok":
            play_wav("ok")
        while alarm["state"] == kind == "countdown":  # tick every second, can still be cancelled by moving
            play_wav("tick")
            time.sleep(0.8)
        while alarm["state"] == kind == "alert":  # siren until the person moves or leaves
            play_wav("siren")
    threading.Thread(target=play, daemon=True).start()


def telegram(text):
    """Send `text` to everyone who pressed Start in the bot. telegram.json = {"token": ..., "chat_ids": [...]}, not in git."""
    try:
        with open("telegram.json") as f:
            cfg = json.load(f)
    except OSError:
        return

    def send():
        api = f"https://api.telegram.org/bot{cfg['token']}/"
        try:
            ids = cfg.get("chat_ids") or {u["message"]["chat"]["id"] for u in
                                          json.load(urlopen(api + "getUpdates", timeout=40))["result"] if "message" in u}
            for chat in ids:
                urlopen(api + "sendMessage", urlencode({"chat_id": chat, "text": text}).encode(), timeout=40)
        except OSError as e:  # no internet: the siren in the room still works
            print("telegram failed:", e, flush=True)
    threading.Thread(target=send, daemon=True).start()


def log_event(now, event):  # caller holds the lock
    event_log.write(f"{now:.3f},{event}\n")
    events.append((now, event))


def check_alarm(now, motion):  # caller holds the lock
    thr = calib["threshold"]
    if thr is None or now < calib["until"]:
        return
    if motion > thr:
        alarm["last_move"] = now
    if not room["occupied"] or now - alarm["last_move"] < STILL_LIMIT:
        if alarm["state"]:
            if alarm["state"] == "alert":
                telegram(f"✅ WiGuard {time.strftime('%H:%M')} — 해제: 다시 움직임 / OK: the person is moving again")
            log_event(now, "ok: moving again" if room["occupied"] else "ok: left the room")
            alarm["state"] = None
            sound("ok")
        return
    if alarm["state"] is None:
        alarm.update(state="countdown", until=now + COUNTDOWN)
        log_event(now, "countdown: no movement")
        sound("countdown")
    elif alarm["state"] == "countdown" and now >= alarm["until"]:
        alarm["state"] = "alert"
        log_event(now, "ALERT: person not moving")
        sound("alert")
        telegram(f"🚨 WiGuard {time.strftime('%H:%M')} — 경보: 방에 사람이 있는데 {STILL_LIMIT}초 넘게 움직임이 없습니다. "
                 f"확인해 주세요.\nALERT: someone is in the room and has not moved for over {STILL_LIMIT} s. Please check on them.")


def read_csi(port):
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 921600, 1
    s.dtr = s.rts = False  # opening with DTR/RTS asserted can reset the board
    frames, new, samples, ref = deque(maxlen=47), 0, [], None
    with s:
        while True:
            line = s.readline().decode("ascii", "ignore").rstrip()
            if not (line.startswith("CSI_DATA") and line.endswith(']"')):
                continue
            try:
                iq = np.array(json.loads(line[line.index('"[') + 1:-1]), dtype=float)
            except ValueError:
                continue
            if iq.size % 2:  # line cut on the serial port
                continue
            frames.append(np.hypot(iq[0::2], iq[1::2]))
            new += 1
            if new < 23 or len(frames) < frames.maxlen:  # update every ~0.5 s over the last ~1 s
                continue
            new = 0
            n = max(set(map(len, frames)), key=[len(f) for f in frames].count)
            a = np.array([f for f in frames if len(f) == n])
            a = a / a.mean(axis=1, keepdims=True)
            motion = float(np.median(sliding_window_view(a, 9, axis=0), axis=-1).std(axis=0).mean())
            profile = np.median(a, axis=0)
            now = time.time()
            with lock:
                if now < calib["until"]:
                    samples.append((motion, profile))
                elif samples:  # calibration just ended
                    # reference from the first half, empty-room level from the second half: measuring the
                    # level on the same samples as the reference makes it too low and every person looks "on the floor"
                    half = len(samples) // 2
                    ref = np.median([p for _, p in samples[:half]], axis=0)
                    calib["threshold"] = 1.6 * float(np.median([m for m, _ in samples]))
                    calib["fp_base"] = float(np.median([np.abs(p - ref).mean() * 100 for _, p in samples[half:]]))
                    samples = []
                fp = float(np.abs(profile - ref).mean() * 100) if ref is not None and len(ref) == n else None
                csi_points.append((now, motion, fp))
                check_alarm(now, motion)
            csi_log.write(f"{now:.3f},{motion:.5f},{'' if fp is None else f'{fp:.3f}'}\n")


def read_radar(port):
    occupied, since = None, time.time()  # since = when the radar started disagreeing with `occupied`
    for frame in radar.frames(port):
        if frame is None:
            continue
        now = time.time()
        state, moving_cm, _, still_cm, _ = frame
        state = (1 if state & 1 and moving_cm <= MAX_CM else 0) | (2 if state & 2 and still_cm <= MAX_CM else 0)
        present = state != 0
        if present == occupied:
            since = now
        elif now - since >= (ENTER_AFTER if present else LEAVE_AFTER):
            with lock:
                if occupied is not None:  # the first reading only sets the starting state
                    log_event(now, "entered" if present else "left")
                room["occupied"] = present
            occupied, since = present, now
        with lock:
            radar_points.append((now, state, *frame[1:]))
        radar_log.write(f"{now:.3f},{','.join(map(str, frame))}\n")  # raw, before the distance cut


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/data":
            with lock:
                body = json.dumps({"now": time.time(), "csi": list(csi_points), "radar": list(radar_points),
                                   "events": list(events), "calibrating": time.time() < calib["until"],
                                   "threshold": calib["threshold"], "fp_base": calib["fp_base"],
                                   "alarm": {k: alarm.get(k) for k in ("state", "until")}}).encode()
            self.send(body, "application/json")
        else:
            with open("dashboard.html", "rb") as f:
                self.send(f.read(), "text/html; charset=utf-8")

    def do_POST(self):  # /calibrate
        with lock:
            calib["until"] = time.time() + CALIBRATION
        self.send(b"{}", "application/json")

    def send(self, body, kind):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csi")
    p.add_argument("--radar")
    p.add_argument("--max-cm", type=int, default=MAX_CM, help="ignore radar targets farther than this")
    p.add_argument("--still", type=int, default=STILL_LIMIT, help="seconds without movement before the countdown")
    p.add_argument("--countdown", type=int, default=COUNTDOWN, help="seconds of warning ticks before the alert")
    args = p.parse_args()
    MAX_CM, STILL_LIMIT, COUNTDOWN = args.max_cm, args.still, args.countdown
    if args.csi:
        threading.Thread(target=read_csi, args=(args.csi,), daemon=True).start()
    if args.radar:
        threading.Thread(target=read_radar, args=(args.radar,), daemon=True).start()
    print("open http://localhost:8000", flush=True)
    for k in ("ok", "siren"):  # sound check at start: if you can't hear this, turn the volume up
        winsound.PlaySound(SOUNDS[k], winsound.SND_FILENAME)
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
