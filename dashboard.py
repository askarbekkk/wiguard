"""Live web dashboard: WiFi CSI (motion + static fingerprint) and the LD2410C radar.

    python dashboard.py --csi COM5 --radar COM6     # either one can be left out
    then open http://localhost:8000
"""
import argparse
import json
import os
import threading
import time
from collections import deque
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
            csi_log.write(f"{now:.3f},{motion:.5f},{'' if fp is None else f'{fp:.3f}'}\n")


def read_radar(port):
    occupied, since = None, time.time()  # since = when the radar started disagreeing with `occupied`
    for frame in radar.frames(port):
        if frame is None:
            continue
        now = time.time()
        present = frame[0] != 0
        if present == occupied:
            since = now
        elif now - since >= (ENTER_AFTER if present else LEAVE_AFTER):
            if occupied is not None:  # the first reading only sets the starting state
                event = "entered" if present else "left"
                event_log.write(f"{now:.3f},{event}\n")
                with lock:
                    events.append((now, event))
            occupied, since = present, now
        with lock:
            radar_points.append((now, *frame))
        radar_log.write(f"{now:.3f},{','.join(map(str, frame))}\n")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/data":
            with lock:
                body = json.dumps({"now": time.time(), "csi": list(csi_points), "radar": list(radar_points),
                                   "events": list(events), "calibrating": time.time() < calib["until"],
                                   "threshold": calib["threshold"], "fp_base": calib["fp_base"]}).encode()
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
    args = p.parse_args()
    if args.csi:
        threading.Thread(target=read_csi, args=(args.csi,), daemon=True).start()
    if args.radar:
        threading.Thread(target=read_radar, args=(args.radar,), daemon=True).start()
    print("open http://localhost:8000", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
