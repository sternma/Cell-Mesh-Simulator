#!/bin/bash
set -e

# Default transmit power if not provided (in mBm; 100 mBm = 1 dBm)
DEFAULT_TX_POWER_MBM=1000  # 10 dBm

# Validate arguments
if [ "$#" -lt 4 ] || [ "$#" -gt 5 ]; then
  echo "Usage: $0 <TOWER_ID> <STATIC_IP> <SSID> <CHANNEL> [TX_POWER_MBM]"
  echo "  <TX_POWER_MBM> optional, defaults to ${DEFAULT_TX_POWER_MBM} mBm (10 dBm)"
  echo "Example: $0 1 192.168.50.11 Tower1 1 500   # 5 dBm"
  exit 1
fi

TOWER_ID="$1"
STATIC_IP="$2"
SSID="$3"
CHANNEL="$4"

# Use provided power level or default
TX_POWER_MBM=${5:-$DEFAULT_TX_POWER_MBM}

# 1. Install & stop hostapd
apt update
apt install -y hostapd
systemctl stop hostapd

# 2. Create hostapd systemd override to reset wlan0 before startup
mkdir -p /etc/systemd/system/hostapd.service.d
cat > /etc/systemd/system/hostapd.service.d/override.conf <<EOF
[Unit]
# Wait for the wlan0 device node to be available
After=sys-subsystem-net-devices-wlan0.device
Wants=sys-subsystem-net-devices-wlan0.device

[Service]
# reset the link
ExecStartPre=/bin/sleep 5
ExecStartPre=/usr/sbin/ip link set wlan0 down
ExecStartPre=/usr/sbin/ip link set wlan0 up

RestartSec=5
EOF

# 3. Set wireless country
raspi-config nonint do_wifi_country US

# 4. Mask wpa_supplicant to prevent it from interfering with hostapd
systemctl stop wpa_supplicant || true
systemctl disable wpa_supplicant || true
systemctl mask wpa_supplicant || true

# 5. Configure TX power
# Ensure correct regulatory domain
iw reg set US
# Apply fixed power
iw dev wlan0 set txpower fixed ${TX_POWER_MBM}

# 6. Write hostapd config
HW_MODE="g"
EXTRA=""
if [ "${CHANNEL}" -gt 14 ]; then
  HW_MODE="a"
  EXTRA="country_code=US"
fi

cat > /etc/hostapd/hostapd.conf <<EOF
ctrl_interface=/var/run/hostapd
ctrl_interface_group=netdev

interface=wlan0
driver=nl80211
ssid=${SSID}
hw_mode=${HW_MODE}
channel=${CHANNEL}
${EXTRA}
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=1
wpa=0
EOF

# 7. Point hostapd to its config
sed -i 's|^#DAEMON_CONF.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

# 8. Enable & start hostapd
systemctl unmask hostapd
systemctl enable hostapd
systemctl restart hostapd

# 9. Report
current_power=$(iw dev wlan0 info | grep txpower)
echo "Tower ${TOWER_ID} configured:" 
 echo "  SSID=${SSID}, CHANNEL=${CHANNEL}, IP=${STATIC_IP}" 
 echo "  TX power set to ${TX_POWER_MBM} mBm (${current_power})"
