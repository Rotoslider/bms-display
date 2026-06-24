#!/usr/bin/env bash
#
# One-step installer for the Battery Monitor web dashboard.
#
#   Run it like this (from inside this folder):
#       bash setup.sh
#
# It installs what's needed, sets the dashboard to start automatically, and
# prints the web address you can open from your phone or computer.
#
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(id -un)"
SERVICE=/etc/systemd/system/bms-display.service

echo "============================================================"
echo " Battery Monitor — setup"
echo " Folder : $DIR"
echo " User   : $USER_NAME"
echo "============================================================"
echo

echo "[1/6] Installing the bits we need (you may be asked for your password)…"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip bluetooth bluez libglib2.0-0

echo
echo "[2/6] Letting the program use Bluetooth…"
sudo usermod -aG bluetooth "$USER_NAME" || true
sudo systemctl enable --now bluetooth || true

echo
echo "[3/6] Setting up Python in a tidy, self-contained folder…"
python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install --upgrade pip >/dev/null
"$DIR/venv/bin/pip" install -r "$DIR/requirements.txt"

echo
echo "[4/6] Preparing your settings file…"
if [ ! -f "$DIR/config.json" ]; then
  cp "$DIR/config.example.json" "$DIR/config.json"
  echo "      Created config.json from the example."
  echo "      >>> IMPORTANT: edit config.json and add your batteries. <<<"
  echo "      Find their addresses with:   $DIR/venv/bin/python $DIR/scan.py"
else
  echo "      config.json already exists — leaving it alone."
fi

echo
echo "[5/6] Installing the auto-start service…"
sed -e "s#__USER__#$USER_NAME#g" -e "s#__DIR__#$DIR#g" \
    "$DIR/systemd/bms-display.service" | sudo tee "$SERVICE" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable bms-display
sudo systemctl restart bms-display

echo
echo "[6/6] Done!"
PORT="$(python3 -c "import json;print(json.load(open('$DIR/config.json'))['web'].get('port',8080))" 2>/dev/null || echo 8080)"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "============================================================"
echo " Open the dashboard in any web browser on your network:"
echo
echo "     http://${IP:-your-pi-ip}:$PORT"
echo "     http://$(hostname).local:$PORT"
echo
echo " If you still need to add your batteries:"
echo "   1) $DIR/venv/bin/python $DIR/scan.py     (find their addresses)"
echo "   2) nano $DIR/config.json                 (add them, then save)"
echo "   3) sudo systemctl restart bms-display"
echo
echo " Check on it any time with:  systemctl status bms-display"
echo "============================================================"
