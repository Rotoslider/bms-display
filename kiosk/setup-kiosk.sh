#!/usr/bin/env bash
#
# OPTIONAL: make a monitor plugged into the Pi show the dashboard full-screen,
# automatically, every time the Pi turns on.
#
# Use this ONLY if your Pi boots to a desktop (Raspberry Pi OS *with desktop*).
# If your Pi has no screen, skip this — just open the web address from your phone.
#
#   Run it like this (from inside the project folder):
#       bash kiosk/setup-kiosk.sh
#
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="$(python3 -c "import json;print(json.load(open('$DIR/config.json'))['web'].get('port',8080))" 2>/dev/null || echo 8080)"
URL="http://localhost:$PORT"

echo "Installing a web browser for the screen…"
sudo apt-get update -y
sudo apt-get install -y chromium-browser unclutter 2>/dev/null \
  || sudo apt-get install -y chromium unclutter

# pick whichever chromium command exists
BROWSER="$(command -v chromium-browser || command -v chromium)"

mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/bms-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Battery Monitor (kiosk)
Exec=$BROWSER --kiosk --noerrdialogs --disable-infobars --incognito --check-for-update-interval=31536000 $URL
X-GNOME-Autostart-enabled=true
EOF

# hide the mouse cursor when idle (nice for a wall display)
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/unclutter.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Hide cursor
Exec=unclutter -idle 3
X-GNOME-Autostart-enabled=true
EOF

echo
echo "Done. Reboot the Pi (sudo reboot) and the screen will open the dashboard"
echo "full-screen by itself. To exit kiosk mode, press Alt+F4 or Ctrl+W."
echo "Showing: $URL"
