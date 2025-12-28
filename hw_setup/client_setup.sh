#!/bin/bash
set -e

# Paths to your existing files
CONFIG="/home/pi/cell-mesh-simulator/src/config/tower_led_config.json"
SCRIPT="/home/pi/cell-mesh-simulator/src/tower_led.py"

# 1. Install dependencies
apt update
apt install -y python3-pip wireless-tools jq wpasupplicant

python3 -m pip install --upgrade pip --break-system-packages
python3 -m pip install blinkt --break-system-packages

python3 -c "import blinkt; print('Blinkt import OK')"

# 1a. Unblock Wi-Fi if soft-blocked
 echo "Unblocking Wi-Fi..."
 rfkill unblock wifi || true

# 1b. Set Wi-Fi country to US (persist across reboots)
 echo "Setting Wi-Fi country to US..."
 raspi-config nonint do_wifi_country US

# 2. Check that your config & script exist Check that your config & script exist
if [ ! -f "$CONFIG" ]; then
  echo "Error: Config file not found at $CONFIG" >&2
  exit 1
fi
if [ ! -f "$SCRIPT" ]; then
  echo "Error: Python script not found at $SCRIPT" >&2
  exit 1
fi

# 3. Set ownership & permissions
chown pi:pi "$CONFIG" "$SCRIPT"
chmod 644 "$CONFIG"
chmod +x  "$SCRIPT"

# 4. Generate wpa_supplicant global config
GLOBAL_CONF="/etc/wpa_supplicant/wpa_supplicant.conf"
INTERF_CONF="/etc/wpa_supplicant/wpa_supplicant-wlan0.conf"
cp "$GLOBAL_CONF" "${GLOBAL_CONF}.bak"
cat > "$GLOBAL_CONF" <<EOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US
EOF
for ssid in $(jq -r 'keys[]' "$CONFIG"); do
  cat >> "$GLOBAL_CONF" <<NET
network={
    ssid="${ssid}"
    key_mgmt=NONE
    scan_ssid=1
    priority=10
    bgscan="learn:1:-70:5"
}
NET
done

# 5. Create interface-specific config
cp "$GLOBAL_CONF" "$INTERF_CONF"
chmod 644 "$INTERF_CONF"

# 6. Setup wpa_supplicant: disable global, enable per-interface
echo "Configuring wpa_supplicant service for wlan0..."
systemctl stop wpa_supplicant.service || true
systemctl disable wpa_supplicant.service || true
systemctl enable wpa_supplicant@wlan0.service
systemctl restart wpa_supplicant@wlan0.service

# 7. Create tower-led systemd service
SERVICE="/etc/systemd/system/tower-led.service"
cat > "$SERVICE" <<EOF
[Unit]
Description=Tower-LED Indicator (dynamic config)
After=network-online.target wpa_supplicant@wlan0.service
Wants=network-online.target wpa_supplicant@wlan0.service

[Service]
User=pi
WorkingDirectory=/home/pi/cell-mesh-simulator/src
ExecStart=/usr/bin/env python3 $SCRIPT
Restart=always
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 8. Enable & start tower-led service
systemctl daemon-reload
systemctl enable tower-led
systemctl restart tower-led

# Final status
echo "✅ Client setup complete."
echo "   • Config: $CONFIG"
echo "   • Script: $SCRIPT"
echo "   • Services: wpa_supplicant@wlan0, tower-led"
