#!/usr/bin/env python3
"""
kc-fork-test.py — 叉臂举升/落下直连测试（UDP WRITE_VAR）

用法:
  python kc-fork-test.py --up          # 举升 (3秒后自动停止)
  python kc-fork-test.py --down        # 落下 (3秒后自动停止)
  python kc-fork-test.py --cycle       # 举升→等3秒→落下
  python kc-fork-test.py --up --hold   # 举升 (手动Ctrl+C停止)
"""
import socket
import struct
import time
import argparse
import sys

# UDP 配置
QR_HOST = '192.168.100.200'
QR_PORT = 17800
AUTH = bytes([0xed, 0x01, 0xe9, 0xd2, 0xb8, 0xa2, 0x6b, 0x4c,
              0x85, 0x72, 0x77, 0xf2, 0xb2, 0xcb, 0x61, 0xb4])
VAR_UP = 'Forkup'      # 举升变量
VAR_DOWN = 'Forkdown'  # 下降变量
DEFAULT_DURATION = 3.0


def write_var(host, port, name, value, retries=3):
    """Write variable via UDP WRITE_VAR (0x00). Retries to handle UDP packet loss."""
    ac = AUTH[:16].ljust(16, b'\x00')
    n = name.encode()[:16].ljust(16, b'\x00')
    data = n + bytes([value])
    hdr = struct.pack('<16sBBHBBBxHxx', ac, 1, 0, 0, 0x10, 0x00, 0, len(data))

    for attempt in range(retries):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2)
        try:
            sock.sendto(hdr + data, (host, port))
            resp, _ = sock.recvfrom(1024)
            sock.close()
            if resp[22] == 0:
                return True
        except socket.timeout:
            sock.close()
        if attempt < retries - 1:
            time.sleep(0.2)  # short delay between retries
    return False


def fork_up(host, port, duration):
    print(f"举升 {VAR_UP}=1", end=' ', flush=True)
    if not write_var(host, port, VAR_UP, 1):
        print("[FAIL]")
        return False
    print("[OK]")
    if duration > 0:
        print(f"  (持续 {duration:.0f} 秒)...", end=' ', flush=True)
        time.sleep(duration)
        write_var(host, port, VAR_UP, 0)
        print("已停止")
    return True


def fork_down(host, port, duration):
    print(f"下降 {VAR_DOWN}=1", end=' ', flush=True)
    if not write_var(host, port, VAR_DOWN, 1):
        print("[FAIL]")
        return False
    print("[OK]")
    if duration > 0:
        print(f"  (持续 {duration:.0f} 秒)...", end=' ', flush=True)
        time.sleep(duration)
        write_var(host, port, VAR_DOWN, 0)
        print("已停止")
    return True


def main():
    parser = argparse.ArgumentParser(description='科聪叉臂直连测试 (UDP WRITE_VAR)')
    parser.add_argument('--up', action='store_true', help='举升')
    parser.add_argument('--down', action='store_true', help='落下')
    parser.add_argument('--cycle', action='store_true', help='举升→3秒→落下')
    parser.add_argument('--duration', type=float, default=DEFAULT_DURATION,
                        help=f'持续时间秒 (默认{DEFAULT_DURATION})')
    parser.add_argument('--hold', action='store_true', help='保持不自动停止')
    parser.add_argument('--host', type=str, default=QR_HOST,
                        help=f'QR主机 (默认{QR_HOST})')
    args = parser.parse_args()

    if not (args.up or args.down or args.cycle):
        args.cycle = True

    duration = 0 if args.hold else args.duration

    print(f"科聪叉臂控制测试 (UDP WRITE_VAR)")
    print(f"QR端口: {args.host}:{QR_PORT}")
    print(f"举升={VAR_UP}  下降={VAR_DOWN}")
    print()

    if args.cycle:
        if not fork_up(args.host, QR_PORT, duration):
            sys.exit(1)
        time.sleep(1)
        if not fork_down(args.host, QR_PORT, duration):
            sys.exit(1)
        print()
        print("[DONE] 测试完成")
    elif args.up:
        fork_up(args.host, QR_PORT, duration)
    elif args.down:
        fork_down(args.host, QR_PORT, duration)


if __name__ == '__main__':
    main()
