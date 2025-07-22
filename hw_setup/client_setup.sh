#!/bin/bash
set -e

# Paths to your existing files
CONFIG="/home/pi/cell-mesh-simulator/src/config/tower_led_config.json"
SCRIPT="/home/pi/cell-mesh-simulator/src/tower_led.py"

# 1. Install dependencies
apt update
apt install -y python3-gpiozero wireless-tools jq wpasupplicant

# 2. Check that your config & script exist
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

# 4. Generate wpa_supplicant.conf from JSON SSIDs
WPA_CONF="/etc/wpa_supplicant/wpa_supplicant.conf"
cp "$WPA_CONF" "${WPA_CONF}.bak"
cat > "$WPA_CONF" <<EOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US
EOF

for ssid in $(jq -r 'keys[]' "$CONFIG"); do
  cat >> "$WPA_CONF" <<NET
network={
    ssid="${ssid}"
    key_mgmt=NONE
    scan_ssid=1
    hidden=1
    priority=10
    bgscan="simple:30:-65:300"
}
NET
done

# 5. Create systemd service unit
SERVICE="/etc/systemd/system/tower-led.service"
cat > "$SERVICE" <<EOF
[Unit]
Description=Tower-LED Indicator (dynamic config)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/env python3 $SCRIPT
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
EOF

# 6. Enable & start the service
systemctl daemon-reload
systemctl enable tower-led
systemctl restart tower-led

echo "✅ Client setup complete."
echo "   • Config: $CONFIG"
echo "   • Script: $SCRIPT"
echo "   • Service: tower-led"
