#!/usr/bin/env python3
"""
kc-fork-test.py — 叉臂四向直连测试（UDP WRITE_VAR）

用法:
  python kc-fork-test.py --up          # 举升 (3秒)
  python kc-fork-test.py --down        # 落下 (3秒)
  python kc-fork-test.py --forward     # 向前 (3秒)
  python kc-fork-test.py --back        # 向后 (3秒)
  python kc-fork-test.py --cycle       # 举升→落下 (上下)
  python kc-fork-test.py --fwdrev      # 向前→向后 (前后)
  python kc-fork-test.py --up --hold   # 持续 (Ctrl+C停止)
"""
import socket
import struct
import time
import argparse
import sys

QR_HOST = '192.168.100.200'
QR_PORT = 17800
AUTH = bytes([0xed, 0x01, 0xe9, 0xd2, 0xb8, 0xa2, 0x6b, 0x4c,
              0x85, 0x72, 0x77, 0xf2, 0xb2, 0xcb, 0x61, 0xb4])

VARS = {
    'up':      'Forkup',
    'down':    'Forkdown',
    'forward': 'Forkforward',
    'back':    'Forkback',
}
DEFAULT_DURATION = 3.0


def write_var(host, port, name, value, retries=3):
    """Write variable via UDP WRITE_VAR (0x00)."""
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
            time.sleep(0.2)
    return False


def move(direction, host, port, duration):
    """Move fork in given direction for duration seconds."""
    var = VARS[direction]
    label = {'up': '举升', 'down': '下降', 'forward': '向前', 'back': '向后'}[direction]
    print(f"{label} {var}=1", end=' ', flush=True)
    if not write_var(host, port, var, 1):
        print("[FAIL]")
        return False
    print("[OK]")
    if duration > 0:
        print(f"  (持续 {duration:.0f} 秒)...", end=' ', flush=True)
        time.sleep(duration)
        write_var(host, port, var, 0)
        print("已停止")
    return True


def main():
    parser = argparse.ArgumentParser(description='科聪叉臂直连测试 (UDP WRITE_VAR)')
    parser.add_argument('--up', action='store_true', help='举升')
    parser.add_argument('--down', action='store_true', help='落下')
    parser.add_argument('--forward', action='store_true', help='向前')
    parser.add_argument('--back', action='store_true', help='向后')
    parser.add_argument('--cycle', action='store_true', help='举升→落下')
    parser.add_argument('--fwdrev', action='store_true', help='向前→向后')
    parser.add_argument('--duration', type=float, default=DEFAULT_DURATION,
                        help=f'持续时间秒 (默认{DEFAULT_DURATION})')
    parser.add_argument('--hold', action='store_true', help='保持不自动停止')
    parser.add_argument('--host', type=str, default=QR_HOST,
                        help=f'QR主机 (默认{QR_HOST})')
    args = parser.parse_args()

    duration = 0 if args.hold else args.duration

    print(f"科聪叉臂控制 (UDP WRITE_VAR)")
    print(f"QR: {args.host}:{QR_PORT}")
    print(f"变量: {', '.join(f'{k}={v}' for k,v in VARS.items())}")
    print()

    if args.cycle:
        if not move('up', args.host, QR_PORT, duration): sys.exit(1)
        time.sleep(1)
        if not move('down', args.host, QR_PORT, duration): sys.exit(1)
        print("\n[DONE] 完成")
    elif args.fwdrev:
        if not move('forward', args.host, QR_PORT, duration): sys.exit(1)
        time.sleep(1)
        if not move('back', args.host, QR_PORT, duration): sys.exit(1)
        print("\n[DONE] 完成")
    elif args.up:
        move('up', args.host, QR_PORT, duration)
    elif args.down:
        move('down', args.host, QR_PORT, duration)
    elif args.forward:
        move('forward', args.host, QR_PORT, duration)
    elif args.back:
        move('back', args.host, QR_PORT, duration)
    else:
        args.cycle = True


if __name__ == '__main__':
    main()
