# WiGuard — camera-free fall and inactivity monitoring with WiFi + a $10 radar

Low-cost, open-source monitoring for older people who live alone in small rooms (*jjokbang*, *goshiwon*), where cameras are not acceptable and wearables get taken off. Two ESP32 boards measure how the WiFi signal moves through the room; a 24 GHz mmWave radar confirms whether someone is still there when they stop moving. Everything runs locally: no camera, no cloud, no subscription.

**Hardware cost: about ₩45,000** (3× ESP32 DevKitC ≈ ₩30,000 + LD2410C radar ≈ ₩14,000).

> Status: working prototype. Motion, presence and "left the room" detection work; fall detection is in progress (see [Results](#results) and [Limitations](#limitations)).

## Why

- Lonely deaths (고독사) in Korea keep rising, and older people most often fall in the bathroom — exactly where cameras cannot go.
- Commercial camera-free systems exist (radar products from telecom and care companies), but they cost hundreds of thousands of won plus a subscription.
- WiFi sensing on ESP32 is cheap, but on its own it cannot tell *a person lying still* from *an empty room*. This project combines it with a cheap radar and measures honestly where each sensor works.

## How it works

```
[ESP32 TX] ── WiFi packets, 100/s ──► [ESP32 RX] ──USB──┐
                                                         ├──► laptop (Python) ──► live dashboard + event log
[LD2410C radar] ──UART──► [ESP32 bridge] ──────USB──────┘
```

1. **WiFi CSI (Channel State Information).** The transmitter sends packets on a fixed channel; the receiver reports the amplitude of ~120 subcarriers for every packet (~47 per second over USB). A human body absorbs and reflects 2.4 GHz signals, so the pattern changes when someone moves.
2. **Signal cleaning.** A small share of packets arrive corrupted (1–7 per second with the onboard antennas). A 9-frame median filter removes them before any decision is made.
3. **Two WiFi features:**
   - **Motion** — how much the subcarrier pattern changes from moment to moment (detects walking, sitting down, getting up).
   - **Fingerprint** — how different the current pattern is from a calibrated *empty room*. This keeps information about a person who is *not* moving, which a motion-only pipeline throws away.
4. **Radar.** The LD2410C reports whether a target is moving or still and at what distance (up to ~6 m), including people who are only breathing.
5. **Decisions.** A short empty-room calibration sets the thresholds for each room. The radar drives *entered / left the room* events; WiFi motion and the fingerprint drive *movement* and *possible person on the floor*.

## Results

Measured on the prototype in one room (2 boards ~1.5 m apart, HT20, onboard PCB antennas).

| Test | Result |
|---|---|
| Empty room, door closed, 60 s | WiFi motion 0.016–0.029, no false spikes, no packet loss |
| Standing still vs walking near the boards | walking is **2–4× higher** than standing still |
| Recorded session (still / walk / sit / lie phases) | motion: walk 0.038 vs still 0.011–0.019 |
| Fingerprint vs empty room, same session | empty 4.2 (2.5–4.7), standing 4.2, sitting 3.7, **lying on the floor 10.4 (10.1–11.3)**, no overlap with empty |
| Radar presence | detects moving and still people up to ~6 m |
| "Left the room" event | reported ~15 s after the person leaves |

![Signal variability while standing still and then walking](docs/still_vs_walking.png)

The fingerprint result comes from **one session** with the reference recorded minutes earlier. It still has to hold up on a different day and at different spots on the floor before it can be trusted.

## Limitations

- **Weak signal.** The onboard PCB antennas give −72 to −82 dBm at 1.5 m. Motion close to the boards is clear; motion in the middle of a 1.5 m link is much weaker. Espressif recommends external antennas.
- **WiFi motion alone cannot see a person lying still** (it looks like an empty room). That is why the fingerprint and the radar exist.
- **The radar needs tuning.** With factory settings it reports "moving" for a person who is only breathing nearby.
- **Sensitivity beyond the room.** With the door open, movement outside the room is picked up. Boards should be placed away from doors and shared walls.
- One room, one person. Not tested with pets, several occupants or a running shower yet.
- **Fall detection is not validated yet**, and this is not a medical device.

## Hardware

| Part | Qty | Role |
|---|---|---|
| ESP32 DevKitC (classic ESP32, USB-C) | 3 | transmitter, receiver, radar bridge |
| HLK-LD2410C 24 GHz radar | 1 | still/moving presence |
| Female–female jumper wires | 4 | radar → bridge board |
| USB data cables + phone charger | | receiver and bridge to the laptop, transmitter on a charger |

Radar wiring (bridge board): `VCC → VIN`, `GND → GND`, `TX → D16`, `RX → D17`, `OUT` unused.

![Radar wiring on the ESP32 board](docs/radar_wiring.jpg)

## Setup

1. Install [ESP-IDF](https://docs.espressif.com/projects/esp-idf/) (tested with v5.5) and clone [espressif/esp-csi](https://github.com/espressif/esp-csi).
2. Switch the examples to 20 MHz (HT20): `git -C esp-csi apply ../firmware/esp-csi-ht20.patch`. HT20 gave a cleaner signal and more frames per second than HT40 on these boards.
3. Flash the boards (`COMx` is the board's port):
   ```
   cd esp-csi/examples/get-started/csi_send   && idf.py set-target esp32 && idf.py -p COMx flash
   cd esp-csi/examples/get-started/csi_recv   && idf.py set-target esp32 && idf.py -p COMy flash
   cd firmware/radar_bridge                   && idf.py set-target esp32 && idf.py -p COMz flash
   ```
4. Python side: `pip install -r requirements.txt`
5. Run the dashboard and open http://localhost:8000:
   ```
   python dashboard.py --csi COMy --radar COMz
   ```
   Press **Calibrate empty room** and leave the room for 20 seconds.

## Files

| File | What it does |
|---|---|
| `dashboard.py`, `dashboard.html` | live web dashboard: WiFi motion, fingerprint, radar energy, entered/left events; saves everything to `data/live/` |
| `csi.py` | reads esp-csi CSV logs, computes amplitudes and the motion measure |
| `radar.py` | parses LD2410C report frames |
| `record.py` | records raw CSI to CSV with start/stop beeps |
| `session.py` | records CSI and webcam video together with timed phases (used only to label training data, never in deployment) |
| `live.py` | simple live motion plot with empty-room calibration |
| `camera_preview.py` | webcam preview for placing the labelling camera |
| `firmware/radar_bridge` | ESP-IDF firmware that forwards the radar's UART to USB |
| `firmware/esp-csi-ht20.patch` | switches the esp-csi examples from HT40 to HT20 |

## Roadmap

- Repeat the fingerprint test on different days and floor positions; tune the radar's motion sensitivity.
- Fall rule: sudden motion spike → stillness → person still present (radar) and on the floor (fingerprint) → countdown with cancel → Telegram alert.
- Label sessions with the synchronized camera and report missed falls, false alarms per hour and time to alert on held-out sessions.
- Run on the ESP32 or a Raspberry Pi instead of a laptop.

## Related work

- [espressif/esp-csi](https://github.com/espressif/esp-csi) — firmware base for CSI capture.
- Research on WiFi fall detection (WiFall, ToiFall, WiBFall) reports very high accuracy in laboratory conditions on research WiFi cards; open ESP32 projects report much lower specificity on held-out data, which is why this project measures on separate sessions and adds a second sensor.
- Commercial camera-free monitors use mmWave radar (for example 60 GHz devices in public toilets and care homes) at a much higher price.

## License

MIT
