#!/usr/bin/env python3
"""
kc-var-sim.py — 科聪变量模拟器 (极简版)
仅模拟 WRITE_VAR/READ_VAR，用于验证举升变量读写逻辑。

启动后自动响应:
  - 0x17 QUERY_RUN_STATUS  → 返回假位置
  - 0x00 WRITE_VAR         → Screen.ForkUp/Down 写1后，0.5s后限位=1
  - 0x01 READ_VAR          → 返回变量值

用法:
  python kc-var-sim.py                     # 启动 (端口17804)
  python kc-var-sim.py --port 17805        # 指定端口
"""
import socket
import struct
import time
import argparse
import threading

AUTH = b'KC-SIMULATOR-01'
HEADER_SIZE = 0x1C

# ── State ──
vars_state = {
    'Screen.ForkUp': 0,
    'Screen.ForkDown': 0,
    'Button.TopLimit': 0,
    'Button.DownLimit': 0,
}
lift_timer = 0.0
lift_active = False

# ── Protocol ──
def encode_frame(cmd, seq, data=b''):
    ac = AUTH[:16].ljust(16, b'\x00')
    return struct.pack('<16sBBHBBBxHxx', ac, 1, 1, seq & 0xFFFF, 0x10, cmd, 0, len(data)) + data

def encode_run_status():
    """Fake 0x17 response: pos=(0,0), AUTO, DONE"""
    buf = bytearray(0xC0)
    struct.pack_into('<d', buf, 0x08, 0.0)    # pos_x
    struct.pack_into('<d', buf, 0x10, 0.0)    # pos_y
    struct.pack_into('<d', buf, 0x18, 0.0)    # heading
    struct.pack_into('<d', buf, 0x20, 0.9)    # battery
    buf[0x2A] = 1    # run_mode = AUTO
    buf[0x2B] = 0    # map_loaded = OK
    buf[0x50] = 0    # task_state = NONE
    buf[0x70] = 3    # loc_status = DONE
    buf[0x74] = 1    # map_count = 1
    buf[0x78:0x78 + 10] = b'kc-var-sim'
    struct.pack_into('<f', buf, 0xB8, 1.0)    # confidence
    return bytes(buf)

def decode_frame(raw):
    if len(raw) < HEADER_SIZE:
        return None
    _, _, msg_type, seq, _, cmd, _, data_len = struct.unpack_from('<16sBBHBBBxH', raw, 0)
    data = raw[HEADER_SIZE:HEADER_SIZE + data_len] if data_len else b''
    return {'cmd': cmd, 'seq': seq, 'data': data, 'is_req': msg_type == 0}

# ── Server ──
def handle_packet(data, addr, sock):
    frame = decode_frame(data)
    if not frame or not frame['is_req']:
        return

    cmd = frame['cmd']
    req_data = frame['data']
    seq = frame['seq']

    if cmd == 0x17:   # QUERY_RUN_STATUS
        resp = encode_run_status()
        sock.sendto(encode_frame(0x17, seq, resp), addr)

    elif cmd == 0x00:  # WRITE_VAR
        if len(req_data) >= 17:
            name = req_data[:16].rstrip(b'\x00').decode('ascii', errors='replace')
            val = req_data[16]
            if name in vars_state:
                vars_state[name] = val
                if name == 'Screen.ForkUp' and val:
                    vars_state['Button.TopLimit'] = 0
                    vars_state['Button.DownLimit'] = 0
                    global lift_timer, lift_active
                    lift_timer = time.monotonic()
                    lift_active = True
                    print(f"  WRITE {name}={val} -> 模拟举升中...")
                elif name == 'Screen.ForkDown' and val:
                    vars_state['Button.TopLimit'] = 0
                    vars_state['Button.DownLimit'] = 0
                    lift_timer = time.monotonic()
                    lift_active = True
                    print(f"  WRITE {name}={val} -> 模拟下降中...")
                else:
                    print(f"  WRITE {name}={val}")
        sock.sendto(encode_frame(0x00, seq), addr)  # ACK

    elif cmd == 0x01:  # READ_VAR
        if len(req_data) >= 16:
            name = req_data[:16].rstrip(b'\x00').decode('ascii', errors='replace')
            val = vars_state.get(name, 0)
            resp = req_data[:16] + bytes([val])
            print(f"  READ {name} = {val}")
            sock.sendto(encode_frame(0x01, seq, resp), addr)
        else:
            sock.sendto(encode_frame(0x01, seq, b'\x00' * 4), addr)

    elif cmd == 0x11:  # AUTO_MANUAL_SWITCH
        sock.sendto(encode_frame(0x11, seq), addr)

    elif cmd == 0xAF:  # Legacy QUERY_ROBOT_STATUS
        sock.sendto(encode_frame(0xAF, seq, encode_run_status()), addr)

def update_loop():
    global lift_active, lift_timer
    while True:
        if lift_active:
            elapsed = time.monotonic() - lift_timer
            if elapsed > 0.5:
                if vars_state.get('Screen.ForkUp'):
                    vars_state['Button.TopLimit'] = 1
                    vars_state['Screen.ForkUp'] = 0
                    print("  -> TopLimit=1 (举升完成)")
                elif vars_state.get('Screen.ForkDown'):
                    vars_state['Button.DownLimit'] = 1
                    vars_state['Screen.ForkDown'] = 0
                    print("  -> DownLimit=1 (下降完成)")
                lift_active = False
        time.sleep(0.05)

def main():
    parser = argparse.ArgumentParser(description='科聪变量模拟器')
    parser.add_argument('--port', type=int, default=17804, help='UDP 端口 (默认17804)')
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', args.port))
    sock.settimeout(0.5)

    threading.Thread(target=update_loop, daemon=True).start()

    print("=" * 50)
    print(f"  科聪变量模拟器")
    print(f"  端口: {args.port}")
    print(f"  模拟变量: Screen.ForkUp/Down, Button.TopLimit/DownLimit")
    print(f"  工作逻辑: WRITE_VAR → 0.5s → 限位=1")
    print("=" * 50)
    print(f"\n  测试: python kc-inspect.py --ip 127.0.0.1 --full")
    print(f"  Ctrl+C 退出\n")

    try:
        while True:
            try:
                data, addr = sock.recvfrom(2048)
                handle_packet(data, addr, sock)
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        print("\n退出")
    finally:
        sock.close()


if __name__ == '__main__':
    main()
