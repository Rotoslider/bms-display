#!/usr/bin/env python3
"""
Find your batteries. Lists every Bluetooth device the Pi can see, so you can pick
out your battery's address and put it in config.json.

Run:  python3 scan.py

Your batteries usually show up with a name that matches the serial number printed
on the battery label (and an address starting A4:C1:37 for the common JBD module).
Copy the address (the AA:BB:CC:DD:EE:FF part) into config.json.
"""
import asyncio
from bleak import BleakScanner


async def main():
    print("Scanning for 15 seconds… (make sure the batteries are on)\n")
    devices = await BleakScanner.discover(timeout=15.0)
    if not devices:
        print("No Bluetooth devices found. Is Bluetooth on? Are the batteries awake?")
        return
    print(f"{'ADDRESS':<20}  NAME")
    print("-" * 45)
    for d in sorted(devices, key=lambda x: (x.name or "zzz")):
        print(f"{d.address:<20}  {d.name or '(no name)'}")
    print("\nPut the address(es) of your batteries into config.json under \"batteries\".")


if __name__ == "__main__":
    asyncio.run(main())
