"""Empty-room radar calibration: measure the noise in each 0.75 m gate and raise the radar's thresholds above it.

    python radar_gates.py COM4 60          # record 60 s with nobody in the room, print the energy per gate
    python radar_gates.py COM4 60 --apply  # same, then write thresholds = empty max + MARGIN into the radar

Needs the two-way radar_bridge firmware (laptop -> radar commands).
"""
import struct
import sys
import time

import serial

CMD_HEAD, CMD_TAIL = b"\xfd\xfc\xfb\xfa", b"\x04\x03\x02\x01"
HEAD, TAIL = b"\xf4\xf3\xf2\xf1", b"\xf8\xf7\xf6\xf5"
MARGIN = 10  # energy points above the loudest empty-room reading


def command(s, word, value=b""):
    body = struct.pack("<H", word) + value
    s.write(CMD_HEAD + struct.pack("<H", len(body)) + body + CMD_TAIL)
    time.sleep(0.15)


def read_params(s):
    """Current per-gate sensitivities (move, still), from the ACK of command 0x0061."""
    s.reset_input_buffer()
    command(s, 0x0061)
    buf = s.read(4096)
    i = buf.find(CMD_HEAD + b"\x1c\x00\x61\x01")
    if i < 0:
        return None
    d = buf[i + 6:i + 6 + 28]  # 61 01, status 00 00, AA, max gate, max move gate, max still gate, 9 move, 9 still, 2 B time
    return list(d[8:17]), list(d[17:26]), struct.unpack_from("<H", d, 26)[0]


def gates(s, seconds):
    """Collect per-gate move and still energies from engineering-mode frames."""
    move, still, buf, end = [[] for _ in range(9)], [[] for _ in range(9)], b"", time.time() + seconds
    while time.time() < end:
        buf += s.read(s.in_waiting or 1)
        while (i := buf.find(HEAD)) >= 0 and len(buf) >= i + 6:
            n = struct.unpack_from("<H", buf, i + 4)[0]
            if len(buf) < i + 10 + n:
                break
            d, buf = buf[i + 6:i + 6 + n], buf[i + 10 + n:]
            if d[:2] != b"\x01\xaa" or n < 35:  # engineering report only
                continue
            nm, ns = d[11], d[12]
            for g in range(nm + 1):
                move[g].append(d[13 + g])
            for g in range(ns + 1):
                still[g].append(d[14 + nm + g])
        if len(buf) > 8192:
            buf = buf[-64:]
    return move, still


if __name__ == "__main__":
    port, seconds = sys.argv[1], float(sys.argv[2])
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 921600, 0.3
    s.dtr = s.rts = False
    with s:
        command(s, 0x00FF, b"\x01\x00")  # enter config mode
        params = read_params(s)
        command(s, 0x0062)  # engineering mode on
        command(s, 0x00FE)  # leave config mode
        print("current thresholds (move / still per gate):", params, flush=True)
        print(f"recording {seconds:.0f} s, room must be empty...", flush=True)
        move, still = gates(s, seconds)
        print("gate  metres     move max/median   still max/median", flush=True)
        for g in range(9):
            mm = max(move[g], default=0); sm = max(still[g], default=0)
            med = lambda v: sorted(v)[len(v) // 2] if v else 0
            print(f"{g:4d}  {g * 0.75:4.2f}-{g * 0.75 + 0.75:4.2f}   {mm:3d} / {med(move[g]):3d}        {sm:3d} / {med(still[g]):3d}", flush=True)
        command(s, 0x00FF, b"\x01\x00")
        command(s, 0x0063)  # engineering mode off
        if "--apply" in sys.argv:
            for g in range(9):
                mv = min(100, max(move[g], default=0) + MARGIN)
                st = min(100, max(still[g], default=0) + MARGIN)
                command(s, 0x0064, b"\x00\x00" + struct.pack("<I", g) + b"\x01\x00" + struct.pack("<I", mv)
                        + b"\x02\x00" + struct.pack("<I", st))
            print("new thresholds:", read_params(s), flush=True)
        command(s, 0x00FE)
