#!/usr/bin/env python3
"""
kc-inspect.py — 科聪控制器直查工具
无需 Kernel，直接通过 UDP 查询控制器状态、变量、地图信息。

用法:
  python kc-inspect.py                          # 查询运行状态
  python kc-inspect.py --full                   # 完整状态+导航+变量检查
  python kc-inspect.py --vars                   # 检查关键变量是否存在
  python kc-inspect.py --watch                  # 持续监控(1秒刷新)
  python kc-inspect.py --ip 192.168.1.100       # 指定IP
"""
import socket
import struct
import sys
import time
import argparse

DEFAULT_HOST = '192.168.100.178'
QR_HOST = '192.168.100.200'
NAV_PORT = 17804
QR_PORT = 17800

AUTH = bytes([0xed, 0x01, 0xe9, 0xd2, 0xb8, 0xa2, 0x6b, 0x4c,
              0x85, 0x72, 0x77, 0xf2, 0xb2, 0xcb, 0x61, 0xb4])

# ── Protocol ──
def enc(cmd, seq=0, data=b''):
    ac = AUTH[:16].ljust(16, b'\x00')
    return struct.pack('<16sBBHBBBxHxx', ac, 1, 0, seq & 0xFFFF, 0x10, cmd, 0, len(data)) + data

def send(cmd, host=DEFAULT_HOST, port=NAV_PORT, data=b'', seq=0, timeout=2):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    s.sendto(enc(cmd, seq, data), (host, port))
    try:
        d, _ = s.recvfrom(2048)
        ec = d[0x1C - 2]
        dl = struct.unpack_from('<H', d, 0x18)[0]
        return ec, d[0x1C:0x1C + dl]
    except socket.timeout:
        return -1, b''
    finally:
        s.close()

# ── Parser ──
def parse_run_status(data):
    if len(data) < 0xC0: return None
    return {
        'pos_x': struct.unpack_from('<d', data, 0x08)[0],
        'pos_y': struct.unpack_from('<d', data, 0x10)[0],
        'heading': struct.unpack_from('<d', data, 0x18)[0],
        'battery': struct.unpack_from('<d', data, 0x20)[0],
        'blocked': data[0x28],
        'charging': data[0x29],
        'run_mode': data[0x2A],   # 0=manual, 1=auto
        'map_loaded': data[0x2B], # 0=OK
        'cur_pt': struct.unpack_from('<I', data, 0x2C)[0],
        'speed_fwd': struct.unpack_from('<d', data, 0x30)[0],
        'task_state': data[0x50], # 0=NONE,1=WAIT,2=GOING,3=PAUSE,4=DONE,5=FAIL
        'map_version': struct.unpack_from('<H', data, 0x52)[0],
        'loc_status': data[0x70], # 0=FAIL,1=SUCCESS,2=LOCATING,3=DONE
        'map_count': struct.unpack_from('<I', data, 0x74)[0],
        'map_name': data[0x78:0x78 + 64].rstrip(b'\x00').decode('ascii', errors='replace'),
        'confidence': struct.unpack_from('<f', data, 0xB8)[0],
    }

# ── Display ──
def color(s, c):
    codes = {'G': '\033[92m', 'R': '\033[91m', 'Y': '\033[93m', 'C': '\033[96m', 'W': '\033[0m', 'B': '\033[1m'}
    return f"{codes.get(c, '')}{s}{codes['W']}"

def show_status(host):
    ec, data = send(0x17, host)
    if ec == -1:
        print(f"  {color('TIMEOUT', 'R')} — 控制器无响应")
        return False
    if ec != 0:
        print(f"  exec=0x{ec:02X} ({color('FAIL', 'R')})")
        return False

    s = parse_run_status(data)
    if not s:
        print(f"  {color('PARSE ERROR', 'R')}")
        return False

    rm = 'AUTO' if s['run_mode'] == 1 else 'MANUAL'
    rmc = 'G' if s['run_mode'] == 1 else 'Y'
    ls = {0: 'FAIL', 1: 'SUCCESS', 2: 'LOCATING', 3: 'DONE'}.get(s['loc_status'], '?')
    lsc = 'G' if s['loc_status'] == 3 else ('Y' if s['loc_status'] == 1 else 'R')
    ts = {0: 'NONE', 1: 'WAIT', 2: 'GOING', 3: 'PAUSE', 4: 'DONE', 5: 'FAIL', 6: 'EXIT'}.get(s['task_state'], '?')
    tsc = 'G' if s['task_state'] in (0, 4) else ('Y' if s['task_state'] == 2 else 'R')

    print(f"  位置:    ({s['pos_x']:.3f}, {s['pos_y']:.3f}) m = ({int(s['pos_x']*1000)}, {int(s['pos_y']*1000)}) mm")
    print(f"  朝向:    {s['heading']:.2f} rad")
    print(f"  模式:    {color(rm, rmc)}")
    print(f"  定位:    {color(ls, lsc)}  置信度: {s['confidence']*100:.0f}%")
    print(f"  任务:    {color(ts, tsc)}  当前点: {s['cur_pt']}")
    print(f"  电量:    {s['battery']*100:.0f}%  {'充电中' if s['charging'] else ''}")
    print(f"  地图:    {s['map_name']} (数量:{s['map_count']} 版本:{s['map_version']})")
    print(f"  阻挡:    {'是' if s['blocked'] else '否'}")
    return True

def check_variable(host, name):
    """Check if a variable exists by reading it. Uses QR port for real controller."""
    qr_host = host
    qr_port = QR_PORT
    # For simulator (127.0.0.1) all ports are handled by the same server
    if host == '127.0.0.1':
        qr_port = NAV_PORT
    vname = name.encode('ascii').ljust(16, b'\x00')
    ec, data = send(0x01, qr_host, qr_port, vname, timeout=1)
    if ec == -1:
        return None, "TIMEOUT"
    if ec != 0:
        return None, f"ERR(0x{ec:02X})"
    has_val = len(data) >= 17
    val = data[16] if has_val else None
    return val, "OK" + (f"={val}" if val is not None else "?EMPTY?")

# ── Main ──
def main():
    parser = argparse.ArgumentParser(description='科聪控制器直查工具')
    parser.add_argument('--ip', default=DEFAULT_HOST, help=f'控制器IP (默认: {DEFAULT_HOST})')
    parser.add_argument('--full', action='store_true', help='完整状态+导航+变量检查')
    parser.add_argument('--vars', action='store_true', help='检查关键变量是否存在')
    parser.add_argument('--watch', action='store_true', help='持续监控')
    args = parser.parse_args()

    print("=" * 55)
    print("  科聪控制器直查工具")
    print(f"  目标: {args.ip}:{NAV_PORT}")
    print("=" * 55)

    if args.watch:
        print("\n持续监控 (Ctrl+C 退出)...\n")
        try:
            while True:
                print(f"\n{'─' * 45}")
                print(f"  {time.strftime('%H:%M:%S')}")
                print(f"{'─' * 45}")
                show_status(args.ip)
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n退出")
        return

    print("\n[0x17 运行状态]")
    ok = show_status(args.ip)
    if not ok:
        sys.exit(1)

    if args.full or args.vars:
        print("\n[变量检查]")
        vars_to_check = [
            ('Screen.ForkUp', '举升控制'),
            ('Screen.ForkDown', '下降控制'),
            ('Button.TopLimit', '上升限位'),
            ('Button.DownLimit', '下降限位'),
        ]
        for vname, desc in vars_to_check:
            val, status = check_variable(args.ip, vname)
            if val is None:
                print(f"  {vname:20s} ({desc}): {color(status, 'R')} — 变量不存在或通讯失败")
            elif val == 0:
                print(f"  {vname:20s} ({desc}): {color('0 (未触发)', 'Y')}")
            else:
                print(f"  {vname:20s} ({desc}): {color(f'{val} (已触发)', 'G')}")

    if args.full:
        print("\n[0x1D 导航状态]")
        ec, data = send(0x1D, args.ip)
        if ec == 0:
            nav_state = data[0x00]
            target_pt = struct.unpack_from('<H', data, 0x04)[0]
            ns = {0:'NONE',1:'WAIT',2:'GOING',3:'PAUSE',4:'DONE',5:'FAIL',6:'EXIT'}.get(nav_state, '?')
            print(f"  导航状态: {ns}")
            print(f"  目标点:   {target_pt}")


if __name__ == '__main__':
    main()
