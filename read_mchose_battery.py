#!/usr/bin/env python3
"""MCHOSE A5 V2 Ultra Legacy HID battery/profile helpers and CLI probe."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Iterable

try:
    import hid  # type: ignore[import-not-found]  # Package name: hidapi
except ImportError:  # Keep pure protocol helpers importable for tests/tools.
    hid = None

VENDOR_IDS = (0x3837, 0x5253)
SUPPORTED_PRODUCT_IDS = (0x100C,)
CONFIG_USAGE_PAGE = 0xFF01
REPORT_ID = 0x11
PAYLOAD_LENGTH = 20
LONG_REPORT_ID = 0x12
LONG_PAYLOAD_LENGTH = 64
COMMAND_STATUS = 0x06
COMMAND_PROFILE_STATE = 0x67
RETRY_DELAYS_SECONDS = (0.025, 0.040, 0.065, 0.100, 0.150, 0.220)


@dataclass(frozen=True)
class BatteryStatus:
    vendor_id: int
    product_id: int
    firmware_raw: int
    connection_mode: int
    connection_active: bool
    battery_percent: int
    charging: bool

    @property
    def connection_name(self) -> str:
        return {0: "wired USB", 1: "2.4G", 2: "Bluetooth"}.get(
            self.connection_mode, f"unknown ({self.connection_mode})"
        )


def require_hid():
    if hid is None:
        raise RuntimeError("缺少 hidapi；请运行：py -m pip install hidapi")
    return hid


def is_supported_candidate(info: dict) -> bool:
    """Restrict access to the tested receiver model and configuration collection."""
    return (
        info.get("vendor_id") in VENDOR_IDS
        and info.get("product_id") in SUPPORTED_PRODUCT_IDS
        and info.get("usage_page") == CONFIG_USAGE_PAGE
    )


def hex_bytes(values: Iterable[int]) -> str:
    return " ".join(f"{value:02X}" for value in values)


def xor_ff(values: Iterable[int]) -> list[int]:
    return [value ^ 0xFF for value in values]


def describe_device(info: dict) -> str:
    product = info.get("product_string") or "unknown product"
    manufacturer = info.get("manufacturer_string") or "unknown manufacturer"
    return (
        f"VID:PID={info['vendor_id']:04X}:{info['product_id']:04X} "
        f"product={product!r}, manufacturer={manufacturer!r}, "
        f"interface={info.get('interface_number')}, usage_page={info.get('usage_page')}"
    )


def normalize_feature_reply(reply: list[int], report_id: int = REPORT_ID) -> list[int]:
    """Return bytes after the HID report ID, regardless of hidapi behavior."""
    if reply and reply[0] == report_id:
        return reply[1:]
    return reply


def decode_status(reply: list[int], request_payload: list[int]) -> BatteryStatus | None:
    """Validate and decode a 0x11/0x06 response; return None for stale data."""
    payload = normalize_feature_reply(reply)
    if len(payload) < 12 or payload[:PAYLOAD_LENGTH] == request_payload:
        return None
    decoded = xor_ff(payload)
    if decoded[0] != COMMAND_STATUS:
        return None
    data = decoded[1:]
    battery = data[9]
    if battery > 100:
        return None
    return BatteryStatus(
        vendor_id=data[0] | (data[1] << 8),
        product_id=data[2] | (data[3] << 8),
        firmware_raw=int.from_bytes(bytes(data[4:8]), "little"),
        connection_mode=data[8] & 0x07,
        connection_active=bool((data[8] >> 3) & 0x01),
        battery_percent=battery,
        charging=bool(data[10]),
    )


def _matches_candidate(status: BatteryStatus, info: dict) -> bool:
    """The receiver reports an internal device identity, not its USB VID/PID.

    Therefore identity cannot be compared byte-for-byte with enumeration data.
    Candidate safety is instead enforced by tested USB VID/PID/usage collection,
    while this validates that a meaningful embedded identity was returned.
    """
    return is_supported_candidate(info) and bool(status.vendor_id and status.product_id)


def legacy_write(info: dict, command: list[int]) -> None:
    """Send one documented Legacy command to a previously verified interface."""
    if not command or len(command) > PAYLOAD_LENGTH:
        raise ValueError("Invalid Legacy command length")
    if not is_supported_candidate(info):
        raise ValueError("Refusing to write to an unsupported HID interface")
    payload = xor_ff(command) + [0xFF] * (PAYLOAD_LENGTH - len(command))
    device = require_hid().device()
    try:
        device.open_path(info["path"])
        sent = device.send_feature_report([REPORT_ID, *payload])
        if sent <= 0:
            raise OSError("HID profile command was not sent")
        time.sleep(0.055)
    finally:
        try:
            device.close()
        except Exception:
            pass


def switch_profile(info: dict, profile_index: int) -> None:
    if profile_index not in (0, 1, 2):
        raise ValueError("profile_index must be 0, 1, or 2")
    legacy_write(info, [0x58, profile_index])


def query_active_profile(info: dict) -> int | None:
    request_payload = [COMMAND_PROFILE_STATE ^ 0xFF] + [0xFF] * (LONG_PAYLOAD_LENGTH - 1)
    device = require_hid().device()
    try:
        device.open_path(info["path"])
        for delay in RETRY_DELAYS_SECONDS:
            sent = device.send_feature_report([LONG_REPORT_ID, *request_payload])
            if sent <= 0:
                raise OSError("HID profile query was not sent")
            time.sleep(delay)
            raw = list(device.get_feature_report(LONG_REPORT_ID, LONG_PAYLOAD_LENGTH + 1))
            payload = normalize_feature_reply(raw, LONG_REPORT_ID)
            if len(payload) < 2 or payload[:LONG_PAYLOAD_LENGTH] == request_payload:
                continue
            decoded = xor_ff(payload)
            if decoded[0] == COMMAND_PROFILE_STATE and decoded[1] in (0, 1, 2):
                return decoded[1]
        return None
    finally:
        try:
            device.close()
        except Exception:
            pass


def query_device(info: dict, verbose: bool = False) -> BatteryStatus | None:
    request_payload = [COMMAND_STATUS ^ 0xFF] + [0xFF] * (PAYLOAD_LENGTH - 1)
    device = require_hid().device()
    try:
        device.open_path(info["path"])
        for attempt, delay in enumerate(RETRY_DELAYS_SECONDS, start=1):
            sent = device.send_feature_report([REPORT_ID, *request_payload])
            if sent <= 0:
                raise OSError("HID status query was not sent")
            if verbose:
                print(f"  TX attempt {attempt} ({sent} bytes): {REPORT_ID:02X} {hex_bytes(request_payload)}")
            time.sleep(delay)
            raw = list(device.get_feature_report(REPORT_ID, PAYLOAD_LENGTH + 1))
            if verbose:
                print(f"  RX attempt {attempt} ({delay * 1000:.0f} ms): {hex_bytes(raw)}")
            status = decode_status(raw, request_payload)
            if status is not None and _matches_candidate(status, info):
                return status
        return None
    finally:
        try:
            device.close()
        except Exception:
            pass


def enumerate_candidates() -> list[dict]:
    return [info for info in require_hid().enumerate() if is_supported_candidate(info)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Read MCHOSE A5 V2 Ultra battery via HID")
    parser.add_argument("--verbose", action="store_true", help="print raw HID reports")
    args = parser.parse_args()
    try:
        candidates = enumerate_candidates()
    except RuntimeError as exc:
        print(exc)
        return 2
    if not candidates:
        print("No supported MCHOSE A5 V2 Ultra HID interface found.")
        print("Confirm the 2.4G receiver is connected and the mouse is switched on.")
        return 1
    print(f"Found {len(candidates)} supported HID interface(s).")
    for index, info in enumerate(candidates, start=1):
        print(f"[{index}] {describe_device(info)}")
    for index, info in enumerate(candidates, start=1):
        print(f"\nTrying interface [{index}]...")
        try:
            status = query_device(info, args.verbose)
        except Exception as exc:
            print(f"  HID access/query failed: {type(exc).__name__}: {exc}")
            continue
        if status is None:
            print("  No valid 0x11/0x06 status reply from this interface.")
            continue
        print("  SUCCESS")
        print(f"  Device reply VID:PID: {status.vendor_id:04X}:{status.product_id:04X}")
        print(f"  Battery: {status.battery_percent}%")
        print(f"  Charging: {'yes' if status.charging else 'no'}")
        print(f"  Connection: {status.connection_name} (active={status.connection_active})")
        print(f"  Firmware raw value: 0x{status.firmware_raw:08X}")
        return 0
    print("\nNo interface produced a valid Legacy status response.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
