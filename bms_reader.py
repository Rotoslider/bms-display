#!/usr/bin/env python3
"""
JBD / Xiaoxiang BLE BMS reader (read-only).

This is the same battery-reading core used by the bms-mqtt-ha project, with the
MQTT parts removed. It connects to a battery over Bluetooth Low Energy, asks for
pack info (register 0x03) and per-cell voltages (0x04), and returns a plain dict.

It NEVER writes any settings to the BMS — it only reads.
"""

import asyncio

from bleak import BleakClient, BleakScanner

FF01 = "0000ff01-0000-1000-8000-00805f9b34fb"  # notify (BMS -> us)
FF02 = "0000ff02-0000-1000-8000-00805f9b34fb"  # write  (us -> BMS)


# ---------------------------------------------------------------------------
# JBD protocol helpers
# ---------------------------------------------------------------------------
def build_cmd(reg: int) -> bytes:
    """Read-register request: DD A5 <reg> 00 <chkH> <chkL> 77."""
    body = bytes([reg, 0x00])
    chk = (0x10000 - sum(body)) & 0xFFFF
    return bytes([0xDD, 0xA5]) + body + bytes([chk >> 8, chk & 0xFF, 0x77])


def u16(d, i):
    return int.from_bytes(d[i:i + 2], "big", signed=False)


def s16(d, i):
    return int.from_bytes(d[i:i + 2], "big", signed=True)


def frame_complete(buf: bytearray) -> bool:
    return len(buf) >= 4 and buf[0] == 0xDD and len(buf) >= 7 + buf[3]


def validate(frame: bytes) -> bool:
    """Verify start/end markers, status OK, and checksum over status+len+data."""
    if len(frame) < 7 or frame[0] != 0xDD or frame[-1] != 0x77:
        return False
    ln = frame[3]
    if len(frame) < 7 + ln or frame[2] != 0x00:
        return False
    chk = (0x10000 - sum(frame[2:4 + ln])) & 0xFFFF
    got = u16(frame, 4 + ln)
    return chk == got


PROT_BITS = [
    "Cell overvolt", "Cell undervolt", "Pack overvolt", "Pack undervolt",
    "Charge overtemp", "Charge undertemp", "Discharge overtemp", "Discharge undertemp",
    "Charge overcurrent", "Discharge overcurrent", "Short circuit", "IC error",
    "FET locked",
]


def decode_protection(bits: int) -> str:
    if not bits:
        return "None"
    flags = [name for i, name in enumerate(PROT_BITS) if bits & (1 << i)]
    return ", ".join(flags) if flags else f"0x{bits:04X}"


def parse_basic(frame: bytes) -> dict:
    d = frame[4:4 + frame[3]]
    nntc = d[22]
    temps = [round((u16(d, 23 + 2 * i) - 2731) / 10.0, 1) for i in range(nntc)]
    fet = d[20]
    prot = u16(d, 16)
    out = {
        "voltage": round(u16(d, 0) / 100.0, 2),
        "current": round(s16(d, 2) / 100.0, 2),
        "remaining_ah": round(u16(d, 4) / 100.0, 2),
        "nominal_ah": round(u16(d, 6) / 100.0, 2),
        "cycles": u16(d, 8),
        "balance_bits": u16(d, 12) | (u16(d, 14) << 16),
        "protection_raw": prot,
        "soc": d[19],
        "num_cells": d[21],
        "fet_charge": bool(fet & 0x01),
        "fet_discharge": bool(fet & 0x02),
    }
    out["power"] = round(out["voltage"] * out["current"], 1)
    for i, t in enumerate(temps):
        out[f"temp_{i + 1}"] = t
    out["temps"] = temps
    if temps:
        out["temp_max"] = max(temps)
        out["temp_min"] = min(temps)
    out["balancing"] = bool(out["balance_bits"])
    out["protection"] = decode_protection(prot)
    out["problem"] = bool(prot)
    return out


def parse_cells(frame: bytes) -> dict:
    d = frame[4:4 + frame[3]]
    n = frame[3] // 2
    mv = [u16(d, 2 * i) for i in range(n)]
    out = {"cells_mv": mv}
    if mv:
        out["cell_min_mv"] = min(mv)
        out["cell_max_mv"] = max(mv)
        out["cell_avg_mv"] = round(sum(mv) / len(mv), 1)
        out["cell_delta_mv"] = max(mv) - min(mv)
        out["cell_min_no"] = mv.index(min(mv)) + 1
        out["cell_max_no"] = mv.index(max(mv)) + 1
    return out


# ---------------------------------------------------------------------------
# BLE read
# ---------------------------------------------------------------------------
async def read_battery(mac: str, poll: dict) -> dict:
    buf = bytearray()
    ev = asyncio.Event()

    def cb(_sender, data):
        buf.extend(data)
        if frame_complete(buf):
            ev.set()

    async def query(reg: int) -> bytes:
        buf.clear()
        ev.clear()
        await client.write_gatt_char(FF02, build_cmd(reg), response=False)
        await asyncio.wait_for(ev.wait(), poll["notify_timeout"])
        frame = bytes(buf[:7 + buf[3]])
        if not validate(frame):
            raise ValueError(f"bad frame for reg 0x{reg:02x}: {frame.hex()}")
        return frame

    # Discover the device fresh (refreshes BlueZ cache). If it isn't advertising
    # right now (e.g. a stale connection is holding it), fall back to connecting
    # by address, which can still attach via BlueZ's device cache.
    device = await BleakScanner.find_device_by_address(
        mac, timeout=poll.get("find_timeout", 8))
    target = device if device is not None else mac

    client = BleakClient(target, timeout=poll["connect_timeout"])
    await client.connect()
    try:
        await asyncio.sleep(poll["settle_seconds"])  # BMS needs a moment before notifications flow
        await client.start_notify(FF01, cb)
        data = {}
        data.update(parse_basic(await query(0x03)))
        data.update(parse_cells(await query(0x04)))
        return data
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def read_battery_retry(mac: str, poll: dict, name: str = "") -> dict:
    attempts = poll.get("attempts", 3)
    last = None
    for i in range(attempts):
        try:
            return await read_battery(mac, poll)
        except Exception as e:
            last = e
            await asyncio.sleep(poll.get("retry_seconds", 3))
    raise last if last else RuntimeError("unknown read failure")
