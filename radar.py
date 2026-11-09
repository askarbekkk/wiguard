"""Read the LD2410C radar through the radar_bridge board.

    python radar.py COM6 10      # print the radar state for 10 seconds
"""
import struct
import sys
import time

import serial

HEAD, TAIL = b"\xf4\xf3\xf2\xf1", b"\xf8\xf7\xf6\xf5"
STATES = {0: "nobody", 1: "moving", 2: "still", 3: "moving+still"}


def frames(port):
    """Yield (state, moving_cm, moving_energy, still_cm, still_energy) from the radar's report frames."""
    buf = b""
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 921600, 1
    s.dtr = s.rts = False  # opening with DTR/RTS asserted can reset the board
    with s:
        while True:
            chunk = s.read(s.in_waiting or 1)
            if not chunk:
                yield None  # nothing for 1 s, let the caller check its clock
                continue
            buf += chunk
            start = buf.find(HEAD)
            if start < 0:
                buf = buf[-3:]
                continue
            if len(buf) < start + 6:
                continue
            n = struct.unpack_from("<H", buf, start + 4)[0]
            end = start + 6 + n + 4
            if len(buf) < end:
                continue
            data, tail = buf[start + 6:start + 6 + n], buf[end - 4:end]
            buf = buf[end:]
            if tail != TAIL or n < 11 or data[1] != 0xAA:  # not a target report (or a garbled one)
                continue
            state, mov_cm, mov_e, still_cm, still_e = struct.unpack_from("<BHBHB", data, 2)
            yield state, mov_cm, mov_e, still_cm, still_e


if __name__ == "__main__":
    port, seconds = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 10
    end = time.time() + seconds
    last = 0
    for frame in frames(port):
        if time.time() > end:
            break
        if frame is None:
            print("no radar data", flush=True)
            continue
        state, mov_cm, mov_e, still_cm, still_e = frame
        if time.time() - last >= 0.5:
            print(f"{STATES.get(state, state):13s} moving {mov_cm:4d} cm e={mov_e:3d} | still {still_cm:4d} cm e={still_e:3d}", flush=True)
            last = time.time()
