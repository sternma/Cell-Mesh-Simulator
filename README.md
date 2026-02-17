### README.md

# Cell Mesh Simulator

A lightweight Raspberry Pi-based system that simulates a cellular network using Wi-Fi access points. Each Raspberry Pi “tower” broadcasts a unique SSID (usually hidden). A portable Raspberry Pi client roams between towers and displays the currently-associated tower on a **Pimoroni Blinkt!** LED bar.

Minimum viable setup is **2 towers + 1 client**, and you can scale to **as many towers and/or clients as you want** without changing code. Add entries to the config, run the setup scripts, done.

---

## Minimum Setup (Recommended Starting Point)

**Minimum viable network:**
- **2× Towers** (Access Points): `Tower1`, `Tower2`
- **1× Client** (Roaming + LED indicator)

Once that’s working, expand by adding more towers and/or more clients.

---

## Repository Structure

```
README.md                        ← (this file)  
src/  
├── tower_led.py                 ← Client roam + LED mapping daemon  
├── tower_gpio_indicator.py      ← Optional tower GPIO client-connected indicator  
└── config/  
    └── tower_led_config.json    ← SSID ➜ { color, freq, bssid }  
  
hw_setup/  
├── tower_setup.sh               ← Tower AP install & hostapd config script  
└── client_setup.sh              ← Client install & systemd service script  
```

---

## 🔧 Hardware

| Component                         | Qty | Notes |
|----------------------------------|-----|------|
| Raspberry Pi 4 (1GB/2GB)         | 3+  | **2+ towers**, **1+ client**; Raspberry Pi OS Lite recommended |
| microSD cards (16GB+)            | 3+  | One per Pi |
| USB-C power supplies             | 2+  | 5 V ⎓ 3 A, for the towers |
| Pimoroni Blinkt! (8-LED bar)     | 1+  | One per client (plugs directly onto GPIO header) |
| USB-C Power bank                 | 1+  | 5 V ⎓ 2 A+ for portable client |
---

## 🚀 Setup

### 1) Tower Setup (Access Points)

Run this on each tower Pi as root:

```bash
sudo hw_setup/tower_setup.sh <TOWER_ID> <SSID> <CHANNEL> [TX_POWER_MBM] [OPTIONS]
```

- **TOWER_ID**: numeric label (used for logging only)
- **SSID**: e.g. `Tower1`
- **CHANNEL**: `1`, `6`, `11` (2.4 GHz) or `36+` (5 GHz)
- **TX_POWER_MBM**: optional transmit power in **mBm** (100 mBm = 1 dBm). Defaults to `1000` (10 dBm).

Optional tower GPIO indicator flags:
- `--enable-gpio-indicator`: enable GPIO output when at least one client is connected
- `--gpio-pins <CSV>`: GPIO output pins (default `18,13,12`)
- `--gpio-on-mask <CSV>`: `0/1` mask aligned to `--gpio-pins` (default `0,1,0`)
- `--gpio-poll-interval <SEC>`: station poll interval in seconds (default `1.0`)

**Minimum setup example (2 towers):**

Tower 1:
```bash
sudo hw_setup/tower_setup.sh 1 Tower1 1 500
```

Tower 2:
```bash
sudo hw_setup/tower_setup.sh 2 Tower2 1 500
```

Tower with optional GPIO indicator (old RGB breadboard pinout, green when connected):
```bash
sudo hw_setup/tower_setup.sh 1 Tower1 1 500 --enable-gpio-indicator --gpio-pins 18,13,12 --gpio-on-mask 0,1,0
```

Notes:
- Towers are configured as **open APs** (`wpa=0`) and default to **hidden SSIDs** (`ignore_broadcast_ssid=1`).
- The setup script disables/masks `wpa_supplicant` on towers to prevent interference with `hostapd`.
- Regulatory domain is set to **US** and a fixed TX power is applied.
- If `--enable-gpio-indicator` is used, a `tower-gpio-indicator` systemd service is installed. It turns configured GPIO outputs on when any station is associated and off when there are no associated stations.

Verify hostapd:

```bash
sudo systemctl status hostapd
journalctl -u hostapd -f
```

If GPIO indicator is enabled:

```bash
sudo systemctl status tower-gpio-indicator
journalctl -u tower-gpio-indicator -f -o cat
```

---

### 2) Client Setup (Roaming + LED)

On the client Pi:

1. Ensure these exist:
   - `src/tower_led.py`
   - `src/config/tower_led_config.json`

2. Run installer:

```bash
sudo hw_setup/client_setup.sh
```

What it does:
- Installs dependencies (Python + `blinkt`, plus `iw`, `rfkill`, etc.)
- Unblocks Wi-Fi and sets country to US
- Creates and starts the `tower-led` systemd service
- **Disables/masks `wpa_supplicant`** (both `wpa_supplicant.service` and `wpa_supplicant@wlan0.service`) so it doesn’t fight roaming

3. Restart after changes:

```bash
sudo systemctl restart tower-led
journalctl -u tower-led -f -o cat
```

Important:
- With `wpa_supplicant` masked, Wi-Fi association is handled entirely by `tower_led.py` using `iw`.
- If you later want “normal Wi-Fi” back on the client for other projects, you’ll need to unmask/enable `wpa_supplicant` again.

---

## 🧠 tower_led_config.json Format

Config lives at:

- `src/config/tower_led_config.json`

It is keyed by SSID. Each entry includes:
- `color`: RGB floats `[0.0–1.0]`
- `freq`: channel frequency in MHz (e.g. `2412` for channel 1)
- `bssid`: AP MAC address (used to map scan results to towers)

**Minimum config example (2 towers):**

```json
{
  "Tower1": { "color": [1.0, 0.0, 0.0], "freq": 2412, "bssid": "aa:bb:cc:dd:ee:01" },
  "Tower2": { "color": [0.0, 1.0, 0.0], "freq": 2412, "bssid": "aa:bb:cc:dd:ee:02" }
}
```

Important:
- `bssid` **must** be a real MAC address (`xx:xx:xx:xx:xx:xx`). Objects with placeholder BSSIDs will be ignored.
- `freq` should match the tower’s channel frequency (e.g. channel 1 = 2412, channel 6 = 2437, channel 11 = 2462).

---

## ➕ Scaling Up (No Code Changes)

This system is designed to scale by configuration and setup scripts alone.

### Add more towers
1. Run `hw_setup/tower_setup.sh` on each new tower with a new SSID/channel.
2. Add a new entry for that SSID in `src/config/tower_led_config.json`.

That’s it. The client automatically considers whatever towers appear in the config.

### Add more clients
1. Put a Blinkt! on each client.
2. Run `hw_setup/client_setup.sh` on each client.
3. Copy the same `src/config/tower_led_config.json` to each client (or customize per client if you want different colors).

There is no enforced limit on the number of towers or clients. Practical limits are just Wi-Fi airtime and interference, which only come into play at very large client and tower populations.

---

## ⚙️ Behavior & Tweaks

The client daemon (`src/tower_led.py`) does:
- Periodic `iw scan` on configured frequencies
- Picks the best tower by RSSI (with a stickiness margin)
- Performs a “hard roam” using `iw disconnect` + `iw connect`
- Updates Blinkt! LEDs to show which SSID it’s currently on **and** signal strength

Useful knobs in `tower_led.py`:
- `SCAN_INTERVAL`: how often to scan (seconds)
- `ROAM_MARGIN_DB`: how aggressively to roam (more negative = roam more)
- `ROAM_COOLDOWN_SEC`: cooldown after roam
- `BRIGHTNESS`, `UNKNOWN_MODE`, `SIGNAL_MIN_DBM`, `SIGNAL_MAX_DBM`

LED behavior note:
- Blinkt! has 8 LEDs. The LED **bar length** represents signal strength (1 LED = weak, 8 LEDs = strong).
- The **color** indicates the currently-associated tower (from `tower_led_config.json`).

---

## 🛠️ Troubleshooting

### Client logs
```bash
journalctl -u tower-led -f -o cat
```

You should see periodic lines like:
- `SCAN: current=TowerX(...) | Tower1=... Tower2=...`
- `Roaming: TowerA (...) → TowerB (...)`
- `Connected to TowerX, RSSI -55 dBm, LEDs 6/8`

### Confirm association + signal
```bash
sudo iw dev wlan0 link
```

### Confirm scan works manually
```bash
sudo iw dev wlan0 scan freq 2412 | head
```

### Common failure modes
- **No SCAN lines**: config produced an empty/invalid `bssid_map` (bad BSSID formatting, placeholder values, etc.)
- **Stuck on one tower**: adjust `ROAM_MARGIN_DB` (make it more negative to roam more)
- **hostapd flapping**: check `journalctl -u hostapd -f` and confirm wlan0 isn’t being managed by other services

---

## 📜 License

Apache License 2.0. See [LICENSE](LICENSE).


