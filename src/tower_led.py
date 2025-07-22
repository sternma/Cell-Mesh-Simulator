#!/usr/bin/env python3
import json
import subprocess
import time
from gpiozero import RGBLED
from pathlib import Path

# LED wiring (GPIO pins)
led = RGBLED(red=17, green=27, blue=22)

# Path to your JSON mapping
CONFIG_PATH = Path("/home/pi/tower_led_config.json")

def load_config():
    """Load SSID→color mapping from JSON file."""
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        # Validate and convert lists to tuples
        return {
            ssid: tuple(color)
            for ssid, color in data.items()
            if isinstance(color, list) and len(color) == 3
        }
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

def get_ssid():
    """Return current associated SSID, or None."""
    try:
        out = subprocess.check_output(["iwgetid", "-r"], stderr=subprocess.DEVNULL)
        return out.decode().strip() or None
    except subprocess.CalledProcessError:
        return None

def main(poll_interval=0.5):
    mapping = load_config()
    last_ssid = None

    while True:
        # reload config each loop in case you edit it on the fly
        mapping = load_config()
        ssid = get_ssid()

        if ssid != last_ssid:
            last_ssid = ssid
            color = mapping.get(ssid)
            if color:
                led.color = color
                print(f"Connected to {ssid}, LED color set to {color}")
            else:
                led.off()
                print(f"{ssid or 'No SSID'} not in config → LED off")

        time.sleep(poll_interval)

if __name__ == "__main__":
    main()
