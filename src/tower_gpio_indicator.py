#!/usr/bin/env python3
import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

from gpiozero import OutputDevice

DEFAULT_CONFIG_PATH = Path("/etc/cell-mesh-simulator/tower_gpio_indicator.json")
DEFAULT_INTERFACE = "wlan0"
DEFAULT_PINS = [18, 13, 12]
DEFAULT_ON_MASK = [0, 1, 0]
DEFAULT_POLL_INTERVAL_SEC = 1.0

_stop = False


def _on_signal(_signum, _frame):
    global _stop
    _stop = True


def _validate_pin_list(value, field_name):
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty list")
    out = []
    for item in value:
        if not isinstance(item, int):
            raise ValueError(f"{field_name} entries must be integers")
        if item < 0:
            raise ValueError(f"{field_name} entries must be >= 0")
        out.append(item)
    return out


def _validate_mask(value, expected_len):
    if not isinstance(value, list) or len(value) != expected_len:
        raise ValueError("on_mask must be a list with one entry per pin")
    out = []
    for item in value:
        if item not in (0, 1):
            raise ValueError("on_mask entries must be 0 or 1")
        out.append(bool(item))
    return out


def load_config(config_path: Path):
    cfg = {
        "interface": DEFAULT_INTERFACE,
        "pins": list(DEFAULT_PINS),
        "on_mask": list(DEFAULT_ON_MASK),
        "poll_interval_sec": DEFAULT_POLL_INTERVAL_SEC,
    }

    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        if not isinstance(user_cfg, dict):
            raise ValueError("config root must be an object")
        cfg.update(user_cfg)

    interface = cfg.get("interface", DEFAULT_INTERFACE)
    if not isinstance(interface, str) or not interface.strip():
        raise ValueError("interface must be a non-empty string")

    pins = _validate_pin_list(cfg.get("pins", DEFAULT_PINS), "pins")
    mask = _validate_mask(cfg.get("on_mask", DEFAULT_ON_MASK), len(pins))

    poll_interval = cfg.get("poll_interval_sec", DEFAULT_POLL_INTERVAL_SEC)
    if not isinstance(poll_interval, (int, float)) or poll_interval <= 0:
        raise ValueError("poll_interval_sec must be a positive number")

    return interface.strip(), pins, mask, float(poll_interval)


def connected_station_count(interface: str):
    try:
        result = subprocess.run(
            ["iw", "dev", interface, "station", "dump"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"WARN: unable to read stations on {interface}: {e}", flush=True)
        return None

    count = 0
    for line in result.stdout.splitlines():
        if line.lstrip().startswith("Station "):
            count += 1
    return count


def set_gpio_state(devices, on_mask, is_connected: bool):
    for dev, enabled_when_connected in zip(devices, on_mask):
        if is_connected and enabled_when_connected:
            dev.on()
        else:
            dev.off()


def main():
    parser = argparse.ArgumentParser(
        description="Tower GPIO indicator: turn GPIO outputs on when any client is connected."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to JSON config (default: {DEFAULT_CONFIG_PATH})",
    )
    args = parser.parse_args()

    try:
        interface, pins, on_mask, poll_interval = load_config(args.config)
    except Exception as e:
        print(f"Error loading config: {e}", flush=True)
        return 1

    devices = [OutputDevice(pin, active_high=True, initial_value=False) for pin in pins]
    set_gpio_state(devices, on_mask, is_connected=False)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    print(
        f"GPIO indicator started: interface={interface}, pins={pins}, on_mask={[int(x) for x in on_mask]}, poll={poll_interval}s",
        flush=True,
    )

    last_connected = None
    last_count = None
    try:
        while not _stop:
            count = connected_station_count(interface)
            if count is not None:
                connected = count > 0
                if connected != last_connected or count != last_count:
                    set_gpio_state(devices, on_mask, is_connected=connected)
                    state = "ON" if connected else "OFF"
                    print(
                        f"Clients connected: {count} -> GPIO {state}",
                        flush=True,
                    )
                    last_connected = connected
                    last_count = count
            time.sleep(poll_interval)
    finally:
        set_gpio_state(devices, on_mask, is_connected=False)
        for dev in devices:
            dev.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
