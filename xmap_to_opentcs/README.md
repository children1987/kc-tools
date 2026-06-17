# xmap_to_opentcs

科聪 xmap 导航地图 → openTCS Plant Model XML 转换工具。

## 快速开始

```bash
python tools/kc-tools/xmap_to_opentcs/xmap_to_opentcs.py <your_map.xmap>
```

输出文件与输入同目录，后缀 `.plant.xml`：

```bash
python tools/kc-tools/xmap_to_opentcs/xmap_to_opentcs.py e:/maps/warehouse.xmap
# → e:/maps/warehouse.plant.xml
```

指定输出路径：

```bash
python tools/kc-tools/xmap_to_opentcs/xmap_to_opentcs.py warehouse.xmap -o e:/opentcs/examples/warehouse.xml
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

openTCS 7.0.0 Plant Model XML，可直接用 **Model Editor** 打开。

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

1. 打开 **Model Editor** → File → Load Model → 选择 `.plant.xml`
2. 检查点和路径是否与科聪地图一致
3. 手动补充（转换工具不生成）：
   - `vehicle` 定义
   - `location` / `locationType`（装卸货、充电站等）
   - `locationLink`
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
├── test_xmap_converter.py   ← 自动化测试
├── test.xmap                ← 测试用的科聪样例地图（3点4边）
├── test.xmap转换示例.md      ← 详细的字段对照和转换文档
└── README.md                ← 本文件
```
