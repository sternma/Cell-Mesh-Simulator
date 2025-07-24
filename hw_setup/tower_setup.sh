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

# 2. Create a dedicated AP interface ap0 from wlan0
ip link set wlan0 down
iw phy phy0 interface add ap0 type ap
ip link set ap0 up

# 3. Configure static IP on ap0
cp /etc/dhcpcd.conf /etc/dhcpcd.conf.bak
cat >> /etc/dhcpcd.conf <<EOF

interface ap0
  static ip_address=${STATIC_IP}/24
  nohook wpa_supplicant
EOF

# 4. Set wireless country
raspi-config nonint do_wifi_country US

# 5. Mask wpa_supplicant to prevent interference
systemctl stop wpa_supplicant
systemctl disable wpa_supplicant
systemctl mask wpa_supplicant

# 6. Configure TX power on ap0
iw reg set US
iw dev ap0 set txpower fixed ${TX_POWER_MBM}

# 7. Write hostapd config for ap0
HW_MODE="g"
EXTRA=""
if [ "${CHANNEL}" -gt 14 ]; then
  HW_MODE="a"
  EXTRA="country_code=US"
fi

cat > /etc/hostapd/hostapd.conf <<EOF
ctrl_interface=/var/run/hostapd
ctrl_interface_group=netdev

interface=ap0
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

# 8. Point hostapd to its config
sed -i 's|^#DAEMON_CONF.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

# 9. Enable & start hostapd
systemctl unmask hostapd
systemctl enable hostapd
systemctl restart hostapd

# 10. Report
current_power=$(iw dev ap0 info | grep txpower)
echo "Tower ${TOWER_ID} configured:" 
 echo "  SSID=${SSID}, CHANNEL=${CHANNEL}, IP=${STATIC_IP}" 
 echo "  TX power set to ${TX_POWER_MBM} mBm (${current_power})"
