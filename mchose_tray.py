#!/usr/bin/env python3
"""MCHOSE A5 V2 Ultra battery indicator for the Windows system tray."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont

from read_mchose_battery import (
    BatteryStatus,
    enumerate_candidates,
    query_active_profile,
    query_device,
    switch_profile,
)

APP_NAME = "MCHOSE Battery"
POLL_INTERVAL_SECONDS = 10 * 60
ICON_SIZE = 64
LOG_PATH = Path.home() / "AppData" / "Local" / "MCHOSEBattery" / "mchose-battery.log"

def configure_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arialbd.ttf", "segoeuib.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def make_icon(text: str, color: tuple[int, int, int]) -> Image.Image:
    """Generate a crisp numeric tray icon in the style of elem."""
    scale = 4
    size = ICON_SIZE * scale
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Rounded dark plate keeps the number readable on light and dark taskbars.
    margin = 2 * scale
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=13 * scale,
        fill=(26, 29, 35, 245),
        outline=(*color, 255),
        width=3 * scale,
    )

    font_size = (34 if len(text) <= 2 else 27) * scale
    font = _font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=1 * scale)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = (size - width) / 2 - bbox[0]
    y = (size - height) / 2 - bbox[1] - 1 * scale
    draw.text(
        (x, y),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        stroke_width=1 * scale,
        stroke_fill=(0, 0, 0, 220),
    )
    return image.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)


def battery_color(percent: int) -> tuple[int, int, int]:
    if percent <= 20:
        return (239, 68, 68)
    if percent <= 50:
        return (245, 158, 11)
    return (34, 197, 94)


def device_candidates() -> list[dict]:
    return enumerate_candidates()


def read_battery_and_profile() -> tuple[BatteryStatus, int | None]:
    candidates = device_candidates()
    errors: list[str] = []
    for info in candidates:
        try:
            status = query_device(info, verbose=False)
            if status is not None:
                try:
                    profile = query_active_profile(info)
                except Exception:
                    logging.exception("Profile query failed; keeping valid battery status")
                    profile = None
                return status, profile
        except Exception as exc:
            errors.append(f"{info.get('vendor_id'):04X}:{info.get('product_id'):04X}: {exc}")
    if not candidates:
        raise RuntimeError("未找到迈从鼠标或 2.4G 接收器")
    detail = "; ".join(errors) if errors else "设备未返回有效状态"
    raise RuntimeError(detail)


class BatteryTray:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.refresh_lock = threading.Lock()
        self.last_status: BatteryStatus | None = None
        self.last_error: str | None = None
        self.active_profile: int | None = None
        profile_menu = pystray.Menu(
            *(
                pystray.MenuItem(
                    f"配置 {index + 1}",
                    self.profile_action(index),
                    checked=self.profile_checked(index),
                    radio=True,
                )
                for index in range(3)
            )
        )
        self.icon = pystray.Icon(
            "mchose-battery",
            make_icon("…", (107, 114, 128)),
            f"{APP_NAME} · 正在读取…",
            menu=pystray.Menu(
                pystray.MenuItem(self.status_text, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("立即刷新", self.refresh_now, default=True),
                pystray.MenuItem("配置文件", profile_menu),
                pystray.MenuItem("退出", self.quit),
            ),
        )

    def profile_action(self, profile_index: int):
        def action(_icon, _item) -> None:
            self.switch_profile_now(profile_index)
        return action

    def profile_checked(self, profile_index: int):
        def checked(_item) -> bool:
            return self.active_profile == profile_index
        return checked

    def status_text(self, _item: pystray.MenuItem) -> str:
        if self.last_status:
            status = self.last_status
            charging = " · 充电中" if status.charging else ""
            return f"电量 {status.battery_percent}% · {status.connection_name}{charging}"
        return self.last_error or "正在读取电量…"

    def update_display(self, status: BatteryStatus) -> None:
        self.last_status = status
        self.last_error = None
        charging = " · 充电中" if status.charging else ""
        # Legacy wired replies leave the wireless-link-active bit cleared.  It does
        # not mean that the USB connection itself is disconnected.
        active = (
            " · 未连接"
            if status.connection_mode in (1, 2) and not status.connection_active
            else ""
        )
        profile = f"\n配置 {self.active_profile + 1}" if self.active_profile is not None else ""
        self.icon.title = (
            f"MCHOSE A5 V2 Ultra\n"
            f"电量：{status.battery_percent}%{charging}\n"
            f"连接：{status.connection_name}{active}"
            f"{profile}"
        )
        text = str(status.battery_percent)
        self.icon.icon = make_icon(text, battery_color(status.battery_percent))
        self.icon.update_menu()

    def update_error(self, message: str) -> None:
        self.last_status = None
        self.last_error = f"读取失败：{message}"
        self.icon.title = f"{APP_NAME}\n{self.last_error}\n双击或右键选择“立即刷新”"
        self.icon.icon = make_icon("?", (107, 114, 128))
        self.icon.update_menu()

    def refresh(self) -> None:
        if not self.refresh_lock.acquire(blocking=False):
            return
        try:
            status, profile_index = read_battery_and_profile()
            if profile_index is not None:
                self.active_profile = profile_index
            logging.info(
                "battery=%s charging=%s mode=%s active=%s",
                status.battery_percent,
                status.charging,
                status.connection_name,
                status.connection_active,
            )
            self.update_display(status)
        except Exception as exc:
            logging.exception("Battery query failed")
            self.update_error(str(exc))
        finally:
            self.refresh_lock.release()

    def refresh_now(self, _icon=None, _item=None) -> None:
        threading.Thread(target=self.refresh, name="battery-refresh", daemon=True).start()

    def switch_profile_now(self, profile_index: int) -> None:
        threading.Thread(
            target=self._switch_profile,
            args=(profile_index,),
            name=f"profile-{profile_index + 1}",
            daemon=True,
        ).start()

    def _switch_profile(self, profile_index: int) -> None:
        if not self.refresh_lock.acquire(blocking=False):
            self.update_error("正在执行其他操作，请稍后重试")
            return
        try:
            errors: list[str] = []
            for info in device_candidates():
                try:
                    # Verify this interface with a read-only status query before writing.
                    status = query_device(info, verbose=False)
                    if status is None:
                        continue
                    switch_profile(info, profile_index)
                    confirmed_profile = query_active_profile(info)
                    if confirmed_profile != profile_index:
                        raise RuntimeError("配置切换后未通过读取确认")
                    refreshed = query_device(info, verbose=False) or status
                    self.active_profile = profile_index
                    logging.info("switched onboard profile=%s", profile_index + 1)
                    self.update_display(refreshed)
                    return
                except Exception as exc:
                    errors.append(str(exc))
            raise RuntimeError("; ".join(errors) or "未找到可用的配置接口")
        except Exception as exc:
            logging.exception("Profile switch failed")
            self.update_error(f"切换配置 {profile_index + 1} 失败：{exc}")
        finally:
            self.refresh_lock.release()

    def poll_loop(self) -> None:
        self.refresh()
        while not self.stop_event.wait(POLL_INTERVAL_SECONDS):
            self.refresh()

    def setup(self, _icon: pystray.Icon) -> None:
        self.icon.visible = True
        threading.Thread(target=self.poll_loop, name="battery-poller", daemon=True).start()

    def quit(self, _icon=None, _item=None) -> None:
        self.stop_event.set()
        self.icon.stop()

    def run(self) -> None:
        self.icon.run(setup=self.setup)


def main() -> int:
    configure_logging()
    try:
        BatteryTray().run()
        return 0
    except Exception as exc:
        logging.exception("Application failed")
        # Preserve an actionable error when launched from a terminal.
        print(f"{APP_NAME} 启动失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
