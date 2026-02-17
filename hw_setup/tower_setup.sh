#!/bin/bash
set -e

# Default transmit power if not provided (in mBm; 100 mBm = 1 dBm)
DEFAULT_TX_POWER_MBM=1000  # 10 dBm
DEFAULT_GPIO_PINS="18,13,12"
DEFAULT_GPIO_ON_MASK="0,1,0"
DEFAULT_GPIO_POLL_INTERVAL_SEC="1.0"

usage() {
  cat <<EOF
Usage: $0 <TOWER_ID> <SSID> <CHANNEL> [TX_POWER_MBM] [OPTIONS]

Arguments:
  <TOWER_ID>       numeric label used for logging
  <SSID>           AP SSID to broadcast
  <CHANNEL>        Wi-Fi channel number
  [TX_POWER_MBM]   optional, defaults to ${DEFAULT_TX_POWER_MBM} mBm (10 dBm)

Options (optional):
  --enable-gpio-indicator        enable tower-side GPIO station indicator service
  --gpio-pins <CSV>              GPIO pin list; default ${DEFAULT_GPIO_PINS}
  --gpio-on-mask <CSV>           0/1 mask aligned to pins; default ${DEFAULT_GPIO_ON_MASK}
  --gpio-poll-interval <SEC>     poll interval in seconds; default ${DEFAULT_GPIO_POLL_INTERVAL_SEC}
  -h, --help                     show this help text

Examples:
  $0 1 Tower1 1 500
  $0 1 Tower1 1 --enable-gpio-indicator
  $0 1 Tower1 1 500 --enable-gpio-indicator --gpio-pins 18,13,12 --gpio-on-mask 0,1,0
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ "$#" -lt 3 ]; then
  usage
  exit 1
fi

TOWER_ID="$1"
SSID="$2"
CHANNEL="$3"
shift 3

TX_POWER_MBM="$DEFAULT_TX_POWER_MBM"
if [ "$#" -gt 0 ] && [[ "$1" != --* ]]; then
  TX_POWER_MBM="$1"
  shift
fi

ENABLE_GPIO_INDICATOR=0
GPIO_PINS_CSV="$DEFAULT_GPIO_PINS"
GPIO_ON_MASK_CSV="$DEFAULT_GPIO_ON_MASK"
GPIO_POLL_INTERVAL_SEC="$DEFAULT_GPIO_POLL_INTERVAL_SEC"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --enable-gpio-indicator)
      ENABLE_GPIO_INDICATOR=1
      shift
      ;;
    --gpio-pins)
      if [ -z "${2:-}" ]; then
        echo "Error: --gpio-pins requires a value" >&2
        exit 1
      fi
      GPIO_PINS_CSV="$2"
      ENABLE_GPIO_INDICATOR=1
      shift 2
      ;;
    --gpio-on-mask)
      if [ -z "${2:-}" ]; then
        echo "Error: --gpio-on-mask requires a value" >&2
        exit 1
      fi
      GPIO_ON_MASK_CSV="$2"
      ENABLE_GPIO_INDICATOR=1
      shift 2
      ;;
    --gpio-poll-interval)
      if [ -z "${2:-}" ]; then
        echo "Error: --gpio-poll-interval requires a value" >&2
        exit 1
      fi
      GPIO_POLL_INTERVAL_SEC="$2"
      ENABLE_GPIO_INDICATOR=1
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown option '$1'" >&2
      usage
      exit 1
      ;;
  esac
done

if ! [[ "$CHANNEL" =~ ^[0-9]+$ ]]; then
  echo "Error: CHANNEL must be numeric" >&2
  exit 1
fi
if ! [[ "$TX_POWER_MBM" =~ ^[0-9]+$ ]]; then
  echo "Error: TX_POWER_MBM must be numeric" >&2
  exit 1
fi

if [ "$ENABLE_GPIO_INDICATOR" -eq 1 ]; then
  if ! [[ "$GPIO_PINS_CSV" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
    echo "Error: --gpio-pins must be a comma-separated list of integers" >&2
    exit 1
  fi
  if ! [[ "$GPIO_ON_MASK_CSV" =~ ^[01](,[01])*$ ]]; then
    echo "Error: --gpio-on-mask must be a comma-separated list of 0/1 values" >&2
    exit 1
  fi
  pin_count=$(awk -F, '{print NF}' <<<"$GPIO_PINS_CSV")
  mask_count=$(awk -F, '{print NF}' <<<"$GPIO_ON_MASK_CSV")
  if [ "$pin_count" -ne "$mask_count" ]; then
    echo "Error: --gpio-pins and --gpio-on-mask must have the same number of entries" >&2
    exit 1
  fi
  if ! [[ "$GPIO_POLL_INTERVAL_SEC" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "Error: --gpio-poll-interval must be a positive number" >&2
    exit 1
  fi
fi

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
sudo raspi-config nonint do_wifi_country US

# 4. Mask wpa_supplicant to prevent it from interfering with hostapd
sudo systemctl stop wpa_supplicant || true
sudo systemctl disable wpa_supplicant || true
sudo systemctl mask wpa_supplicant || true

# 5. Configure TX power
# Ensure correct regulatory domain
sudo iw reg set US
# Apply fixed power
sudo iw dev wlan0 set txpower fixed ${TX_POWER_MBM}

# 6. Write hostapd config
HW_MODE="g"
if [ "${CHANNEL}" -gt 14 ]; then
  HW_MODE="a"
fi

cat > /etc/hostapd/hostapd.conf <<EOF
ctrl_interface=/var/run/hostapd
ctrl_interface_group=netdev

interface=wlan0
driver=nl80211
ssid=${SSID}
hw_mode=${HW_MODE}
channel=${CHANNEL}
country_code=US
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
sleep 1
sudo iw reg set US
sudo iw dev wlan0 set txpower fixed ${TX_POWER_MBM}

# 9. Optional tower-side GPIO indicator
if [ "$ENABLE_GPIO_INDICATOR" -eq 1 ]; then
  GPIO_SCRIPT="/home/pi/cell-mesh-simulator/src/tower_gpio_indicator.py"
  GPIO_CONFIG_DIR="/etc/cell-mesh-simulator"
  GPIO_CONFIG_PATH="${GPIO_CONFIG_DIR}/tower_gpio_indicator.json"
  GPIO_SERVICE="/etc/systemd/system/tower-gpio-indicator.service"

  if [ ! -f "$GPIO_SCRIPT" ]; then
    echo "Error: GPIO script not found at $GPIO_SCRIPT" >&2
    exit 1
  fi

  apt install -y python3-gpiozero

  mkdir -p "$GPIO_CONFIG_DIR"
  GPIO_PINS_JSON="[${GPIO_PINS_CSV//,/, }]"
  GPIO_ON_MASK_JSON="[${GPIO_ON_MASK_CSV//,/, }]"

  cat > "$GPIO_CONFIG_PATH" <<EOF
{
  "interface": "wlan0",
  "pins": ${GPIO_PINS_JSON},
  "on_mask": ${GPIO_ON_MASK_JSON},
  "poll_interval_sec": ${GPIO_POLL_INTERVAL_SEC}
}
EOF

  cat > "$GPIO_SERVICE" <<EOF
[Unit]
Description=Tower GPIO Indicator (client connected state)
After=hostapd.service
Wants=hostapd.service

[Service]
Type=simple
ExecStart=/usr/bin/env python3 ${GPIO_SCRIPT} --config ${GPIO_CONFIG_PATH}
Restart=always
RestartSec=2
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable tower-gpio-indicator
  systemctl restart tower-gpio-indicator
fi

# 10. Report
current_power=$(iw dev wlan0 info | grep txpower)
echo "Tower ${TOWER_ID} configured:" 
echo "  SSID=${SSID}, CHANNEL=${CHANNEL}" 
echo "  TX power set to ${TX_POWER_MBM} mBm (${current_power})"
if [ "$ENABLE_GPIO_INDICATOR" -eq 1 ]; then
  echo "  GPIO indicator: enabled (pins=${GPIO_PINS_CSV}, on_mask=${GPIO_ON_MASK_CSV}, poll=${GPIO_POLL_INTERVAL_SEC}s)"
else
  echo "  GPIO indicator: disabled"
fi
