"""Read ESP32 CSI logs (esp-csi CSV format) and measure how much the signal moves."""
import csv
import json
import sys

import numpy as np


def load(path):
    """CSV with an esp-csi `data` column -> amplitude array (frames x subcarriers)."""
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                iq = json.loads(r["data"])
            except (ValueError, TypeError):
                continue  # broken line from the serial port
            if isinstance(iq, list):
                rows.append(iq)
    n = max(set(map(len, rows)), key=list(map(len, rows)).count)  # usual frame length
    rows = [r for r in rows if len(r) == n]  # drop frames garbled on the serial line
    iq = np.array(rows, dtype=float).reshape(len(rows), -1, 2)
    amp = np.hypot(iq[..., 0], iq[..., 1])
    return amp[:, amp.mean(axis=0) > 0]  # drop always-zero guard subcarriers


def motion(amp, win=20):
    """How much each frame differs from the previous one, smoothed over `win` frames (~1 s at 20 Hz)."""
    amp = amp / amp.mean(axis=1, keepdims=True)  # cancel automatic gain jumps
    d = np.abs(np.diff(amp, axis=0)).mean(axis=1)
    return np.convolve(d, np.ones(win) / win, mode="valid")


if __name__ == "__main__":
    import matplotlib.pyplot as plt

    folder = sys.argv[1] if len(sys.argv) > 1 else "data/external/marcolini"
    classes = ["walking", "standing", "sitting", "lying"]
    fig, ax = plt.subplots(2, 4, figsize=(16, 7))
    for i, c in enumerate(classes):
        amp = load(f"{folder}/{c}1.csv")
        m = motion(amp)
        print(f"{c:9s} frames={len(amp):4d} subcarriers={amp.shape[1]} motion={np.mean([motion(load(f'{folder}/{c}{k}.csv')).mean() for k in (1, 2, 3)]):.4f}")
        ax[0, i].imshow(amp.T, aspect="auto", cmap="viridis")
        ax[0, i].set_title(f"{c}: signal (subcarrier x time)")
        ax[1, i].plot(m)
        ax[1, i].set_title(f"{c}: motion")
    for a in ax[1]:
        a.set_ylim(0, max(a.get_ylim()[1] for a in ax[1]))
    fig.tight_layout()
    fig.savefig("plots/csi_demo.png", dpi=90)
    print("saved plots/csi_demo.png")
