#!/usr/bin/env python3
"""
kc-log.py — openTCS Kernel 日志高亮过滤工具
专注 Kecong 适配器和调度关键事件。

用法:
  python kc-log.py                          # 高亮显示最新日志(默认tail)
  python kc-log.py --follow                 # 实时跟踪(follow模式)
  python kc-log.py --tail 100               # 显示最后100行
  python kc-log.py --filter LIFT            # 仅显示LIFT相关
  python kc-log.py --filter "NAV|LIFT"      # 显示NAV或LIFT
  python kc-log.py --today                  # 仅显示今天的日志
  python kc-log.py --errors                 # 仅显示错误/警告
"""
import os
import sys
import re
import time
import argparse

LOG_FILE = r"C:\Users\ficog\Desktop\opentcs-7.2.1-bin\opentcs-kernel\log\opentcs-kernel.0.log"

# ── Color ──
def color(s, c):
    codes = {'G': '\033[92m', 'R': '\033[91m', 'Y': '\033[93m', 'C': '\033[96m', 'B': '\033[1m', 'W': '\033[0m', 'D': '\033[2m'}
    return f"{codes.get(c, '')}{s}{codes['W']}"

# ── Highlight rules ──
RULES = [
    # (pattern, color_for_keyword, label)
    (r'LIFT (START|WRITE_VAR|WAITING|READ_VAR|DONE|FAILED)', 'C', '[L]'),
    (r'(NAV SEND|NAV RESULT|NAV DISPATCHED)', 'C', '[N]'),
    (r'(enqueueCommand|Nav task)', 'C', '[>]'),
    (r'(Task completed|drive order finished|FINISHED)', 'G', '[+]'),
    (r'(LIFT FAILED|Failed to write|Nav task failed|FAILED|UNROUTABLE)', 'R', '[X]'),
    (r'(Robot error|Robot has errors)', 'R', '[!]'),
    (r'(WARNING|WARN)', 'Y', '[W]'),
    (r'(ERROR|Exception|FATAL)', 'R', '[E]'),
    (r'(BEING_PROCESSED|DISPATCHABLE)', 'Y', '[*]'),
    (r'(TO_BE_UTILIZED|TO_BE_RESPECTED)', 'B', '[I]'),
    (r'(positionResolutionRequested|Reported position)', 'D', '[P]'),
    (r'(KecongUdpChannel|KecongCommAdapter)', 'B', '[K]'),
]

def highlight(line):
    """Apply color rules to a log line."""
    for pattern, c, icon in RULES:
        if re.search(pattern, line):
            return f"{icon} {line}"
    return f"  {line}"

def filter_line(line, pattern):
    return re.search(pattern, line) is not None

def main():
    parser = argparse.ArgumentParser(description='Kernel 日志高亮工具')
    parser.add_argument('--follow', '-f', action='store_true', help='实时跟踪')
    parser.add_argument('--tail', '-t', type=int, default=50, help='显示最后N行 (默认50)')
    parser.add_argument('--filter', type=str, help='仅显示匹配的行 (regex)')
    parser.add_argument('--errors', action='store_true', help='仅显示错误/警告')
    parser.add_argument('--today', action='store_true', help='仅今日')
    parser.add_argument('--file', type=str, default=LOG_FILE, help=f'日志路径')
    args = parser.parse_args()

    log_path = args.file
    if not os.path.exists(log_path):
        print(f"日志文件不存在: {log_path}")
        sys.exit(1)

    # ── Build filter ──
    filters = []
    if args.filter:
        filters.append(re.compile(args.filter))
    if args.errors:
        filters.append(re.compile(r'WARN|ERROR|Exception|failed|FAILED'))
    if args.today:
        import datetime
        today = datetime.datetime.now().strftime('%Y%m%d')
        filters.append(re.compile(today))

    # ── Tail mode ──
    if not args.follow:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        lines = lines[-args.tail:]

        for line in lines:
            line = line.rstrip()
            if filters and not any(f.search(line) for f in filters):
                continue
            print(highlight(line))
        return

    # ── Follow mode ──
    print(f"{color('实时跟踪中 (Ctrl+C 退出)', 'C')}  {log_path}")

    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
        f.seek(0, 2)  # end of file
        try:
            while True:
                line = f.readline()
                if line:
                    line = line.rstrip()
                    if filters and not any(f.search(line) for f in filters):
                        continue
                    print(highlight(line))
                else:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            print(f"\n{color('退出', 'W')}")


if __name__ == '__main__':
    main()
