#!/usr/bin/env python3
import json
import subprocess
import time
import re
from pathlib import Path

import blinkt

# -----------------------
# Configuration
# -----------------------
CONFIG_PATH = Path("/home/pi/cell-mesh-simulator/src/config/tower_led_config.json")
POLL_INTERVAL = 1          # seconds between loops

# Blinkt behavior
BRIGHTNESS = 0.2           # 0.0 - 1.0
SHOW_MODE = "single"       # "single" = one pixel lit per SSID, "all" = all pixels same color
UNKNOWN_MODE = "off"       # "off" or "dim_white"
DISCONNECT_GRACE_SEC = 3.0 # seconds to allow after disconnection before turning off LED
PIXELS = 8                 # Blinkt has 8 LEDs

# WiFi behavior
SCAN_INTERVAL = 2              # seconds between roam evaluations
ROAM_MARGIN_DB = -2.0          # dB; lower = less sticky, higher = more sticky
ROAM_COOLDOWN_SEC = 4.0        # wait after roam before scanning again
SCAN_BACKOFF_SEC = 1.0         # when scan fails, wait a bit
MAX_SCAN_TIME_PER_SSID_SEC = 3 # keep scans short-ish

# Small timings for reliable hard-roams
DISCONNECT_PAUSE_SEC = 0.25
CONNECT_COOLDOWN_SEC = 0.25

# Optionally map towers -> pixel index
TOWER_PIXEL_MAP = {
    "Tower1": 0,
    "Tower2": 1,
    "Tower3": 2,
    "Tower4": 3,
    "Tower5": 4,
    "Tower6": 5,
    "Tower7": 6,
    "Tower8": 7,
    # Tower9/Tower10, etc won't fit on 8 pixels in "single" mode.
    # We'll handle overflow by falling back to "all" mode for those.
}

blinkt.set_clear_on_exit(True)
blinkt.set_brightness(BRIGHTNESS)


# -----------------------
# LED helpers
# -----------------------
def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def float_rgb_to_int(rgb):
    """Convert [0.0-1.0] floats to 0-255 ints."""
    r, g, b = rgb
    return (
        int(round(255 * clamp01(r))),
        int(round(255 * clamp01(g))),
        int(round(255 * clamp01(b))),
    )


def led_clear():
    blinkt.clear()
    blinkt.show()


def led_set_color(rgb_floats, ssid: str | None = None):
    """Apply LED output for the given SSID + RGB."""
    r, g, b = float_rgb_to_int(rgb_floats)

    if SHOW_MODE == "all":
        for i in range(PIXELS):
            blinkt.set_pixel(i, r, g, b)
        blinkt.show()
        return

    # SHOW_MODE == "single"
    blinkt.clear()

    # If tower maps to a pixel, light that one.
    if ssid and ssid in TOWER_PIXEL_MAP:
        idx = TOWER_PIXEL_MAP[ssid]
        blinkt.set_pixel(idx, r, g, b)
        blinkt.show()
        return

    # If we can't map it, fall back to "all"
    for i in range(PIXELS):
        blinkt.set_pixel(i, r, g, b)
    blinkt.show()


def led_unknown():
    """What to show when disconnected or SSID not in config."""
    if UNKNOWN_MODE == "dim_white":
        blinkt.clear()
        for i in range(PIXELS):
            blinkt.set_pixel(i, 10, 10, 10)
        blinkt.show()
    else:
        led_clear()


# -----------------------
# Config + WiFi helpers
# -----------------------
def load_config():
    """
    JSON format:
    {
      "Tower1": {"color": [1.0, 0.0, 0.0], "freq": 2412, "bssid": "aa:bb:..."},
      ...
    }
    Returns:
      color_map: {ssid: (r,g,b)}
      freqs: sorted unique list of freqs
      bssid_map: {bssid_lower: ssid}
    """
    try:
        data = json.loads(CONFIG_PATH.read_text())
        color_map = {}
        freqs = []
        bssid_map = {}

        for ssid, info in data.items():
            if not isinstance(info, dict):
                continue

            color = info.get("color")
            freq = info.get("freq")
            bssid = info.get("bssid")

            if isinstance(color, list) and len(color) == 3:
                color_map[ssid] = tuple(color)

            if isinstance(freq, (int, float)):
                freqs.append(int(freq))

            if isinstance(bssid, str) and re.fullmatch(r"[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}", bssid.strip()):
                bssid_map[bssid.strip().lower()] = ssid

        return color_map, sorted(set(freqs)), bssid_map

    except Exception as e:
        print(f"Error loading config: {e}", flush=True)
        return {}, [], {}


def run(cmd, timeout=None):
    """Run command and return decoded stdout; raises on failure."""
    return subprocess.check_output(
        cmd,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
    ).decode(errors="replace")


def iw_link():
    """
    Return dict {ssid, bssid, signal_dbm} or None if not connected.
    """
    try:
        out = run(["sudo", "iw", "dev", "wlan0", "link"])
    except subprocess.CalledProcessError:
        return None

    if "Not connected." in out:
        return None

    ssid = None
    bssid = None
    signal = None

    m = re.search(r"Connected to ([0-9a-f:]{17})", out, re.I)
    if m:
        bssid = m.group(1).lower()

    m = re.search(r"SSID:\s*(.+)", out)
    if m:
        ssid = m.group(1).strip()

    m = re.search(r"signal:\s*([-0-9]+)\s*dBm", out)
    if m:
        signal = float(m.group(1))

    return {"ssid": ssid, "bssid": bssid, "signal_dbm": signal}


def iw_disconnect():
    subprocess.call(
        ["sudo", "iw", "dev", "wlan0", "disconnect"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def iw_connect(ssid: str) -> int:
    # Hidden SSIDs are fine; iw connect will probe.
    return subprocess.call(
        ["sudo", "iw", "dev", "wlan0", "connect", ssid],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def scan_best_tower_by_bssid(bssid_map, freqs, current_bssid: str | None = None, current_ssid: str | None = None):
    """
    Single scan; collect signal strengths for all towers (by BSSID->tower mapping).
    For the *currently associated* tower:
      - use scan RSSI only if the scan entry is fresh
      - otherwise fall back to iw_link() RSSI

    Returns:
      best_ssid, best_bssid, best_signal_dbm, seen

    Where:
      - best_* is the strongest non-current tower (or None,None,None if none)
      - seen is: {tower_ssid: {"bssid": mac, "signal": dbm, "age_ms": int|None, "source": "scan"|"link"}}
    """
    if not bssid_map:
        return None, None, None, {}

    freq_args = []
    for f in freqs:
        freq_args += ["freq", str(f)]

    cmd = ["sudo", "iw", "dev", "wlan0", "scan"] + freq_args

    try:
        raw = run(cmd, timeout=MAX_SCAN_TIME_PER_SSID_SEC)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return None, None, None, {}

    # Parse scan blocks
    seen = {}  # tower_ssid -> dict(bssid, signal, age_ms, source)
    cur_bssid = None
    cur_signal = None
    cur_age_ms = None

    def commit_current():
        nonlocal cur_bssid, cur_signal, cur_age_ms
        if not cur_bssid or cur_signal is None:
            return
        tower = bssid_map.get(cur_bssid)
        if not tower:
            return

        # Prefer the strongest sample if the same tower appears multiple times
        prev = seen.get(tower)
        if prev is None or cur_signal > prev.get("signal", -9999):
            seen[tower] = {
                "bssid": cur_bssid,
                "signal": float(cur_signal),
                "age_ms": cur_age_ms,
                "source": "scan",
            }

    for line in raw.splitlines():
        if line.startswith("BSS "):
            # flush previous block
            commit_current()

            parts = line.split()
            token = parts[1] if len(parts) >= 2 else ""
            mac = token.split("(")[0].strip().lower()
            cur_bssid = mac if re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac) else None
            cur_signal = None
            cur_age_ms = None

        elif "signal:" in line:
            m = re.search(r"signal:\s*([-0-9.]+)\s*dBm", line)
            if m:
                cur_signal = float(m.group(1))

        elif line.strip().startswith("last seen:") and " ms ago" in line:
            # Example: "last seen: 1573076 ms ago"
            m = re.search(r"last seen:\s*([0-9]+)\s*ms ago", line)
            if m:
                cur_age_ms = int(m.group(1))

    # flush final block
    commit_current()

    # Decide "current tower signal" source:
    # Use scan if fresh enough, else fall back to iw_link().
    # Tune this threshold if you want.
    FRESH_MS = 1500

    current_tower = current_ssid
    if current_bssid:
        current_bssid = current_bssid.lower()

    if current_bssid and current_tower:
        entry = seen.get(current_tower)
        scan_fresh = False
        if entry and entry.get("source") == "scan":
            age = entry.get("age_ms")
            if age is not None and age <= FRESH_MS:
                scan_fresh = True

        if not scan_fresh:
            link = iw_link()
            if link and link.get("bssid") == current_bssid and link.get("signal_dbm") is not None:
                seen[current_tower] = {
                    "bssid": current_bssid,
                    "signal": float(link["signal_dbm"]),
                    "age_ms": None,
                    "source": "link",
                }

    # Pick best non-current tower
    best_ssid = None
    best_bssid = None
    best_signal = -999.0

    for tower, info in seen.items():
        if current_tower and tower == current_tower:
            continue
        sig = info.get("signal")
        if sig is None:
            continue
        if sig > best_signal:
            best_signal = float(sig)
            best_ssid = tower
            best_bssid = info.get("bssid")

    if best_ssid is None:
        return None, None, None, seen

    return best_ssid, best_bssid, best_signal, seen


def scan_best_tower(color_map, freqs):
    """
    For hidden SSIDs, do directed scans per SSID:
      iw dev wlan0 scan ssid <ssid> freq <freq> ...
    Return (best_ssid, best_signal_dbm) among configured towers.
    """
    # build freq args once
    freq_args = []
    for f in freqs:
        freq_args += ["freq", str(f)]

    best_ssid = None
    best_signal = -999.0

    for target_ssid in sorted(color_map.keys()):
        cmd = ["sudo", "iw", "dev", "wlan0", "scan", "ssid", target_ssid] + freq_args
        try:
            raw = run(cmd, timeout=MAX_SCAN_TIME_PER_SSID_SEC)
        except subprocess.TimeoutExpired:
            continue
        except subprocess.CalledProcessError as e:
            # Common during roam/driver churn (e.g. status 245). Back off a bit.
            print(f"Directed scan failed for {target_ssid}: {e}", flush=True)
            time.sleep(SCAN_BACKOFF_SEC)
            continue

        bssid = None
        signal = None
        ssid = None

        for line in raw.splitlines():
            if line.startswith("BSS "):
                parts = line.split()
                token = parts[1] if len(parts) >= 2 else ""
                mac = token.split("(")[0].strip().lower()
                bssid = mac if re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac) else None
                signal = None
                ssid = None

            elif "signal:" in line:
                m = re.search(r"signal:\s*([-0-9.]+)\s*dBm", line)
                signal = float(m.group(1)) if m else None

            elif "SSID:" in line:
                ssid = line.strip().split("SSID:")[-1].strip()

                # accept only the SSID we asked for (ignore \x00... entries)
                if bssid and signal is not None and ssid == target_ssid:
                    if signal > best_signal:
                        best_signal = signal
                        best_ssid = target_ssid

    if best_ssid is None:
        return None, None
    return best_ssid, best_signal


def iw_connect_prefer_bssid(ssid: str, bssid: str | None) -> int:
    # Try to pin to BSSID if supported, fall back to SSID-only.
    if bssid:
        rc = subprocess.call(
            ["sudo", "iw", "dev", "wlan0", "connect", ssid, bssid],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if rc == 0:
            return 0
    return iw_connect(ssid)


def roam_to_best(color_map, freqs, bssid_map, now, last_roam_time):
    """
    Decide whether to roam based on:
      - current tower signal from scan if fresh (else iw_link fallback)
      - best candidate from the same scan
    Then perform "hard roam" via iw disconnect/connect.
    Returns updated last_roam_time.
    """
    if now - last_roam_time < ROAM_COOLDOWN_SEC:
        return last_roam_time

    link = iw_link()
    current_ssid = link["ssid"] if link and link.get("ssid") else None
    current_bssid = link.get("bssid") if link and link.get("bssid") else None

    best_ssid, best_bssid, best_signal, seen = scan_best_tower_by_bssid(
        bssid_map,
        freqs,
        current_bssid=current_bssid,
        current_ssid=current_ssid,
    )
    if not seen:
        return last_roam_time

    # Logging: always include what towers were seen + their strengths
    parts = []
    for tower in sorted(seen.keys()):
        info = seen[tower]
        sig = info.get("signal")
        if sig is None:
            continue
        sig_fmt = int(sig) if float(sig).is_integer() else sig
        if tower == current_ssid and info.get("source") == "link":
            parts.append(f"{tower}={sig_fmt}(link)")
        else:
            parts.append(f"{tower}={sig_fmt}")

    if current_ssid:
        cur_entry = seen.get(current_ssid)
        current_signal = cur_entry.get("signal") if cur_entry else None
        current_source = cur_entry.get("source") if cur_entry else None
        if current_signal is None:
            return last_roam_time

        cur_fmt = int(current_signal) if float(current_signal).is_integer() else current_signal
        cur_suffix = "(link)" if current_source == "link" else ""
        print(f"SCAN: current={current_ssid}({cur_fmt}){cur_suffix} | " + " ".join(parts), flush=True)
    else:
        print("SCAN: current=None | " + " ".join(parts), flush=True)

    if best_ssid is None or best_signal is None:
        return last_roam_time

    # If we're not connected, use the scan result to bootstrap a connection.
    if not current_ssid:
        print(
            f"BOOTSTRAP: connecting to {best_ssid} ({best_signal} dBm) [{best_bssid}]",
            flush=True,
        )
        iw_connect_prefer_bssid(best_ssid, best_bssid)
        time.sleep(CONNECT_COOLDOWN_SEC)
        return now

    # Normal roam logic
    cur_entry = seen.get(current_ssid)
    current_signal = cur_entry.get("signal") if cur_entry else None
    if current_signal is None:
        return last_roam_time

    if best_ssid != current_ssid and best_signal > current_signal + ROAM_MARGIN_DB:
        print(
            f"Roaming: {current_ssid} ({current_signal} dBm) → {best_ssid} ({best_signal} dBm) [{best_bssid}]",
            flush=True,
        )
        iw_disconnect()
        time.sleep(DISCONNECT_PAUSE_SEC)
        iw_connect_prefer_bssid(best_ssid, best_bssid)
        time.sleep(CONNECT_COOLDOWN_SEC)
        return now

    return last_roam_time


def main():
    color_map, freqs, bssid_map = load_config()
    print(f"Loaded towers: {list(color_map.keys())}", flush=True)
    print(f"Scan frequencies: {freqs}", flush=True)

    last_ssid = None
    last_color = None
    last_scan = 0.0
    last_seen_connected = time.time()
    last_roam_time = 0.0

    # Start with LEDs off
    led_clear()

    while True:
        now = time.time()

        if now - last_scan >= SCAN_INTERVAL:
            last_roam_time = roam_to_best(color_map, freqs, bssid_map, now, last_roam_time)
            last_scan = now

        link = iw_link()
        ssid = link["ssid"] if link else None

        if not ssid:
            # Hold last LED briefly during roam churn; only blank after grace.
            if (now - last_seen_connected) >= DISCONNECT_GRACE_SEC:
                if last_ssid is not None:
                    print("Disconnected (no SSID) → LED unknown", flush=True)
                    led_unknown()
                    last_ssid = None
                    last_color = None
            time.sleep(POLL_INTERVAL)
            continue

        last_seen_connected = now

        color = color_map.get(ssid)
        if not color:
            if ssid != last_ssid:
                print(f"{ssid} not in config → LED unknown", flush=True)
            last_ssid = ssid
            last_color = None
            led_unknown()
            time.sleep(POLL_INTERVAL)
            continue

        # Only update LEDs/log if SSID or color changed
        if ssid != last_ssid or color != last_color:
            led_set_color(color, ssid=ssid)
            print(f"Connected to {ssid}, LED set to {color}", flush=True)
            last_ssid = ssid
            last_color = color

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()

