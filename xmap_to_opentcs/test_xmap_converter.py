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
