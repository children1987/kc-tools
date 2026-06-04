#!/usr/bin/env python3
"""kc-e2e-test.py — 适配器集成测试, 用 kc-var-sim 模拟控制器验证 Kernel+Adapter 端到端流程."""
import urllib.request, json, sys, time, argparse
from datetime import datetime

def G(s): return f"\033[92m{s}\033[0m"
def R(s): return f"\033[91m{s}\033[0m"
def Y(s): return f"\033[93m{s}\033[0m"
def B(s): return f"\033[1m{s}\033[0m"

def api_get(kernel, path):
    try:
        with urllib.request.urlopen(kernel + path, timeout=5) as r:
            return json.loads(r.read())
    except: return None

def api_post(kernel, path, body=None):
    d = json.dumps(body).encode() if body else None
    req = urllib.request.Request(kernel + path, data=d, method='POST')
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except: return None

def post_empty(kernel, path):
    req = urllib.request.Request(kernel + path, data=b'', method='POST')
    try: urllib.request.urlopen(req, timeout=5)
    except: pass

def run_order(kernel, vehicle, name, destinations, timeout_sec=120):
    order_name = f"e2e-{name}-{datetime.now().strftime('%H%M%S')}"
    body = {'intendedVehicle': vehicle, 'destinations': destinations}
    if not api_post(kernel, f"/v1/transportOrders/{order_name}", body):
        return False, "API create failed"
    post_empty(kernel, "/v1/dispatcher/trigger")
    start = time.time()
    while time.time() - start < timeout_sec:
        time.sleep(1)
        o = api_get(kernel, f"/v1/transportOrders/{order_name}")
        if not o: continue
        s = o.get('state', '?')
        if s == 'FINISHED': return True, f"{round(time.time()-start,1)}s"
        if s in ('UNROUTABLE', 'FAILED'): return False, s
    return False, "TIMEOUT"

def main():
    p = argparse.ArgumentParser(description='适配器集成测试')
    p.add_argument('--test', choices=['nop','fork','full','all'], default='all')
    p.add_argument('--url', default='http://127.0.0.1:55200')
    p.add_argument('--vehicle', default='AGV-001')
    p.add_argument('--timeout', type=int, default=120)
    args = p.parse_args()
    kernel, vehicle, timeout_sec = args.url, args.vehicle, args.timeout

    print("=" * 55)
    print(f"  适配器集成测试  {kernel}")
    print("=" * 55)

    print(f"\n{B('[CHECK]')} Kernel...")
    v = api_get(kernel, f"/v1/vehicles/{vehicle}")
    if not v:
        print(f"  {R('FAIL')} Kernel 未响应"); sys.exit(1)
    il = v.get('integrationLevel', '?')
    if il != 'TO_BE_UTILIZED':
        for _ in range(30):
            time.sleep(2)
            v = api_get(kernel, f"/v1/vehicles/{vehicle}")
            if v and v.get('integrationLevel') == 'TO_BE_UTILIZED': break
    print(f"  {G('PASS')} (state={v.get('state','?')}, pos={v.get('currentPosition','?')})")

    tests = {
        'nop':  ('[NOP]  Loc-2:NOP→Loc-1:NOP',  [{'locationName':'Loc-2','operation':'NOP'},{'locationName':'Loc-1','operation':'NOP'}]),
        'fork': ('[FORK] Loc-2:LOAD→Loc-2:UNLOAD',[{'locationName':'Loc-2','operation':'LOAD'},{'locationName':'Loc-2','operation':'UNLOAD'}]),
        'full': ('[FULL] NOP→LOAD→UNLOAD→NOP',   [{'locationName':'Loc-2','operation':'NOP'},{'locationName':'Loc-2','operation':'LOAD'},{'locationName':'Loc-2','operation':'UNLOAD'},{'locationName':'Loc-1','operation':'NOP'}]),
    }
    to_run = tests if args.test == 'all' else {args.test: tests[args.test]}
    results = {}
    for name, (label, dests) in to_run.items():
        print(f"\n{B(label)}")
        ok, detail = run_order(kernel, vehicle, name, dests, timeout_sec)
        print(f"  {G('PASS') if ok else R('FAIL')} ({detail})")
        results[name] = ok
        time.sleep(2)

    print(f"\n{'='*55}")
    pn = sum(1 for v in results.values() if v)
    print(f"  结果: {pn}/{len(results)}  {'ALL PASS' if pn==len(results) else 'FAIL'}")
    for name, ok in results.items():
        print(f"    {name:6s}: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if pn == len(results) else 1)

if __name__ == '__main__':
    main()
