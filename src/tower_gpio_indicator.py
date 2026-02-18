#!/usr/bin/env python3
import argparse
import json
import logging
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

from gpiozero import OutputDevice

DEFAULT_CONFIG_PATH = Path("/etc/cell-mesh-simulator/tower_gpio_indicator.json")
DEFAULT_INTERFACE = "wlan0"
DEFAULT_PINS = (18, 13, 12)
DEFAULT_ON_MASK = (False, True, False)
DEFAULT_POLL_INTERVAL_SEC = 1.0
IW_TIMEOUT_SEC = 3
VALID_CONFIG_KEYS = {"interface", "pins", "on_mask", "poll_interval_sec"}
STATION_LINE_RE = re.compile(r"^\s*Station\s+")

LOGGER = logging.getLogger("tower_gpio_indicator")


@dataclass(frozen=True)
class IndicatorConfig:
    interface: str
    pins: tuple[int, ...]
    on_mask: tuple[bool, ...]
    poll_interval_sec: float


def _validate_pin_list(value: Any, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty list")
    out: list[int] = []
    for item in value:
        if not isinstance(item, int) or isinstance(item, bool):
            raise ValueError(f"{field_name} entries must be integers")
        if item < 0:
            raise ValueError(f"{field_name} entries must be >= 0")
        out.append(item)
    return tuple(out)


def _validate_mask(value: Any, expected_len: int) -> tuple[bool, ...]:
    if not isinstance(value, list) or len(value) != expected_len:
        raise ValueError("on_mask must be a list with one entry per pin")
    out: list[bool] = []
    for item in value:
        if isinstance(item, bool):
            out.append(item)
            continue
        if isinstance(item, int) and item in (0, 1):
            out.append(bool(item))
            continue
        raise ValueError("on_mask entries must be bool or 0/1")
    return tuple(out)


def load_config(config_path: Path) -> IndicatorConfig:
    cfg = {
        "interface": DEFAULT_INTERFACE,
        "pins": list(DEFAULT_PINS),
        "on_mask": [int(x) for x in DEFAULT_ON_MASK],
        "poll_interval_sec": DEFAULT_POLL_INTERVAL_SEC,
    }

    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        if not isinstance(user_cfg, dict):
            raise ValueError("config root must be an object")
        unknown = sorted(set(user_cfg.keys()) - VALID_CONFIG_KEYS)
        if unknown:
            LOGGER.warning("Ignoring unknown config keys: %s", ", ".join(unknown))
        cfg.update(user_cfg)
    else:
        LOGGER.warning("Config %s not found; using defaults", config_path)

    interface = cfg.get("interface", DEFAULT_INTERFACE)
    if not isinstance(interface, str) or not interface.strip():
        raise ValueError("interface must be a non-empty string")

    pins = _validate_pin_list(cfg.get("pins", DEFAULT_PINS), "pins")
    mask = _validate_mask(cfg.get("on_mask", DEFAULT_ON_MASK), len(pins))

    poll_interval = cfg.get("poll_interval_sec", DEFAULT_POLL_INTERVAL_SEC)
    if not isinstance(poll_interval, (int, float)) or poll_interval <= 0:
        raise ValueError("poll_interval_sec must be a positive number")

    return IndicatorConfig(
        interface=interface.strip(),
        pins=pins,
        on_mask=mask,
        poll_interval_sec=float(poll_interval),
    )


def connected_station_count(interface: str) -> int:
    result = subprocess.run(
        ["iw", "dev", interface, "station", "dump"],
        check=True,
        capture_output=True,
        text=True,
        timeout=IW_TIMEOUT_SEC,
    )
    return sum(1 for line in result.stdout.splitlines() if STATION_LINE_RE.match(line))


def set_gpio_state(devices: list[OutputDevice], on_mask: tuple[bool, ...], is_connected: bool) -> None:
    for dev, enabled_when_connected in zip(devices, on_mask):
        if is_connected and enabled_when_connected:
            dev.on()
        else:
            dev.off()


def build_devices(pins: tuple[int, ...]) -> list[OutputDevice]:
    devices: list[OutputDevice] = []
    try:
        for pin in pins:
            devices.append(OutputDevice(pin, active_high=True, initial_value=False))
    except Exception:
        for dev in devices:
            dev.close()
        raise
    return devices


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> int:
    configure_logging()

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
        config = load_config(args.config)
    except Exception as e:
        LOGGER.error("Failed to load config: %s", e)
        return 1

    try:
        devices = build_devices(config.pins)
    except Exception as e:
        LOGGER.error("Failed to initialize GPIO output pins %s: %s", list(config.pins), e)
        return 1

    set_gpio_state(devices, config.on_mask, is_connected=False)

    stop_event = Event()

    def on_signal(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    LOGGER.info(
        "Started: interface=%s, pins=%s, on_mask=%s, poll=%.3fs",
        config.interface,
        list(config.pins),
        [int(x) for x in config.on_mask],
        config.poll_interval_sec,
    )

    last_connected: bool | None = None
    last_count: int | None = None
    poll_error_active = False

    try:
        while not stop_event.is_set():
            try:
                count = connected_station_count(config.interface)
                if poll_error_active:
                    LOGGER.info("Station polling recovered on %s", config.interface)
                    poll_error_active = False
            except FileNotFoundError:
                LOGGER.error("'iw' command not found; install wireless tools on this host")
                return 1
            except subprocess.TimeoutExpired:
                if not poll_error_active:
                    LOGGER.warning("Timed out polling stations on %s", config.interface)
                    poll_error_active = True
                stop_event.wait(config.poll_interval_sec)
                continue
            except subprocess.CalledProcessError as e:
                if not poll_error_active:
                    stderr = (e.stderr or "").strip()
                    detail = stderr if stderr else str(e)
                    LOGGER.warning("Failed polling stations on %s: %s", config.interface, detail)
                    poll_error_active = True
                stop_event.wait(config.poll_interval_sec)
                continue

            connected = count > 0
            if connected != last_connected or count != last_count:
                set_gpio_state(devices, config.on_mask, is_connected=connected)
                state = "ON" if connected else "OFF"
                LOGGER.info("Clients connected=%d -> GPIO %s", count, state)
                last_connected = connected
                last_count = count

            stop_event.wait(config.poll_interval_sec)
    finally:
        set_gpio_state(devices, config.on_mask, is_connected=False)
        for dev in devices:
            dev.close()
        LOGGER.info("Stopped; GPIO outputs cleared")

    return 0


if __name__ == "__main__":
    sys.exit(main())
