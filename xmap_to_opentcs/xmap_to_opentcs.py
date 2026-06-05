#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KeCong xmap to openTCS Plant Model XML v7.0.0 converter."""

from __future__ import annotations

import argparse
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


MM_PER_M = 1000


@dataclass
class KcPoint:
    kc_id: str
    x_m: float
    y_m: float
    class_name: str = "LandMark"


@dataclass
class KcPath:
    secondary_id: str
    start_id: str
    end_id: str
    direction: str
    is_forbidden: bool
    nav_fix_angle_rad: float | None


def _m_to_mm(value: float) -> int:
    return int(round(value * MM_PER_M))


def _dist_mm(p1: KcPoint, p2: KcPoint) -> int:
    dx = (p2.x_m - p1.x_m) * MM_PER_M
    dy = (p2.y_m - p1.y_m) * MM_PER_M
    return int(round(math.hypot(dx, dy)))


def _point_name(kc_id: str) -> str:
    return f"KC-{kc_id}"


def _path_name(src: str, dst: str) -> str:
    return f"{_point_name(src)} --- {_point_name(dst)}"


def parse_kc_xmap(xmap_path: Path) -> tuple[str, list[KcPoint], list[KcPath]]:
    root = ET.parse(xmap_path).getroot()
    header = root.find("header")
    map_name = (header.attrib.get("name") if header is not None else "") or xmap_path.stem

    points: dict[str, KcPoint] = {}
    for node in root.findall("advanced_point"):
        kc_id = node.attrib.get("id", "")
        pos = node.find("pos")
        if pos is None or not kc_id:
            continue
        points[kc_id] = KcPoint(
            kc_id=kc_id,
            x_m=float(pos.attrib["x"]),
            y_m=float(pos.attrib["y"]),
            class_name=node.attrib.get("class_name", "LandMark"),
        )

    paths: list[KcPath] = []
    for curve in root.findall("advanced_curve"):
        if curve.attrib.get("is_forbidden") == "1":
            continue
        start = curve.find("start_pos")
        end = curve.find("end_pos")
        if start is None or end is None:
            continue
        nav_fix = None
        if curve.attrib.get("is_navi_fix_angle") == "1":
            nav_fix = float(curve.attrib.get("nav_fix_angle", "0"))
        paths.append(
            KcPath(
                secondary_id=curve.attrib.get("secondary_id", ""),
                start_id=start.attrib["id"],
                end_id=end.attrib["id"],
                direction=curve.attrib.get("Direction", "forward"),
                is_forbidden=False,
                nav_fix_angle_rad=nav_fix,
            )
        )

    return map_name, list(points.values()), paths


def build_opentcs_xml(
    model_name: str,
    points: list[KcPoint],
    paths: list[KcPath],
) -> ET.ElementTree:
    point_by_id = {p.kc_id: p for p in points}
    outgoing: dict[str, list[str]] = {p.kc_id: [] for p in points}
    arrival_angle_deg: dict[str, float] = {}

    for path in paths:
        if path.start_id not in point_by_id or path.end_id not in point_by_id:
            continue
        outgoing[path.start_id].append(_path_name(path.start_id, path.end_id))
        if path.nav_fix_angle_rad is not None:
            arrival_angle_deg[path.end_id] = math.degrees(path.nav_fix_angle_rad)

    model = ET.Element(
        "model",
        {
            "version": "7.0.0",
            "name": model_name,
        },
    )

    for pt in points:
        angle = arrival_angle_deg.get(pt.kc_id)
        angle_str = f"{angle:.1f}" if angle is not None else "NaN"
        attrs = {
            "name": _point_name(pt.kc_id),
            "positionX": str(_m_to_mm(pt.x_m)),
            "positionY": str(_m_to_mm(pt.y_m)),
            "positionZ": "0",
            "vehicleOrientationAngle": angle_str,
            "type": "HALT_POSITION",
        }
        point_el = ET.SubElement(model, "point", attrs)
        ET.SubElement(
            point_el,
            "maxVehicleBoundingBox",
            {
                "length": "1000",
                "width": "1000",
                "height": "1000",
                "referenceOffsetX": "0",
                "referenceOffsetY": "0",
            },
        )
        for path_name in outgoing.get(pt.kc_id, []):
            ET.SubElement(point_el, "outgoingPath", {"name": path_name})
        ET.SubElement(
            point_el,
            "property",
            {"name": "kc:markerId", "value": pt.kc_id},
        )
        ET.SubElement(
            point_el,
            "property",
            {"name": "kc:className", "value": pt.class_name},
        )
        ET.SubElement(
            point_el,
            "pointLayout",
            {
                "labelOffsetX": "-10",
                "labelOffsetY": "-20",
                "layerId": "0",
            },
        )

    for path in paths:
        if path.start_id not in point_by_id or path.end_id not in point_by_id:
            continue
        src = point_by_id[path.start_id]
        dst = point_by_id[path.end_id]
        path_el = ET.SubElement(
            model,
            "path",
            {
                "name": _path_name(path.start_id, path.end_id),
                "sourcePoint": _point_name(path.start_id),
                "destinationPoint": _point_name(path.end_id),
                "length": str(_dist_mm(src, dst)),
                "maxVelocity": "1000",
                "maxReverseVelocity": "0",
                "locked": "false",
            },
        )
        ET.SubElement(
            path_el,
            "property",
            {"name": "kc:secondaryId", "value": path.secondary_id},
        )
        ET.SubElement(
            path_el,
            "property",
            {"name": "kc:direction", "value": path.direction},
        )
        if path.nav_fix_angle_rad is not None:
            ET.SubElement(
                path_el,
                "property",
                {
                    "name": "kc:navFixAngleDeg",
                    "value": f"{math.degrees(path.nav_fix_angle_rad):.1f}",
                },
            )
        ET.SubElement(
            path_el,
            "pathLayout",
            {"connectionType": "DIRECT", "layerId": "0"},
        )

    # Minimal visualLayout — required by openTCS ModelEditor to avoid
    # "Invalid name" deserialization warning (JAXB creates a default
    # VisualLayoutTO with empty name when the element is absent).
    vl = ET.SubElement(model, "visualLayout", {"name": "VLayout", "scaleX": "50.0", "scaleY": "50.0"})
    ET.SubElement(vl, "layer", {"id": "0", "ordinal": "0", "visible": "true", "name": "Default layer", "groupId": "0"})
    ET.SubElement(vl, "layerGroup", {"id": "0", "name": "Default layer group", "visible": "true"})

    return ET.ElementTree(model)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert KeCong xmap to openTCS plant model XML")
    parser.add_argument("input", type=Path, help="Path to *.xmap navigation map")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output XML path (default: same dir, .plant.xml suffix)",
    )
    args = parser.parse_args()

    map_name, points, paths = parse_kc_xmap(args.input)
    tree = build_opentcs_xml(f"KC_{map_name}", points, paths)

    output = args.output or args.input.with_suffix(".plant.xml")
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="    ")
    tree.write(output, encoding="UTF-8", xml_declaration=True)
    print(f"Converted {len(points)} points, {len(paths)} paths -> {output}")


if __name__ == "__main__":
    main()
