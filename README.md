# MCHOSE Battery Tray

适用于 Windows 的轻量系统托盘工具，通过 2.4G 接收器或 USB 有线连接显示 **MCHOSE A5 V2 Ultra** 的实时电量。

> 当前已验证 2.4G 接收器 `VID:PID 3837:100C` 和有线 USB `VID:PID 41E4:1101`，配置接口的 usage page 均为 `0xFF01`。程序不会上传数据，也不依赖官方 M HUB。

## 功能

- 托盘图标直接显示电量数字
- 绿色（>50%）、黄色（21–50%）、红色（≤20%）边框
- 悬停显示电量、连接方式、充电状态及当前配置
- 每 10 分钟自动刷新，可随时手动刷新
- 在“配置文件”菜单切换板载配置 1、2、3
- 日志记录读取和切换错误

## 安全说明

电量和当前配置查询是只读操作。选择“配置 1/2/3”时，程序会向鼠标发送 Legacy 命令 `0x58`，修改当前启用的板载配置，但不会改写各配置中的按键、DPI、宏或固件。写入前会先用只读状态查询验证受支持的 HID 接口，写入后会读取配置进行确认。

本项目是非官方社区工具，请自行承担使用风险。

## 环境

- Windows 10/11（64 位）
- Python 3.11–3.13（从源码运行或构建时）
- MCHOSE A5 V2 Ultra（2.4G 接收器或 USB 有线连接）

## 从源码运行

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\mchose_tray.py
```

程序没有主窗口。启动后请查看任务栏通知区域；图标可能在折叠菜单中。

也可运行只读协议探针：

```powershell
.\.venv\Scripts\python.exe .\read_mchose_battery.py --verbose
```

## 测试与检查

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m ruff check .
```

测试使用模拟 HID 设备，不会访问或修改真实鼠标。

## 构建 EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

脚本使用独立的 `.build-venv`，先运行测试和 Ruff，再生成 `dist\MCHOSE-Battery.exe`。GitHub Actions 也会在 Windows 上测试并上传构建产物。

## 日志

```text
%LOCALAPPDATA%\MCHOSEBattery\mchose-battery.log
```

## 协议概要

- Legacy 状态：Feature Report `0x11`、命令 `0x06`、20-byte payload
- 当前配置：Feature Report `0x12`、命令 `0x67`、64-byte payload
- 切换配置：Feature Report `0x11`、命令 `0x58`
- payload 每个字节 XOR `0xFF`

## 致谢与参考项目

本项目在实现过程中主要参考、借鉴了以下两个开源项目：

- [zynox-xonyz/MCHOSE-local-hub](https://github.com/zynox-xonyz/MCHOSE-local-hub)：提供 MCHOSE Legacy/Modern HID 协议研究成果。本项目的 Feature Report、命令编号、XOR 编码、响应布局和重试策略主要以其协议文档及实现为依据。
- [Fuwn/elem](https://github.com/Fuwn/elem)：托盘电量工具的产品形态和“直接在托盘图标中显示电量数字”的设计思路参考了该项目。

本项目是独立的 Python 实现，并针对实机检测到的 MCHOSE A5 V2 Ultra 接收器接口进行了适配和验证。感谢上述项目作者公开相关代码与研究成果。

## 许可证

[MIT License](LICENSE)
