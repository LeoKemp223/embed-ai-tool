#!/usr/bin/env python
"""Saleae 逻辑分析仪采集工具。

为 `logic-analyzer` skill 提供可重复调用的执行入口，支持：

- 探测 logic2-automation 环境与 Logic 2 自动化服务连通性
- 列出已连接的 Saleae 设备
- 在线采集数字通道波形（定时模式）
- 添加 I2C / SPI / UART(Async Serial) 协议解码器
- 导出解码数据表（CSV）与原始波形（CSV）

依赖 Logic 2 桌面软件运行并开启 automation server（默认端口 10430）。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import socket
import sys
import time
from dataclasses import dataclass, field
from typing import Any

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from saleae import automation
    HAS_AUTOMATION = True
except ImportError:
    HAS_AUTOMATION = False

DEFAULT_PORT = 10430

# 采集输出根目录：默认 <工程根>/captures/logic-analyzer，可用 LA_CAPTURE_DIR 覆盖。
# 工程根按脚本位置 .../embed-ai-tool/skills/logic-analyzer/scripts 上溯 4 级推断。
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "..", "..", ".."))
DEFAULT_CAPTURE_DIR = os.environ.get(
    "LA_CAPTURE_DIR", os.path.join(_PROJECT_ROOT, ".captures", "logic-analyzer")
)


def capture_output_path(label: str, ext: str = "csv") -> str:
    """为某个解码器生成默认导出路径：<默认目录>/<label>_<时间戳>.<ext>。"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(DEFAULT_CAPTURE_DIR, f"{label}_{stamp}.{ext}")


def resolve_user_path(path: str) -> str:
    """用户显式给的路径：绝对原样，相对则相对默认采集目录。"""
    return path if os.path.isabs(path) else os.path.join(DEFAULT_CAPTURE_DIR, path)

# Logic 2 界面中协议解码器的名称与设置键（必须与界面文字完全一致）
ANALYZER_NAMES = {"i2c": "I2C", "spi": "SPI", "uart": "Async Serial", "can": "CAN"}

# 每种协议：spec 短键 -> Logic 2 settings 键名。值为 int 通道或数值。
# 必填键缺失会报错；可选键（如 SPI 的 miso/cs）缺失则不传给 API。
ANALYZER_SPECS = {
    "i2c": {
        "keys": {"scl": "SCL", "sda": "SDA"},
        "required": ["scl", "sda"],
    },
    "spi": {
        "keys": {"clk": "Clock", "mosi": "MOSI", "miso": "MISO", "cs": "Enable"},
        "required": ["clk"],
    },
    "uart": {
        "keys": {"rx": "Input Channel", "baud": "Bit Rate (Bits/s)"},
        "required": ["rx"],
    },
    "can": {
        "keys": {"can": "CAN", "baud": "Bit Rate (Bits/s)"},
        "required": ["can"],
    },
}


def parse_analyzer_spec(spec: str) -> dict:
    """解析 --analyzer 字符串，如 "i2c:scl=0,sda=1" 或 "uart:rx=2,baud=115200"。

    返回 {"proto": "i2c", "label": "i2c", "name": "I2C", "settings": {...}}。
    出错抛 ValueError，附带可读信息。
    """
    if ":" not in spec:
        raise ValueError(f"解码器格式应为 '协议:键=值,...'，收到: {spec!r}")
    proto, _, kv = spec.partition(":")
    proto = proto.strip().lower()
    if proto not in ANALYZER_SPECS:
        raise ValueError(f"不支持的协议 {proto!r}，可选: {', '.join(ANALYZER_SPECS)}")

    keymap = ANALYZER_SPECS[proto]["keys"]
    raw: dict[str, str] = {}
    for pair in kv.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"{proto}: 参数应为 键=值，收到 {pair!r}")
        k, _, v = pair.partition("=")
        raw[k.strip().lower()] = v.strip()

    missing = [k for k in ANALYZER_SPECS[proto]["required"] if k not in raw]
    if missing:
        raise ValueError(f"{proto}: 缺少必填参数 {missing}（可用: {list(keymap)}）")

    settings: dict[str, Any] = {}
    for short, val in raw.items():
        if short not in keymap:
            raise ValueError(f"{proto}: 未知参数 {short!r}（可用: {list(keymap)}）")
        # baud 等非通道数值保持整数；通道也是整数
        settings[keymap[short]] = int(val)

    return {"proto": proto, "label": proto, "name": ANALYZER_NAMES[proto],
            "settings": settings}


def legacy_decode_to_spec(args) -> dict | None:
    """把旧的 --decode i2c --i2c-scl 0 ... 形式转成 analyzer spec（向后兼容）。"""
    d = args.decode
    if not d:
        return None
    if d == "i2c":
        s = {"SCL": args.i2c_scl, "SDA": args.i2c_sda}
    elif d == "spi":
        s = {"Clock": args.spi_clk, "MOSI": args.spi_mosi,
             "MISO": args.spi_miso, "Enable": args.spi_cs}
        s = {k: v for k, v in s.items() if v is not None}
    elif d == "uart":
        s = {"Input Channel": args.uart_rx, "Bit Rate (Bits/s)": args.baudrate}
    else:
        return None
    return {"proto": d, "label": d, "name": ANALYZER_NAMES[d], "settings": s}


def collect_analyzer_specs(args) -> list[dict]:
    """汇总所有解码器：优先 --analyzer（可多个），否则回退旧 --decode。"""
    specs: list[dict] = []
    for raw in (args.analyzer or []):
        specs.append(parse_analyzer_spec(raw))
    if not specs:
        legacy = legacy_decode_to_spec(args)
        if legacy:
            specs.append(legacy)
    # 同协议出现多次时，label 加序号区分（i2c, i2c2, ...）以免导出文件重名
    seen: dict[str, int] = {}
    for sp in specs:
        seen[sp["proto"]] = seen.get(sp["proto"], 0) + 1
        if seen[sp["proto"]] > 1:
            sp["label"] = f"{sp['proto']}{seen[sp['proto']]}"
    return specs


def radix_type(name: str):
    """将 --radix 取值映射到 automation.RadixType。"""
    return {
        "hex": automation.RadixType.HEXADECIMAL,
        "dec": automation.RadixType.DECIMAL,
        "bin": automation.RadixType.BINARY,
        "ascii": automation.RadixType.ASCII,
    }[name]


@dataclass
class LAResult:
    status: str  # success, failure
    summary: str
    mode: str | None = None
    connection: str | None = None
    rows: list[dict] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    failure_category: str | None = None
    evidence: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 参数解析辅助
# ---------------------------------------------------------------------------

def parse_channels(spec: str) -> list[int]:
    """解析通道表达式，如 "0-3" 或 "0,1,4,7" 或 "0-3,7"。"""
    chans: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            chans.extend(range(int(lo), int(hi) + 1))
        else:
            chans.append(int(part))
    return sorted(set(chans))


def parse_samplerate(spec: str) -> int:
    """解析采样率，支持 24M / 10M / 500K / 数字。"""
    s = spec.strip().upper()
    mult = 1
    if s.endswith("G"):
        mult, s = 1_000_000_000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith("K"):
        mult, s = 1_000, s[:-1]
    return int(float(s) * mult)


def probe_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """探测 TCP 端口是否可连接。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 连接管理
# ---------------------------------------------------------------------------

def connect(address: str, port: int, timeout: float):
    """连接 Logic 2 automation server，返回 (manager, err)。"""
    try:
        mgr = automation.Manager.connect(
            address=address, port=port, connect_timeout_seconds=timeout
        )
        return mgr, None
    except Exception as e:
        return None, str(e)


def launch_and_connect(app_path: str | None, port: int, timeout: float):
    """启动 Logic 2 并连接（Manager 关闭时自动退出该 Logic 2）。返回 (manager, err)。"""
    try:
        mgr = automation.Manager.launch(
            application_path=app_path or None,
            port=port,
            connect_timeout_seconds=timeout,
        )
        return mgr, None
    except Exception as e:
        return None, str(e)


def open_manager(args):
    """按 --launch 决定是启动新 Logic 2 还是连接已运行的实例。"""
    if getattr(args, "launch", False):
        # launch 启动较慢，超时放宽
        return launch_and_connect(args.app_path, args.port,
                                  max(args.connect_timeout, 30.0))
    return connect(args.address, args.port, args.connect_timeout)


# ---------------------------------------------------------------------------
# 设备列举
# ---------------------------------------------------------------------------

def list_devices(mgr, include_sim: bool) -> LAResult:
    devs = mgr.get_devices(include_simulation_devices=include_sim)
    rows = []
    for d in devs:
        rows.append({
            "device_id": getattr(d, "device_id", None),
            "device_type": str(getattr(d, "device_type", "")),
            "is_simulation": getattr(d, "is_simulation", None),
        })
    if not rows:
        return LAResult(status="failure", summary="未发现已连接的 Saleae 设备",
                        failure_category="no-device", rows=rows)
    return LAResult(status="success", summary=f"发现 {len(rows)} 个设备", rows=rows)


# ---------------------------------------------------------------------------
# 采集 + 解码 + 导出
# ---------------------------------------------------------------------------

def run_capture(mgr, args) -> LAResult:
    channels = parse_channels(args.channels)
    samplerate = parse_samplerate(args.samplerate)

    # 解析解码器规格（--analyzer 可多个，回退旧 --decode）
    try:
        specs = collect_analyzer_specs(args)
    except ValueError as e:
        return LAResult(status="failure", summary="解码器参数错误",
                        failure_category="decode-error", evidence=[str(e)])

    raw_dir = resolve_user_path(args.raw_dir) if args.raw_dir else None
    save_path = resolve_user_path(args.save) if args.save else None

    dev_cfg = automation.LogicDeviceConfiguration(
        enabled_digital_channels=channels,
        digital_sample_rate=samplerate,
    )
    cap_cfg = automation.CaptureConfiguration(
        capture_mode=automation.TimedCaptureMode(duration_seconds=args.duration)
    )
    conn = f"{args.address}:{args.port} ch={channels} {samplerate}Hz {args.duration}s"

    try:
        cap = mgr.start_capture(
            device_id=args.device_id,
            device_configuration=dev_cfg,
            capture_configuration=cap_cfg,
        )
    except Exception as e:
        return LAResult(status="failure", summary="启动采集失败", connection=conn,
                        failure_category="capture-failure", evidence=[str(e)])

    result = LAResult(status="success", summary="", connection=conn, mode="capture")
    try:
        cap.wait()  # 定时模式：等待采集结束

        # 逐个添加解码器
        added: list[tuple[dict, Any]] = []
        for sp in specs:
            try:
                handle = cap.add_analyzer(sp["name"], label=sp["label"],
                                          settings=sp["settings"])
                added.append((sp, handle))
            except Exception as e:
                cap.close()
                return LAResult(status="failure",
                                summary=f"{sp['name']} 解码器添加失败",
                                connection=conn, failure_category="decode-error",
                                evidence=[str(e), f"label={sp['label']}",
                                          f"settings={sp['settings']}"])

        # 导出原始波形
        if raw_dir:
            os.makedirs(raw_dir, exist_ok=True)
            cap.export_raw_data_csv(directory=raw_dir, digital_channels=channels)
            result.outputs.append(raw_dir)

        # 每个解码器各自导出一个 CSV
        # 单解码器且用户指定了 --output 时用该路径，否则按 label 自动命名
        radix = radix_type(args.radix)
        for sp, handle in added:
            if args.output and len(added) == 1:
                out_path = resolve_user_path(args.output)
            else:
                out_path = capture_output_path(sp["label"], "csv")
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            export_cfg = automation.DataTableExportConfiguration(
                analyzer=handle, radix=radix
            )
            cap.export_data_table(filepath=out_path, analyzers=[export_cfg],
                                  iso8601_timestamp=True)
            result.outputs.append(out_path)

        if save_path:
            os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
            cap.save_capture(filepath=save_path)
            result.outputs.append(save_path)

        parts = [f"采集完成 {args.duration}s"]
        if added:
            parts.append(f"{len(added)} 个解码器: " +
                         ", ".join(sp["label"] for sp, _ in added))
        result.summary = "，".join(parts)
        return result
    except Exception as e:
        return LAResult(status="failure", summary="采集过程出错", connection=conn,
                        failure_category="capture-failure", evidence=[str(e)])
    finally:
        try:
            cap.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def print_report(result: LAResult, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        return
    icon = "✅" if result.status == "success" else "❌"
    print(f"结果: {icon} {result.summary}")
    if result.connection:
        print(f"  连接: {result.connection}")
    if result.failure_category:
        print(f"  失败分类: {result.failure_category}")
    for row in result.rows:
        print(f"  {row}")
    for out in result.outputs:
        print(f"  📄 输出: {out}")
    for ev in result.evidence:
        print(f"  · {ev}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Saleae 逻辑分析仪采集工具")
    # 模式
    p.add_argument("--detect", action="store_true", help="探测环境与 Logic 2 连通性")
    p.add_argument("--devices", action="store_true", help="列出已连接的 Saleae 设备")
    p.add_argument("--capture", action="store_true", help="执行在线采集")
    # 连接
    p.add_argument("--address", default="127.0.0.1", help="Logic 2 地址（默认 127.0.0.1）")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"自动化服务端口（默认 {DEFAULT_PORT}）")
    p.add_argument("--connect-timeout", type=float, default=5.0, help="连接超时秒数")
    p.add_argument("--launch", action="store_true",
                   help="自动启动 Logic 2（用完自动关闭），无需手动开软件")
    p.add_argument("--app-path", help="Logic 2 可执行文件路径（--launch 时；不填自动查找）")
    p.add_argument("--device-id", help="指定设备 ID（不填用第一个）")
    p.add_argument("--include-sim", action="store_true", help="包含 Logic 2 仿真设备")
    # 采集
    p.add_argument("--channels", default="0-3", help="数字通道，如 0-3 或 0,1,4,7")
    p.add_argument("--samplerate", default="10M", help="数字采样率，如 24M/10M/500K")
    p.add_argument("--duration", type=float, default=5.0, help="采集持续秒数（定时模式）")
    # 解码（推荐）：可重复，一次采集挂多个解码器
    p.add_argument("--analyzer", action="append", metavar="SPEC",
                   help="解码器，格式 '协议:键=值,...'，可重复。"
                        "如 i2c:scl=0,sda=1 / uart:rx=2,baud=115200 / "
                        "spi:clk=3,mosi=4,miso=5,cs=6")
    # 解码（旧式，向后兼容；--analyzer 存在时忽略这些）
    p.add_argument("--decode", choices=["i2c", "spi", "uart"], help="（兼容）单协议解码类型")
    p.add_argument("--i2c-sda", type=int, default=0, help="（兼容）I2C SDA 通道")
    p.add_argument("--i2c-scl", type=int, default=1, help="（兼容）I2C SCL 通道")
    p.add_argument("--spi-mosi", type=int, help="（兼容）SPI MOSI 通道")
    p.add_argument("--spi-miso", type=int, help="（兼容）SPI MISO 通道")
    p.add_argument("--spi-clk", type=int, help="（兼容）SPI Clock 通道")
    p.add_argument("--spi-cs", type=int, help="（兼容）SPI Enable/CS 通道")
    p.add_argument("--uart-rx", type=int, default=0, help="（兼容）UART 输入通道")
    p.add_argument("--baudrate", type=int, default=115200, help="（兼容）UART 波特率")
    # 输出
    p.add_argument("--output", help="单解码器时的 CSV 路径；多解码器时忽略，按 label 自动命名")
    p.add_argument("--radix", choices=["hex", "dec", "bin", "ascii"], default="hex",
                   help="数据表数值进制（默认 hex）")
    p.add_argument("--raw-dir", help="原始波形导出目录")
    p.add_argument("--save", help="保存 .sal 采集文件路径")
    p.add_argument("--format", choices=["table", "json"], default="table", help="输出格式")
    return p


def do_detect(args) -> int:
    print("\n📊 逻辑分析仪环境探测：")
    if HAS_AUTOMATION:
        print("  ✅ logic2-automation 已安装")
    else:
        print("  ❌ logic2-automation 未安装（pip install logic2-automation）")
        return 1

    # 探测端口
    reachable = probe_port(args.address, args.port, timeout=2.0)
    if reachable:
        print(f"  ✅ 端口 {args.address}:{args.port} 可连接")
    else:
        print(f"  ❌ 端口 {args.address}:{args.port} 无法连接")

    # 尝试建立 automation 连接
    mgr, err = connect(args.address, args.port, args.connect_timeout)
    if mgr is None:
        print(f"  ❌ 未连接到 Logic 2 自动化服务")
        print(f"     提示: 打开 Logic 2 → Preferences → 勾选 Enable automation server")
        if not reachable:
            print(f"     端口 {args.port} 未监听，确认 Logic 2 已运行且端口正确")
        if err:
            print(f"     {err}")
        return 1
    try:
        info = mgr.get_app_info()
        print(f"  ✅ 已连接 Logic 2: {info}")
        devs = mgr.get_devices(include_simulation_devices=args.include_sim)
        print(f"  设备数: {len(devs)}")
        for d in devs:
            print(f"    - {getattr(d, 'device_id', '?')} ({getattr(d, 'device_type', '?')})")
    finally:
        mgr.close()
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not HAS_AUTOMATION and not args.detect:
        print("❌ logic2-automation 未安装，请运行: pip install logic2-automation")
        return 1

    if args.detect:
        return do_detect(args)

    if not (args.devices or args.capture):
        parser.print_help()
        return 1

    mgr, err = open_manager(args)
    if mgr is None:
        if args.launch:
            print("❌ 启动 Logic 2 失败")
            print("  提示: 确认已安装 Logic 2，或用 --app-path 指定可执行文件路径")
        else:
            print(f"❌ 连接失败: {args.address}:{args.port}")
            print("  提示: 确认 Logic 2 已运行并开启 automation server，或加 --launch 自动启动")
        if err:
            print(f"  {err}")
        return 1

    try:
        if args.devices:
            result = list_devices(mgr, args.include_sim)
            print_report(result, args.format)
            return 0 if result.status == "success" else 1

        if args.capture:
            result = run_capture(mgr, args)
            print_report(result, args.format)
            return 0 if result.status == "success" else 1
    finally:
        mgr.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())


