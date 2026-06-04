#!/usr/bin/env python3
"""
kc-diag.py — Kernel 状态诊断工具
检测扫单线程、适配器连接、订单积压等异常。

用法:
  python kc-diag.py                      # 全诊断
  python kc-diag.py --watch              # 持续监控 (10秒刷新)
  python kc-diag.py --sweep-only         # 仅扫单诊断
"""
import os
import sys
import re
import time
import json
import urllib.request
import argparse
from datetime import datetime, timedelta

LOG_FILE = r"C:\Users\ficog\Desktop\opentcs-7.2.1-bin\opentcs-kernel\log\opentcs-kernel.0.log"
KERNEL = "http://127.0.0.1:55200"

def G(s): return f"\033[92m{s}\033[0m"
def R(s): return f"\033[91m{s}\033[0m"
def Y(s): return f"\033[93m{s}\033[0m"
def B(s): return f"\033[1m{s}\033[0m"

def api_get(path):
    try:
        with urllib.request.urlopen(KERNEL + path, timeout=5) as r:
            return json.loads(r.read())
    except: return None

def read_log(tail=200):
    if not os.path.exists(LOG_FILE): return []
    with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    return lines[-tail:]

def parse_time(line):
    m = re.match(r'\[(\d{8})-(\d{2}:\d{2}:\d{2})[-,]', line)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y%m%d %H:%M:%S")
        except: pass
    return None

def diag_sweep(lines):
    """Detect if sweep is working."""
    print(f"\n{B('[扫单诊断]')}")

    raw_creates = []
    activations = []
    dispatches = []

    for line in lines:
        if 'createTransportOrder' in line:
            raw_creates.append(line)
        if 'RAW -> ACTIVE' in line:
            activations.append(line)
        if 'DISPATCHABLE -> BEING_PROCESSED' in line:
            dispatches.append(line)

    now = datetime.now()

    # Recent orders (last 5 min)
    recent_raw = [l for l in raw_creates if parse_time(l) and (now - parse_time(l)).seconds < 300]
    recent_act = [l for l in activations if parse_time(l) and (now - parse_time(l)).seconds < 300]

    print(f"  近5分钟创建: {len(recent_raw)} 个订单")
    print(f"  近5分钟激活: {len(recent_act)} 个订单 (RAW->ACTIVE)")

    # Stuck orders - created but never activated
    for rl in recent_raw:
        order_match = re.search(r'name=([^,]+)', rl)
        if order_match:
            order_name = order_match.group(1)
            activated = any(order_name in al for al in activations)
            if not activated:
                rt = parse_time(rl)
                age = int((now - rt).seconds) if rt else 0
                if age > 60:
                    print(f"  {R('STUCK')} {order_name} — 创建{age}s 仍未激活")

    if len(recent_raw) > 0 and len(recent_act) == 0:
        timeline = sorted([(parse_time(l), 'RAW') for l in recent_raw if parse_time(l)],
                         key=lambda x: x[0] if x[0] else datetime.min)
        if timeline:
            first = timeline[0][0]
            gap = int((now - first).seconds)
            print(f"  {R('扫单可能已停止!')} 首个待激活单已等待{gap}s")
            print(f"  检查: orderpool.sweepInterval 当前为 60000ms")
    elif len(recent_raw) == 0:
        print(f"  {Y('无待处理订单')}")

def diag_adapter(lines):
    """Check adapter connection status."""
    print(f"\n{B('[适配器诊断]')}")
    channels = []
    last_enable = None
    init_skipped = False

    for line in lines:
        if 'KecongUdpChannel opened' in line:
            channels.append(line)
        if 'autoInit disabled' in line:
            init_skipped = True
            last_enable = parse_time(line)

    if channels:
        for ch in channels[-2:]:
            match = re.search(r'opened: ([^\s]+:\d+)', ch)
            if match:
                print(f"  {G('连接')} {match.group(1)}")
    else:
        print(f"  {R('未检测到 UDP 连接')}")

    if init_skipped:
        if last_enable:
            print(f"  {Y('autoInit 已关闭')} ({last_enable.strftime('%H:%M:%S')})")

def diag_errors(lines):
    """Check for errors/exceptions."""
    print(f"\n{B('[异常诊断]')}")
    errors = [l for l in lines if 'Exception' in l or 'FATAL' in l or 'ERROR' in l
              if 'SSL encryption disabled' not in l
              if 'custom.properties not found' not in l]
    if errors:
        for e in errors[-3:]:
            print(f"  {R('ERR')} {e.strip()[:120]}")
    else:
        print(f"  {G('无严重异常')}")

def diag_orders():
    """Check stuck orders via REST API."""
    print(f"\n{B('[订单积压]')}")
    orders = api_get("/v1/transportOrders")
    if not orders:
        print(f"  {Y('无法获取订单列表 (Kernel离线?)')}")
        return
    stuck = {}
    for o in orders:
        s = o.get('state', '?')
        if s in ('RAW', 'DISPATCHABLE'):
            name = o.get('name', '?')
            stuck[name] = s
    if stuck:
        for name, s in stuck.items():
            print(f"  {Y(s)} {name}")
        print(f"  共 {len(stuck)} 个待处理订单")
    else:
        print(f"  {G('无积压')}")

def main():
    parser = argparse.ArgumentParser(description='Kernel 状态诊断工具')
    parser.add_argument('--watch', action='store_true', help='持续监控(10秒刷新)')
    parser.add_argument('--sweep-only', action='store_true', help='仅扫单诊断')
    parser.add_argument('--tail', type=int, default=200, help='扫描最近N行日志')
    args = parser.parse_args()

    print("=" * 55)
    print(f"  Kernel 状态诊断  {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 55)

    def run_diag():
        lines = read_log(args.tail)
        if args.sweep_only:
            diag_sweep(lines)
        else:
            diag_sweep(lines)
            diag_adapter(lines)
            diag_errors(lines)
            diag_orders()

    run_diag()

    if args.watch:
        print(f"\n{Y('持续监控中 (Ctrl+C 退出)...')}")
        try:
            while True:
                time.sleep(10)
                print(f"\n{'─'*55}")
                print(f"  {datetime.now().strftime('%H:%M:%S')}")
                print(f"{'─'*55}")
                run_diag()
        except KeyboardInterrupt:
            print("\n退出")


if __name__ == '__main__':
    main()
