#!/usr/bin/env python3
"""
sync-model.py — 科聪模型同步工具
从控制器获取当前坐标，自动更新 openTCS 模型文件 (zhongwu.xml)

用法:
  python sync-model.py                          # 从控制器读取当前位置，设为点1
  python sync-model.py --pt1 1000,2000          # 手动指定点1坐标(mm)
  python sync-model.py --pt2 3000,5000          # 手动指定点2坐标(mm)
  python sync-model.py --ip 192.168.1.100       # 指定控制器IP
"""
import socket
import struct
import argparse
import math
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# ── 配置 ──
SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parent
DEFAULT_MODEL = WORKSPACE / "opentcs-7.2.1-bin/opentcs-modeleditor/data/zhongwu.xml"
DEFAULT_KERNEL_MODEL = WORKSPACE / "opentcs-7.2.1-bin/opentcs-kernel/data/model.xml"
DEFAULT_AUTH = bytes([0xed, 0x01, 0xe9, 0xd2, 0xb8, 0xa2, 0x6b, 0x4c,
                       0x85, 0x72, 0x77, 0xf2, 0xb2, 0xcb, 0x61, 0xb4])
NAV_PORT = 17804

# ── 协议工具 ──
def encode_frame(auth_code, cmd, seq, data=b''):
    ac = auth_code[:16].ljust(16, b'\x00')
    return struct.pack('<16sBBHBBBxHxx', ac, 1, 0, seq & 0xFFFF, 0x10, cmd, 0, len(data)) + data

def query_controller(ip, port=NAV_PORT, auth=DEFAULT_AUTH, timeout=3):
    """查询控制器 0x17 获取当前位置"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    sock.sendto(encode_frame(auth, 0x17, 0), (ip, port))
    try:
        data, _ = sock.recvfrom(2048)
        sock.close()
        d = data[0x1C:]
        px = struct.unpack_from('<d', d, 0x08)[0]  # meters
        py = struct.unpack_from('<d', d, 0x10)[0]
        heading = struct.unpack_from('<d', d, 0x18)[0]
        rm = d[0x2A]      # run mode: 0=manual, 1=auto
        ls = d[0x70]      # loc status
        ts = d[0x50]      # task state
        bat = struct.unpack_from('<d', d, 0x20)[0]
        cp = struct.unpack_from('<I', d, 0x2C)[0]
        return {
            'x_m': px, 'y_m': py, 'heading': heading,
            'x_mm': int(px * 1000), 'y_mm': int(py * 1000),
            'run_mode': rm, 'loc_status': ls, 'task_state': ts,
            'battery': bat, 'cur_pt': cp,
            'ts_name': {0:'NONE',1:'WAIT',2:'GOING',3:'PAUSE',4:'DONE',5:'FAIL',6:'EXIT'}.get(ts, str(ts)),
            'ls_name': {0:'FAIL',1:'SUCCESS',2:'LOCATING',3:'DONE'}.get(ls, str(ls)),
        }
    except socket.timeout:
        sock.close()
        return None

# ── 模型操作 ──
def load_model(path):
    tree = ET.parse(path)
    root = tree.getroot()
    return tree, root

def find_element(root, tag, name_attr='name', name_value=None):
    """查找 XML 元素"""
    for el in root.findall(tag):
        if name_value is None or el.get(name_attr) == name_value:
            return el
    return None

def update_point(root, pt_name, x_mm, y_mm):
    pt = find_element(root, 'point', 'name', pt_name)
    if pt is not None:
        pt.set('positionX', str(x_mm))
        pt.set('positionY', str(y_mm))
        return True
    return False

def update_location(root, loc_name, x_mm, y_mm):
    loc = find_element(root, 'location', 'name', loc_name)
    if loc is not None:
        loc.set('positionX', str(x_mm))
        loc.set('positionY', str(y_mm))
        return True
    return False

def update_path_length(root, path_name, length_mm):
    path = find_element(root, 'path', 'name', path_name)
    if path is not None:
        path.set('length', str(length_mm))
        return True
    return False

def calc_distance(x1, y1, x2, y2):
    return int(math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2))

def save_model(tree, path):
    tree.write(path, encoding='UTF-8', xml_declaration=True)
    print(f"  [OK] 已保存: {path}")

# ── 主程序 ──
def main():
    parser = argparse.ArgumentParser(description='科聪模型同步工具')
    parser.add_argument('--ip', type=str, default='192.168.100.178', help='控制器IP (默认: 192.168.100.178)')
    parser.add_argument('--pt1', type=str, help='点1坐标, 格式: "x,y" (mm)')
    parser.add_argument('--pt2', type=str, help='点2坐标, 格式: "x,y" (mm)')
    parser.add_argument('--step1', action='store_true', help='两步采集: 记录当前点为点1')
    parser.add_argument('--step2', action='store_true', help='两步采集: 记录当前点为点2, 更新模型')
    parser.add_argument('--auto', action='store_true', help='全自动: 采集点1→0x16走到点2→采集点2→更新模型')
    parser.add_argument('--dry-run', action='store_true', help='仅查询不修改')
    args = parser.parse_args()

    model_path = DEFAULT_MODEL
    kernel_path = DEFAULT_KERNEL_MODEL

    print("=" * 55)
    print("  科聪模型同步工具")
    print("=" * 55)

    # ── 两步采集模式 ──
    pending_file = model_path.parent / ".sync_pending.txt"
    pt1_x, pt1_y, pt2_x, pt2_y = None, None, None, None

    if args.step1:
        print(f"\n[Step 1/2] 读取当前点为 点1...")
        status = query_controller(args.ip)
        if status is None:
            print(f"  [FAIL] 无法连接控制器 {args.ip}:{NAV_PORT}")
            sys.exit(1)
        pt1_x, pt1_y = status['x_mm'], status['y_mm']
        pending_file.write_text(f"{pt1_x},{pt1_y}")
        print(f"  点1 = ({pt1_x}, {pt1_y}) mm  (已暂存)")
        print(f"\n  请将车移动到 点2，然后运行: python sync-model.py --step2")
        return

    if args.step2:
        if not pending_file.exists():
            print("[FAIL] 未找到暂存文件，请先运行 --step1")
            sys.exit(1)
        print(f"\n[Step 2/2] 读取当前点为 点2...")
        status = query_controller(args.ip)
        if status is None:
            print(f"  [FAIL] 无法连接控制器 {args.ip}:{NAV_PORT}")
            sys.exit(1)
        pt1_str = pending_file.read_text().strip()
        pt1_x, pt1_y = map(int, pt1_str.split(','))
        pt2_x, pt2_y = status['x_mm'], status['y_mm']
        pending_file.unlink()
        print(f"  点1 = ({pt1_x}, {pt1_y}) mm  (已加载)")
        print(f"  点2 = ({pt2_x}, {pt2_y}) mm  (当前位置)")

    # ── 全自动采集模式 ──
    if args.auto:
        print("\n[全自动] 采集模型坐标...")
        print(f"\n[1/3] 读取点1 (当前位置)...")
        status = query_controller(args.ip)
        if status is None:
            print(f"  [FAIL] 无法连接控制器 {args.ip}:{NAV_PORT}")
            sys.exit(1)
        pt1_x, pt1_y = status['x_mm'], status['y_mm']
        print(f"  点1 = ({pt1_x}, {pt1_y}) mm")

        print(f"\n[2/3] 导航到点2 (0x16)...")
        nav = struct.pack('<BBBB8s', 0, 0, 0, 0, b'2'.ljust(8, b'\x00')).ljust(432, b'\x00')
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        sock.sendto(encode_frame(DEFAULT_AUTH, 0x16, 0, nav), (args.ip, NAV_PORT))
        try:
            d, _ = sock.recvfrom(1024)
            ec = d[0x1C - 2]
            print(f"  exec=0x{ec:02x} ({'SUCCESS' if ec == 0 else 'FAIL'})")
            if ec != 0:
                print("  [FAIL] 导航命令被拒绝")
                sock.close(); sys.exit(1)
        except socket.timeout:
            print("  [FAIL] 超时")
            sock.close(); sys.exit(1)
        sock.close()

        print("  等待到达...", end=' ', flush=True)
        for _ in range(60):
            import time
            time.sleep(1)
            s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s2.settimeout(2)
            s2.sendto(encode_frame(DEFAULT_AUTH, 0x17, 0), (args.ip, NAV_PORT))
            try:
                d2, _ = s2.recvfrom(2048); s2.close()
                ts = d2[0x1C + 0x50]; px = struct.unpack_from('<d', d2, 0x1C + 0x08)[0]; py = struct.unpack_from('<d', d2, 0x1C + 0x10)[0]
                ts_n = {0:'NONE',1:'WAIT',2:'GOING',3:'PAUSE',4:'DONE',5:'FAIL'}
                print(f".", end='', flush=True)
                if ts == 4:
                    pt2_x, pt2_y = int(px * 1000), int(py * 1000)
                    print(f"\n  到达点2: ({pt2_x}, {pt2_y}) mm")
                    break
                elif ts == 5:
                    print(f"\n  [FAIL] 导航失败")
                    sys.exit(1)
            except: pass
        else:
            print("\n  [FAIL] 超时(60s)未到达")
            sys.exit(1)

        print(f"\n[3/3] 更新模型...")

    # ── 手动/自动读取点位 ──

    if not args.step1 and not args.step2:
        if args.pt1:
            parts = args.pt1.split(',')
            pt1_x, pt1_y = int(parts[0].strip()), int(parts[1].strip())
            print(f"\n[手动] 点1: ({pt1_x}, {pt1_y}) mm")

        if args.pt2:
            parts = args.pt2.split(',')
            pt2_x, pt2_y = int(parts[0].strip()), int(parts[1].strip())
            print(f"[手动] 点2: ({pt2_x}, {pt2_y}) mm")

        # ── 从控制器获取 ──
        if pt1_x is None or pt2_x is None:
            print(f"\n[查询] 连接 {args.ip}:{NAV_PORT} ...")
            status = query_controller(args.ip)
            if status is None:
                print(f"  [FAIL] 无法连接控制器 {args.ip}:{NAV_PORT}")
                print(f"  请确认: 1) 网络连通 2) 控制器已开机 3) IP正确")
                sys.exit(1)

            print(f"  位置: ({status['x_mm']}, {status['y_mm']}) mm")
            print(f"  朝向: {status['heading']:.2f} rad")
            print(f"  模式: {'AUTO' if status['run_mode'] == 1 else 'MANUAL'}")
            print(f"  定位: {status['ls_name']}")
            print(f"  任务: {status['ts_name']}")
            print(f"  电量: {status['battery'] * 100:.0f}%")
            print(f"  当前点ID: {status['cur_pt']}")

            if pt1_x is None:
                pt1_x, pt1_y = status['x_mm'], status['y_mm']
                print(f"\n  -> 点1 自动设为当前位置: ({pt1_x}, {pt1_y}) mm")
                print(f"  (如需两步采集: python sync-model.py --step1 然后 --step2)")

    if args.dry_run:
        print("\n[dry-run] 仅查询，不修改模型")
        return

    # ── 计算并更新模型 ──
    if pt2_x is None:
        print("\n[提示] 未指定点2，请输入坐标 (格式: x,y)：", end=' ')
        line = sys.stdin.readline().strip()
        if line:
            parts = line.split(',')
            pt2_x, pt2_y = int(parts[0].strip()), int(parts[1].strip())
        else:
            tree, _ = load_model(model_path)
            old_pt1 = find_element(tree.getroot(), 'point', 'name', '1')
            old_pt2 = find_element(tree.getroot(), 'point', 'name', '2')
            if old_pt1 is not None and old_pt2 is not None:
                dx = int(old_pt2.get('positionX')) - int(old_pt1.get('positionX'))
                dy = int(old_pt2.get('positionY')) - int(old_pt1.get('positionY'))
                pt2_x = pt1_x + dx
                pt2_y = pt1_y + dy
                print(f"  -> 点2 保持相对偏移: ({pt2_x}, {pt2_y}) mm")

    if pt2_x is None:
        print("[FAIL] 无法确定点2坐标")
        sys.exit(1)

    dist = calc_distance(pt1_x, pt1_y, pt2_x, pt2_y)

    print(f"\n[更新] 模型:")
    print(f"  点1: ({pt1_x}, {pt1_y}) mm  (车当前位置)")
    print(f"  点2: ({pt2_x}, {pt2_y}) mm")
    print(f"  距离: {dist} mm ({dist / 1000:.1f} m)")

    tree, root = load_model(model_path)
    update_point(root, '1', pt1_x, pt1_y)
    update_point(root, '2', pt2_x, pt2_y)
    update_location(root, 'Loc-1', pt1_x, pt1_y)
    update_location(root, 'Loc-2', pt2_x, pt2_y)
    update_path_length(root, '1 -- 2', dist)
    update_path_length(root, '2 -- 1', dist)
    save_model(tree, model_path)

    if kernel_path.exists():
        save_model(tree, kernel_path)
        print("\n[提示] 模型已同步到 Kernel data/ 目录")

    print("\n[完成] 请重启 Kernel 使模型生效")


if __name__ == '__main__':
    main()
