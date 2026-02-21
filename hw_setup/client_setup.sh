#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SRC_DIR="${REPO_DIR}/src"
SCRIPT_PATH="${SRC_DIR}/client_roaming_led.py"
TOWER_CONFIG_PATH="${SRC_DIR}/config/client_tower_config.json"

RUNTIME_CONFIG_DIR="/etc/cell-mesh-simulator"
RUNTIME_CONFIG_PATH="${RUNTIME_CONFIG_DIR}/client_roaming_led.json"

SERVICE_NAME="cell-mesh-client"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  cat <<EOF
Usage: sudo hw_setup/client_setup.sh

Installs and configures the client roaming daemon and systemd service.
Creates:
  - ${SERVICE_PATH}
  - ${RUNTIME_CONFIG_PATH}
EOF
  exit 0
fi

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root: sudo hw_setup/client_setup.sh" >&2
  exit 1
fi

echo "Installing client dependencies..."
apt update
apt install -y python3-pip iw rfkill

python3 -m pip install --upgrade pip --break-system-packages
python3 -m pip install blinkt --break-system-packages
python3 -c "import blinkt; print('Blinkt import OK')"

echo "Preparing Wi-Fi interface..."
rfkill unblock wifi || true
if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_wifi_country US || true
else
  echo "Warning: raspi-config not found; skipping country setup" >&2
fi
ip link set wlan0 up || true

echo "Disabling wpa_supplicant to avoid roaming conflicts..."
for unit in wpa_supplicant.service wpa_supplicant@wlan0.service; do
  systemctl stop "${unit}" 2>/dev/null || true
  systemctl disable "${unit}" 2>/dev/null || true
  systemctl mask "${unit}" 2>/dev/null || true
done

if [ ! -f "${SCRIPT_PATH}" ]; then
  echo "Error: client daemon not found at ${SCRIPT_PATH}" >&2
  exit 1
fi
if [ ! -f "${TOWER_CONFIG_PATH}" ]; then
  echo "Error: tower config not found at ${TOWER_CONFIG_PATH}" >&2
  exit 1
fi

chmod 755 "${SCRIPT_PATH}"
chmod 644 "${TOWER_CONFIG_PATH}"

mkdir -p "${RUNTIME_CONFIG_DIR}"
if [ ! -f "${RUNTIME_CONFIG_PATH}" ]; then
  cat > "${RUNTIME_CONFIG_PATH}" <<'EOF'
{
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
  "pixels": 8
}
EOF
  chmod 644 "${RUNTIME_CONFIG_PATH}"
fi

echo "Validating client and tower config files..."
python3 "${SCRIPT_PATH}" \
  --tower-config "${TOWER_CONFIG_PATH}" \
  --runtime-config "${RUNTIME_CONFIG_PATH}" \
  --validate-config \
  --log-level INFO >/dev/null

cat > "${SERVICE_PATH}" <<EOF
[Unit]
Description=Cell Mesh Client Roaming + Blinkt LED
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${SRC_DIR}
ExecStartPre=/sbin/ip link set wlan0 up
ExecStart=/usr/bin/env python3 ${SCRIPT_PATH} --tower-config ${TOWER_CONFIG_PATH} --runtime-config ${RUNTIME_CONFIG_PATH}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "Client setup complete."
echo "  Script: ${SCRIPT_PATH}"
echo "  Service: ${SERVICE_NAME}"
echo "  Tower config: ${TOWER_CONFIG_PATH}"
echo "  Runtime config: ${RUNTIME_CONFIG_PATH}"
echo "  Follow logs: journalctl -u ${SERVICE_NAME} -f -o cat"
