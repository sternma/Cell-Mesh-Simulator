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
├── client_roaming_led.py        ← Client roam + LED mapping daemon  
├── tower_gpio_indicator.py      ← Optional tower GPIO client-connected indicator  
└── config/  
    └── client_tower_config.json ← SSID ➜ { color, freq, bssid }  
  
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
| Tower GPIO indicator parts (optional) | 1+ set per tower | LED or other indicator load, suitable resistor/driver, jumper wires |
---

## 🧱 Build Steps (Fresh Pi Images)

Use these for first-time bring-up on fresh Raspberry Pi OS Lite installs.

### Tower (per tower Pi)

1. Flash a fresh **Raspberry Pi OS Lite** image to a microSD card and insert it into the Pi.
2. Power on with **wired Ethernet** connected.  
   (After tower setup, normal Wi-Fi client access is disabled on the tower.)
3. Clone this repo:
   ```bash
   git clone https://github.com/sternma/Cell-Mesh-Simulator.git
   cd Cell-Mesh-Simulator
   ```
4. Run tower setup:
   ```bash
   sudo hw_setup/tower_setup.sh <TOWER_ID> <SSID> <CHANNEL> [TX_POWER_MBM] [OPTIONS]
   ```
5. Optional: enable tower GPIO indicator service at setup time:
   ```bash
   sudo hw_setup/tower_setup.sh 1 Tower1 1 500 --enable-gpio-indicator
   ```

### Client (per client Pi)

1. Flash a fresh **Raspberry Pi OS Lite** image to a microSD card and insert it into the Pi.
2. Install and attach the **Pimoroni Blinkt!** LED bar.
3. Power on with **wired Ethernet** connected.  
   (After client setup, normal Wi-Fi client management is disabled.)
4. Clone this repo:
   ```bash
   git clone https://github.com/sternma/Cell-Mesh-Simulator.git
   cd Cell-Mesh-Simulator
   ```
5. Edit the client tower config:
   - Open `src/config/client_tower_config.json`.
   - Replace the example/placeholder entries (including fake BSSIDs like `in:se:rt:he:re:00`) with your real tower SSIDs, BSSIDs, frequencies, and colors.
   - Ensure at least one tower entry contains valid values before continuing.
6. Run client setup:
   ```bash
   sudo hw_setup/client_setup.sh
   ```

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

Passing any `--gpio-*` option also enables the indicator service automatically.

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

### 1a) Optional Tower GPIO Indicator (Behavior)

When enabled, `hw_setup/tower_setup.sh` installs:
- Script: `/home/pi/cell-mesh-simulator/src/tower_gpio_indicator.py`
- Config: `/etc/cell-mesh-simulator/tower_gpio_indicator.json`
- Systemd service: `/etc/systemd/system/tower-gpio-indicator.service`

Runtime behavior:
- Polls associated stations using `iw dev wlan0 station dump`
- If station count is `> 0`, turns ON only pins where `on_mask` is `1`
- If station count is `0`, turns all configured outputs OFF
- On shutdown/error cleanup, turns all configured outputs OFF

Default config written by setup:

```json
{
  "interface": "wlan0",
  "pins": [18, 13, 12],
  "on_mask": [0, 1, 0],
  "poll_interval_sec": 1.0
}
```

Config rules:
- `pins` must be a non-empty integer array.
- `on_mask` must have exactly one entry per pin.
- `on_mask` entries may be `0/1` or `true/false`.
- `poll_interval_sec` must be a positive number.

Service operations:

```bash
sudo systemctl status tower-gpio-indicator
sudo systemctl restart tower-gpio-indicator
journalctl -u tower-gpio-indicator -f -o cat
```

Disable/remove behavior:

```bash
sudo systemctl disable --now tower-gpio-indicator
```

Path note:
- The optional indicator service currently points to `/home/pi/cell-mesh-simulator/src/tower_gpio_indicator.py`. If your clone lives somewhere else, update `GPIO_SCRIPT` in `hw_setup/tower_setup.sh` before enabling the feature.

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
   - `src/client_roaming_led.py`
   - `src/config/client_tower_config.json`

2. Run installer:

```bash
sudo hw_setup/client_setup.sh
```

What it does:
- Installs dependencies (Python + `blinkt`, plus `iw`, `rfkill`, etc.)
- Unblocks Wi-Fi and sets country to US
- Creates and starts the `cell-mesh-client` systemd service
- Creates runtime config at `/etc/cell-mesh-simulator/client_roaming_led.json` (if missing)
- **Disables/masks `wpa_supplicant`** (both `wpa_supplicant.service` and `wpa_supplicant@wlan0.service`) so it doesn’t fight roaming

3. Restart after changes:

```bash
sudo systemctl restart cell-mesh-client
journalctl -u cell-mesh-client -f -o cat
```

Important:
- With `wpa_supplicant` masked, Wi-Fi association is handled entirely by `client_roaming_led.py` using `iw`.
- If you later want “normal Wi-Fi” back on the client for other projects, you’ll need to unmask/enable `wpa_supplicant` again.

---

## 🧠 Client Config Files

The client uses **two different config files**:

- `src/config/client_tower_config.json`: tower map (SSID, color, freq, bssid). You maintain this file.
- `/etc/cell-mesh-simulator/client_roaming_led.json`: runtime behavior (scan cadence, roam margin, brightness, etc.). `hw_setup/client_setup.sh` creates this if missing.

The systemd service passes both explicitly:

```bash
--tower-config src/config/client_tower_config.json
--runtime-config /etc/cell-mesh-simulator/client_roaming_led.json
```

---

## 🧠 client_tower_config.json (Tower Map) Format

Config lives at:

- `src/config/client_tower_config.json`

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

## 🧠 client_roaming_led.json (Runtime) Format

Runtime config lives at:

- `/etc/cell-mesh-simulator/client_roaming_led.json`

This controls daemon behavior (not tower definitions), including:
- `scan_interval_sec`
- `roam_margin_db`
- `roam_cooldown_sec`
- `brightness`
- `unknown_mode`

---

## ➕ Scaling Up (No Code Changes)

This system is designed to scale by configuration and setup scripts alone.

### Add more towers
1. Run `hw_setup/tower_setup.sh` on each new tower with a new SSID/channel.
2. Add a new entry for that SSID in `src/config/client_tower_config.json`.

That’s it. The client automatically considers whatever towers appear in the config.

### Add more clients
1. Put a Blinkt! on each client.
2. Run `hw_setup/client_setup.sh` on each client.
3. Copy the same `src/config/client_tower_config.json` to each client (or customize per client if you want different colors).

There is no enforced limit on the number of towers or clients. Practical limits are just Wi-Fi airtime and interference, which only come into play at very large client and tower populations.

---

## ⚙️ Behavior & Tweaks

The client daemon (`src/client_roaming_led.py`) does:
- Periodic `iw scan` on configured frequencies
- Picks the best tower by RSSI (with a stickiness margin)
- Performs a “hard roam” using `iw disconnect` + `iw connect`
- Updates Blinkt! LEDs to show which SSID it’s currently on **and** signal strength

Useful knobs in `/etc/cell-mesh-simulator/client_roaming_led.json`:
- `scan_interval_sec`: how often to scan/consider roams
- `roam_margin_db`: roaming stickiness (more negative = roam more)
- `roam_cooldown_sec`: cooldown after a roam
- `brightness`, `unknown_mode`, `signal_min_dbm`, `signal_max_dbm`
- `disconnect_grace_sec`, `scan_freshness_ms`, `scan_timeout_sec`

LED behavior note:
- Blinkt! has 8 LEDs. The LED **bar length** represents signal strength (1 LED = weak, 8 LEDs = strong).
- The **color** indicates the currently-associated tower (from `client_tower_config.json`).

---

## 🛠️ Troubleshooting

### Client logs
```bash
journalctl -u cell-mesh-client -f -o cat
```

You should see periodic lines like:
- `SCAN current=TowerX(...) | Tower1=... Tower2=...`
- `ROAM TowerA(...) -> TowerB(...) [...]`
- `Connected TowerX RSSI=-55 dBm LEDs=6/8`

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
- **Stuck on one tower**: adjust `roam_margin_db` (make it more negative to roam more)
- **hostapd flapping**: check `journalctl -u hostapd -f` and confirm wlan0 isn’t being managed by other services
- **tower-gpio-indicator not starting**: check `journalctl -u tower-gpio-indicator -e -o cat`, then verify `python3-gpiozero` is installed and the script path exists.
- **GPIO never turns on**: verify the tower actually has associated clients with `iw dev wlan0 station dump`.
- **GPIO mask appears inverted**: remember `on_mask=1` means "pin ON when connected"; `0` means always OFF.

### Single-Pi validation path
If you only have one Raspberry Pi, you can still validate the client daemon:

1. Put at least one real tower entry (real `bssid` + `freq`) in `src/config/client_tower_config.json`, then flash the Pi as a client and run `sudo hw_setup/client_setup.sh`.
2. Run a quick diagnosis (no daemon loop):
```bash
sudo python3 src/client_roaming_led.py --validate-config
sudo python3 src/client_roaming_led.py --diagnose
```
3. Run live daemon logs:
```bash
journalctl -u cell-mesh-client -f -o cat
```
4. Manually test Blinkt output by joining/leaving a reachable Wi-Fi AP listed in `src/config/client_tower_config.json`:
```bash
sudo iw dev wlan0 disconnect
```
5. Confirm LED transitions and connection state:
```bash
sudo iw dev wlan0 link
```

---

## 📜 License

Apache License 2.0. See [LICENSE](LICENSE).
