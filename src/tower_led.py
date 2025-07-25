#!/usr/bin/env python3
import json
import subprocess
import time
import re
from gpiozero import Device, RGBLED
from gpiozero.pins.rpigpio import RPiGPIOFactory
from pathlib import Path

# LED wiring (GPIO pins)
Device.pin_factory = RPiGPIOFactory()
led = RGBLED(red=18, green=13, blue=12)

# Configuration
CONFIG_PATH = Path("/home/pi/cell-mesh-simulator/src/config/tower_led_config.json")
POLL_INTERVAL = 1  # seconds between loops


def load_config():
    """
    Load tower configuration.
    JSON format:
    {
      "Tower1": {"color": [1.0, 0.0, 0.0], "freq": 2412},
      "Tower2": {"color": [0.0, 1.0, 0.0], "freq": 2437},
      ...
    }
    Returns:
      color_map: {ssid: (r, g, b)}
      freqs: [freq1, freq2, ...]
    """
    try:
        data = json.loads(CONFIG_PATH.read_text())
        color_map = {}
        freqs = []
        for ssid, info in data.items():
            if not isinstance(info, dict):
                continue
            color = info.get("color")
            freq = info.get("freq")
            if isinstance(color, list) and len(color) == 3 and isinstance(freq, (int, float)):
                color_map[ssid] = tuple(color)
                freqs.append(int(freq))
        return color_map, list(set(freqs))
    except Exception as e:
        print(f"Error loading config: {e}", flush=True)
        return {}, []


def get_ssid():
    """Return current SSID or None."""
    try:
        out = subprocess.check_output(["sudo", "iwconfig", "wlan0"], stderr=subprocess.DEVNULL).decode()
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
        out = subprocess.check_output(["sudo", "iw", "dev", "wlan0", "link"], stderr=subprocess.DEVNULL).decode()
        m = re.search(r"Connected to ([0-9a-f:]{17})", out)
        return m.group(1) if m else None
    except subprocess.CalledProcessError:
        return None


def roam_to_best(color_map, freqs):
    """Scan specified frequencies, pick strongest known tower and roam to its BSSID."""
    current = get_current_bssid()
    best_signal = -999.0
    best_bssid = None

    # Flush old BSS entries
    subprocess.call(["sudo", "wpa_cli", "-i", "wlan0", "bss_flush"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # build args
    cmd = ["sudo","iw","dev","wlan0","scan"]
    freq_args = []
    for freq in freqs:
      freq_args.append("freq")
      freq_args.append(str(freq))

    # parse BSS / signal / SSID from raw …
    cmd = ["sudo", "iw", "dev", "wlan0", "scan"] + freq_args
    try:
        raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()
    except subprocess.CalledProcessError as e:
        print(f"Scan failed: {e}", flush=True)
        return

    # Parse scan output
    bssid = None
    signal = None
    ssid = None
    for line in raw.splitlines():
        if line.startswith("BSS "):
            parts = line.split()
            bssid = parts[1] if len(parts) >= 2 else None
        elif "signal:" in line:
            m = re.search(r"signal:\s*([-0-9.]+)\s*dBm", line)
            signal = float(m.group(1)) if m else None
        elif "SSID:" in line:
            ssid = line.strip().split("SSID:")[-1].strip()
            if bssid and ssid in color_map and signal is not None:
                if signal > best_signal:
                    best_signal = signal
                    best_bssid = bssid

    if best_bssid and best_bssid != current:
        print(f"Roaming from {current} to {best_bssid} (signal {best_signal} dBm)", flush=True)
        subprocess.call(["sudo", "wpa_cli", "-i", "wlan0", "roam", best_bssid], stdout=subprocess.DEVNULL)


def main():
    color_map, freqs = load_config()
    print(f"Loaded towers: {list(color_map.keys())}", flush=True)
    print(f"Scan frequencies: {freqs}", flush=True)
    last_ssid = None
    while True:
        roam_to_best(color_map, freqs)
        ssid = get_ssid()
        if ssid and ssid != last_ssid:
            last_ssid = ssid
            color = color_map.get(ssid)
            if color:
                led.color = color
                print(f"Connected to {ssid}, LED color set to {color}", flush=True)
            else:
                led.off()
                print(f"{ssid} not in config → LED off", flush=True)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
