from __future__ import annotations

import unittest
from unittest.mock import patch

import read_mchose_battery as protocol


INFO = {
    "path": b"device",
    "vendor_id": 0x3837,
    "product_id": 0x100C,
    "usage_page": 0xFF01,
}


class FakeDevice:
    def __init__(self, replies: dict[int, list[list[int]]] | None = None) -> None:
        self.replies = replies or {}
        self.sent: list[list[int]] = []
        self.opened_path = None
        self.closed = False

    def open_path(self, path) -> None:
        self.opened_path = path

    def send_feature_report(self, report: list[int]) -> int:
        self.sent.append(report)
        return len(report)

    def get_feature_report(self, report_id: int, _length: int) -> list[int]:
        queue = self.replies.setdefault(report_id, [])
        return queue.pop(0) if queue else []

    def close(self) -> None:
        self.closed = True


class ProtocolTests(unittest.TestCase):
    def test_xor_ff(self) -> None:
        source = [0x00, 0x58, 0xFF]
        self.assertEqual(protocol.xor_ff(source), [0xFF, 0xA7, 0x00])
        self.assertEqual(source, [0x00, 0x58, 0xFF])

    def test_candidate_filter_is_strict(self) -> None:
        self.assertTrue(protocol.is_supported_candidate(INFO))
        self.assertFalse(protocol.is_supported_candidate({**INFO, "product_id": 1}))
        self.assertFalse(protocol.is_supported_candidate({**INFO, "usage_page": 1}))

    def test_decode_status(self) -> None:
        data = [0xE4, 0x41, 0x01, 0x11, 0x06, 0x02, 0x06, 0x00, 0x09, 81, 0]
        raw = [protocol.REPORT_ID, *protocol.xor_ff([protocol.COMMAND_STATUS, *data])]
        status = protocol.decode_status(raw, [0xF9] + [0xFF] * 19)
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status.battery_percent, 81)
        self.assertEqual(status.connection_name, "2.4G")
        self.assertTrue(status.connection_active)
        self.assertFalse(status.charging)

    def test_decode_status_rejects_echo_and_invalid_battery(self) -> None:
        request = [0xF9] + [0xFF] * 19
        self.assertIsNone(protocol.decode_status([protocol.REPORT_ID, *request], request))
        decoded = [protocol.COMMAND_STATUS, *([0] * 9), 101, 0]
        self.assertIsNone(protocol.decode_status(protocol.xor_ff(decoded), request))

    def test_switch_profile_packet(self) -> None:
        fake = FakeDevice()
        with patch.object(protocol, "hid") as hid_mock, patch.object(protocol.time, "sleep"):
            hid_mock.device.return_value = fake
            protocol.switch_profile(INFO, 2)
        self.assertEqual(fake.sent, [[0x11, 0xA7, 0xFD, *([0xFF] * 18)]])
        self.assertTrue(fake.closed)

    def test_write_rejects_unverified_interface(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported HID interface"):
            protocol.switch_profile({**INFO, "usage_page": 1}, 0)

    def test_query_active_profile_skips_echo(self) -> None:
        request = [0x98] + [0xFF] * 63
        decoded_reply = [protocol.COMMAND_PROFILE_STATE, 1] + [0] * 62
        fake = FakeDevice({protocol.LONG_REPORT_ID: [
            [protocol.LONG_REPORT_ID, *request],
            [protocol.LONG_REPORT_ID, *protocol.xor_ff(decoded_reply)],
        ]})
        with patch.object(protocol, "hid") as hid_mock, patch.object(protocol.time, "sleep"):
            hid_mock.device.return_value = fake
            self.assertEqual(protocol.query_active_profile(INFO), 1)
        self.assertEqual(len(fake.sent), 2)

    def test_query_device_resends_until_valid(self) -> None:
        request = [0xF9] + [0xFF] * 19
        data = [0xE4, 0x41, 0x01, 0x11, 0x06, 0x02, 0x06, 0x00, 0x09, 81, 0]
        reply = [protocol.REPORT_ID, *protocol.xor_ff([protocol.COMMAND_STATUS, *data])]
        fake = FakeDevice({protocol.REPORT_ID: [[protocol.REPORT_ID, *request], reply]})
        with patch.object(protocol, "hid") as hid_mock, patch.object(protocol.time, "sleep"):
            hid_mock.device.return_value = fake
            status = protocol.query_device(INFO)
        self.assertEqual(status.battery_percent if status else None, 81)
        self.assertEqual(len(fake.sent), 2)


if __name__ == "__main__":
    unittest.main()
