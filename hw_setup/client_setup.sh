#!/bin/bash
set -e
#NOTE: RUN WITH SUDO

# Paths to your existing files
CONFIG="/home/pi/cell-mesh-simulator/src/config/tower_led_config.json"
SCRIPT="/home/pi/cell-mesh-simulator/src/tower_led.py"

# 1. Install dependencies
apt update
apt install -y python3-pip iw rfkill jq

python3 -m pip install --upgrade pip --break-system-packages
python3 -m pip install blinkt --break-system-packages

python3 -c "import blinkt; print('Blinkt import OK')"

# 1a. Unblock Wi-Fi if soft-blocked
echo "Unblocking Wi-Fi..."
rfkill unblock wifi || true

# 1b. Set Wi-Fi country to US (persist across reboots)
echo "Setting Wi-Fi country to US..."
raspi-config nonint do_wifi_country US

# 1c. Bring wlan0 up (best-effort)
echo "Bringing wlan0 up..."
ip link set wlan0 up || true

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

# 4. Create tower-led systemd service
SERVICE="/etc/systemd/system/tower-led.service"
cat > "$SERVICE" <<EOF
[Unit]
Description=Tower-LED Indicator (dynamic config)
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/cell-mesh-simulator/src

# Make sure the interface exists and is up before python starts.
# This is best-effort; python will still handle reconnects.
ExecStartPre=/sbin/ip link set wlan0 up

ExecStart=/usr/bin/env python3 $SCRIPT
Restart=always
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 5. Enable & start tower-led service
systemctl daemon-reload
systemctl enable tower-led
systemctl restart tower-led

# Final status
echo "✅ Client setup complete."
echo "   • Config: $CONFIG"
echo "   • Script: $SCRIPT"
echo "   • Services: tower-led"

