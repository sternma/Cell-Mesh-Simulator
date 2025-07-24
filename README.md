# Cell Mesh Simulator

A lightweight Raspberry Pi-based system that simulates a cellular network using Wi‑Fi access points. Four Pi “towers” each broadcast a unique SSID (hidden if desired), and a portable Pi client roams between them, lighting an RGB LED to reflect which tower it’s associated with.

---

## Repository Structure

```
README.md                        ← (this file)
src/
├── tower_led.py                 ← Client LED-mapping script
└── config/
    └── tower_led_config.json    ← SSID ➔ RGB color mapping

hw_setup/
├── tower_setup.sh               ← Tower AP install & config script
└── client_setup.sh              ← Client install & config script
```

---

## 🔧 Hardware

| Component                  | Qty   | Notes                                                  |
| -------------------------- | ----- | ------------------------------------------------------ |
| Raspberry Pi 4 (1 GB/2 GB) |   5   |  4 for towers, 1 for client; OS Lite image recommended |
| microSD cards (16 GB+)     |   5   | Pre‑flashed with Raspberry Pi OS Lite                  |
| USB‑C power supplies       |   5   | 5 V ⎓ 3 A                                              |
| Breadboard & jumpers       |   1   | For client LED wiring                                  |
| Common‑cathode RGB LED     |   1   | 4‑pin (R/G/B + GND)                                    |
| 220 Ω resistors            |   3   | ¼ W recommended                                        |
| (Optional) Power bank      |   1   | 5 V ⎓ 2 A+, for truly portable client                  |

---

## 🔌 Breadboard Wiring

Before you power on the client, wire the RGB LED to your Pi GPIO header and breadboard as follows:

```
Pi GPIO18 ──220 Ω──► Red LED pin
Pi GPIO13 ──220 Ω──► Green LED pin
Pi GPIO12 ──220 Ω──► Blue LED pin
Pi GND    ─────────► LED common cathode
```

- Use ¼ W (0.25 W) 220 Ω resistors on each color leg to limit current (~5–10 mA per channel).
- Place the LED’s long lead (common cathode) into the GND rail of the breadboard.
- Double‑check your wiring before powering up to avoid any shorts.

---

## 🚀 Setup

### 1. Tower Setup

1. **Run the script** on each tower Pi as root:

   ```bash
   sudo hw_setup/tower_setup.sh <ID> <STATIC_IP> <SSID> <CHANNEL> [TX_POWER_MBM]
   ```

   * **ID**: Tower number (1–4)
   * **STATIC\_IP**: e.g. `192.168.50.11`
   * **SSID**: e.g. `Tower1`
   * **CHANNEL**: `1`, `6`, `11` (2.4 GHz) or `36+` (5 GHz)
   * **TX_POWER_MBM**: (optional) transmit power in mBm; defaults to `1000` (10 dBm)

2. **Optional hidden SSID**: edit `/etc/hostapd/hostapd.conf` and set `ignore_broadcast_ssid=0` to make SSID visible.  Hidden by default.

3. **Verify**:

   ```bash
   sudo systemctl status hostapd
   ```

### 2. Client Setup

1. **Place your custom files** under:

   * Config: `src/config/tower_led_config.json`
   * Script: `src/tower_led.py`

2. **Run the installer** as root:

   ```bash
   sudo hw_setup/client_setup.sh
   ```

3. **Edit** `tower_led_config.json` to add or change SSID–color entries:

   ```json
   {
     "Tower1": [1.0, 0.0, 0.0],  // Red
     "Tower2": [0.0, 1.0, 0.0],  // Green
     "Tower5": [1.0, 0.0, 1.0]   // Magenta
   }
   ```

4. **Restart** the service after updates:

   ```bash
   sudo systemctl restart tower-led
   ```

---

## ⚙️ Configuration & Tweaks

* **Transmission Power**: adjust AP TX gain via `iw dev wlan0 set txpower fixed <mBm>` or in `hostapd` unit drop-in.
* **Roaming Sensitivity**: tune `bgscan` in `/etc/wpa_supplicant/wpa_supplicant.conf`:

  ```ini
  bgscan="simple:30:-65:300"
  ```
* **Adding Towers**: add SSID→color to `tower_led_config.json`; no code changes needed.
* **Hidden SSIDs**: set `scan_ssid=1` and `hidden=1` in each wpa\_supplicant network stanza (client script does this by default).

---

## 🛠️ Troubleshooting

* **Logs**:

  * Tower: `journalctl -u hostapd -f`
  * Client: `journalctl -u tower-led -f`
* **Check association**:

  ```bash
  iwgetid -r        # shows current SSID
  iw dev wlan0 link # shows BSSID & signal strength
  ```
* **Temperature** (Pi 4): `vcgencmd measure_temp`

---

## 📜 License

This project is released under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
