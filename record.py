"""Record CSI lines from the receiver board into a CSV that csi.load() can read.

    python record.py COM5 10 data/raw/test.csv   # port, seconds, output file
"""
import sys
import time
import winsound

import serial

HEADER = ("type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,aggregation,stbc,fec_coding,"
          "sgi,noise_floor,ampdu_cnt,channel,secondary_channel,local_timestamp,ant,sig_len,rx_state,len,first_word,data\n")

if __name__ == "__main__":
    port, seconds, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    n = 0
    time.sleep(5)  # time to get into position
    with serial.Serial(port, 921600, timeout=1) as s, open(out, "w", newline="") as f:
        f.write(HEADER)
        s.reset_input_buffer()  # drop lines buffered during the pause
        winsound.Beep(1000, 300)  # start
        end = time.time() + seconds
        while time.time() < end:
            line = s.readline().decode("ascii", "ignore")
            if line.startswith("CSI_DATA") and line.rstrip().endswith(']"'):
                f.write(line.rstrip() + "\n")
                n += 1
    winsound.Beep(600, 600)  # stop
    print(f"{n} frames in {seconds:.0f} s (~{n / seconds:.0f}/s) -> {out}")
