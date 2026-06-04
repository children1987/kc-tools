# KC Tools

科聪控制器辅助工具集。

## sync-model.py — 模型同步工具

从科聪控制器获取当前坐标，自动更新 openTCS 模型文件，快速具备调试条件。

### 用法

```bash
# 全自动采集（推荐）
# 读取当前位置为点1 → 0x16 导航到点2 → 等待到达 → 采集点2 → 更新模型
python sync-model.py --auto

# 两步手动采集
python sync-model.py --step1          # 车在点1时运行 → 暂存坐标
python sync-model.py --step2          # 车在点2时运行 → 自动更新模型

# 手动指定坐标
python sync-model.py --pt1 1000,2000 --pt2 3000,5000

# 一键切换模式
python sync-model.py --sim            # 切换为模拟器模式 (127.0.0.1)
python sync-model.py --real           # 切换为实车模式 (192.168.100.178/200)

# 仅查看状态（不修改模型）
python sync-model.py --dry-run

# 指定控制器 IP
python sync-model.py --auto --ip 192.168.1.100
```

### 依赖

```bash
pip install -r requirements.txt
```

无外部依赖——仅使用 Python 标准库。

### 工作流程

```
全自动 (--auto):
┌──────────────────────────────────────────────┐
│ 1. 0x17 查询当前位置 → 设点1               │
│ 2. 0x16 导航到点2 (控制器地图中的 "2")      │
│ 3. 等待 0x17 返回 TS=4(DONE)                │
│ 4. 0x17 查询新位置 → 设点2                  │
│ 5. 更新 zhongwu.xml → 同步到 Kernel data/    │
└──────────────────────────────────────────────┘

两步采集 (--step1 / --step2):
  在点1运行 --step1 → 手动移动车到点2 → 运行 --step2

一步采集 (默认):
  运行 → 读取当前位置为点1 → 手动输入点2坐标 → 更新模型
```

### 输出文件

| 文件 | 说明 |
|------|------|
| `opentcs-modeleditor/data/zhongwu.xml` | Plant Model |
| `opentcs-kernel/data/model.xml` | Kernel 加载的模型 |

修改后需重启 Kernel 生效。

---

## kc-inspect.py — 控制器直查工具

无需 Kernel，直接通过 UDP 查询控制器运行状态、变量信息。

```bash
python kc-inspect.py                    # 查询运行状态
python kc-inspect.py --full             # 完整状态 + 导航 + 变量检查
python kc-inspect.py --vars             # 仅检查关键变量
python kc-inspect.py --watch            # 持续监控 (1秒刷新)
python kc-inspect.py --ip 192.168.1.100 # 指定 IP
```

输出示例：
```
[0x17 运行状态]
  位置:    (1.458, 4.935) m = (1458, 4935) mm
  模式:    AUTO
  定位:    DONE  置信度: 100%
  任务:    NONE
  电量:    90%
  地图:    kc-map (数量:1 版本:1)

[变量检查]
  Screen.ForkUp     (举升控制): 0 (未触发)
  Button.TopLimit   (上升限位): 1 (已触发)
```

---

## kc-test.py — 端到端测试工具

一键下发运输单并监控执行结果，无需手动敲 curl。

```bash
python kc-test.py                           # 默认: 前进→举升→放下→返回
python kc-test.py --nop                     # 仅移动: 点1→点2→点1
python kc-test.py --fork                    # 仅举升: LOAD+UNLOAD
python kc-test.py --single "Loc-2" "NOP"    # 单步自定义
python kc-test.py --wait 180                # 超时 180 秒
```

---

## kc-log.py — 日志高亮工具

高亮 Kernel 日志中的 Kecong 适配器关键事件。

```bash
python kc-log.py                        # 高亮最后 50 行
python kc-log.py --follow               # 实时跟踪
python kc-log.py --filter LIFT          # 仅 LIFT 事件
python kc-log.py --filter "NAV|LIFT"    # NAV 或 LIFT
python kc-log.py --errors               # 仅错误/警告
python kc-log.py --today                # 仅今天
```

标签说明：
- `[L]` LIFT 举升相关  `[N]` NAV 导航  `[+]` 完成  `[X]` 失败
- `[!]` 机器人错误  `[W]` 警告  `[E]` 严重错误  `[*]` 调度状态

---

## kc-var-sim.py — 变量模拟器 (极简版)

轻量 UDP 服务器，仅模拟 WRITE_VAR/READ_VAR，用于本地验证举升变量读写逻辑。

```bash
python kc-var-sim.py                    # 启动 (端口 17804)
python kc-var-sim.py --port 17805      # 指定端口
```

启动后：
- 接收 `WRITE_VAR Screen.ForkUp=1` → 0.5s 后 `Button.TopLimit=1`
- 接收 `WRITE_VAR Screen.ForkDown=1` → 0.5s 后 `Button.DownLimit=1`
- `READ_VAR` 返回当前变量值

配合验证：`python kc-inspect.py --ip 127.0.0.1 --full`

> 注意：需先关闭 17804 端口的 kc-simulator，避免端口冲突。

---

## kc-e2e-test.py — 适配器集成测试

用 kc-var-sim 模拟控制器，完整验证 Kernel + Adapter 端到端流程。

```bash
python kc-e2e-test.py                     # 全部测试
python kc-e2e-test.py --test nop          # 仅导航
python kc-e2e-test.py --test fork         # 仅举升
python kc-e2e-test.py --test full         # 完整流程
python kc-e2e-test.py --timeout 180       # 超时 180s
```

前提：kc-var-sim + Kernel 已启动，模型为模拟器模式。

---

## kc-diag.py — Kernel 状态诊断

扫描日志和 REST API，检测扫单线程、适配器连接、订单积压等异常。

```bash
python kc-diag.py                      # 全诊断
python kc-diag.py --watch              # 持续监控 (10秒刷新)
python kc-diag.py --sweep-only         # 仅扫单诊断
```
