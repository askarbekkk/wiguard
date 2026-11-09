"""Live view: how much the CSI signal is changing right now.

    python live.py COM5
"""
import json
import sys
import time
from collections import deque

import matplotlib.pyplot as plt
import numpy as np
import serial
from numpy.lib.stride_tricks import sliding_window_view

port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
CALIBRATION = 40  # first 40 half-seconds = 20 s with nobody in the room (a quiet empty room is ~0.02)
calib = []
threshold = strong = None  # set from the calibration: the room's own noise level
history = deque([0.0] * 60, maxlen=60)  # last 60 half-seconds = 30 s

plt.ion()
fig, ax = plt.subplots(figsize=(9, 4))
bars = ax.bar(range(60), history, color="tab:gray")
ax.set_ylim(0, 0.08)
ax.set_title("Calibrating: leave the room or stay still (20 s)")
ax.set_xticks([])

fig.canvas.manager.window.attributes("-topmost", 1)  # keep the window above VS Code
log = open("data/live_log.csv", "w")
start = time.time()

with serial.Serial(port, 921600, timeout=1) as s:
    frames = deque(maxlen=47)  # last ~1 s
    new = 0
    while plt.fignum_exists(fig.number):
        line = s.readline().decode("ascii", "ignore")
        if line.startswith("CSI_DATA") and line.rstrip().endswith(']"'):
            try:
                iq = np.array(json.loads(line[line.index('"[') + 1:line.rindex('"')]), dtype=float)
            except ValueError:
                continue
            if iq.size % 2 == 0:  # an odd count means the line was cut on the serial port
                frames.append(np.hypot(iq[0::2], iq[1::2]))
                new += 1
        if new >= 23 and len(frames) == frames.maxlen:  # update every ~0.5 s over the last ~1 s
            new = 0
            n = max(set(map(len, frames)), key=[len(f) for f in frames].count)
            a = np.array([f for f in frames if len(f) == n])
            a = a[:, a.mean(axis=0) > 0]
            a = a / a.mean(axis=1, keepdims=True)
            a = np.median(sliding_window_view(a, 9, axis=0), axis=-1)  # drop single garbled packets
            history.append(float(a.std(axis=0).mean()))
            log.write(f"{time.time() - start:.1f},{history[-1]:.4f}\n")
            log.flush()
            if threshold is None:
                calib.append(history[-1])
                if len(calib) == CALIBRATION:
                    # skip the first 5 s (time to walk out); median, so a door slam can't inflate it
                    threshold = 1.6 * float(np.median(calib[10:]))
                    strong = 2.5 * threshold
                    ax.axhline(threshold, color="tab:orange", ls="--", lw=1)
                    ax.axhline(strong, color="tab:red", ls="--", lw=1)
                    ax.set_title(f"Signal change (last 30 s) — threshold {threshold:.3f}")
                    print(f"calibrated: threshold={threshold:.4f} strong={strong:.4f}", flush=True)
            for i, (b, h) in enumerate(zip(bars, history)):
                b.set_height(h)
                if threshold is None:
                    continue
                held = i > 0 and history[i - 1] > threshold  # ignore a single half-second blip
                b.set_color("tab:red" if h > strong else "tab:orange" if h > threshold and held else "tab:blue")
            plt.pause(0.01)
