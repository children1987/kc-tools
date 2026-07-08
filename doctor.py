#!/usr/bin/env python3
"""
doctor.py — 阿根廷项目现场诊断工具
=====================================
一键检查网络、配置、服务、日志、环境，生成报告文件。
双击 doctor.bat 即可运行。

设计原则:
  - 零依赖: 仅用 Python 标准库
  - 只读: 不修改任何配置文件
  - 容错: 单项失败不影响后续检查
  - 自包含: 协议层内联，不依赖其他 .py 文件
"""
import socket
import struct
import sys
import os
import re
import json
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════
# 协议层（与 kc-inspect.py 保持一致）
# ═══════════════════════════════════════════════════════════════════════

AUTH = bytes([0xed, 0x01, 0xe9, 0xd2, 0xb8, 0xa2, 0x6b, 0x4c,
              0x85, 0x72, 0x77, 0xf2, 0xb2, 0xcb, 0x61, 0xb4])

NAV_PORT = 17804
QR_PORT = 17800

REAL_NAV_HOST = "192.168.100.178"
REAL_QR_HOST = "192.168.100.200"
SIM_HOST = "127.0.0.1"

KERNEL_URL = "http://localhost:55200"
APP_URL = "http://localhost:8081"


def enc(cmd, seq=0, data=b''):
    ac = AUTH[:16].ljust(16, b'\x00')
    return struct.pack('<16sBBHBBBxHxx', ac, 1, 0, seq & 0xFFFF, 0x10, cmd, 0, len(data)) + data


def send(cmd, host, port=NAV_PORT, data=b'', seq=0, timeout=3):
    """发送 UDP 命令，返回 (exec_code, payload)。exec_code=-1 表示超时。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(enc(cmd, seq, data), (host, port))
        d, _ = s.recvfrom(2048)
        ec = d[0x1C - 2]
        dl = struct.unpack_from('<H', d, 0x18)[0]
        return ec, d[0x1C:0x1C + dl]
    except socket.timeout:
        return -1, b''
    except OSError:
        return -1, b''
    finally:
        s.close()


def parse_run_status(data):
    """解析 0x17 响应。返回 dict 或 None。"""
    if len(data) < 0xC0:
        return None
    return {
        'pos_x': struct.unpack_from('<d', data, 0x08)[0],
        'pos_y': struct.unpack_from('<d', data, 0x10)[0],
        'heading': struct.unpack_from('<d', data, 0x18)[0],
        'battery': struct.unpack_from('<d', data, 0x20)[0],
        'blocked': data[0x28],
        'charging': data[0x29],
        'run_mode': data[0x2A],
        'map_loaded': data[0x2B],
        'cur_pt': struct.unpack_from('<I', data, 0x2C)[0],
        'speed_fwd': struct.unpack_from('<d', data, 0x30)[0],
        'task_state': data[0x50],
        'map_version': struct.unpack_from('<H', data, 0x52)[0],
        'loc_status': data[0x70],
        'map_count': struct.unpack_from('<I', data, 0x74)[0],
        'map_name': data[0x78:0x78 + 64].rstrip(b'\x00').decode('ascii', errors='replace'),
        'confidence': struct.unpack_from('<f', data, 0xB8)[0],
    }


# ── 执行码对照 ──
EXEC_CODES = {
    0x00: "成功",
    0x01: "失败(未知)",
    0x02: "服务码错误",
    0x03: "命令码错误",
    0x04: "帧头错误",
    0x05: "长度错误",
    0x80: "导航状态冲突",
    0xFF: "认证码错误(AUTH)",
}

# ═══════════════════════════════════════════════════════════════════════
# 路径解析
# ═══════════════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parent.parent


def find_opentcs_dir():
    """自动发现 opentcs-X.Y.Z-bin 目录。"""
    candidates = sorted(WORKSPACE.glob("opentcs-*-bin"), reverse=True)
    for c in candidates:
        if (c / "opentcs-kernel" / "data" / "model.xml").exists():
            return c
    return None


OPENTCS_DIR = find_opentcs_dir()

FORK_UDP_FILE = WORKSPACE / "projects" / "argentina-app" / "app" / "fork_udp.py"
MODEL_FILE = WORKSPACE / "projects" / "argentina-app" / "model.xml"
KERNEL_MODEL_FILE = OPENTCS_DIR / "opentcs-kernel" / "data" / "model.xml" if OPENTCS_DIR else None

# 日志文件（取最近修改的）
LOG_FILE = None
if OPENTCS_DIR:
    log_dir = OPENTCS_DIR / "opentcs-kernel" / "log"
    if log_dir.exists():
        candidates = sorted(log_dir.glob("opentcs-kernel*.log"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            LOG_FILE = candidates[0]

# ═══════════════════════════════════════════════════════════════════════
# 输出基础设施
# ═══════════════════════════════════════════════════════════════════════

REPORT_LINES: list[str] = []
FAIL_COUNT = 0
WARN_COUNT = 0


def color(s, c):
    codes = {'G': '\033[92m', 'R': '\033[91m', 'Y': '\033[93m', 'C': '\033[96m', 'W': '\033[0m', 'B': '\033[1m'}
    return f"{codes.get(c, '')}{s}{codes['W']}"


def both(msg):
    """同时输出到控制台和报告。"""
    print(msg)
    # 去掉 ANSI 转义码写入纯文本报告
    plain = re.sub(r'\033\[\d+(;\d+)?m', '', msg)
    REPORT_LINES.append(plain)


def ok(msg):
    global FAIL_COUNT, WARN_COUNT
    both(f"  {color('[OK]', 'G')}    {msg}")


def fail(msg):
    global FAIL_COUNT
    FAIL_COUNT += 1
    both(f"  {color('[FAIL]', 'R')}  {msg}")


def warn(msg):
    global WARN_COUNT
    WARN_COUNT += 1
    both(f"  {color('[WARN]', 'Y')}  {msg}")


def info(msg):
    both(f"  {color('[INFO]', 'C')}  {msg}")


def section(title):
    both("")
    both(f"{color('——', 'C')} {color(title, 'B')} {color('——', 'C')}")


# ═══════════════════════════════════════════════════════════════════════
# L1: 网络连通性
# ═══════════════════════════════════════════════════════════════════════

def check_ping(host, label):
    """ping 2 次，3 秒超时。"""
    try:
        r = subprocess.run(
            ["ping", "-n", "2", "-w", "3000", host],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            # 提取平均延迟
            m = re.search(r'Average\s*=\s*(\d+)ms', r.stdout, re.IGNORECASE)
            if not m:
                m = re.search(r'平均\s*=\s*(\d+)ms', r.stdout)
            latency = f" — 平均 {m.group(1)}ms" if m else ""
            ok(f"ping {host} ({label}){latency}")
            return True
        else:
            fail(f"ping {host} ({label}) — 不通")
            return False
    except subprocess.TimeoutExpired:
        fail(f"ping {host} ({label}) — 超时")
        return False
    except FileNotFoundError:
        warn(f"ping 命令不可用，跳过 {host} ({label})")
        return True  # not a hard failure


def check_udp_controller(host, port, label):
    """UDP 0x17 查询控制器。"""
    ec, data = send(0x17, host, port, timeout=3)
    if ec == -1:
        fail(f"UDP 0x17 {host}:{port} ({label}) — 超时，控制器无响应")
        return False
    if ec != 0:
        reason = EXEC_CODES.get(ec, f"未知(0x{ec:02X})")
        fail(f"UDP 0x17 {host}:{port} ({label}) — exec=0x{ec:02X} ({reason})")
        return False

    s = parse_run_status(data)
    if s:
        rm = 'AUTO' if s['run_mode'] == 1 else 'MANUAL'
        batt = f"{s['battery'] * 100:.0f}%"
        pos = f"({s['pos_x']:.2f}, {s['pos_y']:.2f})m"
        conf = f"{s['confidence'] * 100:.0f}%"
        ok(f"UDP 0x17 {host}:{port} ({label}) — {rm}, 电量={batt}, 位置={pos}, 置信度={conf}")
        return True
    else:
        warn(f"UDP 0x17 {host}:{port} ({label}) — 响应但解析失败 (len={len(data)})")
        return False


def diag_network() -> bool:
    """L1: 网络连通性诊断。"""
    all_ok = True

    # 判断当前模式
    mode = detect_mode()

    if mode == "real":
        # 实车模式：检查双 IP
        if not check_ping(REAL_NAV_HOST, "导航控制器"):
            all_ok = False
        if not check_ping(REAL_QR_HOST, "QR/变量控制器"):
            all_ok = False
        if not check_udp_controller(REAL_NAV_HOST, NAV_PORT, "导航端口"):
            all_ok = False
        # QR 端口不响应 0x17 是正常的（它是变量端口），仅尝试 ping
        info(f"网络模式: 实车 (Real Vehicle)")
    elif mode == "sim":
        # 模拟器模式：检查本地
        if not check_ping(SIM_HOST, "本机"):
            all_ok = False
        if not check_udp_controller(SIM_HOST, NAV_PORT, "模拟器"):
            all_ok = False
        info(f"网络模式: 模拟器 (Simulator)")
    else:
        warn(f"无法判断当前模式（fork_udp.py 中 controller_ip 未知）")
        # 仍然尝试检查实车 IP
        check_ping(REAL_NAV_HOST, "导航控制器(推测)")
        check_ping(REAL_QR_HOST, "QR/变量控制器(推测)")

    # 本机 IP 信息
    try:
        r = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if 'IPv4' in line or 'IP Address' in line or 'Subnet Mask' in line or '子网掩码' in line:
                info(f"  {line.strip()}")
            elif 'Ethernet' in line or '以太网' in line or '无线' in line or 'Wireless' in line:
                if 'adapter' in line.lower() or '适配器' in line:
                    info(f"  {line.strip()}")
    except Exception:
        pass  # ipconfig not critical

    return all_ok


# ═══════════════════════════════════════════════════════════════════════
# L2: 模型配置一致性
# ═══════════════════════════════════════════════════════════════════════

def extract_model_ips(xml_path: Path) -> dict | None:
    """从 model.xml 提取 kecong:navHost 和 kecong:qrHost。"""
    if not xml_path or not xml_path.exists():
        return None
    content = xml_path.read_text(encoding="utf-8")
    nav = re.search(r'<property name="kecong:navHost" value="([^"]+)"', content)
    qr = re.search(r'<property name="kecong:qrHost" value="([^"]+)"', content)
    if nav and qr:
        return {"navHost": nav.group(1), "qrHost": qr.group(1)}
    return None


def extract_fork_udp_ip() -> str | None:
    """从 fork_udp.py 提取 controller_ip 默认值。"""
    if not FORK_UDP_FILE.exists():
        return None
    content = FORK_UDP_FILE.read_text(encoding="utf-8")
    m = re.search(r'controller_ip:\s*str\s*=\s*"([^"]+)"', content)
    return m.group(1) if m else None


def detect_mode() -> str | None:
    """判断当前 sim/real 模式。"""
    ip = extract_fork_udp_ip()
    if ip == SIM_HOST:
        return "sim"
    elif ip == REAL_QR_HOST or ip == REAL_NAV_HOST:
        return "real"
    return None


def check_points_exist(xml_path: Path, point_names: list[str]) -> tuple[int, list[str]]:
    """检查模型文件中是否存在指定点位。返回 (存在数, 缺失列表)。"""
    if not xml_path.exists():
        return 0, point_names
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        all_points = {p.get("name") for p in root.findall(".//point") if p.get("name")}
        missing = [p for p in point_names if p not in all_points]
        return len(point_names) - len(missing), missing
    except ET.ParseError:
        return 0, point_names


def check_vehicle_exists(xml_path: Path, vehicle_name: str) -> bool:
    """检查车辆定义是否存在。"""
    if not xml_path.exists():
        return False
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        return any(v.get("name") == vehicle_name for v in root.findall(".//vehicle"))
    except ET.ParseError:
        return False


def diag_model() -> bool:
    """L2: 模型配置一致性诊断。"""
    all_ok = True

    # 提取三个 IP 源
    fork_ip = extract_fork_udp_ip()
    kernel_ips = extract_model_ips(KERNEL_MODEL_FILE)
    master_ips = extract_model_ips(MODEL_FILE)

    # fork_udp.py
    if fork_ip:
        ok(f"fork_udp.py: controller_ip = {fork_ip}")
    else:
        fail(f"fork_udp.py: 未找到 controller_ip 定义")
        all_ok = False

    # Kernel model.xml
    if kernel_ips:
        ok(f"Kernel model.xml:    navHost={kernel_ips['navHost']}, qrHost={kernel_ips['qrHost']}")
    else:
        fail(f"Kernel model.xml ({KERNEL_MODEL_FILE}): 未找到 kecong:navHost/qrHost 属性")
        all_ok = False

    # 主副本 model.xml
    if master_ips:
        ok(f"主副本 model.xml:    navHost={master_ips['navHost']}, qrHost={master_ips['qrHost']}")
    else:
        warn(f"主副本 model.xml ({MODEL_FILE}): 未找到 kecong:navHost/qrHost 属性")

    # 交叉比对
    mode = detect_mode()
    if mode == "real":
        expected_nav = REAL_NAV_HOST
        expected_qr = REAL_QR_HOST
    elif mode == "sim":
        expected_nav = SIM_HOST
        expected_qr = SIM_HOST
    else:
        expected_nav = expected_qr = None

    if expected_nav and kernel_ips:
        issues = []
        if kernel_ips["navHost"] != expected_nav:
            issues.append(f"navHost={kernel_ips['navHost']} (应为 {expected_nav})")
        if kernel_ips["qrHost"] != expected_qr:
            issues.append(f"qrHost={kernel_ips['qrHost']} (应为 {expected_qr})")
        if issues:
            fail(f"Kernel model.xml IP 与 {mode} 模式不匹配: {', '.join(issues)}")
            all_ok = False
        else:
            ok(f"Kernel model.xml IP 匹配 {mode} 模式")

    # 检查主副本是否与 Kernel 一致
    if kernel_ips and master_ips:
        if kernel_ips == master_ips:
            ok("主副本与 Kernel model.xml 一致")
        else:
            warn(f"主副本与 Kernel model.xml 不一致！主副本: nav={master_ips['navHost']},qr={master_ips['qrHost']} | Kernel: nav={kernel_ips['navHost']},qr={kernel_ips['qrHost']}")

    # 关键点位检查（使用 Kernel 模型）
    KEY_POINTS = ["KC-2041", "KC-2042", "KC-1", "KC-500", "KC-501"]
    if KERNEL_MODEL_FILE and KERNEL_MODEL_FILE.exists():
        found, missing = check_points_exist(KERNEL_MODEL_FILE, KEY_POINTS)
        if missing:
            warn(f"Kernel 模型缺少点位: {', '.join(missing)} (可能导致 ObjectUnknownException)")
        else:
            ok(f"关键点位全部存在 ({len(KEY_POINTS)} 个)")

    # 车辆定义
    if KERNEL_MODEL_FILE and KERNEL_MODEL_FILE.exists():
        if check_vehicle_exists(KERNEL_MODEL_FILE, "AGV-001"):
            ok("车辆定义存在: AGV-001")
        else:
            fail("Kernel 模型中未找到车辆 AGV-001")
            all_ok = False

    return all_ok


# ═══════════════════════════════════════════════════════════════════════
# L3: 服务运行状态
# ═══════════════════════════════════════════════════════════════════════

def api_get(path: str) -> dict | None:
    """Kernel REST API GET 请求。"""
    try:
        req = urllib.request.Request(
            f"{KERNEL_URL}/v1{path}",
            headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return None


def check_port_bound(port: int) -> bool:
    """检查 UDP 端口是否被占用。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.1)
    try:
        s.bind(("127.0.0.1", port))
        s.close()
        return False
    except OSError:
        return True


def diag_services() -> bool:
    """L3: 服务运行状态诊断。"""
    all_ok = True

    # Kernel REST API
    vehicles = api_get("/vehicles")
    if vehicles is None:
        fail(f"Kernel REST API 无响应 ({KERNEL_URL})")
        all_ok = False
    else:
        ok(f"Kernel REST API 响应正常 ({KERNEL_URL})")
        # AGV-001 详情
        agv = None
        if isinstance(vehicles, list):
            for v in vehicles:
                if isinstance(v, dict) and v.get("name") == "AGV-001":
                    agv = v
                    break
        if agv:
            il = agv.get("integrationLevel", "?")
            el = agv.get("energyLevel", "?")
            ps = agv.get("procState", "?")
            pos = agv.get("currentPosition", "?")
            ok(f"AGV-001: integrationLevel={il}, energyLevel={el}, procState={ps}, position={pos}")

            # 关键状态检查
            if il not in ("TO_BE_UTILIZED", "UNAVAILABLE"):
                warn(f"AGV-001 integrationLevel={il} (通常应为 TO_BE_UTILIZED)")
            if isinstance(el, (int, float)) and el < 20:
                warn(f"AGV-001 电量低: {el}%")
        else:
            warn("Kernel 返回了车辆列表但未找到 AGV-001")

    # 运输单积压
    orders = api_get("/transportOrders")
    if orders is not None:
        if isinstance(orders, list):
            # 过滤非终态订单
            backlog = []
            for o in orders:
                if isinstance(o, dict) and o.get("state") not in ("FINISHED", "FAILED", "WITHDRAWN", None):
                    backlog.append(f"{o.get('name', '?')} ({o.get('state', '?')})")
            if backlog:
                warn(f"积压订单 ({len(backlog)} 个): {', '.join(backlog[:5])}{'...' if len(backlog) > 5 else ''}")
            else:
                ok("运输单: 无积压")
    else:
        info("运输单查询跳过 (Kernel API 不可用)")

    # argentina-app
    try:
        req = urllib.request.Request(APP_URL, headers={"Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=3) as r:
            ok(f"argentina-app HTTP 响应正常 ({APP_URL}, status={r.status})")
    except Exception:
        warn(f"argentina-app HTTP 无响应 ({APP_URL}) — 可能未启动")

    # 端口占用检查
    mode = detect_mode()
    port_17804_used = check_port_bound(NAV_PORT)
    port_17800_used = check_port_bound(QR_PORT)

    if port_17804_used:
        if mode == "real":
            warn(f"端口 {NAV_PORT} 已被占用 — 实车模式下应仅 Kernel/适配器使用此端口，可能 kc-simulator 未停止！")
            warn(f"  → 排查: netstat -ano | findstr {NAV_PORT}，如非 Java 进程则停掉")
        else:
            info(f"端口 {NAV_PORT} 已占用（模拟器模式，正常）")
    else:
        info(f"端口 {NAV_PORT} 空闲")

    if port_17800_used:
        info(f"端口 {QR_PORT} 已占用")
    else:
        info(f"端口 {QR_PORT} 空闲")

    return all_ok


# ═══════════════════════════════════════════════════════════════════════
# L4: 日志异常分析
# ═══════════════════════════════════════════════════════════════════════

def diag_logs() -> bool:
    """L4: 日志异常分析。"""
    if not LOG_FILE or not LOG_FILE.exists():
        warn(f"未找到 Kernel 日志文件")
        return True  # not a hard failure

    mtime = datetime.fromtimestamp(LOG_FILE.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    info(f"日志文件: {LOG_FILE.relative_to(WORKSPACE)} (最后修改: {mtime})")

    try:
        content = LOG_FILE.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
    except Exception:
        warn("无法读取日志文件")
        return True

    # 取最近 1000 行
    recent = lines[-1000:]

    # 异常检测
    error_patterns = [
        ("Exception", "异常"),
        ("FATAL", "严重错误"),
        ("ObjectUnknownException", "引用不存在的对象(点位/路径)"),
        ("exec=0xFF", "认证码错误(AUTH)"),
        ("Auth code error", "认证码错误"),
        ("timeout", "超时"),
        ("Unhandled exception", "未处理异常"),
    ]

    error_counts = {}
    for line in recent:
        line_upper = line.upper()
        for pattern, desc in error_patterns:
            if pattern.upper() in line_upper:
                error_counts[desc] = error_counts.get(desc, 0) + 1

    if error_counts:
        summary = ", ".join(f"{desc}×{n}" for desc, n in sorted(error_counts.items(), key=lambda x: -x[1]))
        fail(f"近 {len(recent)} 行中发现异常: {summary}")
        # 打印最后几条异常行
        error_lines = []
        for line in recent:
            line_upper = line.upper()
            if any(p.upper() in line_upper for p, _ in error_patterns):
                error_lines.append(line.strip())
        for el in error_lines[-5:]:
            ts_match = re.search(r'\[(\d{8}-\d{2}:\d{2}:\d{2})[,\-\]]', el)
            ts = ts_match.group(1) if ts_match else "?"
            info(f"  [{ts}] ...{el[-120:]}")
        return False
    else:
        ok(f"近 {len(recent)} 行无异常")

    # 最近 WARNING/ERROR
    warn_lines = [l for l in recent if 'WARNING' in l.upper() or 'ERROR' in l.upper() or 'WARN' in l.upper()]
    if warn_lines:
        info(f"最近 {len(warn_lines)} 条 WARNING/ERROR (共 {len(recent)} 行):")
        for wl in warn_lines[-10:]:
            ts_match = re.search(r'\[(\d{8}-\d{2}:\d{2}:\d{2})[,\-\]]', wl)
            ts = ts_match.group(1) if ts_match else "?"
            info(f"  [{ts}] ...{wl[-140:]}")
    else:
        ok("无 WARNING/ERROR 行")

    return True


# ═══════════════════════════════════════════════════════════════════════
# L5: 环境元信息
# ═══════════════════════════════════════════════════════════════════════

def diag_environment() -> bool:
    """L5: 环境元信息。"""
    # Python
    info(f"Python: {sys.version}")

    # Java
    try:
        r = subprocess.run(["java", "-version"], capture_output=True, text=True, timeout=5)
        ver_line = r.stderr.splitlines()[0] if r.stderr else (r.stdout.splitlines()[0] if r.stdout else "?")
        ok(f"Java: {ver_line.strip()}")
    except FileNotFoundError:
        warn("Java 未安装或不在 PATH 中")
    except subprocess.TimeoutExpired:
        warn("java -version 超时")
    except Exception:
        warn("无法获取 Java 版本")

    # 模式
    mode = detect_mode()
    mode_str = "实车 (Real Vehicle)" if mode == "real" else ("模拟器 (Simulator)" if mode == "sim" else "未知")
    if mode:
        ok(f"当前模式: {mode_str}")
    else:
        warn(f"当前模式: {mode_str} (fork_udp.py 中 controller_ip 未识别)")

    # opentcs 目录
    if OPENTCS_DIR:
        info(f"openTCS 目录: {OPENTCS_DIR}")
    else:
        warn("未找到 openTCS-*-bin 目录")

    # 关键文件存在性
    files_status = []
    for label, path in [
        ("fork_udp.py", FORK_UDP_FILE),
        ("主副本 model.xml", MODEL_FILE),
        ("Kernel model.xml", KERNEL_MODEL_FILE),
        ("Kernel 日志", LOG_FILE),
    ]:
        exists = path and path.exists()
        status = "存在" if exists else "缺失"
        if not exists:
            status = color("缺失", 'R')
        files_status.append(f"{label}: {status}")
    info("关键文件: " + ", ".join(files_status))

    return True


# ═══════════════════════════════════════════════════════════════════════
# 修复建议
# ═══════════════════════════════════════════════════════════════════════

REMEDIATIONS = {
    "ping不通": [
        "检查 PC 与控制器是否在同一网段 (192.168.100.x)",
        "检查网线是否插好",
        "检查 Windows 防火墙是否拦截了 ICMP 和 UDP",
    ],
    "UDP超时": [
        "控制器可能未开机或导航服务未启动",
        "检查 Windows 防火墙是否拦截了 UDP 端口 17804/17800",
        "用 kc-inspect.py --ip <IP> --full 直接测试",
    ],
    "认证码错误": [
        "控制器认证码与代码中 AUTH 常量不一致",
        "联系科聪技术支持确认控制器认证码",
    ],
    "模型IP不匹配": [
        f"运行 switch-real.bat 切回模拟器再切实车（修复 IP 切换 bug）",
        f"或运行: python switch-env.py --sim && python switch-env.py --real",
        f"然后重启 openTCS Kernel",
    ],
    "端口冲突": [
        f"运行: netstat -ano | findstr {NAV_PORT}",
        f"找到占用端口的 PID，用 taskkill /pid <PID> 终止",
        f"实车模式下务必停止 kc-simulator",
    ],
    "模型缺少点位": [
        "Kernel 模型文件是旧版本，缺少 argentina-app 引用的点位",
        "用最新 argentina.xmap 重新生成: python xmap_to_opentcs.py argentina.xmap",
        "或从 tools/kc-tools/xmap_to_opentcs/model-argentina.xml 复制",
    ],
    "ObjectUnknownException": [
        "运输单引用的点位在模型文件中不存在",
        "更新 model.xml 添加缺失点位，或修改运输单引用已有点位",
    ],
    "Kernel无响应": [
        "检查 Kernel 是否已启动: 运行 startKernel.bat",
        "检查 Java 进程: tasklist | findstr java",
        "查看 Kernel 窗口是否有异常输出",
    ],
    "argentina-app无响应": [
        "检查 argentina-app 是否已启动: 运行 run.bat",
        "检查端口 8081 是否被占用: netstat -ano | findstr 8081",
    ],
    "AGV-001不存在": [
        "Kernel 加载的模型文件中没有 AGV-001 车辆定义",
        "确认 model.xml 中包含 <vehicle name=\"AGV-001\" ...> 定义",
    ],
    "订单积压": [
        "访问 http://localhost:55200/v1/transportOrders 查看积压订单",
        "如果订单引用不存在的点位 → 更新 model.xml",
        "如果车辆不可用 → 检查 Kernel 日志中适配器连接状态",
        "可以手动 Withdraw 无法执行的订单释放队列",
    ],
}


def _print_remediation():
    """根据诊断结果打印修复建议。"""
    hints = set()

    # 分析 REPORT_LINES 中的 FAIL/WARN
    report_text = "\n".join(REPORT_LINES)

    if "ping" in report_text and "[FAIL]" in report_text:
        hints.add("ping不通")
    if "超时" in report_text and "[FAIL]" in report_text:
        hints.add("UDP超时")
    if "认证码" in report_text or "AUTH" in report_text:
        hints.add("认证码错误")
    if "IP" in report_text and "不匹配" in report_text:
        hints.add("模型IP不匹配")
    if "端口" in report_text and "占用" in report_text:
        hints.add("端口冲突")
    if "缺少点位" in report_text:
        hints.add("模型缺少点位")
    if "ObjectUnknownException" in report_text:
        hints.add("ObjectUnknownException")
    if "Kernel" in report_text and "无响应" in report_text:
        hints.add("Kernel无响应")
    if "argentina-app" in report_text and "无响应" in report_text:
        hints.add("argentina-app无响应")
    if "AGV-001" in report_text and ("未找到" in report_text or "不存在" in report_text):
        hints.add("AGV-001不存在")
    if "积压" in report_text:
        hints.add("订单积压")

    if not hints:
        both("  未检测到需要修复的问题。如果仍然连不上，请将报告文件发给远程支持团队。")
        return

    for i, hint in enumerate(sorted(hints), 1):
        both(f"  {i}. [{hint}]")
        for line in REMEDIATIONS.get(hint, []):
            both(f"     - {line}")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    global FAIL_COUNT, WARN_COUNT

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = SCRIPT_DIR / f"doctor-report-{timestamp}.txt"

    # 报告头
    REPORT_LINES.append("阿根廷项目 — 现场诊断报告 (Doctor)")
    REPORT_LINES.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    REPORT_LINES.append(f"计算机名: {socket.gethostname()}")
    REPORT_LINES.append("=" * 60)

    # 控制台头
    print(color("=" * 60, 'B'))
    print(color("  阿根廷项目 — 现场诊断工具 (Doctor)", 'B'))
    print(color(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", 'B'))
    print(color("=" * 60, 'B'))

    # ── 逐层诊断 ──
    results: list[tuple[str, bool]] = []

    section("第一层：网络连通性")
    results.append(("L1 网络", diag_network()))

    section("第二层：模型配置一致性")
    results.append(("L2 模型", diag_model()))

    section("第三层：服务运行状态")
    results.append(("L3 服务", diag_services()))

    section("第四层：日志异常分析")
    results.append(("L4 日志", diag_logs()))

    section("第五层：环境元信息")
    results.append(("L5 环境", diag_environment()))

    # ── 摘要 ──
    section("诊断摘要")
    failed = [name for name, ok_result in results if not ok_result]
    if FAIL_COUNT == 0 and WARN_COUNT == 0:
        both(f"  {color('[OK]', 'G')}    全部检查通过，未发现问题！")
    else:
        parts = []
        if FAIL_COUNT > 0:
            parts.append(f"{color('[FAIL]', 'R')} {FAIL_COUNT} 项")
        if WARN_COUNT > 0:
            parts.append(f"{color('[WARN]', 'Y')} {WARN_COUNT} 项")
        both(f"  {'  '.join(parts)}")
        if failed:
            both(f"  问题层: {', '.join(failed)}")

    # ── 修复建议 ──
    section("修复建议")
    _print_remediation()

    # ── 写入报告 ──
    REPORT_LINES.append("")
    REPORT_LINES.append("=" * 60)
    REPORT_LINES.append("报告结束")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(REPORT_LINES))

    both("")
    both(f"{color('报告已保存:', 'C')} {report_path}")
    both(f"{color('请将此文件发给远程支持团队进行分析。', 'C')}")

    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
