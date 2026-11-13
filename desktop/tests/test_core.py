"""Автотесты ядра: 2D-редактирование, штриховка, размеры, штамп, 3D-операции, виды, история, файлы, экспорт."""
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cad import edit2d, geometry as geo, ops  # noqa: E402
from cad.dims import check_tolerance, dim_text, pick_distance, render  # noqa: E402
from cad.export2d import to_dxf, to_svg  # noqa: E402
from cad.linestyles import wavy_points  # noqa: E402
from cad.model import (  # noqa: E402
    History, Project, make_angdim, make_arc, make_circle, make_diadim, make_dim, make_hatch, make_leader, make_line,
    make_raddim, make_rect, make_rough, sheet_size,
)
from cad.projection import make_drawing, project_view  # noqa: E402
from cad.stamp import hit_cell, stamp_cells  # noqa: E402


def close(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


class Trim(unittest.TestCase):
    def test_line_between_two_crossings(self):
        ents = [make_line(0, 0, 100, 0), make_line(30, -10, 30, 10), make_line(70, -10, 70, 10)]
        n = edit2d.trim(ents, ents[0]["id"], (50, 0))
        self.assertEqual(n, 2)
        lines = sorted((e for e in ents if e["y1"] == 0 and e["y2"] == 0), key=lambda e: e["x1"])
        self.assertTrue(close((lines[0]["x1"], lines[0]["x2"]), (0, 30)))
        self.assertTrue(close((lines[1]["x1"], lines[1]["x2"]), (70, 100)))

    def test_line_end_segment(self):
        ents = [make_line(0, 0, 100, 0), make_line(30, -10, 30, 10)]
        edit2d.trim(ents, ents[0]["id"], (10, 0))
        kept = [e for e in ents if e["y1"] == 0 and e["y2"] == 0][0]
        self.assertTrue(close((kept["x1"], kept["x2"]), (30, 100)))

    def test_circle_becomes_arc(self):
        c = make_circle(0, 0, 10)
        ents = [c, make_line(-20, 0, 20, 0)]
        edit2d.trim(ents, c["id"], (0, 10))  # верхняя половина
        arc = next(e for e in ents if e["type"] == "arc")
        self.assertAlmostEqual(arc["a0"], 180.0, 6)
        self.assertAlmostEqual(arc["a1"], 0.0, 6)

    def test_no_crossings_deletes(self):
        ents = [make_line(0, 0, 10, 0)]
        edit2d.trim(ents, ents[0]["id"], (5, 0))
        self.assertEqual(ents, [])


class Extend(unittest.TestCase):
    def test_line_to_nearest(self):
        ents = [make_line(0, 0, 10, 0), make_line(30, -5, 30, 5), make_line(50, -5, 50, 5)]
        gain = edit2d.extend(ents, ents[0]["id"], (9, 0))
        self.assertAlmostEqual(gain, 20)
        self.assertAlmostEqual(ents[0]["x2"], 30)

    def test_nothing_ahead(self):
        ents = [make_line(0, 0, 10, 0)]
        with self.assertRaises(ValueError):
            edit2d.extend(ents, ents[0]["id"], (9, 0))


class CornerOps(unittest.TestCase):
    def corner(self):
        a, b = make_line(0, 0, 50, 0), make_line(0, 0, 0, 40)
        return [a, b], a, b

    def test_chamfer_two_legs(self):
        ents, a, b = self.corner()
        ch = edit2d.chamfer(ents, a["id"], (30, 0), b["id"], (0, 30), 5, 8)
        self.assertTrue(close((ch["x1"], ch["y1"], ch["x2"], ch["y2"]), (5, 0, 0, 8)))
        self.assertAlmostEqual(min(a["x1"], a["x2"]), 5)
        self.assertAlmostEqual(min(b["y1"], b["y2"]), 8)

    def test_chamfer_by_angle_45(self):
        ents, a, b = self.corner()
        ch = edit2d.chamfer(ents, a["id"], (30, 0), b["id"], (0, 30), 5, angle=45)
        self.assertAlmostEqual(math.hypot(ch["x2"] - ch["x1"], ch["y2"] - ch["y1"]), 5 * math.sqrt(2), 6)

    def test_fillet_tangent(self):
        ents, a, b = self.corner()
        arc = edit2d.fillet(ents, a["id"], (30, 0), b["id"], (0, 30), 6)
        self.assertTrue(close((arc["cx"], arc["cy"], arc["r"]), (6, 6, 6)))
        self.assertAlmostEqual(geo.arc_sweep(arc) if hasattr(geo, "arc_sweep") else (arc["a1"] - arc["a0"]) % 360, 90, 6)
        self.assertAlmostEqual(min(a["x1"], a["x2"]), 6)
        # После скругления контур остаётся связным: концы дуги совпадают с концами отрезков.
        c = geo.contours(ents + [make_line(50, 0, 50, 40), make_line(50, 40, 0, 40)])
        self.assertEqual(c.closed, 1)

    def test_fillet_too_big(self):
        ents, a, b = self.corner()
        with self.assertRaises(ValueError):
            edit2d.fillet(ents, a["id"], (30, 0), b["id"], (0, 30), 60)


class Transforms(unittest.TestCase):
    def test_mirror_copy(self):
        ents = [make_arc(10, 5, 3, 0, 90)]
        m = edit2d.mirror(ents, [ents[0]["id"]], (0, 0), (0, 1))[0]
        self.assertEqual(len(ents), 2)
        self.assertTrue(close((m["cx"], m["cy"]), (-10, 5)))
        self.assertTrue(close((m["a0"], m["a1"]), (90, 180)))

    def test_pattern_circular(self):
        ents = [make_circle(20, 0, 2)]
        edit2d.pattern_circular(ents, [ents[0]["id"]], (0, 0), 6)
        self.assertEqual(len(ents), 6)
        angs = sorted(round(math.degrees(math.atan2(e["cy"], e["cx"])) % 360) for e in ents)
        self.assertEqual(angs, [0, 60, 120, 180, 240, 300])

    def test_pattern_linear(self):
        ents = [make_circle(0, 0, 1)]
        edit2d.pattern_linear(ents, [ents[0]["id"]], 3, 2, 10, 5)
        self.assertEqual(sorted((e["cx"], e["cy"]) for e in ents), [(0, 0), (0, 5), (10, 0), (10, 5), (20, 0), (20, 5)])


class Offset(unittest.TestCase):
    def test_rect_outward_and_inward(self):
        ents = make_rect(0, 0, 40, 20)
        out = edit2d.offset(ents, ents[0]["id"], 5, (-10, -10))
        xs = [p for e in out for p in (e["x1"], e["x2"])]
        self.assertAlmostEqual(min(xs), -5)
        self.assertAlmostEqual(max(xs), 45)
        ents2 = make_rect(0, 0, 40, 20)
        inn = edit2d.offset(ents2, ents2[0]["id"], 5, (20, 10))
        ys = [p for e in inn for p in (e["y1"], e["y2"])]
        self.assertAlmostEqual(min(ys), 5)
        self.assertAlmostEqual(max(ys), 15)

    def test_circle(self):
        ents = [make_circle(0, 0, 10)]
        self.assertAlmostEqual(edit2d.offset(ents, ents[0]["id"], 3, (0, 0))[0]["r"], 7)

    def test_single_line(self):
        ents = [make_line(0, 0, 10, 0)]
        n = edit2d.offset(ents, ents[0]["id"], 2, (5, -5), whole_contour=False)[0]
        self.assertAlmostEqual(n["y1"], -2)


class Hatch(unittest.TestCase):
    def test_region_with_hole(self):
        ents = make_rect(0, 0, 40, 40) + [make_circle(20, 20, 8)]
        b = edit2d.hatch_region(ents, (5, 5))
        self.assertEqual(len(b), 2)
        h = make_hatch(b, "metal", 2, 45)
        segs = edit2d.hatch_segments(h)
        self.assertGreater(len(segs), 20)
        for x1, y1, x2, y2 in segs:  # ни один штрих не заходит в отверстие
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            self.assertGreater(math.hypot(mx - 20, my - 20), 8 - 1e-6)
            self.assertTrue(-1e-6 <= mx <= 40 + 1e-6 and -1e-6 <= my <= 40 + 1e-6)

    def test_patterns(self):
        b = [[(0, 0), (30, 0), (30, 30), (0, 30)]]
        counts = {p: len(edit2d.hatch_segments(make_hatch(b, p, 2, 45))) for p in ("metal", "nonmetal", "concrete", "glass")}
        self.assertGreater(counts["nonmetal"], counts["metal"])
        self.assertTrue(all(v > 0 for v in counts.values()))

    def test_click_outside(self):
        with self.assertRaises(ValueError):
            edit2d.hatch_region(make_rect(0, 0, 10, 10), (50, 50))


class Dimensions(unittest.TestCase):
    def test_values_and_prefixes(self):
        self.assertEqual(render(make_dim(0, 0, 30, 40, 5, "horizontal")).texts[0][3], "30")
        self.assertEqual(render(make_dim(0, 0, 30, 40, 5, "vertical")).texts[0][3], "40")
        self.assertEqual(render(make_dim(0, 0, 30, 40, 5, "aligned")).texts[0][3], "50")
        self.assertEqual(render(make_diadim(0, 0, 6.25)).texts[0][3], "⌀12,5")
        self.assertEqual(render(make_raddim(0, 0, 4)).texts[0][3], "R4")
        self.assertEqual(render(make_angdim(0, 0, 0, 30)).texts[0][3], "30°")
        self.assertIn("Ra 3,2", render(make_rough(0, 0, "3,2")).texts[0][3])
        self.assertEqual(render(make_leader(0, 0, 10, 10, "2 отв.")).texts[0][3], "2 отв.")

    def test_tolerances(self):
        d = make_dim(0, 0, 50, 0, 5, "horizontal")
        for tol, text in (("H7", "50H7"), ("H7/g6", "50H7/g6"), ("±0.1", "50±0,1"), ("+0,2/-0,1", "50 (+0,2/-0,1)")):
            d["tol"] = check_tolerance(tol)
            self.assertEqual(dim_text(d, 50), text)
        with self.assertRaises(ValueError):
            check_tolerance("abc")

    def test_arrows_and_pick(self):
        d = render(make_dim(0, 0, 40, 0, 10, "horizontal"))
        self.assertEqual(len(d.arrows), 2)
        self.assertLess(pick_distance(make_dim(0, 0, 40, 0, 10, "horizontal"), 20, 10), 0.5)


class Stamp(unittest.TestCase):
    def test_formats_and_cells(self):
        self.assertEqual(sheet_size("A4", "portrait"), (210, 297))
        self.assertEqual(sheet_size("A1", "landscape"), (841, 594))
        p = Project()
        ops.set_frame(p, "A2", "portrait")
        cells = stamp_cells(p.frame)
        self.assertAlmostEqual(sum(c.w * c.h for c in cells), 185 * 55)
        fields = {c.field for c in cells if c.field}
        for f in ("name", "designation", "material", "mass", "scale", "people.Разраб.", "people.Пров."):
            self.assertIn(f, fields)
        name_cell = next(c for c in cells if c.field == "name")
        self.assertEqual(hit_cell(p.frame, name_cell.x + 5, name_cell.y + 5).field, "name")


class Solids(unittest.TestCase):
    def test_flange_with_holes(self):
        p = Project()
        p.entities = make_rect(-40, -40, 80, 80) + [make_circle(0, 0, 15)] + [make_circle(30 * math.cos(a), 30 * math.sin(a), 4) for a in (0.785, 2.356, 3.927, 5.498)]
        ops.create_feature(p, "extrude", height=10)
        self.assertEqual(p.entities, [])  # эскиз ушёл в операцию
        s = geo.build_solid(p.features)
        expected = (80 * 80 - math.pi * 15 ** 2 - 4 * math.pi * 16) * 10
        self.assertAlmostEqual(s.volume / expected, 1, 2)

    def test_edit_sketch_rebuilds(self):
        p = Project()
        p.entities = [make_circle(0, 0, 10)]
        f = ops.create_feature(p, "extrude", height=5)
        v1 = geo.build_solid(p.features).volume
        f["sketch"][0]["r"] = 20  # «поменял диаметр в эскизе»
        v2 = geo.build_solid(p.features).volume
        self.assertAlmostEqual(v2 / v1, 4, 1)
        f["height"] = 10
        self.assertAlmostEqual(geo.build_solid(p.features).volume / v1, 8, 1)

    def test_revolve_bushing(self):
        p = Project()
        p.entities = make_rect(10, 0, 10, 30) + [make_line(0, -5, 0, 40, "axis")]
        ops.create_feature(p, "revolve", angle=360)
        s = geo.build_solid(p.features)
        self.assertAlmostEqual(s.volume / (math.pi * (20 ** 2 - 10 ** 2) * 30), 1, 2)
        lo, hi = s.bbox()
        self.assertAlmostEqual(float(hi[1] - lo[1]), 30, 3)   # ось вращения — вдоль Y мира

    def test_revolve_needs_axis(self):
        p = Project()
        p.entities = make_rect(10, 0, 10, 30)
        with self.assertRaises(ValueError):
            ops.create_feature(p, "revolve")

    def test_cut_through_and_intersect(self):
        p = Project()
        p.entities = make_rect(0, 0, 40, 40)
        ops.create_feature(p, "extrude", height=10)
        p.entities = [make_circle(20, 20, 5)]
        ops.create_feature(p, "cut", through=True)
        s = geo.build_solid(p.features)
        self.assertAlmostEqual(s.volume / ((1600 - math.pi * 25) * 10), 1, 2)
        p.entities = make_rect(0, 0, 20, 40)
        ops.create_feature(p, "extrude", height=10, op="intersect")
        s2 = geo.build_solid(p.features)
        self.assertLess(s2.volume, s.volume)

    def test_shell(self):
        p = Project()
        p.entities = make_rect(0, 0, 40, 30)
        ops.create_feature(p, "extrude", height=20)
        ops.create_feature(p, "shell", thickness=2, open_top=True)
        s = geo.build_solid(p.features)
        self.assertIsNone(s.statuses[p.features[-1]["id"]])
        inner = 36 * 26 * 18
        self.assertAlmostEqual(s.volume / (40 * 30 * 20 - inner), 1, 1)

    def test_fillet_and_chamfer_3d(self):
        for kind in ("fillet3d", "chamfer3d"):
            p = Project()
            p.entities = make_rect(0, 0, 40, 30)
            ops.create_feature(p, "extrude", height=20)
            ops.create_feature(p, kind, size=3)
            s = geo.build_solid(p.features)
            self.assertIsNone(s.statuses[p.features[-1]["id"]], kind)
            self.assertLess(s.volume, 40 * 30 * 20)
            lo, hi = s.bbox()
            self.assertAlmostEqual(float(hi[0] - lo[0]), 40, 1)  # габарит не меняется

    def test_open_contour_error(self):
        p = Project()
        p.entities = [make_line(0, 0, 10, 0), make_line(10, 0, 10, 10)]
        with self.assertRaises(ValueError):
            ops.create_feature(p, "extrude", height=5)


class Views(unittest.TestCase):
    def test_three_views_with_hidden_hole(self):
        p = Project()
        p.entities = make_rect(0, 0, 60, 40) + [make_circle(30, 20, 8)]
        ops.create_feature(p, "extrude", height=15)
        s = geo.build_solid(p.features)
        vis, hid, box = project_view(s, "front")
        self.assertTrue(close(box, (0, 0, 60, 15), 1e-3))
        self.assertTrue(hid, "отверстие на главном виде — невидимые линии")
        vis_t, hid_t, box_t = project_view(s, "top")
        self.assertTrue(close(box_t, (0, 0, 60, 40), 1e-3))
        self.assertFalse(hid_t, "сверху отверстие видно целиком")
        info = make_drawing(p, s)
        gen = [e for e in p.drawing if e.get("gen") == "views"]
        self.assertGreater(info["lines"], 10)
        self.assertTrue(any(e["style"] == "hidden" for e in gen))
        dims = [e for e in gen if e["type"] == "dim"]
        self.assertEqual(sorted(render(d).texts[0][3] for d in dims), ["15", "40", "60"])
        before = len(p.drawing)
        make_drawing(p, s)  # повторная генерация заменяет, а не дублирует
        self.assertEqual(len(p.drawing), before)

    def test_collinear_pieces_merged(self):
        p = Project()
        p.entities = make_rect(0, 0, 80, 60) + [make_circle(40, 30, 12), make_circle(10, 10, 3)]
        ops.create_feature(p, "extrude", height=12)
        vis, hid, _ = project_view(geo.build_solid(p.features), "front")
        self.assertEqual((len(vis), len(hid)), (4, 4), "контур — 4 отрезка, два отверстия — 4 штриховые")

    def test_filleted_body_keeps_outline(self):
        p = Project()
        p.entities = make_rect(0, 0, 80, 60)
        ops.create_feature(p, "extrude", height=12)
        ops.create_feature(p, "fillet3d", size=1.5)
        vis, _, _ = project_view(geo.build_solid(p.features), "top")
        xs = [x for v in vis for x in (v[0], v[2])]
        self.assertAlmostEqual(min(xs), 0, delta=0.05)
        self.assertAlmostEqual(max(xs), 80, delta=0.05)


class HistoryFiles(unittest.TestCase):
    def test_undo_redo(self):
        p = Project()
        h = History(p)
        h.push()
        p.entities.append(make_line(0, 0, 1, 1))
        h.push()
        p.entities.append(make_circle(0, 0, 1))
        self.assertTrue(h.undo())
        self.assertEqual(len(p.entities), 1)
        self.assertTrue(h.undo())
        self.assertEqual(len(p.entities), 0)
        self.assertTrue(h.redo())
        self.assertEqual(len(p.entities), 1)

    def test_save_load_and_v1_migration(self):
        p = Project()
        p.entities = make_rect(0, 0, 10, 10)
        ops.create_feature(p, "extrude", height=3)
        p.drawing.append(make_hatch([[(0, 0), (5, 0), (5, 5)]]))
        path = os.path.join(tempfile.mkdtemp(), "t.k3d")
        p.save(path)
        q = Project.load(path)
        self.assertEqual(len(q.features[0]["sketch"]), 4)
        v1 = {"schema": "k3d/1", "entities": [make_dim(0, 0, 1, 0)], "features": [{"id": "f", "type": "cut", "through": True, "polygons": [[[0, 0], [1, 0], [1, 1]]]}]}
        m = Project.from_dict(v1)
        self.assertEqual(m.features[0]["type"], "extrude")
        self.assertEqual(m.features[0]["op"], "cut")
        self.assertEqual(len(m.drawing), 1)


class Export(unittest.TestCase):
    def test_dxf_svg_all_types(self):
        p = Project(name="Фланец")
        ops.set_frame(p, "A3", "landscape")
        p.drawing = [make_line(0, 0, 50, 0, s) for s in ("main", "thin", "hidden", "axis", "fold", "wavy")] + [
            make_circle(0, 0, 5), make_arc(0, 0, 8, 0, 90), make_dim(0, 0, 50, 0), make_diadim(0, 0, 5), make_raddim(0, 0, 8),
            make_angdim(0, 0, 0, 45), make_leader(0, 0, 10, 10, "текст"), make_rough(20, 20), make_hatch([[(0, 0), (20, 0), (20, 20), (0, 20)]])]
        dxf = to_dxf(p)
        for token in (b"HIDDEN", b"CENTER", b"PHANTOM", b"SOLID", b"ARC", "Фланец".encode("cp1251")):
            self.assertIn(token, dxf)
        svg = to_svg(p)
        self.assertIn("stroke-dasharray", svg)
        self.assertIn("⌀10", svg)
        self.assertGreater(len(wavy_points(0, 0, 50, 0)), 10)


class LibraryCoreTest(unittest.TestCase):
    def test_rotation_moves_ports_and_keeps_labels_upright(self):
        from cad import library
        ents = library.instantiate("qf1", 10, 20, 90, 1)
        self.assertEqual(library.ports_world("qf1", 10, 20, 90), {"вход": (10.0, 20.0), "выход": (30.0, 20.0)})
        lab = next(e for e in ents if e.get("blk_role") == "label")
        self.assertEqual((lab["text"], lab["ang"]), ("QF1", 0.0))
        arc_ents = library.instantiate("door", 0, 0, 90)
        arc = next(e for e in arc_ents if e["type"] == "arc")
        self.assertEqual((arc["a0"], arc["a1"]), (90.0, 180.0))
        big = library.instantiate("pe", 0, 0, 0, 3)
        self.assertAlmostEqual(min(e["y2"] for e in big if e["type"] == "line"), -30.0)

    def test_next_label(self):
        from cad import library
        self.assertEqual([library.next_label(s) for s in ("QF1", "ОП-12", "QF09", "А", "Ось Ж", "Б1", "")],
                         ["QF2", "ОП-13", "QF10", "Б", "Ось И", "Б2", ""])

    def test_copies_of_blocks_are_new_instances(self):
        from cad import library
        ents = library.instantiate("fu", 0, 0)
        edit2d.pattern_linear(ents, [e["id"] for e in ents], 3, 1, 20, 0)
        self.assertEqual(len({e["blk"] for e in ents}), 3)
        self.assertEqual(len(library.group_ids(ents, ents[-1]["id"])), len(ents) // 3)

    def test_text_entity_render_pick_export(self):
        from cad.dims import pick_distance
        from cad.export2d import to_dxf, to_svg
        from cad.model import make_text
        p = Project()
        t = make_text(10, 10, "ОП-12", 5, 0, "left")
        p.drawing.append(t)
        self.assertEqual(pick_distance(t, 15, 12), 0.0)
        self.assertGreater(pick_distance(t, 5, 12), 1.0, "левее начала строки — мимо")
        self.assertIn("ОП-12".encode("cp1251"), to_dxf(p, with_frame=False))
        self.assertIn(">ОП-12</text>", to_svg(p, with_frame=False))
        r = make_text(0, 0, "ABC", 5, 90, "left")
        self.assertEqual(pick_distance(r, -2.5, 4), 0.0, "повёрнутая надпись выбирается вдоль строки")


if __name__ == "__main__":
    unittest.main()
