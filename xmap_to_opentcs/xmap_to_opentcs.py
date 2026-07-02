#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kecong xmap to openTCS Plant Model XML v7.0.0 converter.

Generates a Kernel-ready model.xml with vehicle, locationType, and locations
by default (simulator mode).  Use --real for real-controller defaults,
or --no-vehicle for navigation topology only.
"""

from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
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


@dataclass
class VehicleConfig:
    """Kecong vehicle definition for the generated openTCS model."""
    name: str = "AGV-001"
    nav_host: str = "127.0.0.1"
    nav_port: int = 17804
    qr_host: str = "127.0.0.1"
    qr_port: int = 17800
    auth_code: str = "KC-SIMULATOR-01"
    poll_interval: int = 100
    auto_init: bool = False
    energy_source: str | None = None
    energy_var_name: str | None = None
    energy_var_offset: int = 0
    energy_var_port: str | None = None
    energy_config_path: str | None = None


@dataclass
class LocationConfig:
    """Controls location generation from points."""
    count: int = 1       # -1 means "all points"
    start_index: int = 0


# ── coordinate helpers ────────────────────────────────────────────────────

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


def _current_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── simulator map_config.json builder ──────────────────────────────────────

def build_map_config_json(
    points: list[KcPoint],
    paths: list[KcPath],
) -> dict:
    """Build the simulator map_config.json structure from parsed xmap data.

    Returns a dict with "points" and "paths" keys matching the format
    expected by :class:`~agv_engine.VirtualAgv` / :class:`~udp_server.UdpServer`.

    Coordinates are in **meters** (not mm).  Paths preserve the original
    direction from the xmap — no automatic bidirectioning.
    """
    point_by_id = {p.kc_id: p for p in points}

    # ── Points (sorted by ID so KC-1 is first = simulator start position) ──
    map_points: list[dict] = []
    for pt in sorted(points, key=lambda p: int(p.kc_id)):
        map_points.append({
            "id": int(pt.kc_id),
            "x": pt.x_m,
            "y": pt.y_m,
            "name": _point_name(pt.kc_id),
        })

    # ── Paths (preserve original direction from xmap) ───────────────────
    map_paths: list[dict] = []
    path_id = 1

    for p in paths:
        if p.start_id not in point_by_id or p.end_id not in point_by_id:
            continue
        map_paths.append({
            "id": path_id,
            "from": int(p.start_id),
            "to": int(p.end_id),
        })
        path_id += 1

    return {"points": map_points, "paths": map_paths}


# ── xmap parser ──────────────────────────────────────────────────────────

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
                direction=curve.attrib.get("Direction") or curve.attrib.get("direction", "forward"),
                is_forbidden=False,
                nav_fix_angle_rad=nav_fix,
            )
        )

    return map_name, list(points.values()), paths


# ── openTCS XML builder ───────────────────────────────────────────────────

def build_opentcs_xml(
    model_name: str,
    points: list[KcPoint],
    paths: list[KcPath],
    *,
    vehicle: VehicleConfig | None = None,
    locations: LocationConfig | None = None,
    point_tags: dict[str, list[tuple[str, str]]] | None = None,
) -> ET.ElementTree:
    """Build an openTCS 7.0.0 Plant Model ElementTree.

    When *vehicle* is None (backward-compatible), only points, paths, and
    visualLayout are generated — the model still needs manual editing before
    it can be used by the Kernel.

    When *vehicle* is provided, a full Kernel-ready model is produced:
    vehicle, locationType, locations, and tcs:modelFileLastModified are
    included.

    *point_tags* is an optional dict mapping point kc_id (str) to a list of
    (name, value) property pairs to inject into that point element.
    """
    point_by_id = {p.kc_id: p for p in points}
    outgoing: dict[str, list[str]] = {p.kc_id: [] for p in points}
    arrival_angle_deg: dict[str, float] = {}

    for p in paths:
        if p.start_id not in point_by_id or p.end_id not in point_by_id:
            continue
        outgoing[p.start_id].append(_path_name(p.start_id, p.end_id))
        if p.nav_fix_angle_rad is not None:
            arrival_angle_deg[p.end_id] = math.degrees(p.nav_fix_angle_rad)

    model = ET.Element(
        "model",
        {"version": "7.0.0", "name": model_name},
    )

    # ── 1. Points ───────────────────────────────────────────────────

    point_elements: list[ET.Element] = []
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
        point_el = ET.Element("point", attrs)
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
        # Inject optional point tags (e.g. kc:isLowDoor, kc:isCharger)
        for tag_name, tag_value in (point_tags or {}).get(pt.kc_id, []):
            ET.SubElement(
                point_el,
                "property",
                {"name": tag_name, "value": tag_value},
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
        point_elements.append(point_el)

    for el in point_elements:
        model.append(el)

    # ── 2. Paths ────────────────────────────────────────────────────

    path_elements: list[ET.Element] = []
    for p in paths:
        if p.start_id not in point_by_id or p.end_id not in point_by_id:
            continue
        src = point_by_id[p.start_id]
        dst = point_by_id[p.end_id]
        path_el = ET.Element(
            "path",
            {
                "name": _path_name(p.start_id, p.end_id),
                "sourcePoint": _point_name(p.start_id),
                "destinationPoint": _point_name(p.end_id),
                "length": str(_dist_mm(src, dst)),
                "maxVelocity": "1000",
                "maxReverseVelocity": "0",
                "locked": "false",
            },
        )
        ET.SubElement(
            path_el,
            "property",
            {"name": "kc:secondaryId", "value": p.secondary_id},
        )
        ET.SubElement(
            path_el,
            "property",
            {"name": "kc:direction", "value": p.direction},
        )
        if p.nav_fix_angle_rad is not None:
            ET.SubElement(
                path_el,
                "property",
                {
                    "name": "kc:navFixAngleDeg",
                    "value": f"{math.degrees(p.nav_fix_angle_rad):.1f}",
                },
            )
        ET.SubElement(
            path_el,
            "pathLayout",
            {"connectionType": "DIRECT", "layerId": "0"},
        )
        path_elements.append(path_el)

    for el in path_elements:
        model.append(el)

    # ── 3-5. Vehicle + locationType + locations (new) ───────────────

    if vehicle is not None:
        _build_vehicle_element(model, vehicle)
        loc_type_name = _build_location_type(model)
        _build_locations(model, points, locations or LocationConfig(), loc_type_name)

    # ── 6. VisualLayout ─────────────────────────────────────────────

    vl = ET.SubElement(model, "visualLayout", {"name": "VLayout", "scaleX": "50.0", "scaleY": "50.0"})
    ET.SubElement(vl, "layer", {"id": "0", "ordinal": "0", "visible": "true", "name": "Default layer", "groupId": "0"})
    ET.SubElement(vl, "layerGroup", {"id": "0", "name": "Default layer group", "visible": "true"})

    # ── 7. Model timestamp ──────────────────────────────────────────

    if vehicle is not None:
        ET.SubElement(
            model,
            "property",
            {"name": "tcs:modelFileLastModified", "value": _current_utc()},
        )

    return ET.ElementTree(model)


# ── sub-element builders ──────────────────────────────────────────────────

def _build_vehicle_element(model: ET.Element, cfg: VehicleConfig) -> ET.Element:
    vehicle_el = ET.SubElement(
        model,
        "vehicle",
        {
            "name": cfg.name,
            "energyLevelCritical": "0",
            "energyLevelGood": "80",
            "energyLevelFullyRecharged": "100",
            "energyLevelSufficientlyRecharged": "90",
            "maxVelocity": "1000",
            "maxReverseVelocity": "500",
            "envelopeKey": "",
        },
    )
    ET.SubElement(
        vehicle_el,
        "boundingBox",
        {
            "length": "1000",
            "width": "600",
            "height": "300",
            "referenceOffsetX": "0",
            "referenceOffsetY": "0",
        },
    )
    _add_kecong_properties(vehicle_el, cfg)
    ET.SubElement(vehicle_el, "vehicleLayout", {"color": "#FF0000"})
    return vehicle_el


def _add_kecong_properties(vehicle_el: ET.Element, cfg: VehicleConfig) -> None:
    props: list[tuple[str, str]] = [
        ("kecong:navHost", cfg.nav_host),
        ("kecong:navPort", str(cfg.nav_port)),
        ("kecong:pollInterval", str(cfg.poll_interval)),
        ("kecong:qrHost", cfg.qr_host),
        ("kecong:qrPort", str(cfg.qr_port)),
        ("kecong:autoInit", str(cfg.auto_init).lower()),
    ]
    # Energy — only emit if explicitly configured
    if cfg.energy_source:
        props.append(("kecong:energySource", cfg.energy_source))
    if cfg.energy_var_name:
        props.append(("kecong:energyVarName", cfg.energy_var_name))
        props.append(("kecong:energyVarOffset", hex(cfg.energy_var_offset)))
        if cfg.energy_var_port:
            props.append(("kecong:energyVarPort", cfg.energy_var_port))
    if cfg.energy_config_path:
        props.append(("kecong:energyConfigPath", cfg.energy_config_path))
    props.append(("kecong:authCode", cfg.auth_code))

    for name, value in props:
        ET.SubElement(vehicle_el, "property", {"name": name, "value": value})


def _build_location_type(model: ET.Element) -> str:
    name = "LType-0001"
    lt_el = ET.SubElement(model, "locationType", {"name": name})
    for op in ("LOAD", "UNLOAD", "NOP", "FORK_FWD", "FORK_REV"):
        ET.SubElement(lt_el, "allowedOperation", {"name": op})
    ET.SubElement(lt_el, "locationTypeLayout", {"locationRepresentation": "NONE"})
    return name


def _build_locations(
    model: ET.Element,
    points: list[KcPoint],
    loc_cfg: LocationConfig,
    loc_type_name: str,
) -> None:
    count = len(points) if loc_cfg.count == -1 else min(loc_cfg.count, len(points))
    for i in range(loc_cfg.start_index, loc_cfg.start_index + count):
        if i >= len(points):
            break
        pt = points[i]
        point_name = _point_name(pt.kc_id)
        loc_name = f"Loc-{point_name}"
        loc_el = ET.SubElement(
            model,
            "location",
            {
                "name": loc_name,
                "positionX": str(_m_to_mm(pt.x_m)),
                "positionY": str(_m_to_mm(pt.y_m)),
                "positionZ": "0",
                "locked": "false",
                "type": loc_type_name,
            },
        )
        ET.SubElement(loc_el, "link", {"point": point_name})
        ET.SubElement(
            loc_el,
            "locationLayout",
            {
                "labelOffsetX": "-10",
                "labelOffsetY": "-20",
                "locationRepresentation": "DEFAULT",
                "layerId": "0",
            },
        )


# ── CLI ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert Kecong xmap navigation map to openTCS plant model XML."
    )
    parser.add_argument("input", type=Path, help="Path to *.xmap navigation map")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output XML path (default: same dir as input, model.xml)",
    )

    # Vehicle configuration
    veh = parser.add_argument_group("vehicle configuration")
    veh.add_argument("--vehicle-name", default="AGV-001",
                     help="Vehicle name (default: AGV-001)")
    veh.add_argument("--nav-host", default="127.0.0.1",
                     help="Navigation controller IP (default: 127.0.0.1)")
    veh.add_argument("--nav-port", type=int, default=17804,
                     help="Navigation UDP port (default: 17804)")
    veh.add_argument("--qr-host", default="127.0.0.1",
                     help="QR controller IP (default: 127.0.0.1)")
    veh.add_argument("--qr-port", type=int, default=17800,
                     help="QR UDP port (default: 17800)")
    veh.add_argument("--auth-code", default="KC-SIMULATOR-01",
                     help="Protocol auth code (default: KC-SIMULATOR-01)")
    veh.add_argument("--auto-init", action="store_true",
                     help="Enable auto-initialization on vehicle enable (on by default with --real)")
    veh.add_argument("--real", action="store_true",
                     help="Use real controller defaults: 192.168.100.178/200, empty auth, auto-init")

    # Location generation
    loc = parser.add_argument_group("location generation")
    loc.add_argument("--location-count", type=int, default=1,
                     help="Number of locations to auto-generate (default: 1 at first point)")
    loc.add_argument("--all-points-as-locations", action="store_true",
                     help="Generate a location for every point")

    # Optional energy configuration
    energy = parser.add_argument_group("energy configuration (optional)")
    energy.add_argument("--energy-source", choices=["PROTOCOL", "READ_VAR", "READ_MULTI_VAR"],
                        help="Battery energy source type")
    energy.add_argument("--energy-var-name", help="Variable name for READ_VAR / READ_MULTI_VAR")
    energy.add_argument("--energy-var-offset", type=int, default=0,
                        help="Byte offset for READ_MULTI_VAR (default: 0)")
    energy.add_argument("--energy-var-port", choices=["NAV", "QR"],
                        help="Which UDP port to use for variable reads")
    energy.add_argument("--energy-config-path", help="Path to energy config JSON file")

    # Backward-compat: skip vehicle generation entirely
    parser.add_argument("--no-vehicle", action="store_true",
                        help="Generate only navigation topology (points + paths), no vehicle/locations")

    # Simulator map config output
    sim = parser.add_argument_group("simulator map config")
    sim.add_argument("--map-config-output", type=Path,
                     help="Path for the simulator map_config.json (default: alongside model.xml)")
    sim.add_argument("--no-map-config", action="store_true",
                     help="Skip generating the simulator map_config.json")

    # Point property tagging
    tag = parser.add_argument_group("point property tagging")
    tag.add_argument("--tag-low-doors", action="store_true",
                     help="Auto-tag KC-50X and KC-408 points with kc:isLowDoor=true")
    tag.add_argument("--tag-charger", type=str, metavar="POINT",
                     help="Tag the given point name with kc:isCharger=true (e.g. --tag-charger KC-1)")

    # Deployment
    deploy = parser.add_argument_group("deployment")
    deploy.add_argument("--deploy", type=Path, metavar="KERNEL_DATA_DIR",
                        help="Copy model.xml and map_config.json to Kernel data dir "
                             "(e.g. --deploy opentcs-7.3.0-bin/opentcs-kernel/data)")

    args = parser.parse_args()

    map_name, points, paths = parse_kc_xmap(args.input)

    # Compute point tags from CLI flags (applies to both --no-vehicle and normal modes)
    point_tags: dict[str, list[tuple[str, str]]] = {}
    if args.tag_low_doors:
        for pt in points:
            pid = int(pt.kc_id)
            if (500 <= pid <= 509) or pid == 408:
                point_tags.setdefault(pt.kc_id, []).append(
                    ("kc:isLowDoor", "true"))
    if args.tag_charger:
        charger_name = args.tag_charger
        if charger_name.startswith("KC-"):
            charger_id = charger_name[3:]
            if charger_id in {p.kc_id for p in points}:
                point_tags.setdefault(charger_id, []).append(
                    ("kc:isCharger", "true"))
            else:
                print(f"Warning: --tag-charger point '{charger_name}' not found in map")
        else:
            print(f"Warning: --tag-charger expects KC- prefix, got '{charger_name}'")

    if args.no_vehicle:
        tree = build_opentcs_xml(f"KC_{map_name}", points, paths,
                                 point_tags=point_tags or None)
    else:
        if args.real:
            args.nav_host = "192.168.100.178"
            args.qr_host = "192.168.100.200"
            args.auth_code = ""
            args.auto_init = True

        vehicle = VehicleConfig(
            name=args.vehicle_name,
            nav_host=args.nav_host,
            nav_port=args.nav_port,
            qr_host=args.qr_host,
            qr_port=args.qr_port,
            auth_code=args.auth_code,
            poll_interval=100,
            auto_init=args.auto_init,
            energy_source=args.energy_source,
            energy_var_name=args.energy_var_name,
            energy_var_offset=args.energy_var_offset,
            energy_var_port=args.energy_var_port,
            energy_config_path=args.energy_config_path,
        )

        loc_count = -1 if args.all_points_as_locations else args.location_count
        locations = LocationConfig(count=loc_count, start_index=0)

        tree = build_opentcs_xml(f"KC_{map_name}", points, paths,
                                 vehicle=vehicle, locations=locations,
                                 point_tags=point_tags or None)

    output = args.output or args.input.parent / "model.xml"
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="    ")
    tree.write(output, encoding="UTF-8", xml_declaration=True)
    print(f"Converted {len(points)} points, {len(paths)} paths -> {output}")

    # ── Simulator map_config.json ───────────────────────────────────────
    if not args.no_map_config:
        map_json = build_map_config_json(points, paths)
        map_config_path = args.map_config_output or output.parent / "map_config.json"
        map_config_path.parent.mkdir(parents=True, exist_ok=True)
        map_config_path.write_text(
            json.dumps(map_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Simulator map: {len(map_json['points'])} points, "
              f"{len(map_json['paths'])} paths -> {map_config_path}")


if __name__ == "__main__":
    main()
