#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

BLINKT_IMPORT_ERROR: Exception | None = None
try:
    import blinkt
except Exception as exc:  # pragma: no cover - hardware/lib dependent
    blinkt = None  # type: ignore[assignment]
    BLINKT_IMPORT_ERROR = exc

LOGGER = logging.getLogger("client_roaming_led")

SRC_DIR = Path(__file__).resolve().parent
DEFAULT_TOWER_CONFIG_PATH = SRC_DIR / "config" / "client_tower_config.json"
DEFAULT_RUNTIME_CONFIG_PATH = Path("/etc/cell-mesh-simulator/client_roaming_led.json")

BSSID_RE = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")
SCAN_BSS_RE = re.compile(r"^BSS\s+([0-9a-f:]{17})\(", re.IGNORECASE)
SCAN_SIGNAL_RE = re.compile(r"signal:\s*([-0-9.]+)\s*dBm", re.IGNORECASE)
SCAN_LAST_SEEN_RE = re.compile(r"last seen:\s*([0-9]+)\s*ms ago", re.IGNORECASE)
LINK_BSSID_RE = re.compile(r"Connected to ([0-9a-f:]{17})", re.IGNORECASE)
LINK_SSID_RE = re.compile(r"SSID:\s*(.+)")
LINK_SIGNAL_RE = re.compile(r"signal:\s*([-0-9.]+)\s*dBm", re.IGNORECASE)


@dataclass(frozen=True)
class RuntimeConfig:
    interface: str
    poll_interval_sec: float
    scan_interval_sec: float
    scan_timeout_sec: float
    roam_margin_db: float
    roam_cooldown_sec: float
    scan_freshness_ms: int
    disconnect_grace_sec: float
    disconnect_pause_sec: float
    connect_cooldown_sec: float
    brightness: float
    unknown_mode: str
    signal_min_dbm: float
    signal_max_dbm: float
    pixels: int


@dataclass(frozen=True)
class Tower:
    ssid: str
    bssid: str
    color: tuple[float, float, float]
    freq: int


@dataclass(frozen=True)
class LinkState:
    ssid: str
    bssid: str
    signal_dbm: float | None


@dataclass(frozen=True)
class SeenTower:
    ssid: str
    bssid: str
    signal_dbm: float
    age_ms: int | None
    source: str  # "scan" or "link"


DEFAULT_RUNTIME_CONFIG = {
    "interface": "wlan0",
    "poll_interval_sec": 1.0,
    "scan_interval_sec": 2.0,
    "scan_timeout_sec": 3.0,
    "roam_margin_db": -2.0,
    "roam_cooldown_sec": 4.0,
    "scan_freshness_ms": 1500,
    "disconnect_grace_sec": 3.0,
    "disconnect_pause_sec": 0.25,
    "connect_cooldown_sec": 0.25,
    "brightness": 0.2,
    "unknown_mode": "off",
    "signal_min_dbm": -90.0,
    "signal_max_dbm": -20.0,
    "pixels": 8,
}


class IwClient:
    def __init__(self, interface: str, timeout_sec: float) -> None:
        self.interface = interface
        self.timeout_sec = timeout_sec

    def _run(self, args: list[str], timeout_sec: float | None = None) -> str:
        timeout = self.timeout_sec if timeout_sec is None else timeout_sec
        result = subprocess.run(
            ["iw", "dev", self.interface] + args,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout

    def link(self) -> LinkState | None:
        out = self._run(["link"])
        if "Not connected." in out:
            return None

        m_bssid = LINK_BSSID_RE.search(out)
        m_ssid = LINK_SSID_RE.search(out)
        if not m_bssid or not m_ssid:
            return None

        bssid = m_bssid.group(1).lower()
        ssid = m_ssid.group(1).strip()
        signal_dbm: float | None = None
        m_signal = LINK_SIGNAL_RE.search(out)
        if m_signal:
            signal_dbm = float(m_signal.group(1))

        return LinkState(ssid=ssid, bssid=bssid, signal_dbm=signal_dbm)

    def scan(self, freqs: list[int], timeout_sec: float) -> str:
        args = ["scan"]
        for freq in freqs:
            args.extend(["freq", str(freq)])
        return self._run(args, timeout_sec=timeout_sec)

    def disconnect(self) -> None:
        timeout = max(self.timeout_sec, 5.0)
        subprocess.run(
            ["iw", "dev", self.interface, "disconnect"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def connect(self, ssid: str, bssid: str | None = None) -> bool:
        timeout = max(self.timeout_sec, 8.0)
        cmd = ["iw", "dev", self.interface, "connect", ssid]
        if bssid:
            cmd.append(bssid)
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True
        if bssid:
            result = subprocess.run(
                ["iw", "dev", self.interface, "connect", ssid],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode == 0
        return False


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def float_rgb_to_int(rgb: tuple[float, float, float]) -> tuple[int, int, int]:
    r, g, b = rgb
    return (
        int(round(255 * clamp01(r))),
        int(round(255 * clamp01(g))),
        int(round(255 * clamp01(b))),
    )


def signal_to_led_count(signal_dbm: float | None, cfg: RuntimeConfig) -> int:
    if signal_dbm is None:
        return 1
    lo = cfg.signal_min_dbm
    hi = cfg.signal_max_dbm
    if hi <= lo:
        return cfg.pixels
    normalized = clamp01((signal_dbm - lo) / (hi - lo))
    return int(normalized * (cfg.pixels - 1)) + 1


def led_clear() -> None:
    if blinkt is None:
        return
    blinkt.clear()
    blinkt.show()


def led_unknown(cfg: RuntimeConfig) -> None:
    if blinkt is None:
        return
    if cfg.unknown_mode == "dim_white":
        blinkt.clear()
        for i in range(cfg.pixels):
            blinkt.set_pixel(i, 10, 10, 10)
        blinkt.show()
        return
    led_clear()


def led_set_strength_color(color: tuple[float, float, float], signal_dbm: float | None, cfg: RuntimeConfig) -> int:
    if blinkt is None:
        return 0
    r, g, b = float_rgb_to_int(color)
    count = signal_to_led_count(signal_dbm, cfg)
    blinkt.clear()
    for i in range(count):
        blinkt.set_pixel(i, r, g, b)
    blinkt.show()
    return count


def _coerce_numeric(value: Any, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    return float(value)


def load_runtime_config(runtime_config_path: Path, interface_override: str | None) -> RuntimeConfig:
    cfg = dict(DEFAULT_RUNTIME_CONFIG)

    if runtime_config_path.exists():
        user_cfg = json.loads(runtime_config_path.read_text(encoding="utf-8"))
        if not isinstance(user_cfg, dict):
            raise ValueError("runtime config root must be an object")
        unknown_keys = sorted(set(user_cfg.keys()) - set(DEFAULT_RUNTIME_CONFIG.keys()))
        if unknown_keys:
            LOGGER.warning("Ignoring unknown runtime config keys: %s", ", ".join(unknown_keys))
        cfg.update(user_cfg)
    else:
        LOGGER.warning("Runtime config %s not found; using defaults", runtime_config_path)

    if interface_override:
        cfg["interface"] = interface_override

    interface = cfg.get("interface")
    if not isinstance(interface, str) or not interface.strip():
        raise ValueError("interface must be a non-empty string")

    unknown_mode = cfg.get("unknown_mode")
    if unknown_mode not in ("off", "dim_white"):
        raise ValueError("unknown_mode must be either 'off' or 'dim_white'")

    brightness = _coerce_numeric(cfg.get("brightness"), "brightness")
    if not 0.0 <= brightness <= 1.0:
        raise ValueError("brightness must be between 0.0 and 1.0")

    pixels_f = _coerce_numeric(cfg.get("pixels"), "pixels")
    if int(pixels_f) != pixels_f or int(pixels_f) <= 0:
        raise ValueError("pixels must be a positive integer")
    pixels = int(pixels_f)

    poll_interval_sec = _coerce_numeric(cfg.get("poll_interval_sec"), "poll_interval_sec")
    scan_interval_sec = _coerce_numeric(cfg.get("scan_interval_sec"), "scan_interval_sec")
    scan_timeout_sec = _coerce_numeric(cfg.get("scan_timeout_sec"), "scan_timeout_sec")
    roam_margin_db = _coerce_numeric(cfg.get("roam_margin_db"), "roam_margin_db")
    roam_cooldown_sec = _coerce_numeric(cfg.get("roam_cooldown_sec"), "roam_cooldown_sec")
    disconnect_grace_sec = _coerce_numeric(cfg.get("disconnect_grace_sec"), "disconnect_grace_sec")
    disconnect_pause_sec = _coerce_numeric(cfg.get("disconnect_pause_sec"), "disconnect_pause_sec")
    connect_cooldown_sec = _coerce_numeric(cfg.get("connect_cooldown_sec"), "connect_cooldown_sec")
    signal_min_dbm = _coerce_numeric(cfg.get("signal_min_dbm"), "signal_min_dbm")
    signal_max_dbm = _coerce_numeric(cfg.get("signal_max_dbm"), "signal_max_dbm")
    scan_freshness_ms_f = _coerce_numeric(cfg.get("scan_freshness_ms"), "scan_freshness_ms")

    if any(
        value <= 0
        for value in (
            poll_interval_sec,
            scan_interval_sec,
            scan_timeout_sec,
            roam_cooldown_sec,
            disconnect_grace_sec,
            connect_cooldown_sec,
        )
    ):
        raise ValueError("interval and cooldown values must be positive")
    if disconnect_pause_sec < 0:
        raise ValueError("disconnect_pause_sec must be >= 0")
    if signal_max_dbm <= signal_min_dbm:
        raise ValueError("signal_max_dbm must be greater than signal_min_dbm")
    if scan_freshness_ms_f < 0 or int(scan_freshness_ms_f) != scan_freshness_ms_f:
        raise ValueError("scan_freshness_ms must be a non-negative integer")

    return RuntimeConfig(
        interface=interface.strip(),
        poll_interval_sec=poll_interval_sec,
        scan_interval_sec=scan_interval_sec,
        scan_timeout_sec=scan_timeout_sec,
        roam_margin_db=roam_margin_db,
        roam_cooldown_sec=roam_cooldown_sec,
        scan_freshness_ms=int(scan_freshness_ms_f),
        disconnect_grace_sec=disconnect_grace_sec,
        disconnect_pause_sec=disconnect_pause_sec,
        connect_cooldown_sec=connect_cooldown_sec,
        brightness=brightness,
        unknown_mode=unknown_mode,
        signal_min_dbm=signal_min_dbm,
        signal_max_dbm=signal_max_dbm,
        pixels=pixels,
    )


def _validate_color(color: Any, ssid: str) -> tuple[float, float, float]:
    if not isinstance(color, list) or len(color) != 3:
        raise ValueError(f"{ssid}: color must be a 3-element list")
    vals: list[float] = []
    for idx, item in enumerate(color):
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise ValueError(f"{ssid}: color[{idx}] must be numeric")
        vals.append(clamp01(float(item)))
    return vals[0], vals[1], vals[2]


def load_tower_config(tower_config_path: Path) -> tuple[dict[str, Tower], dict[str, str], list[int]]:
    if not tower_config_path.exists():
        raise FileNotFoundError(f"tower config not found: {tower_config_path}")

    raw = json.loads(tower_config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("tower config root must be an object")

    towers: dict[str, Tower] = {}
    bssid_map: dict[str, str] = {}
    freqs: set[int] = set()

    for ssid, info in raw.items():
        if not isinstance(ssid, str) or not ssid.strip():
            LOGGER.warning("Skipping entry with invalid SSID key: %r", ssid)
            continue
        if not isinstance(info, dict):
            LOGGER.warning("Skipping %s: entry must be an object", ssid)
            continue

        try:
            color = _validate_color(info.get("color"), ssid)

            freq = info.get("freq")
            if not isinstance(freq, (int, float)) or isinstance(freq, bool):
                raise ValueError("freq must be numeric")
            freq_int = int(freq)
            if freq_int <= 0:
                raise ValueError("freq must be > 0")

            bssid = info.get("bssid")
            if not isinstance(bssid, str):
                raise ValueError("bssid must be a string")
            bssid_norm = bssid.strip().lower()
            if not BSSID_RE.fullmatch(bssid_norm):
                raise ValueError(f"invalid bssid format: {bssid!r}")
        except ValueError as exc:
            LOGGER.warning("Skipping %s: %s", ssid, exc)
            continue

        tower = Tower(ssid=ssid.strip(), bssid=bssid_norm, color=color, freq=freq_int)
        towers[tower.ssid] = tower
        bssid_map[bssid_norm] = tower.ssid
        freqs.add(freq_int)

    if not towers:
        raise ValueError("tower config contains no valid tower entries")

    return towers, bssid_map, sorted(freqs)


def parse_scan_seen_towers(scan_output: str, bssid_map: dict[str, str]) -> dict[str, SeenTower]:
    seen: dict[str, SeenTower] = {}
    cur_bssid: str | None = None
    cur_signal: float | None = None
    cur_age_ms: int | None = None

    def commit_current() -> None:
        nonlocal cur_bssid, cur_signal, cur_age_ms
        if cur_bssid is None or cur_signal is None:
            return
        ssid = bssid_map.get(cur_bssid)
        if not ssid:
            return
        prev = seen.get(ssid)
        if prev is None or cur_signal > prev.signal_dbm:
            seen[ssid] = SeenTower(
                ssid=ssid,
                bssid=cur_bssid,
                signal_dbm=float(cur_signal),
                age_ms=cur_age_ms,
                source="scan",
            )

    for line in scan_output.splitlines():
        m_bss = SCAN_BSS_RE.search(line)
        if m_bss:
            commit_current()
            cur_bssid = m_bss.group(1).lower()
            cur_signal = None
            cur_age_ms = None
            continue

        if cur_bssid is None:
            continue

        m_signal = SCAN_SIGNAL_RE.search(line)
        if m_signal:
            cur_signal = float(m_signal.group(1))
            continue

        m_age = SCAN_LAST_SEEN_RE.search(line)
        if m_age:
            cur_age_ms = int(m_age.group(1))

    commit_current()
    return seen


def maybe_fill_current_from_link(
    seen: dict[str, SeenTower],
    current: LinkState | None,
    cfg: RuntimeConfig,
    bssid_map: dict[str, str],
) -> None:
    if current is None:
        return
    if bssid_map.get(current.bssid) != current.ssid:
        return
    if current.signal_dbm is None:
        return

    existing = seen.get(current.ssid)
    if existing and existing.source == "scan" and existing.age_ms is not None and existing.age_ms <= cfg.scan_freshness_ms:
        return

    seen[current.ssid] = SeenTower(
        ssid=current.ssid,
        bssid=current.bssid,
        signal_dbm=float(current.signal_dbm),
        age_ms=None,
        source="link",
    )


def pick_best_non_current(seen: dict[str, SeenTower], current_ssid: str | None) -> SeenTower | None:
    best: SeenTower | None = None
    for entry in seen.values():
        if current_ssid and entry.ssid == current_ssid:
            continue
        if best is None or entry.signal_dbm > best.signal_dbm:
            best = entry
    return best


def log_scan_state(current: LinkState | None, seen: dict[str, SeenTower]) -> None:
    parts: list[str] = []
    for ssid in sorted(seen.keys()):
        entry = seen[ssid]
        sig = int(entry.signal_dbm) if entry.signal_dbm.is_integer() else entry.signal_dbm
        suffix = "(link)" if entry.source == "link" else ""
        parts.append(f"{ssid}={sig}{suffix}")

    if current is None:
        LOGGER.info("SCAN current=None | %s", " ".join(parts))
        return

    cur = seen.get(current.ssid)
    if cur:
        sig = int(cur.signal_dbm) if cur.signal_dbm.is_integer() else cur.signal_dbm
        suffix = "(link)" if cur.source == "link" else ""
        LOGGER.info("SCAN current=%s(%s)%s | %s", current.ssid, sig, suffix, " ".join(parts))
    else:
        LOGGER.info("SCAN current=%s(unknown) | %s", current.ssid, " ".join(parts))


def maybe_roam(
    iw: IwClient,
    cfg: RuntimeConfig,
    bssid_map: dict[str, str],
    freqs: list[int],
    now_monotonic: float,
    last_roam_time: float,
) -> float:
    if now_monotonic - last_roam_time < cfg.roam_cooldown_sec:
        return last_roam_time

    current = iw.link()
    scan_output = iw.scan(freqs, timeout_sec=cfg.scan_timeout_sec)
    seen = parse_scan_seen_towers(scan_output, bssid_map)
    maybe_fill_current_from_link(seen, current, cfg, bssid_map)
    current_managed = current is not None and bssid_map.get(current.bssid) == current.ssid

    if not seen:
        LOGGER.info("SCAN saw no configured towers")
        return last_roam_time

    log_scan_state(current, seen)
    best = pick_best_non_current(seen, current.ssid if current_managed and current else None)
    if best is None:
        return last_roam_time

    if not current_managed:
        if current is not None:
            LOGGER.info("Current network %s is unmanaged; switching to configured tower", current.ssid)
            iw.disconnect()
            if cfg.disconnect_pause_sec > 0:
                time.sleep(cfg.disconnect_pause_sec)
        LOGGER.info("BOOTSTRAP connect -> %s (%.1f dBm) [%s]", best.ssid, best.signal_dbm, best.bssid)
        if iw.connect(best.ssid, best.bssid):
            time.sleep(cfg.connect_cooldown_sec)
            return now_monotonic
        LOGGER.warning("Bootstrap connect failed: ssid=%s bssid=%s", best.ssid, best.bssid)
        return last_roam_time

    assert current is not None
    cur_seen = seen.get(current.ssid)
    if cur_seen is None:
        return last_roam_time

    if best.ssid != current.ssid and best.signal_dbm > (cur_seen.signal_dbm + cfg.roam_margin_db):
        LOGGER.info(
            "ROAM %s(%.1f dBm) -> %s(%.1f dBm) [%s]",
            current.ssid,
            cur_seen.signal_dbm,
            best.ssid,
            best.signal_dbm,
            best.bssid,
        )
        iw.disconnect()
        if cfg.disconnect_pause_sec > 0:
            time.sleep(cfg.disconnect_pause_sec)
        if iw.connect(best.ssid, best.bssid):
            time.sleep(cfg.connect_cooldown_sec)
            return now_monotonic
        LOGGER.warning("Roam connect failed: ssid=%s bssid=%s", best.ssid, best.bssid)
        LOGGER.info("Attempting recovery reconnect to current SSID %s", current.ssid)
        iw.connect(current.ssid, current.bssid)

    return last_roam_time


def run_diagnostics(
    iw: IwClient,
    cfg: RuntimeConfig,
    towers: dict[str, Tower],
    bssid_map: dict[str, str],
    freqs: list[int],
) -> int:
    LOGGER.info("DIAG start")
    LOGGER.info("DIAG interface=%s towers=%d freqs=%s", cfg.interface, len(towers), freqs)

    try:
        link = iw.link()
        if link is None:
            LOGGER.info("DIAG link: not connected")
        else:
            LOGGER.info("DIAG link: ssid=%s bssid=%s signal=%s", link.ssid, link.bssid, link.signal_dbm)
    except Exception as exc:
        LOGGER.error("DIAG failed to read link state: %s", exc)
        return 1

    try:
        scan_output = iw.scan(freqs, timeout_sec=cfg.scan_timeout_sec)
        seen = parse_scan_seen_towers(scan_output, bssid_map)
        maybe_fill_current_from_link(seen, link, cfg, bssid_map)
        if not seen:
            LOGGER.warning("DIAG scan: no configured towers detected")
        else:
            for ssid in sorted(seen.keys()):
                entry = seen[ssid]
                LOGGER.info(
                    "DIAG tower=%s bssid=%s signal=%.1f source=%s age_ms=%s",
                    entry.ssid,
                    entry.bssid,
                    entry.signal_dbm,
                    entry.source,
                    entry.age_ms,
                )
    except Exception as exc:
        LOGGER.error("DIAG scan failed: %s", exc)
        return 1

    LOGGER.info("DIAG complete")
    return 0


def run_daemon(
    iw: IwClient,
    cfg: RuntimeConfig,
    towers: dict[str, Tower],
    bssid_map: dict[str, str],
    freqs: list[int],
) -> int:
    if blinkt is None:
        LOGGER.error("Blinkt module import failed: %s", BLINKT_IMPORT_ERROR)
        return 1

    blinkt.set_clear_on_exit(True)
    blinkt.set_brightness(cfg.brightness)
    led_clear()

    stop_event = Event()

    def handle_signal(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    LOGGER.info(
        "Started interface=%s towers=%d freqs=%s brightness=%.2f unknown_mode=%s",
        cfg.interface,
        len(towers),
        freqs,
        cfg.brightness,
        cfg.unknown_mode,
    )

    last_scan = 0.0
    last_roam_time = 0.0
    last_seen_connected = time.monotonic()
    last_visual_key: tuple[Any, ...] | None = None
    scan_error_active = False

    try:
        while not stop_event.is_set():
            now = time.monotonic()

            if now - last_scan >= cfg.scan_interval_sec:
                try:
                    last_roam_time = maybe_roam(iw, cfg, bssid_map, freqs, now, last_roam_time)
                    scan_error_active = False
                except FileNotFoundError:
                    LOGGER.error("'iw' command not found")
                    return 1
                except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                    if not scan_error_active:
                        LOGGER.warning("Scan/roam step failed: %s", exc)
                        scan_error_active = True
                except Exception as exc:
                    LOGGER.exception("Unexpected scan/roam error: %s", exc)
                last_scan = now

            link: LinkState | None
            try:
                link = iw.link()
            except FileNotFoundError:
                LOGGER.error("'iw' command not found")
                return 1
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                LOGGER.warning("Link read failed: %s", exc)
                link = None

            if link is None:
                if now - last_seen_connected >= cfg.disconnect_grace_sec:
                    visual_key = ("unknown", cfg.unknown_mode)
                    if visual_key != last_visual_key:
                        led_unknown(cfg)
                        LOGGER.info("Disconnected -> LED unknown")
                        last_visual_key = visual_key
                stop_event.wait(cfg.poll_interval_sec)
                continue

            last_seen_connected = now
            tower = towers.get(link.ssid)
            if tower is None:
                visual_key = ("unknown_ssid", link.ssid)
                if visual_key != last_visual_key:
                    led_unknown(cfg)
                    LOGGER.info("Connected to SSID not in config: %s -> LED unknown", link.ssid)
                    last_visual_key = visual_key
                stop_event.wait(cfg.poll_interval_sec)
                continue

            level = signal_to_led_count(link.signal_dbm, cfg)
            visual_key = ("tower", tower.ssid, level)
            if visual_key != last_visual_key:
                led_set_strength_color(tower.color, link.signal_dbm, cfg)
                sig_str = f"{link.signal_dbm:.0f} dBm" if link.signal_dbm is not None else "unknown"
                LOGGER.info("Connected %s RSSI=%s LEDs=%d/%d", tower.ssid, sig_str, level, cfg.pixels)
                last_visual_key = visual_key

            stop_event.wait(cfg.poll_interval_sec)
    finally:
        led_clear()
        LOGGER.info("Stopped; LEDs cleared")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Client roaming + Blinkt LED daemon")
    parser.add_argument(
        "--tower-config",
        type=Path,
        default=DEFAULT_TOWER_CONFIG_PATH,
        help=f"Tower mapping JSON path (default: {DEFAULT_TOWER_CONFIG_PATH})",
    )
    parser.add_argument(
        "--runtime-config",
        type=Path,
        default=DEFAULT_RUNTIME_CONFIG_PATH,
        help=f"Runtime options JSON path (default: {DEFAULT_RUNTIME_CONFIG_PATH})",
    )
    parser.add_argument("--interface", type=str, default=None, help="Wi-Fi interface override (e.g. wlan0)")
    parser.add_argument("--diagnose", action="store_true", help="Run environment scan/link diagnostics then exit")
    parser.add_argument("--validate-config", action="store_true", help="Validate config files then exit")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level (DEBUG, INFO, WARNING, ERROR)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.log_level)

    try:
        cfg = load_runtime_config(args.runtime_config, args.interface)
        towers, bssid_map, freqs = load_tower_config(args.tower_config)
    except Exception as exc:
        LOGGER.error("Configuration error: %s", exc)
        return 1

    iw = IwClient(interface=cfg.interface, timeout_sec=cfg.scan_timeout_sec)

    if args.validate_config:
        LOGGER.info("Config validation passed: towers=%d freqs=%s", len(towers), freqs)
        return 0

    if args.diagnose:
        return run_diagnostics(iw, cfg, towers, bssid_map, freqs)

    return run_daemon(iw, cfg, towers, bssid_map, freqs)


if __name__ == "__main__":
    sys.exit(main())
