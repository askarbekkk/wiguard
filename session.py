"""Record CSI and webcam video together, with a beep at every phase change.

    python session.py s01 COM6       # -> data/sessions/s01/{csi.csv, video.mp4, video_times.csv, phases.csv}

Every CSI line and every video frame gets the laptop clock (host_time), so the two line up exactly.
"""
import os
import sys
import threading
import time
import winsound

import cv2
import serial

from record import HEADER

PORT = sys.argv[2] if len(sys.argv) > 2 else "COM6"  # the COM number changes with the USB socket
CAMERA = 1
PHASES = [  # (seconds, label) — edit for each session
    (20, "empty"),
    (30, "stand"),
    (30, "walk"),
    (30, "sit"),
    (30, "lie"),
    (20, "leave"),
]

name = sys.argv[1]
out = f"data/sessions/{name}"
os.makedirs(out, exist_ok=True)
stop = threading.Event()
csi_count = 0  # frames received so far, shown on screen so a dead link is noticed during recording


def read_csi():
    global csi_count
    with serial.Serial(PORT, 921600, timeout=1) as s, open(f"{out}/csi.csv", "w", newline="") as f:
        f.write("host_time," + HEADER)
        s.reset_input_buffer()
        while not stop.is_set():
            line = s.readline().decode("ascii", "ignore").rstrip()
            if line.startswith("CSI_DATA") and line.endswith(']"'):
                f.write(f"{time.time():.3f},{line}\n")
                csi_count += 1


def beep(freq=1000):
    threading.Thread(target=winsound.Beep, args=(freq, 300), daemon=True).start()


cap = cv2.VideoCapture(CAMERA)
ok, frame = cap.read()
# assumes the webcam runs at 30 fps; exact frame times are in video_times.csv anyway
video = cv2.VideoWriter(f"{out}/video.mp4", cv2.VideoWriter_fourcc(*"mp4v"), 30, (frame.shape[1], frame.shape[0]))
times = open(f"{out}/video_times.csv", "w")
phases = open(f"{out}/phases.csv", "w")
phases.write("label,start,end\n")
threading.Thread(target=read_csi, daemon=True).start()

print("Phases:", ", ".join(f"{label} {sec}s" for sec, label in PHASES), flush=True)
start = time.time()
ends = [start + sum(sec for sec, _ in PHASES[:i + 1]) for i in range(len(PHASES))]
phase = 0
beep()
last_count, last_check, rate = 0, start, 0
while phase < len(PHASES):
    ok, frame = cap.read()
    now = time.time()
    if now >= ends[phase]:
        phases.write(f"{PHASES[phase][1]},{ends[phase] - PHASES[phase][0]:.3f},{ends[phase]:.3f}\n")
        phase += 1
        beep(1000 if phase < len(PHASES) else 500)
        continue
    if now - last_check >= 1:
        rate, last_count, last_check = csi_count - last_count, csi_count, now
        if rate == 0:
            print(f"WARNING: no CSI at {now - start:.0f}s — check the receiver cable and TX power", flush=True)
    if ok:
        label = PHASES[phase][1]
        video.write(frame)  # the video stays clean; the overlay is only on screen
        times.write(f"{now:.3f}\n")
        cv2.putText(frame, f"{label.upper()}  {ends[phase] - now:4.1f}s", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
        cv2.putText(frame, f"CSI {rate}/s", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 200, 0) if rate > 20 else (0, 0, 255), 2)
        cv2.imshow("session", frame)
        cv2.waitKey(1)

stop.set()
time.sleep(1.5)
video.release()
cap.release()
cv2.destroyAllWindows()
print(f"saved {out}", flush=True)
