#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for xmap_to_opentcs converter — validates every field end-to-end."""

from __future__ import annotations

import io
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

# SUT
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xmap_to_opentcs as sut  # noqa: E402

TEST_XMAP = Path(__file__).resolve().parent / "test.xmap"


# ── parse_kc_xmap ──────────────────────────────────────────────────────

class TestParseKcXmap:
    def test_map_name(self):
        name, _, _ = sut.parse_kc_xmap(TEST_XMAP)
        assert name == "newNav"

    def test_point_count(self):
        _, points, _ = sut.parse_kc_xmap(TEST_XMAP)
        assert len(points) == 3

    def test_path_count(self):
        _, _, paths = sut.parse_kc_xmap(TEST_XMAP)
        assert len(paths) == 4

    def test_point_ids(self):
        _, points, _ = sut.parse_kc_xmap(TEST_XMAP)
        ids = {p.kc_id for p in points}
        assert ids == {"1", "2", "3"}

    def test_point_coordinates(self):
        _, points, _ = sut.parse_kc_xmap(TEST_XMAP)
        by_id = {p.kc_id: p for p in points}
        assert by_id["1"].x_m == pytest.approx(-4.888219451292729)
        assert by_id["1"].y_m == pytest.approx(-12.827974107086018)
        assert by_id["2"].x_m == pytest.approx(-4.888219451292729)
        assert by_id["2"].y_m == pytest.approx(-6.428413474428517)
        assert by_id["3"].x_m == pytest.approx(-2.1623542985850306)
        assert by_id["3"].y_m == pytest.approx(-6.428413474428517)

    def test_point_class_name_default(self):
        _, points, _ = sut.parse_kc_xmap(TEST_XMAP)
        for p in points:
            assert p.class_name == "LandMark"

    def test_path_secondary_ids(self):
        _, _, paths = sut.parse_kc_xmap(TEST_XMAP)
        sids = {p.secondary_id for p in paths}
        assert sids == {"1-1", "1-2", "2-1", "2-2"}

    def test_path_directions(self):
        _, _, paths = sut.parse_kc_xmap(TEST_XMAP)
        dirs = {(p.start_id, p.end_id, p.direction) for p in paths}
        assert ("2", "1", "backward") in dirs
        assert ("1", "2", "forward") in dirs
        assert ("2", "3", "forward") in dirs
        assert ("3", "2", "forward") in dirs

    def test_nav_fix_angle_on_curve_2_1(self):
        """Path 2→3 (secondary_id=2-1) has is_navi_fix_angle=1, nav_fix_angle=π/2."""
        _, _, paths = sut.parse_kc_xmap(TEST_XMAP)
        path = next(p for p in paths if p.secondary_id == "2-1")
        assert path.nav_fix_angle_rad is not None
        assert path.nav_fix_angle_rad == pytest.approx(math.pi / 2)

    def test_no_nav_fix_on_other_curves(self):
        _, _, paths = sut.parse_kc_xmap(TEST_XMAP)
        for p in paths:
            if p.secondary_id != "2-1":
                assert p.nav_fix_angle_rad is None, \
                    f"{p.secondary_id} should not have nav_fix_angle"

    def test_forbidden_paths_are_skipped(self):
        """is_forbidden=1 curves are not included in path list."""
        _, _, paths = sut.parse_kc_xmap(TEST_XMAP)
        # test.xmap 没有禁行边；验证所有 paths 的 is_forbidden 是 False
        for p in paths:
            assert p.is_forbidden is False
            assert p.secondary_id  # 确保有 legitimate 数据


# ── build_opentcs_xml ───────────────────────────────────────────────────

@pytest.fixture(scope="module")
def plant_xml():
    map_name, points, paths = sut.parse_kc_xmap(TEST_XMAP)
    tree = sut.build_opentcs_xml(f"KC_{map_name}", points, paths)
    return tree.getroot()


class TestBuildOpentcsXml:
    def test_model_root(self, plant_xml):
        assert plant_xml.tag == "model"
        assert plant_xml.attrib["version"] == "7.0.0"
        assert plant_xml.attrib["name"] == "KC_newNav"

    def test_point_count(self, plant_xml):
        points = plant_xml.findall("point")
        assert len(points) == 3

    def test_path_count(self, plant_xml):
        paths = plant_xml.findall("path")
        assert len(paths) == 4

    # ── Point 字段 ──────────────────────────────────────────────

    @pytest.mark.parametrize("kc_id, expected_name, expected_x, expected_y", [
        ("1", "KC-1", -4888, -12828),
        ("2", "KC-2", -4888, -6428),
        ("3", "KC-3", -2162, -6428),
    ])
    def test_point_name_position(self, plant_xml, kc_id, expected_name, expected_x, expected_y):
        pt = plant_xml.find(f"point/../point/property[@name='kc:markerId'][@value='{kc_id}']/..")
        # 根据 kc:markerId 找到对应的 point
        for point_el in plant_xml.findall("point"):
            marker = point_el.find("property[@name='kc:markerId']")
            if marker is not None and marker.attrib["value"] == kc_id:
                assert point_el.attrib["name"] == expected_name
                assert point_el.attrib["positionX"] == str(expected_x)
                assert point_el.attrib["positionY"] == str(expected_y)
                assert point_el.attrib["positionZ"] == "0"
                assert point_el.attrib["type"] == "HALT_POSITION"
                return
        pytest.fail(f"Point with kc:markerId={kc_id} not found")

    def test_kc3_has_arrival_angle(self, plant_xml):
        """KC-3 should have vehicleOrientationAngle≈90.0° (from 2→3 nav_fix_angle)."""
        pt3 = None
        for pt in plant_xml.findall("point"):
            m = pt.find("property[@name='kc:markerId']")
            if m is not None and m.attrib["value"] == "3":
                pt3 = pt
                break
        assert pt3 is not None
        assert pt3.attrib["vehicleOrientationAngle"] == "90.0"

    def test_kc1_kc2_have_nan_angle(self, plant_xml):
        for pt in plant_xml.findall("point"):
            m = pt.find("property[@name='kc:markerId']")
            if m is not None and m.attrib["value"] in ("1", "2"):
                assert pt.attrib["vehicleOrientationAngle"] == "NaN"

    def test_all_points_have_bounding_box(self, plant_xml):
        for pt in plant_xml.findall("point"):
            bb = pt.find("maxVehicleBoundingBox")
            assert bb is not None
            assert bb.attrib["length"] == "1000"
            assert bb.attrib["width"] == "1000"
            assert bb.attrib["height"] == "1000"
            assert bb.attrib["referenceOffsetX"] == "0"
            assert bb.attrib["referenceOffsetY"] == "0"

    def test_all_points_have_properties(self, plant_xml):
        for pt in plant_xml.findall("point"):
            marker = pt.find("property[@name='kc:markerId']")
            assert marker is not None, f"Point {pt.attrib.get('name')} missing kc:markerId"
            assert marker.attrib["value"] in ("1", "2", "3")

            cls = pt.find("property[@name='kc:className']")
            assert cls is not None, f"Point {pt.attrib.get('name')} missing kc:className"
            assert cls.attrib["value"] == "LandMark"

    def test_all_points_have_layout(self, plant_xml):
        for pt in plant_xml.findall("point"):
            layout = pt.find("pointLayout")
            assert layout is not None
            assert layout.attrib["labelOffsetX"] == "-10"
            assert layout.attrib["labelOffsetY"] == "-20"
            assert layout.attrib["layerId"] == "0"

    # ── Outgoing paths ──────────────────────────────────────────

    def test_kc1_outgoing(self, plant_xml):
        pt1 = _find_point(plant_xml, "1")
        out = [o.attrib["name"] for o in pt1.findall("outgoingPath")]
        assert out == ["KC-1 --- KC-2"]

    def test_kc2_outgoing(self, plant_xml):
        pt2 = _find_point(plant_xml, "2")
        out = [o.attrib["name"] for o in pt2.findall("outgoingPath")]
        assert sorted(out) == ["KC-2 --- KC-1", "KC-2 --- KC-3"]

    def test_kc3_outgoing(self, plant_xml):
        pt3 = _find_point(plant_xml, "3")
        out = [o.attrib["name"] for o in pt3.findall("outgoingPath")]
        assert out == ["KC-3 --- KC-2"]

    # ── Path 字段 ───────────────────────────────────────────────

    @pytest.mark.parametrize("sec_id, src, dst, length, direction", [
        ("1-1", "KC-2", "KC-1", "6400", "backward"),
        ("1-2", "KC-1", "KC-2", "6400", "forward"),
        ("2-1", "KC-2", "KC-3", "2726", "forward"),
        ("2-2", "KC-3", "KC-2", "2726", "forward"),
    ])
    def test_path_attributes(self, plant_xml, sec_id, src, dst, length, direction):
        path = _find_path(plant_xml, sec_id)
        assert path.attrib["sourcePoint"] == src
        assert path.attrib["destinationPoint"] == dst
        assert path.attrib["length"] == length
        assert path.attrib["maxVelocity"] == "1000"
        assert path.attrib["maxReverseVelocity"] == "0"
        assert path.attrib["locked"] == "false"

        dir_prop = path.find("property[@name='kc:direction']")
        assert dir_prop is not None
        assert dir_prop.attrib["value"] == direction

    def test_path_2_1_has_nav_fix_angle(self, plant_xml):
        path = _find_path(plant_xml, "2-1")
        nav = path.find("property[@name='kc:navFixAngleDeg']")
        assert nav is not None
        assert nav.attrib["value"] == "90.0"

    def test_other_paths_no_nav_fix_angle(self, plant_xml):
        for sec_id in ("1-1", "1-2", "2-2"):
            path = _find_path(plant_xml, sec_id)
            nav = path.find("property[@name='kc:navFixAngleDeg']")
            assert nav is None, f"{sec_id} should not have kc:navFixAngleDeg"

    # ── VisualLayout ────────────────────────────────────────────

    def test_visual_layout_present(self, plant_xml):
        vl = plant_xml.find("visualLayout")
        assert vl is not None
        assert vl.attrib["name"] == "VLayout"
        assert vl.attrib["scaleX"] == "50.0"
        assert vl.attrib["scaleY"] == "50.0"

    def test_visual_layout_has_layer(self, plant_xml):
        layer = plant_xml.find("visualLayout/layer")
        assert layer is not None
        assert layer.attrib["id"] == "0"
        assert layer.attrib["name"] == "Default layer"
        assert layer.attrib["visible"] == "true"

    def test_visual_layout_has_layer_group(self, plant_xml):
        group = plant_xml.find("visualLayout/layerGroup")
        assert group is not None
        assert group.attrib["id"] == "0"
        assert group.attrib["name"] == "Default layer group"

    # ── Path layout ─────────────────────────────────────────────

    def test_all_paths_have_layout(self, plant_xml):
        for path in plant_xml.findall("path"):
            layout = path.find("pathLayout")
            assert layout is not None
            assert layout.attrib["connectionType"] == "DIRECT"
            assert layout.attrib["layerId"] == "0"


# ── 坐标转换精度 ────────────────────────────────────────────────────────

class TestCoordinatePrecision:
    def test_m_to_mm_rounding(self):
        assert sut._m_to_mm(0.001) == 1
        assert sut._m_to_mm(0.0014) == 1
        assert sut._m_to_mm(0.0015) == 2
        assert sut._m_to_mm(1.0) == 1000
        assert sut._m_to_mm(-1.234) == -1234

    def test_dist_mm_horizontal(self):
        a = sut.KcPoint(kc_id="a", x_m=0, y_m=0)
        b = sut.KcPoint(kc_id="b", x_m=1.0, y_m=0)
        assert sut._dist_mm(a, b) == 1000

    def test_dist_mm_vertical(self):
        a = sut.KcPoint(kc_id="a", x_m=0, y_m=0)
        b = sut.KcPoint(kc_id="b", x_m=0, y_m=2.0)
        assert sut._dist_mm(a, b) == 2000

    def test_dist_mm_actual_kc2_to_kc3(self):
        """Verify real distance: KC-2 (-4.888, -6.428) to KC-3 (-2.162, -6.428)."""
        kc2 = sut.KcPoint(kc_id="2", x_m=-4.888219451292729, y_m=-6.428413474428517)
        kc3 = sut.KcPoint(kc_id="3", x_m=-2.1623542985850306, y_m=-6.428413474428517)
        d = sut._dist_mm(kc2, kc3)
        assert d == 2726  # from the docs


# ── 边界情况 ────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_xmap_no_points(self, tmp_path):
        """Map with no advanced_point / advanced_curve elements."""
        xmap = tmp_path / "empty.xmap"
        xmap.write_text('<MAP><header name="empty"/></MAP>', encoding="utf-8")
        name, points, paths = sut.parse_kc_xmap(xmap)
        assert name == "empty"
        assert points == []
        assert paths == []

    def test_point_without_pos_skipped(self, tmp_path):
        xmap = tmp_path / "no_pos.xmap"
        xmap.write_text("""<MAP><header name="t"/>
            <advanced_point id="1"><!-- no pos --></advanced_point>
            <advanced_point id="2"><pos x="1" y="2"/></advanced_point>
        </MAP>""", encoding="utf-8")
        _, points, _ = sut.parse_kc_xmap(xmap)
        assert len(points) == 1
        assert points[0].kc_id == "2"

    def test_point_without_id_skipped(self, tmp_path):
        xmap = tmp_path / "no_id.xmap"
        xmap.write_text("""<MAP><header name="t"/>
            <advanced_point id=""><pos x="1" y="2"/></advanced_point>
        </MAP>""", encoding="utf-8")
        _, points, _ = sut.parse_kc_xmap(xmap)
        assert len(points) == 0

    def test_curve_without_start_pos_skipped(self, tmp_path):
        xmap = tmp_path / "no_start.xmap"
        xmap.write_text("""<MAP><header name="t"/>
            <advanced_point id="1"><pos x="0" y="0"/></advanced_point>
            <advanced_curve secondary_id="x" Direction="forward">
                <end_pos id="1"/>
            </advanced_curve>
        </MAP>""", encoding="utf-8")
        _, points, paths = sut.parse_kc_xmap(xmap)
        assert len(points) == 1
        assert len(paths) == 0

    def test_curve_with_unknown_points_skipped_in_build(self, tmp_path):
        """Path referencing non-existent point IDs is omitted."""
        name = "ghost"
        pts = [sut.KcPoint(kc_id="1", x_m=0, y_m=0)]
        paths = [sut.KcPath(secondary_id="x", start_id="1", end_id="999",
                            direction="forward", is_forbidden=False,
                            nav_fix_angle_rad=None)]
        tree = sut.build_opentcs_xml(name, pts, paths)
        root = tree.getroot()
        assert len(root.findall("point")) == 1
        assert len(root.findall("path")) == 0

    def test_forbidden_path_filtered(self, tmp_path):
        xmap = tmp_path / "forbidden.xmap"
        xmap.write_text("""<MAP><header name="t"/>
            <advanced_point id="1"><pos x="0" y="0"/></advanced_point>
            <advanced_point id="2"><pos x="1" y="0"/></advanced_point>
            <advanced_curve secondary_id="ok" is_forbidden="0" Direction="forward">
                <start_pos id="1"/><end_pos id="2"/>
            </advanced_curve>
            <advanced_curve secondary_id="bad" is_forbidden="1" Direction="forward">
                <start_pos id="2"/><end_pos id="1"/>
            </advanced_curve>
        </MAP>""", encoding="utf-8")
        _, _, paths = sut.parse_kc_xmap(xmap)
        assert len(paths) == 1
        assert paths[0].secondary_id == "ok"

    def test_map_name_fallback_to_filename(self, tmp_path):
        xmap = tmp_path / "my_map.xmap"
        xmap.write_text("<MAP></MAP>", encoding="utf-8")
        name, _, _ = sut.parse_kc_xmap(xmap)
        assert name == "my_map"

    def test_nav_fix_angle_multiple(self, tmp_path):
        """
        Two curves to the same destination with is_navi_fix_angle=1.
        The last one wins for vehicleOrientationAngle.
        """
        xmap = tmp_path / "multi_fix.xmap"
        xmap.write_text('''<MAP><header name="t"/>
            <advanced_point id="1"><pos x="0" y="0"/></advanced_point>
            <advanced_point id="2"><pos x="10" y="0"/></advanced_point>
            <advanced_point id="3"><pos x="20" y="0"/></advanced_point>
            <advanced_curve secondary_id="a" is_forbidden="0" Direction="forward"
                is_navi_fix_angle="1" nav_fix_angle="1.5707963267948966">
                <start_pos id="1"/><end_pos id="3"/>
            </advanced_curve>
            <advanced_curve secondary_id="b" is_forbidden="0" Direction="forward"
                is_navi_fix_angle="1" nav_fix_angle="3.141592653589793">
                <start_pos id="2"/><end_pos id="3"/>
            </advanced_curve>
        </MAP>''', encoding="utf-8")
        _, pts, pths = sut.parse_kc_xmap(xmap)
        tree = sut.build_opentcs_xml("t", pts, pths)
        root = tree.getroot()
        # pt3 should have angle = 180° (the later curve wins)
        pt3 = _find_point(root, "3")
        assert pt3.attrib["vehicleOrientationAngle"] == "180.0"


# ── Vehicle / location / timestamp (Kernel-ready model) ───────────────────

@pytest.fixture(scope="module")
def full_model():
    """Complete Kernel-ready model with vehicle, locations, timestamp."""
    map_name, points, paths = sut.parse_kc_xmap(TEST_XMAP)
    vehicle = sut.VehicleConfig(name="AGV-001")
    locations = sut.LocationConfig(count=1)
    tree = sut.build_opentcs_xml(f"KC_{map_name}", points, paths,
                                  vehicle=vehicle, locations=locations)
    return tree.getroot()


@pytest.fixture(scope="module")
def full_model_all_locs():
    """Kernel-ready model with a location for every point."""
    map_name, points, paths = sut.parse_kc_xmap(TEST_XMAP)
    vehicle = sut.VehicleConfig(name="AGV-001")
    locations = sut.LocationConfig(count=-1)  # all points
    tree = sut.build_opentcs_xml(f"KC_{map_name}", points, paths,
                                  vehicle=vehicle, locations=locations)
    return tree.getroot()


class TestVehicleElement:
    def test_vehicle_present(self, full_model):
        veh = full_model.find("vehicle")
        assert veh is not None
        assert veh.attrib["name"] == "AGV-001"

    def test_vehicle_energy_attrs(self, full_model):
        veh = full_model.find("vehicle")
        assert veh.attrib["energyLevelCritical"] == "0"
        assert veh.attrib["energyLevelGood"] == "80"
        assert veh.attrib["energyLevelFullyRecharged"] == "100"
        assert veh.attrib["maxVelocity"] == "1000"
        assert veh.attrib["maxReverseVelocity"] == "500"

    def test_vehicle_bounding_box(self, full_model):
        bb = full_model.find("vehicle/boundingBox")
        assert bb is not None
        assert bb.attrib["length"] == "1000"
        assert bb.attrib["width"] == "600"
        assert bb.attrib["height"] == "300"

    def test_vehicle_has_kecong_properties(self, full_model):
        veh = full_model.find("vehicle")
        props = {p.attrib["name"]: p.attrib["value"] for p in veh.findall("property")}
        assert props["kecong:navHost"] == "127.0.0.1"
        assert props["kecong:navPort"] == "17804"
        assert props["kecong:qrHost"] == "127.0.0.1"
        assert props["kecong:qrPort"] == "17800"
        assert props["kecong:authCode"] == "KC-SIMULATOR-01"
        assert props["kecong:pollInterval"] == "100"
        assert props["kecong:autoInit"] == "false"

    def test_vehicle_has_layout(self, full_model):
        layout = full_model.find("vehicle/vehicleLayout")
        assert layout is not None
        assert layout.attrib["color"] == "#FF0000"

    def test_default_config_is_simulator(self):
        """VehicleConfig defaults match simulator settings."""
        cfg = sut.VehicleConfig()
        assert cfg.nav_host == "127.0.0.1"
        assert cfg.qr_host == "127.0.0.1"
        assert cfg.auth_code == "KC-SIMULATOR-01"
        assert cfg.auto_init is False

    def test_real_config_has_controller_defaults(self):
        """Explicit --real should use real controller settings."""
        cfg = sut.VehicleConfig(
            nav_host="192.168.100.178",
            qr_host="192.168.100.200",
            auth_code="",
            auto_init=True,
        )
        assert cfg.nav_host == "192.168.100.178"
        assert cfg.qr_host == "192.168.100.200"
        assert cfg.auth_code == ""
        assert cfg.auto_init is True


class TestLocationTypeElement:
    def test_location_type_present(self, full_model):
        lt = full_model.find("locationType")
        assert lt is not None
        assert lt.attrib["name"] == "LType-0001"

    def test_location_type_has_fork_ops(self, full_model):
        lt = full_model.find("locationType")
        ops = {o.attrib["name"] for o in lt.findall("allowedOperation")}
        assert ops == {"LOAD", "UNLOAD", "NOP", "FORK_FWD", "FORK_REV"}


class TestLocationElements:
    def test_default_one_location(self, full_model):
        locs = full_model.findall("location")
        assert len(locs) == 1
        assert locs[0].attrib["name"] == "Loc-KC-1"

    def test_all_points_as_locations(self, full_model_all_locs):
        locs = full_model_all_locs.findall("location")
        assert len(locs) == 3  # test.xmap has 3 points

    def test_location_names(self, full_model_all_locs):
        loc_names = {loc.attrib["name"] for loc in full_model_all_locs.findall("location")}
        assert loc_names == {"Loc-KC-1", "Loc-KC-2", "Loc-KC-3"}

    def test_location_links_to_point(self, full_model):
        loc = full_model.find("location")
        link = loc.find("link")
        assert link is not None
        assert link.attrib["point"] == "KC-1"

    def test_location_position_matches_point(self, full_model):
        """Location positionX/Y must equal its linked point's position."""
        loc = full_model.find("location")
        pt1 = _find_point(full_model, "1")
        assert loc.attrib["positionX"] == pt1.attrib["positionX"]
        assert loc.attrib["positionY"] == pt1.attrib["positionY"]
        assert loc.attrib["type"] == "LType-0001"

    def test_location_has_layout(self, full_model):
        layout = full_model.find("location/locationLayout")
        assert layout is not None
        assert layout.attrib["locationRepresentation"] == "DEFAULT"


class TestTimestampProperty:
    def test_timestamp_present(self, full_model):
        prop = full_model.find("property[@name='tcs:modelFileLastModified']")
        assert prop is not None

    def test_timestamp_iso_format(self, full_model):
        prop = full_model.find("property[@name='tcs:modelFileLastModified']")
        value = prop.attrib["value"]
        # ISO 8601: 2026-07-01T10:49:05Z
        assert "T" in value
        assert value.endswith("Z")
        assert len(value) == 20  # yyyy-MM-ddTHH:mm:ssZ


class TestElementOrdering:
    def test_children_in_schema_order(self, full_model):
        """Model children must be: point* path* vehicle locationType location* visualLayout property."""
        order = []
        expected_order = ["point", "path", "vehicle", "locationType",
                          "location", "visualLayout", "property"]
        for child in full_model:
            order.append(child.tag)
        # Verify relative order (use index positions)
        for tag in expected_order:
            assert tag in order, f"Missing element: {tag}"
        indices = {tag: order.index(tag) for tag in expected_order}
        # point before path before vehicle ...
        assert indices["point"] < indices["path"]
        assert indices["path"] < indices["vehicle"]
        assert indices["vehicle"] < indices["locationType"]
        assert indices["locationType"] < indices["location"]
        assert indices["location"] < indices["visualLayout"]
        assert indices["visualLayout"] < indices["property"]


class TestBackwardCompat:
    """When vehicle=None, output is identical to pre-optimization behavior."""
    def test_no_vehicle_element(self):
        name, pts, pths = sut.parse_kc_xmap(TEST_XMAP)
        tree = sut.build_opentcs_xml(name, pts, pths)
        root = tree.getroot()
        assert root.find("vehicle") is None

    def test_no_location_or_timestamp(self):
        name, pts, pths = sut.parse_kc_xmap(TEST_XMAP)
        tree = sut.build_opentcs_xml(name, pts, pths)
        root = tree.getroot()
        assert root.find("locationType") is None
        assert root.find("location") is None
        assert root.find("property[@name='tcs:modelFileLastModified']") is None


# ── helpers ─────────────────────────────────────────────────────────────

def _find_point(root: ET.Element, kc_id: str) -> ET.Element:
    for pt in root.findall("point"):
        m = pt.find("property[@name='kc:markerId']")
        if m is not None and m.attrib["value"] == kc_id:
            return pt
    raise ValueError(f"Point with kc:markerId={kc_id} not found")


def _find_path(root: ET.Element, secondary_id: str) -> ET.Element:
    for p in root.findall("path"):
        m = p.find("property[@name='kc:secondaryId']")
        if m is not None and m.attrib["value"] == secondary_id:
            return p
    raise ValueError(f"Path with kc:secondaryId={secondary_id} not found")
