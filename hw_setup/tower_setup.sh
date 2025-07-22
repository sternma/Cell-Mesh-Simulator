#!/bin/bash
set -e

if [ "$#" -ne 4 ]; then
  echo "Usage: $0 <TOWER_ID> <STATIC_IP> <SSID> <CHANNEL>"
  echo "Example: $0 1 192.168.50.11 Tower1 1"
  exit 1
fi

TOWER_ID="$1"
STATIC_IP="$2"
SSID="$3"
CHANNEL="$4"

# 1. Install & stop hostapd
apt update
apt install -y hostapd
systemctl stop hostapd

# 2. Configure static IP on wlan0
cp /etc/dhcpcd.conf /etc/dhcpcd.conf.bak
cat >> /etc/dhcpcd.conf <<EOF

interface wlan0
  static ip_address=${STATIC_IP}/24
  nohook wpa_supplicant
EOF

# 3. Set wireless country
raspi-config nonint do_wifi_country US

# 4. Write hostapd config
HW_MODE="g"
EXTRA=""
if [ "${CHANNEL}" -gt 14 ]; then
  HW_MODE="a"
  EXTRA="country_code=US"
fi

cat > /etc/hostapd/hostapd.conf <<EOF
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

# 5. Point hostapd to its config
sed -i 's|^#DAEMON_CONF.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

# 6. Enable & start
systemctl unmask hostapd
systemctl enable hostapd
systemctl restart hostapd

echo "Tower ${TOWER_ID} configured:"
echo "  SSID=${SSID}, CHANNEL=${CHANNEL}, IP=${STATIC_IP}"
