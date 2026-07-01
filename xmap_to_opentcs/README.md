# xmap_to_opentcs

科聪 xmap 导航地图 → openTCS Plant Model XML 转换工具。

**默认输出 Kernel 可直接使用的完整 model.xml**（含 vehicle、locationType、location），无需手动补充。

## 快速开始

```bash
python tools/kc-tools/xmap_to_opentcs/xmap_to_opentcs.py <your_map.xmap>
```

输出文件默认为输入同目录下的 `model.xml`：

```bash
python tools/kc-tools/xmap_to_opentcs/xmap_to_opentcs.py e:/maps/warehouse.xmap
# → e:/maps/model.xml  （完整 Kernel-ready 模型）
```

指定输出路径：

```bash
python tools/kc-tools/xmap_to_opentcs/xmap_to_opentcs.py warehouse.xmap -o model.xml
```

仅生成导航拓扑（points + paths，不含 vehicle/location）：

```bash
python tools/kc-tools/xmap_to_opentcs/xmap_to_opentcs.py warehouse.xmap --no-vehicle
```

## CLI 选项

### 车辆配置

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--vehicle-name` | `AGV-001` | 车辆名称 |
| `--nav-host` | `127.0.0.1` | 激光导航控制器 IP |
| `--nav-port` | `17804` | 导航 UDP 端口 |
| `--qr-host` | `127.0.0.1` | QR/磁导航控制器 IP |
| `--qr-port` | `17800` | QR/变量 UDP 端口 |
| `--auth-code` | `KC-SIMULATOR-01` | 协议认证码 |
| `--auto-init` | (off) | 启用自动初始化（`--real` 时默认开启） |
| `--real` | — | 实车控制器模式：`192.168.100.178/200` + 空认证码 + 自动初始化 |

### 位置生成

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--location-count N` | `1` | 生成 N 个 location，从第一个点开始 |
| `--all-points-as-locations` | — | 为每个点生成一个 location |

### 电量配置（可选）

| 选项 | 可选值 | 说明 |
|------|--------|------|
| `--energy-source` | `PROTOCOL`, `READ_VAR`, `READ_MULTI_VAR` | 电量读取方式 |
| `--energy-var-name` | string | READ_VAR / READ_MULTI_VAR 模式下的变量名 |
| `--energy-var-offset` | int | READ_MULTI_VAR 模式下的字节偏移 |
| `--energy-var-port` | `NAV`, `QR` | 变量读取使用的 UDP 端口 |
| `--energy-config-path` | path | 电量配置 JSON 文件路径 |

### 其他

| 选项 | 说明 |
|------|------|
| `-o`, `--output` | 输出路径（默认：输入同目录下的 `model.xml`） |
| `--no-vehicle` | 仅生成导航拓扑，不含 vehicle/location（用于手动编辑） |

## 用法示例

### 模拟器调试（默认）

```bash
# 默认就是模拟器模式，直接转换即可
python tools/kc-tools/xmap_to_opentcs/xmap_to_opentcs.py argentina.xmap
```

生成的 model.xml 带 `kecong:navHost=127.0.0.1`、`kecong:authCode=KC-SIMULATOR-01`，配合 `kc-simulator` 使用。

### 实车部署

```bash
# --real 一键切换到实车控制器默认配置
python tools/kc-tools/xmap_to_opentcs/xmap_to_opentcs.py argentina.xmap --real
```

等价于手动指定：
```bash
python tools/kc-tools/xmap_to_opentcs/xmap_to_opentcs.py argentina.xmap \
    --nav-host 192.168.100.178 --qr-host 192.168.100.200 \
    --auth-code "" --auto-init
```

实车控制器 IP 和认证码最终请联系科聪技术支持确认。

### 为所有点生成装卸货位置

```bash
python tools/kc-tools/xmap_to_opentcs/xmap_to_opentcs.py warehouse.xmap --all-points-as-locations
```

## 依赖

- Python ≥ 3.8，无第三方依赖（只用了标准库 `xml.etree.ElementTree`、`argparse`、`math`）

## 输入格式

科聪 xmap XML 文件，典型结构见 [test.xmap](test.xmap)：

```xml
<MAP>
  <header name="warehouse" ... />

  <!-- 路径点 -->
  <advanced_point id="1" class_name="LandMark" ...>
    <pos x="0.0" y="0.0"/>
  </advanced_point>

  <!-- 有向路径 -->
  <advanced_curve secondary_id="1-1" Direction="forward"
                  is_navi_fix_angle="1" nav_fix_angle="1.5708"
                  is_forbidden="0" ...>
    <start_pos id="1"/>
    <end_pos id="2"/>
  </advanced_curve>
</MAP>
```

⚠️ **注意**：只转换导航地图（`*.xmap`），不要转换定位点云地图（`*.loc.xmap`）。

## 输出格式

openTCS 7.0.0 Plant Model XML，可直接用 **Model Editor** 打开，也可直接上传至 Kernel。

```xml
<?xml version='1.0' encoding='UTF-8'?>
<model version="7.0.0" name="KC_warehouse">
  <point name="KC-1" positionX="0" positionY="0" positionZ="0"
         vehicleOrientationAngle="NaN" type="HALT_POSITION">
    <outgoingPath name="KC-1 --- KC-2"/>
    <property name="kc:markerId" value="1"/>
    <property name="kc:className" value="LandMark"/>
  </point>

  <path name="KC-1 --- KC-2" sourcePoint="KC-1" destinationPoint="KC-2"
        length="5000" maxVelocity="1000" maxReverseVelocity="0" locked="false">
    <property name="kc:secondaryId" value="1-1"/>
    <property name="kc:direction" value="forward"/>
  </path>

  <vehicle name="AGV-001" energyLevelCritical="0" ...>
    <property name="kecong:navHost" value="127.0.0.1"/>
    <property name="kecong:navPort" value="17804"/>
    ...
  </vehicle>

  <locationType name="LType-0001">
    <allowedOperation name="LOAD"/>
    <allowedOperation name="UNLOAD"/>
    <allowedOperation name="NOP"/>
    <allowedOperation name="FORK_FWD"/>
    <allowedOperation name="FORK_REV"/>
  </locationType>

  <location name="Loc-KC-1" positionX="0" positionY="0" ... type="LType-0001">
    <link point="KC-1"/>
  </location>

  <visualLayout name="VLayout" scaleX="50.0" scaleY="50.0">
    <property name="tcs:modelFileLastModified" value="2026-07-01T..."/>
  </visualLayout>
</model>
```

## 转换规则

| 科聪 xmap | openTCS Plant Model | 说明 |
|-----------|---------------------|------|
| `advanced_point/@id` | `point/@name` = `KC-{id}` | 点名加 `KC-` 前缀 |
| `advanced_point/@id` | `property kc:markerId` | 保留原 ID，供 CommAdapter 下发导航 |
| `pos/@x`, `pos/@y` | `point/@positionX/Y` | **× 1000**（米 → 毫米） |
| `advanced_curve` 每条 | 一条 `path` | 正反向各一条，不合并 |
| 起止点 id | `path/@sourcePoint`, `@destinationPoint` | 对应 `KC-{id}` |
| 欧氏距离 | `path/@length` | 毫米，整数 |
| `is_navi_fix_angle=1` | `point/@vehicleOrientationAngle` | `nav_fix_angle` 弧度 → 度 |
| `is_forbidden=1` | 不生成 path | 跳过禁行边 |
| `Direction` | `property kc:direction` | `forward` / `backward` |
| `secondary_id` | `property kc:secondaryId` | 路径段编号 |
| `class_name` | `property kc:className` | 点分类，默认 `LandMark` |

### 关键 property 说明

这些 `kc:*` property 供 **KecongCommAdapter** 运行时读取，`xmap_to_opentcs.py` 负责写入：

| property | 写入位置 | 谁在消费 | 用途 |
|----------|---------|---------|------|
| `kc:markerId` | point | `KecongCommAdapter.buildNavControlData()` | UDP 0x16 导航命令的目标点 ID（科聪原始点号） |
| `kc:className` | point | （保留） | 科聪点分类标记 |
| `kc:secondaryId` | path | （保留，后续用于 0xAE 路径拼接导航） | 路径段编号 |
| `kc:direction` | path | （保留） | 行车方向 |
| `kc:navFixAngleDeg` | path | （保留） | 到达姿态角度（度） |

## 在 openTCS 中使用

1. 直接转换：`python xmap_to_opentcs.py warehouse.xmap`
2. 打开 **Model Editor** → File → Load Model → 选择 `model.xml` 检查拓扑
3. 如需要，手动补充：
   - `locationType` 中的额外操作（如 `RECHARGE`）
   - 充电站 / 特殊工位的 `location`
4. Upload model to kernel
5. CommAdapter 收到 `MovementCommand` 时会读取 `kc:markerId` 下发 UDP 0x16 导航

## 验证

```bash
python -m pytest tools/kc-tools/xmap_to_opentcs/test_xmap_converter.py -v
```

## 目录结构

```
xmap_to_opentcs/
├── xmap_to_opentcs.py       ← 转换工具本体
├── test_xmap_converter.py   ← 自动化测试（67 cases）
├── test.xmap                ← 测试用的科聪样例地图（3点4边）
├── test.plant.xml           ← 测试期望输出
├── test.xmap转换示例.md      ← 详细的字段对照和转换文档
└── README.md                ← 本文件
```
