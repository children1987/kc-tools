#!/usr/bin/env python3
"""
switch-env.py — 模拟器 ↔ 实车 一键切换工具
============================================
同时修改 argentina-app 和 openTCS 模型文件中的所有相关配置。

切换项:
  1. fork_udp.py              controller_ip
  2. kernel model.xml         kecong:navHost / kecong:qrHost
  3. argentina-app model.xml  kecong:navHost / kecong:qrHost

注意: 认证码 (authCode) 已统一为科聪标准二进制码，模拟器和实车一致，无需切换。

用法:
  python switch-env.py --sim      # 切换到模拟器模式
  python switch-env.py --real     # 切换到实车模式
  python switch-env.py --status   # 查看当前模式
"""

import socket
import argparse
import re
from pathlib import Path

# ── 路径（相对于脚本所在目录）──
SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parent.parent

# argentina-app
FORK_UDP_FILE = WORKSPACE / "projects" / "argentina-app" / "app" / "fork_udp.py"

# openTCS 模型文件
MODEL_FILES = [
    WORKSPACE / "opentcs-7.3.0-bin" / "opentcs-kernel" / "data" / "model.xml",
    WORKSPACE / "projects" / "argentina-app" / "model.xml",
]

# ── 配置常量 ──
SIM_NAV_HOST = "127.0.0.1"
SIM_QR_HOST = "127.0.0.1"

REAL_NAV_HOST = "192.168.100.178"
REAL_QR_HOST = "192.168.100.200"


def detect_mode() -> str | None:
    """根据 fork_udp.py 的 controller_ip 判断当前模式。"""
    if not FORK_UDP_FILE.exists():
        return None
    content = FORK_UDP_FILE.read_text(encoding="utf-8")
    m = re.search(r'controller_ip:\s*str\s*=\s*"([^"]+)"', content)
    if not m:
        return None
    ip = m.group(1)
    if ip == "127.0.0.1":
        return "sim"
    elif ip == REAL_QR_HOST:
        return "real"
    return None


def show_status() -> None:
    """打印当前状态。"""
    print(f"\n当前环境状态")
    print("-" * 50)
    mode = detect_mode()
    if mode == "sim":
        print(f"  模式:         模拟器 (Simulator)")
    elif mode == "real":
        print(f"  模式:         实车 (Real Vehicle)")
    else:
        print(f"  模式:         (未识别)")

    # fork_udp.py
    if FORK_UDP_FILE.exists():
        content = FORK_UDP_FILE.read_text(encoding="utf-8")
        m = re.search(r'controller_ip:\s*str\s*=\s*"([^"]+)"', content)
        print(f"  fork_udp.py:  {m.group(1) if m else '(未识别)'}")
    else:
        print(f"  fork_udp.py:  (文件不存在)")

    # model files
    for model_file in MODEL_FILES:
        _check_model_status(model_file)

    # 端口检查
    sim_running = _check_port(17804)
    print(f"  模拟器进程:    {'运行中' if sim_running else '未运行'} (端口17804)")
    print()


def _check_model_status(model_file: Path) -> None:
    """显示单个模型文件的当前配置。"""
    if not model_file.exists():
        print(f"  {model_file.name}: (文件不存在)")
        return

    content = model_file.read_text(encoding="utf-8")
    nav = re.search(r'<property name="kecong:navHost" value="([^"]+)"', content)
    qr = re.search(r'<property name="kecong:qrHost" value="([^"]+)"', content)

    nav_val = nav.group(1) if nav else "未设置"
    qr_val = qr.group(1) if qr else "未设置"

    # 显示相对路径
    try:
        rel_path = model_file.relative_to(WORKSPACE)
    except ValueError:
        rel_path = model_file
    print(f"  {rel_path}: nav={nav_val}, qr={qr_val}")


def _check_port(port: int) -> bool:
    """检查本地端口是否被占用。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.1)
    try:
        s.bind(("127.0.0.1", port))
        s.close()
        return False
    except OSError:
        return True


# ═══════════════════════════════════════════════════════════════════════
# 切换逻辑
# ═══════════════════════════════════════════════════════════════════════

def switch_to(target: str) -> None:
    """执行完整切换。"""
    target_name = "实车 (Real Vehicle)" if target == "real" else "模拟器 (Simulator)"
    now = detect_mode()

    print(f"\n切换到: {target_name}")
    print("=" * 50)

    if now == target:
        print(f"  [INFO] 当前已是 {target_name} 模式，无需切换\n")
        return

    errors: list[str] = []

    # ── 1. fork_udp.py ──
    errors += _switch_fork_udp(target)

    # ── 2. 模型文件 ──
    for model_file in MODEL_FILES:
        errors += _switch_model_xml(model_file, target)

    # ── 结果汇总 ──
    print("=" * 50)
    if errors:
        print(f"  [WARN] 切换完成，但有 {len(errors)} 个问题:")
        for e in errors:
            print(f"    - {e}")
    else:
        print(f"  [OK] 全部切换完成！")

    _print_post_actions(target)
    print()


def _switch_fork_udp(target: str) -> list[str]:
    """切换 fork_udp.py 中的 controller_ip。"""
    errors: list[str] = []
    new_ip = REAL_QR_HOST if target == "real" else "127.0.0.1"

    if not FORK_UDP_FILE.exists():
        return [f"找不到文件: {FORK_UDP_FILE}"]

    content = FORK_UDP_FILE.read_text(encoding="utf-8")
    pattern = r'(controller_ip:\s*str\s*=\s*)"[^"]*"(.*)'
    if re.search(pattern, content):
        content = re.sub(pattern, rf'\g<1>"{new_ip}"\g<2>', content)
        FORK_UDP_FILE.write_text(content, encoding="utf-8")
        print(f"  [OK] fork_udp.py → controller_ip = {new_ip}")
    else:
        errors.append(f"fork_udp.py 中未找到 controller_ip 定义")

    return errors


def _switch_model_xml(model_file: Path, target: str) -> list[str]:
    """切换模型 XML 文件中的车辆 IP 属性。

    切换项:
      - kecong:navHost    127.0.0.1 ↔ 192.168.100.178
      - kecong:qrHost     127.0.0.1 ↔ 192.168.100.200
    """
    errors: list[str] = []
    fname = model_file.name

    if not model_file.exists():
        errors.append(f"找不到文件: {model_file}")
        return errors

    content = model_file.read_text(encoding="utf-8")
    original = content

    new_nav = REAL_NAV_HOST if target == "real" else SIM_NAV_HOST
    new_qr = REAL_QR_HOST if target == "real" else SIM_QR_HOST

    # 切换 IP
    nav_pattern = r'(<property name="kecong:navHost" value=")[^"]*(")'
    qr_pattern = r'(<property name="kecong:qrHost" value=")[^"]*(")'

    nav_count = len(re.findall(nav_pattern, content))
    qr_count = len(re.findall(qr_pattern, content))

    content = re.sub(nav_pattern, rf'\g<1>{new_nav}\g<2>', content)
    content = re.sub(qr_pattern, rf'\g<1>{new_qr}\g<2>', content)

    if content != original:
        model_file.write_text(content, encoding="utf-8")
        print(f"  [OK] {fname}: navHost={new_nav}, qrHost={new_qr}")
    else:
        print(f"  [--] {fname}: 无需修改 (已是目标值)")

    if nav_count == 0:
        errors.append(f"{fname}: 未找到 kecong:navHost 属性")
    if qr_count == 0:
        errors.append(f"{fname}: 未找到 kecong:qrHost 属性")

    return errors


def _print_post_actions(target: str) -> None:
    """打印切换后需要的手动操作。"""
    print()
    print(f"  *** 后续操作: ***")
    if target == "sim":
        print(f"    1. 确保 simulators/kc-simulator 已启动")
        print(f"    2. 重启 openTCS Kernel + argentina-app")
    else:
        print(f"    1. 确保 simulators/kc-simulator 已停止")
        print(f"    2. 确认控制器网络可达: ping {REAL_NAV_HOST}")
        print(f"    3. 重启 openTCS Kernel + argentina-app")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="模拟器 ↔ 实车 一键切换工具 — 同时更新 argentina-app + openTCS 模型文件"
    )
    parser.add_argument("--sim", action="store_true", help="切换到模拟器模式")
    parser.add_argument("--real", action="store_true", help="切换到实车模式")
    parser.add_argument("--status", action="store_true", help="查看当前模式")
    args = parser.parse_args()

    if args.sim:
        switch_to("sim")
    elif args.real:
        switch_to("real")
    else:
        show_status()


if __name__ == "__main__":
    main()
