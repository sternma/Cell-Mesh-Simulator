#!/usr/bin/env python3
import json
import subprocess
import time
import re
from gpiozero import Device, RGBLED
from gpiozero.pins.rpigpio import RPiGPIOFactory
from pathlib import Path

# Only consider SSIDs matching Tower<number>
TOWER_PATTERN = re.compile(r'^Tower\d+$')

# LED wiring (GPIO pins)
Device.pin_factory = RPiGPIOFactory()
led = RGBLED(red=18, green=13, blue=12)

# Configuration
CONFIG_PATH = Path("/home/pi/cell-mesh-simulator/src/config/tower_led_config.json")
POLL_INTERVAL = 1  # seconds between cycles


def load_config():
    """Load SSID→color mapping from JSON file."""
    try:
        data = json.loads(CONFIG_PATH.read_text())
        return {ssid: tuple(color)
                for ssid, color in data.items()
                if isinstance(color, list) and len(color) == 3}
    except Exception as e:
        print(f"Error loading config: {e}", flush=True)
        return {}


def get_ssid():
    """Return current SSID or None."""
    try:
        out = subprocess.check_output(["sudo","iwconfig", "wlan0"], stderr=subprocess.DEVNULL).decode()
        m = re.search(r'ESSID:"([^"]+)"', out)
        if m:
            essid = m.group(1)
            return essid if essid != "off/any" else None
    except subprocess.CalledProcessError:
        pass
    return None


def get_current_bssid():
    """Return current connected BSSID or None."""
    try:
        out = subprocess.check_output(["sudo","iw", "dev", "wlan0", "link"], stderr=subprocess.DEVNULL).decode()
        m = re.search(r"Connected to ([0-9a-f:]{17})", out)
        return m.group(1) if m else None
    except subprocess.CalledProcessError:
        return None


def roam_to_best(mapping):
    """Scan environment, pick strongest Tower<n> SSID, and roam to its BSSID."""
    # Flush any cached/ignored BSS entries
    subprocess.call(["sudo","wpa_cli", "-i", "wlan0", "bss_flush"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Active scan via iw
    try:
        raw = subprocess.check_output(["sudo", "iw", "dev", "wlan0", "scan"], stderr=subprocess.DEVNULL).decode()
    except subprocess.CalledProcessError as e:
        print(f"Scan failed: {e}", flush=True)
        return

    best_signal = -999.0
    best_bssid = None
    current_bssid = get_current_bssid()
    bssid = None
    signal = None

    for line in raw.splitlines():
        if line.startswith("BSS "):
            parts = line.split()
            bssid = parts[1] if len(parts) >= 2 else None
        elif "signal:" in line:
            m = re.search(r"signal:\s*([-0-9.]+)\s*dBm", line)
            signal = float(m.group(1)) if m else None
        elif "SSID:" in line:
            ssid = line.strip().split("SSID:")[-1].strip()
            # Only consider our tower SSIDs
            if not TOWER_PATTERN.match(ssid):
                continue
            if bssid and ssid in mapping and signal is not None:
                if signal > best_signal:
                    best_signal = signal
                    best_bssid = bssid

    if best_bssid and best_bssid != current_bssid:
        print(f"Roaming from {current_bssid} to {best_bssid} (signal {best_signal} dBm)", flush=True)
        subprocess.call(["sudo", "wpa_cli", "-i", "wlan0", "roam", best_bssid], stdout=subprocess.DEVNULL)


def main():
    mapping = load_config()
    last_ssid = None
    while True:
        roam_to_best(mapping)
        ssid = get_ssid()
        # Only update LED when connected to a valid SSID
        if ssid and ssid != last_ssid:
            last_ssid = ssid
            color = mapping.get(ssid)
            if color:
                led.color = color
                print(f"Connected to {ssid}, LED color set to {color}", flush=True)
            else:
                # Unknown SSID (e.g., not part of our towers)
                led.off()
                print(f"{ssid} not in config → LED off", flush=True)
        # Skip updating on ssid=None to avoid blinking when briefly unassociated
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
