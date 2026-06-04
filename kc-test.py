#!/usr/bin/env python3
"""
kc-test.py — openTCS 端到端测试工具
一键下发运输单并监控执行结果。

用法:
  python kc-test.py                                     # 默认: 前进→举升→放下→返回
  python kc-test.py --nop                               # 仅移动点1→点2→点1
  python kc-test.py --fork                              # 仅举升+放下(不动)
  python kc-test.py --single "Loc-2" "NOP"              # 单步自定义
  python kc-test.py --wait 120                          # 超时120秒
"""
import urllib.request
import urllib.error
import json
import time
import sys
import argparse
from datetime import datetime

KERNEL_URL = "http://127.0.0.1:55200"

# ── API ──
def api_get(path):
    try:
        with urllib.request.urlopen(KERNEL_URL + path, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [ERR] GET {path}: {e}")
        return None

def api_post(path, body=None):
    data = json.dumps(body).encode('utf-8') if body else None
    req = urllib.request.Request(KERNEL_URL + path, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [ERR] POST {path}: {e}")
        return None

def post_empty(path):
    req = urllib.request.Request(KERNEL_URL + path, data=b'', method='POST')
    try:
        urllib.request.urlopen(req, timeout=10)
    except:
        pass

# ── Color ──
def c(s, color):
    codes = {'G': '\033[92m', 'R': '\033[91m', 'Y': '\033[93m', 'C': '\033[96m', 'W': '\033[0m', 'B': '\033[1m'}
    return f"{codes.get(color, '')}{s}{codes['W']}"

TS  = {0:'NONE', 1:'WAIT', 2:'GOING', 3:'PAUSE', 4:'DONE', 5:'FAIL', 6:'EXIT'}

# ── Presets ──
PRESETS = {
    'full': [
        ('Loc-2', 'NOP'), ('Loc-2', 'LOAD'), ('Loc-2', 'UNLOAD'), ('Loc-1', 'NOP')
    ],
    'nop': [
        ('Loc-2', 'NOP'), ('Loc-1', 'NOP')
    ],
    'fork': [
        ('Loc-2', 'LOAD'), ('Loc-2', 'UNLOAD')
    ],
}

def main():
    global KERNEL_URL
    parser = argparse.ArgumentParser(description='openTCS 端到端测试工具')
    parser.add_argument('--full', action='store_true', help='完整流程: 前进→举升→放下→返回')
    parser.add_argument('--nop', action='store_true', help='仅移动: 点1→点2→点1')
    parser.add_argument('--fork', action='store_true', help='仅举升: LOAD+UNLOAD')
    parser.add_argument('--single', nargs=2, metavar=('LOC', 'OP'), help='单步: --single Loc-2 LOAD')
    parser.add_argument('--wait', type=int, default=120, help='最大等待秒数 (默认120)')
    parser.add_argument('--vehicle', type=str, default='AGV-001', help='车辆名')
    parser.add_argument('--url', type=str, default='http://127.0.0.1:55200', help='Kernel URL')
    args = parser.parse_args()
    KERNEL_URL = args.url

    # ── Build destinations ──
    if args.full:
        dests = PRESETS['full']
        preset = '完整流程'
    elif args.nop:
        dests = PRESETS['nop']
        preset = '仅移动'
    elif args.fork:
        dests = PRESETS['fork']
        preset = '仅举升'
    elif args.single:
        dests = [(args.single[0], args.single[1])]
        preset = f'{args.single[0]}:{args.single[1]}'
    else:
        dests = PRESETS['full']
        preset = '完整流程 (默认)'

    order_name = f"kc-test-{datetime.now().strftime('%H%M%S')}"

    print("=" * 55)
    print(f"  openTCS 端到端测试")
    print(f"  车辆: {args.vehicle}  模式: {preset}")
    print(f"  订单: {order_name}")
    print("=" * 55)

    # ── Check Kernel ──
    print("\n[1/4] 检查 Kernel...")
    vehicle = api_get(f"/v1/vehicles/{args.vehicle}")
    if vehicle is None:
        print(f"  {c('FAIL', 'R')} — Kernel 未响应")
        sys.exit(1)

    state = vehicle.get('state', '?')
    pos = vehicle.get('currentPosition', '?')
    il = vehicle.get('integrationLevel', '?')
    print(f"  车辆: {c(state, 'G')}  位置: {pos}  集成: {il}")
    if state != 'IDLE':
        print(f"  {c('车辆非 IDLE 状态，请先处理', 'Y')}")

    # ── Create order ──
    print(f"\n[2/4] 创建运输单...")
    body = {
        'intendedVehicle': args.vehicle,
        'destinations': [{'locationName': loc, 'operation': op} for loc, op in dests]
    }
    result = api_post(f"/v1/transportOrders/{order_name}", body)
    if result is None:
        print(f"  {c('FAIL', 'R')} — 创建失败")
        sys.exit(1)
    print(f"  {c('OK', 'G')}  dests={len(dests)}")

    # ── Trigger dispatcher ──
    print(f"\n[3/4] 触发调度...")
    post_empty("/v1/dispatcher/trigger")
    time.sleep(1)

    # ── Monitor ──
    print(f"\n[4/4] 监控执行 (超时 {args.wait}s)...")
    start = time.time()
    last_state = None

    while time.time() - start < args.wait:
        time.sleep(1)
        elapsed = int(time.time() - start)
        order = api_get(f"/v1/transportOrders/{order_name}")
        if order is None:
            print(f"  {elapsed}s: {c('connection lost', 'R')}")
            continue

        state = order.get('state', '?')
        if state != last_state:
            icon = '●' if state in ('BEING_PROCESSED', 'FINISHED') else '○'
            sc = 'G' if state == 'FINISHED' else ('Y' if state == 'BEING_PROCESSED' else 'W')
            print(f"  {elapsed:>3}s: {icon} {c(state, sc)}")
            last_state = state

        if state == 'FINISHED':
            break

    # ── Result ──
    order = api_get(f"/v1/transportOrders/{order_name}")
    if order and order.get('state') == 'FINISHED':
        elapsed = round(time.time() - start, 1)
        print(f"\n  {c('FINISHED', 'G')}  ({elapsed}s)")
    else:
        print(f"\n  {c('TIMEOUT or FAILED', 'R')}")
        v = api_get(f"/v1/vehicles/{args.vehicle}")
        if v:
            print(f"  当前状态: {v.get('state', '?')}  位置: {v.get('currentPosition', '?')}")


if __name__ == '__main__':
    main()
