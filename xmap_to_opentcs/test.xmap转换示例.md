# test.xmap → openTCS 转换示例

基于 `e:\KC\测试\test.xmap`（3 点、4 条有向边）的完整转换示例。

---

## 1. 一键转换

```powershell
py -3 E:\OpenTCS\tools\xmap_to_opentcs.py "e:\KC\测试\test.xmap" -o E:\OpenTCS\examples\test.plant.xml
```

输出：`E:\OpenTCS\examples\test.plant.xml`（openTCS 7.0.0 Plant Model 格式）

---

## 2. 科聪源地图拓扑

```
        KC-1  (-4.888, -12.828)
          ↑↓  竖直 ~6.40m
        KC-2  (-4.888,  -6.428)
          ?   水平 ~2.73m
        KC-3  (-2.162,  -6.428)
```

| 科聪 curve | secondary_id | 起点→终点 | Direction | 备注 |
|------------|--------------|-----------|-----------|------|
| 1 | 1-1 | 2 → 1 | backward | 竖直段反向 |
| 2 | 1-2 | 1 → 2 | forward | 竖直段正向 |
| 3 | 2-1 | 2 → 3 | forward | 到点姿态 90° |
| 4 | 2-2 | 3 → 2 | forward | 水平段返回 |

坐标单位：**米**（科聪 `pos x/y`）。

---

## 3. 字段映射规则

| 科聪 xmap | openTCS Plant Model | 转换规则 |
|-----------|---------------------|----------|
| `advanced_point/@id` | `point/@name` | `KC-{id}`，如 `KC-1` |
| `advanced_point/@id` | `property kc:markerId` | 保留原 ID，供 CommAdapter 发 UDP 0x16 |
| `pos/@x`, `pos/@y` | `point/@positionX/Y` | **× 1000**（米 → 毫米） |
| `advanced_curve` 每条边 | 一条 `path` | 正反向各一条，不合并 |
| 起止点 id | `path/@sourcePoint`, `@destinationPoint` | 对应 `KC-{id}` |
| 欧氏距离 | `path/@length` | 毫米，整数 |
| `is_navi_fix_angle=1` | `point/@vehicleOrientationAngle` | `nav_fix_angle` 弧度 → 度 |
| `is_forbidden=1` | 不生成 path | 跳过禁行边 |

**CommAdapter 约定**：下发导航时读 `kc:markerId`（即 `1`、`2`、`3`），不要发 openTCS 点名 `KC-1`。

---

## 4. 转换结果对照表

### 4.1 Points

| 科聪 id | openTCS 点名 | positionX (mm) | positionY (mm) | 到点角度 |
|---------|--------------|----------------|----------------|----------|
| 1 | KC-1 | -4888 | -12828 | — |
| 2 | KC-2 | -4888 | -6428 | — |
| 3 | KC-3 | -2162 | -6428 | 90.0°（来自 2→3 边） |

### 4.2 Paths

| openTCS path 名 | source → dest | length (mm) | kc:secondaryId | kc:direction |
|-----------------|---------------|-------------|----------------|--------------|
| KC-2 --- KC-1 | KC-2 → KC-1 | 6400 | 1-1 | backward |
| KC-1 --- KC-2 | KC-1 → KC-2 | 6400 | 1-2 | forward |
| KC-2 --- KC-3 | KC-2 → KC-3 | 2726 | 2-1 | forward |
| KC-3 --- KC-2 | KC-3 → KC-2 | 2726 | 2-2 | forward |

---

## 5. 生成的 XML 片段（节选）

```xml
<?xml version='1.0' encoding='UTF-8'?>
<model version="7.0.0" name="KC_newNav">
    <point name="KC-1" positionX="-4888" positionY="-12828" positionZ="0"
           vehicleOrientationAngle="NaN" type="HALT_POSITION">
        <outgoingPath name="KC-1 --- KC-2"/>
        <property name="kc:markerId" value="1"/>
        <property name="kc:className" value="LandMark"/>
    </point>
    <point name="KC-3" positionX="-2162" positionY="-6428" positionZ="0"
           vehicleOrientationAngle="90.0" type="HALT_POSITION">
        <outgoingPath name="KC-3 --- KC-2"/>
        <property name="kc:markerId" value="3"/>
    </point>
    <path name="KC-2 --- KC-3" sourcePoint="KC-2" destinationPoint="KC-3"
          length="2726" maxVelocity="1000" maxReverseVelocity="0" locked="false">
        <property name="kc:secondaryId" value="2-1"/>
        <property name="kc:direction" value="forward"/>
        <property name="kc:navFixAngleDeg" value="90.0"/>
    </path>
</model>
```

完整文件见：`E:\OpenTCS\examples\test.plant.xml`

---

## 6. 在 openTCS 中使用

1. 打开 **Model Editor** → File → Load Model → 选择 `test.plant.xml`
2. 检查 3 点 4 边是否与科聪地图一致
3. 手动补充（本示例未包含）：
   - `vehicle` 定义
   - `location` + `locationLink`（若需装卸/充电）
   - `locationType` / 操作类型
4. Upload model to kernel
5. CommAdapter 收到 `MovementCommand` 时：
   - 目标 openTCS Point → 读 `kc:markerId`
   - UDP 0x16 下发 ASCII 点号 `"1"` / `"2"` / `"3"`

---

## 7. 脚本核心逻辑（Python 伪代码）

```python
for ap in xmap.findall("advanced_point"):
    kc_id = ap.attrib["id"]
    x_mm = round(float(ap.find("pos").attrib["x"]) * 1000)
    y_mm = round(float(ap.find("pos").attrib["y"]) * 1000)
    create_point(name=f"KC-{kc_id}", x=x_mm, y=y_mm, property={"kc:markerId": kc_id})

for curve in xmap.findall("advanced_curve"):
    if curve.attrib.get("is_forbidden") == "1":
        continue
    src = curve.find("start_pos").attrib["id"]
    dst = curve.find("end_pos").attrib["id"]
    create_path(f"KC-{src} --- KC-{dst}", src, dst, length_mm=dist(src, dst))
```

完整实现：`E:\OpenTCS\tools\xmap_to_opentcs.py`

---

## 8. 注意事项

- **仅转换导航地图 `test.xmap`**，不要转换 `test.loc.xmap`（定位点云）
- 负坐标合法；Model Editor 中若显示偏屏幕外，可调整 layout 或平移视图
- 科聪 `need_request=true`（交通管理）与 openTCS Scheduler 可能重复，联调时需明确由哪一层管锁
- 大地图建议在脚本中增加：`ChargePoint` → `Location`、`HomePoint` → `PARK_POSITION` 等规则

---

*生成日期：2026-06-02*
