#!/usr/bin/env python3
"""
switch-env.py — 模拟器 ↔ 实车 一键切换工具
============================================
修改 argentina-app fork_udp.py 中的 controller_ip，
一键切换叉臂 UDP 控制的目标地址。

注意: 本脚本不修改 model.xml — 模型文件的切换请手动处理。

用法:
  python switch-env.py --sim      # 切换到模拟器模式 (127.0.0.1)
  python switch-env.py --real     # 切换到实车模式 (192.168.100.200)
  python switch-env.py --status   # 查看当前模式
"""

import socket
import argparse
import re
from pathlib import Path

# ── 路径 ──
SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parent
FORK_UDP_FILE = WORKSPACE / "projects" / "argentina-app" / "app" / "fork_udp.py"

SIM_IP = "127.0.0.1"
REAL_IP = "192.168.100.200"


def detect_mode() -> str | None:
    """根据 fork_udp.py 的 controller_ip 判断当前模式。"""
    if not FORK_UDP_FILE.exists():
        return None
    content = FORK_UDP_FILE.read_text(encoding="utf-8")
    m = re.search(r'controller_ip:\s*str\s*=\s*"([^"]+)"', content)
    if not m:
        return None
    ip = m.group(1)
    if ip == SIM_IP:
        return "sim"
    elif ip == REAL_IP:
        return "real"
    return None


def show_status():
    """打印当前状态。"""
    print(f"\n当前环境状态")
    print("-" * 40)
    mode = detect_mode()
    if mode == "sim":
        print(f"  fork_udp.py controller_ip = {SIM_IP}  (模拟器)")
    elif mode == "real":
        print(f"  fork_udp.py controller_ip = {REAL_IP}  (实车)")
    else:
        print(f"  fork_udp.py controller_ip = (未识别)")

    sim_running = _check_port(17804)
    print(f"  模拟器进程 (端口17804): {'运行中' if sim_running else '未运行'}")
    print()


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


def switch_to(target: str):
    """执行切换。"""
    target_name = "实车 (Real Vehicle)" if target == "real" else "模拟器 (Simulator)"
    new_ip = REAL_IP if target == "real" else SIM_IP
    now = detect_mode()

    print(f"\n切换到: {target_name}")
    print("-" * 40)

    if now == target:
        print(f"  [INFO] 当前已是 {target_name} 模式，无需切换\n")
        return

    if not FORK_UDP_FILE.exists():
        print(f"  [ERR] 找不到文件: {FORK_UDP_FILE}\n")
        return

    content = FORK_UDP_FILE.read_text(encoding="utf-8")
    pattern = r'(controller_ip:\s*str\s*=\s*)"[^"]*"(.*)'
    if re.search(pattern, content):
        content = re.sub(pattern, rf'\g<1>"{new_ip}"\g<2>', content)
        FORK_UDP_FILE.write_text(content, encoding="utf-8")
        print(f"  [OK] fork_udp.py controller_ip = {new_ip}")
    else:
        print(f"  [ERR] 未找到 controller_ip 定义")
        return

    print("-" * 40)
    print(f"  [OK] 切换完成！")
    print()
    print(f"  *** 后续操作: ***")
    print(f"     - 重启 argentina-app 使修改生效")
    if target == "sim":
        print(f"     - 确保 simulators/kc-simulator 已启动")
    else:
        print(f"     - 确保 simulators/kc-simulator 已停止")
    print()


def main():
    parser = argparse.ArgumentParser(description="模拟器 ↔ 实车 一键切换工具")
    parser.add_argument("--sim", action="store_true", help="切换到模拟器模式")
    parser.add_argument("--real", action="store_true", help="切换到实车模式")
    parser.add_argument("--status", action="store_true", help="查看当前模式（默认）")
    args = parser.parse_args()

    if args.sim:
        switch_to("sim")
    elif args.real:
        switch_to("real")
    else:
        show_status()


if __name__ == "__main__":
    main()
