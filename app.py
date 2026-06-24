#!/usr/bin/env python3
"""
Battery BMS -> local web dashboard.

Reads your JBD/Xiaoxiang BLE battery BMSs over Bluetooth and serves a simple,
auto-refreshing web page on your local network. No cloud, no MQTT, no Solar
Assistant required. Open it from any phone/tablet/computer on the same network,
or show it full-screen on a monitor plugged into the Pi (see kiosk/).

Run:  python3 app.py        (normally started by the systemd service)
"""

import asyncio
import json
import logging
import os
import threading
import time

from flask import Flask, jsonify, render_template

import bms_reader

LOG = logging.getLogger("bms-display")
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("BMS_DISPLAY_CONFIG", os.path.join(HERE, "config.json"))

app = Flask(__name__)

# Shared, latest-known reading per battery. Guarded by LOCK.
STATE = {}          # bid -> {"name","data","ts","error"}
LOCK = threading.Lock()
CONFIG = {}


def load_config():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    cfg.setdefault("web", {})
    cfg.setdefault("poll", {})
    cfg["web"].setdefault("title", "Battery Monitor")
    cfg["web"].setdefault("port", 8080)
    cfg["web"].setdefault("poll_seconds", 60)     # gap between full rounds
    cfg["web"].setdefault("refresh_seconds", 5)   # how often the browser re-fetches
    cfg["web"].setdefault("stale_seconds", 0)     # 0 = auto (2 rounds + a margin)
    for b in cfg["batteries"]:
        b["bid"] = b["mac"].replace(":", "").lower()[-6:]
    return cfg


def poller(cfg):
    """Background thread: round-robin read every battery forever."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    poll = cfg["poll"]
    while True:
        for batt in cfg["batteries"]:
            bid = batt["bid"]
            try:
                data = loop.run_until_complete(
                    bms_reader.read_battery_retry(batt["mac"], poll, batt["name"]))
                with LOCK:
                    STATE[bid] = {"name": batt["name"], "data": data,
                                  "ts": time.time(), "error": None}
                LOG.info("[%s] %.2fV %.2fA SOC %d%% d=%dmV",
                         batt["name"], data["voltage"], data["current"],
                         data["soc"], data.get("cell_delta_mv", 0))
            except Exception as e:
                msg = str(e) or type(e).__name__
                with LOCK:
                    prev = STATE.get(bid, {})
                    STATE[bid] = {"name": batt["name"], "data": prev.get("data"),
                                  "ts": prev.get("ts"), "error": msg}
                LOG.warning("[%s] read failed: %s", batt["name"], msg)
            time.sleep(poll.get("gap_seconds", 1.5))
        time.sleep(max(1, cfg["web"].get("poll_seconds", 60)))


def stale_after(cfg):
    s = cfg["web"].get("stale_seconds", 0)
    if s:
        return s
    n = max(1, len(cfg["batteries"]))
    per = cfg["poll"].get("gap_seconds", 1.5) + cfg["poll"].get("connect_timeout", 12)
    return int(2 * (n * per + cfg["web"].get("poll_seconds", 60)) + 30)


@app.route("/")
def index():
    return render_template("index.html",
                           title=CONFIG["web"]["title"],
                           refresh=CONFIG["web"]["refresh_seconds"])


@app.route("/api/data")
def api_data():
    now = time.time()
    stale = stale_after(CONFIG)
    out = []
    currents, socs, deltas, temps, cellmins, cellmaxs, volts = [], [], [], [], [], [], []
    with LOCK:
        for batt in CONFIG["batteries"]:
            st = STATE.get(batt["bid"], {})
            data = st.get("data")
            ts = st.get("ts")
            age = int(now - ts) if ts else None
            online = bool(data) and age is not None and age <= stale
            out.append({
                "bid": batt["bid"],
                "name": batt["name"],
                "online": online,
                "age_s": age,
                "error": st.get("error"),
                "data": data,
            })
            if online and data:
                volts.append(data["voltage"])
                currents.append(data["current"])
                socs.append(data["soc"])
                if "cell_delta_mv" in data:
                    deltas.append(data["cell_delta_mv"])
                    cellmins.append(data["cell_min_mv"])
                    cellmaxs.append(data["cell_max_mv"])
                if data.get("temps"):
                    temps.extend(data["temps"])
    summary = {
        "pack_count": len(out),
        "online_count": sum(1 for b in out if b["online"]),
        "bank_voltage": round(sum(volts) / len(volts), 2) if volts else None,
        "total_current": round(sum(currents), 2) if currents else None,
        "total_power": round(sum(volts[i] * currents[i] for i in range(len(volts))), 0) if volts else None,
        "avg_soc": round(sum(socs) / len(socs)) if socs else None,
        "max_delta_mv": max(deltas) if deltas else None,
        "min_cell_mv": min(cellmins) if cellmins else None,
        "max_cell_mv": max(cellmaxs) if cellmaxs else None,
        "max_temp": max(temps) if temps else None,
    }
    return jsonify({"updated": int(now), "summary": summary, "batteries": out})


def main():
    global CONFIG
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    CONFIG = load_config()
    with LOCK:
        for b in CONFIG["batteries"]:
            STATE[b["bid"]] = {"name": b["name"], "data": None, "ts": None,
                               "error": "starting up..."}
    threading.Thread(target=poller, args=(CONFIG,), daemon=True).start()
    port = int(CONFIG["web"]["port"])
    LOG.info("web dashboard on http://0.0.0.0:%d  (open it from any device on your network)", port)
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=4)
    except ImportError:
        # waitress not installed -> fall back to Flask's built-in server
        app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
