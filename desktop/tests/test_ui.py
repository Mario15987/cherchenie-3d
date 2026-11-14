"""Автотест интерфейса: каждый инструмент — щелчками по виду, каждая кнопка ленты — нажатием.

Кнопка считается рабочей, только если после нажатия наблюдаемо меняется состояние: проект, активный инструмент,
вкладка, камера, открытая форма, предупреждение или записанный файл. Окна не показываются (Ask.AUTO).
Запуск: .venv/Scripts/python -m unittest tests.test_ui
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QKeySequence, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cad import ai, geometry as geo  # noqa: E402
from cad.dialogs import Ask  # noqa: E402
from cad.model import Project, make_circle, make_line, make_rect  # noqa: E402

from tests.env import APP, ERRORS, TMP  # noqa: E402  — временные config.json и user_library.json
from cad import library  # noqa: E402
from cad.mainwindow import MainWindow  # noqa: E402


def lines(ents):
    return [e for e in ents if e["type"] == "line"]


class UITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Ask.AUTO = True
        cls.w = MainWindow()
        cls.w.show()
        APP.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.w.dirty = False
        cls.w.close()
        Ask.AUTO = False

    def setUp(self):
        ERRORS.clear()
        Ask.answers = {}
        self.w.cfg["canvas"] = "fragment"   # каждый тест начинает с бесконечного полотна
        self.w.new_project()
        self.w.work.setCurrentIndex(0)

    def tearDown(self):
        self.assertEqual(ERRORS, [], "исключения в обработчиках Qt")

    # ------------------------------------------------------------ помощники
    def view(self, sheet=False):
        self.w.work.setCurrentIndex(1 if sheet else 0)
        v = self.w.cur2d()
        v.fit_all()
        return v

    def put(self, ents, sheet=False):
        v = self.view(sheet)
        self.w.history.push()   # как действие пользователя: отменяемо
        v.target().extend(ents)
        self.w.refresh()
        return v

    def tool(self, name, sheet=False):
        self.w.work.setCurrentIndex(1 if sheet else 0)
        self.w.set_tool(name)
        return self.w.cur2d()

    # ------------------------------------------------------------ черчение
    def test_draw_closed_chain_with_mouse(self):
        v = self.tool("line")
        for p in [(0, 0), (40, 0), (40, 30), (0, 30), (0, 0)]:
            v.click(*p)
        self.assertEqual(len(lines(self.w.project.entities)), 4)
        self.assertEqual(v.points, [], "цепочка должна закончиться на замыкании")
        self.assertEqual(geo.contours(self.w.project.profile_entities()).closed, 1)

    def test_precise_input_panel(self):
        tp = self.w.tool_panel
        self.tool("line")
        tp.spins["x1"].setValue(10)
        tp.spins["y1"].setValue(5)
        tp.spins["length"].setValue(50)
        tp.spins["angle"].setValue(30)
        tp.apply()
        e = self.w.project.entities[-1]
        self.assertAlmostEqual(e["x2"], 10 + 50 * math.cos(math.radians(30)), 6)
        self.assertAlmostEqual(e["y2"], 5 + 25, 6)
        self.tool("circle")
        tp.spins["cx"].setValue(3)
        tp.spins["d"].setValue(24)
        self.assertAlmostEqual(tp.spins["r"].value(), 12)
        tp.apply()
        self.assertEqual(self.w.project.entities[-1]["r"], 12)
        self.tool("rect")
        for k, val in (("x", 0), ("y", 0), ("w", 30), ("h", 20)):
            tp.spins[k].setValue(val)
        tp.apply()
        self.assertEqual(len(lines(self.w.project.entities)), 5)
        self.tool("arc")
        for k, val in (("cx", 0), ("cy", 0), ("r", 7), ("a0", 0), ("a1", 90)):
            tp.spins[k].setValue(val)
        tp.apply()
        self.assertEqual(self.w.project.entities[-1]["type"], "arc")
        self.tool("axis")
        tp.apply()
        self.assertEqual(self.w.project.entities[-1]["style"], "axis")

    def test_line_styles(self):
        for i, style in enumerate(("main", "thin", "hidden", "axis", "fold", "wavy")):
            self.w.style_box.setCurrentIndex(i)
            v = self.tool("line")
            v.click(0, i * 10)
            v.click(30, i * 10)
            v.cancel()
            self.assertEqual(self.w.project.entities[-1]["style"], style)
        # стиль из списка применяется к выделенному
        v = self.w.cur2d()
        v.select([self.w.project.entities[0]["id"]])
        self.w.style_box.setCurrentIndex(2)
        self.assertEqual(self.w.project.entities[0]["style"], "hidden")

    def test_snaps(self):
        v = self.put([make_line(0, 0, 50.3, 0), make_line(20.1, -10, 20.1, 30)])
        self.assertEqual(set(v.snaps), {"end", "mid", "center", "intersection", "perp", "tangent", "grid"})
        x, y, _, kind = v.snap(50.2, 0.1)
        self.assertEqual((round(x, 3), kind), (50.3, "end"))
        x, y, _, kind = v.snap(25.2, 0.1)
        self.assertEqual((round(x, 3), kind), (25.15, "mid"))
        x, y, _, kind = v.snap(20.2, 0.05)
        self.assertEqual((round(x, 3), round(y, 3), kind), (20.1, 0.0, "intersection"))
        for k, a in self.w.snap_actions.items():
            a.setChecked(k == "grid")
        self.assertEqual(v.snaps, {"grid"})
        self.assertEqual(v.snap(50.2, 0.1)[3], "grid")
        for a in self.w.snap_actions.values():
            a.setChecked(True)

    # ------------------------------------------------------------ редактирование
    def test_trim_and_extend(self):
        v = self.put([make_line(0, 0, 40, 0), make_line(20, -10, 20, 10), make_line(0, 20, 10, 20), make_line(30, 10, 30, 30)])
        self.tool("trim").click(35, 0)
        self.assertTrue(any(abs(e["x1"] - 0) < 1e-6 and abs(e["x2"] - 20) < 1e-6 and e["y1"] == 0 for e in lines(self.w.project.entities)))
        self.tool("extend").click(9, 20)
        self.assertTrue(any(abs(max(e["x1"], e["x2"]) - 30) < 1e-6 and e["y1"] == 20 for e in lines(self.w.project.entities)))
        self.assertEqual(v.tool, "extend")

    def test_chamfer_fillet_2d(self):
        self.put([make_line(0, 0, 40, 0), make_line(0, 0, 0, 30)])
        v = self.tool("chamfer")
        v.params.update(chamfer_d1=5, chamfer_d2=5, chamfer_angle=0)
        v.click(20, 0)
        v.click(0, 15)
        self.assertEqual(len(lines(self.w.project.entities)), 3)
        self.put([make_line(100, 0, 140, 0), make_line(100, 0, 100, 30)])
        v = self.tool("fillet")
        v.params["fillet_r"] = 6
        v.click(120, 0)
        v.click(100, 15)
        arcs = [e for e in self.w.project.entities if e["type"] == "arc"]
        self.assertEqual(len(arcs), 1)
        self.assertAlmostEqual(arcs[0]["r"], 6)

    def test_offset_mirror_patterns(self):
        self.put(make_rect(0, 0, 40, 30))
        v = self.tool("offset")
        v.params.update(offset_d=5, offset_whole=True)
        v.click(20, 0)
        v.click(20, -3)
        self.assertEqual(len(lines(self.w.project.entities)), 8)
        lo = min(min(e["y1"], e["y2"]) for e in self.w.project.entities)
        self.assertAlmostEqual(lo, -5)

        ids = [e["id"] for e in self.w.project.entities]
        v = self.tool("mirror")
        v.selected = ids
        v.click(60, -20)
        v.click(60, 50)
        self.assertEqual(len(self.w.project.entities), 16)

        self.put([make_circle(200, 0, 2)])
        cid = self.w.project.entities[-1]["id"]
        v = self.tool("pattern_lin")
        v.selected = [cid]
        v.params.update(pat_nx=3, pat_ny=2, pat_dx=10, pat_dy=10)
        self.assertTrue(v.apply_now())
        self.assertEqual(sum(e["type"] == "circle" for e in self.w.project.entities), 6)

        self.put([make_circle(320, 0, 2)])
        cid = self.w.project.entities[-1]["id"]
        v = self.tool("pattern_circ")
        v.selected = [cid]
        v.params.update(pat_count=4, pat_angle=360)
        v.click(300, 0)
        self.assertEqual(sum(e["type"] == "circle" and math.isclose(math.dist((e["cx"], e["cy"]), (300, 0)), 20) for e in self.w.project.entities), 4)

    def test_hatch(self):
        self.put(make_rect(0, 0, 40, 30) + [make_circle(20, 15, 5)], sheet=True)
        for pattern in ("metal", "nonmetal", "concrete", "glass"):
            v = self.tool("hatch", sheet=True)
            v.params.update(hatch_pattern=pattern, hatch_step=3, hatch_angle=45)
            v.click(5, 5)
            h = self.w.project.drawing[-1]
            self.assertEqual((h["type"], h["pattern"]), ("hatch", pattern))
            self.assertEqual(len(h["boundary"]), 2, "окружность внутри — отверстие в штриховке")

    # ------------------------------------------------------------ размеры
    def test_dimensions_and_tolerance(self):
        self.put([make_line(0, 0, 40, 0), make_line(0, 0, 30, 30), make_circle(100, 0, 10)], sheet=True)
        d = self.w.project.drawing
        for t, pts, kind in (("dim_h", [(0, 0), (40, 0), (20, -10)], "horizontal"), ("dim_v", [(30, 30), (30, 0), (45, 15)], "vertical"),
                             ("dim_a", [(0, 0), (30, 30), (5, 25)], "aligned")):
            v = self.tool(t, sheet=True)
            for p in pts:
                v.click(*p)
            self.assertEqual((d[-1]["type"], d[-1]["kind"]), ("dim", kind))
        for t, typ in (("dim_dia", "diadim"), ("dim_rad", "raddim")):
            v = self.tool(t, sheet=True)
            v.click(110, 0)
            v.click(120, 10)
            self.assertEqual((d[-1]["type"], d[-1]["r"]), (typ, 10))
        v = self.tool("dim_ang", sheet=True)
        v.click(30, 0)
        v.click(20, 20)
        v.click(25, 10)
        self.assertEqual(d[-1]["type"], "angdim")
        self.assertAlmostEqual((d[-1]["a2"] - d[-1]["a1"]) % 360, 45, 3)
        v = self.tool("leader", sheet=True)
        v.params["leader_text"] = "Покрытие Хим.Окс"
        v.click(0, 0)
        v.click(20, 20)
        self.assertEqual(d[-1]["text"], "Покрытие Хим.Окс")
        v = self.tool("rough", sheet=True)
        v.params.update(rough_param="Rz", rough_value="20")
        v.click(50, 50)
        self.assertEqual((d[-1]["param"], d[-1]["value"]), ("Rz", "20"))
        # «Допуск и текст…» в панели параметров размера: допуск
        dim = next(e for e in d if e["type"] == "dim")
        Ask.answers = {"tol": "H7/g6"}
        self.w.edit_dim_form(dim["id"])
        self.assertEqual(dim["tol"], "H7/g6")
        Ask.answers = {"tol": "±0.1"}
        self.w.edit_dim_form(dim["id"])
        self.assertEqual(dim["tol"], "±0,1")
        Ask.answers = {"tol": "Q99"}
        self.w.edit_dim_form(dim["id"])
        self.assertEqual(dim["tol"], "±0,1", "неверный допуск отвергнут")
        self.assertTrue(Ask.answers.get("_warnings"))

    # ------------------------------------------------------------ лист и штамп
    def test_frame_and_stamp(self):
        for fmt in ("A4", "A3", "A2", "A1"):
            for orient in ("portrait", "landscape"):
                Ask.answers = {"format": fmt, "orient": orient}
                self.w.edit_frame()
                self.assertEqual((self.w.project.frame["format"], self.w.project.frame["orient"]), (fmt, orient))
        v = self.tool("frame", sheet=True)
        v.click(100, 50)
        self.assertEqual((self.w.project.frame["x"], self.w.project.frame["y"]), (100, 50))
        Ask.answers = {"name": "Вал", "designation": "АБВГ.715311.001", "material": "Сталь 45 ГОСТ 1050-2013", "mass": "1,2",
                       "scale": "1:2", "people.Разраб.": "Петров", "people.Пров.": "Сидоров"}
        self.w.edit_stamp("name")
        fr = self.w.project.frame
        self.assertEqual((self.w.project.name, fr["scale"], fr["people"]["Разраб."], fr["people"]["Пров."]), ("Вал", "1:2", "Петров", "Сидоров"))
        # двойной щелчок по графе штампа даёт сигнал с именем поля
        from cad.stamp import hit_cell, stamp_cells
        got = []
        self.w.sheet.stampField.connect(got.append)
        c = next(c for c in stamp_cells(fr) if c.field == "designation")
        self.assertEqual(hit_cell(fr, c.x + c.w / 2, c.y + c.h / 2).field, "designation")
        self.w.sheet.stampField.emit("designation")
        self.assertEqual(got, ["designation"])

    # ------------------------------------------------------------ 3D, дерево, история
    def _plate(self):
        self.put(make_rect(0, 0, 60, 40) + [make_circle(30, 20, 8)])
        Ask.answers = {"height": 10}
        self.w.extrude()
        return self.w.solid.volume

    def test_3d_operations(self):
        v0 = self._plate()
        self.assertAlmostEqual(v0, (60 * 40 - math.pi * 64) * 10, delta=v0 * 0.01)
        self.assertEqual(self.w.project.entities, [], "эскиз ушёл в операцию")
        self.put([make_circle(10, 10, 3)])
        Ask.answers = {"through": True}
        self.w.cut()
        self.assertLess(self.w.solid.volume, v0 - 200)
        self.put(make_rect(0, 0, 60, 40))
        Ask.answers = {"height": 5, "base": "top"}
        self.w.extrude()
        v1 = self.w.solid.volume
        Ask.answers = {"size": 1.0}
        self.w.edge3d("chamfer3d")
        self.assertLess(self.w.solid.volume, v1)
        Ask.answers = {"thickness": 1.5, "open_top": True}
        self.w.shell()
        self.assertLess(self.w.solid.volume, v1 / 2)
        Ask.answers = {"size": 0.5}
        self.w.edge3d("fillet3d")
        for f in self.w.project.features:
            self.assertIsNone(self.w.solid.statuses.get(f["id"]), f["name"])
        self.assertEqual(len(self.w.project.features), 6)

    def test_revolve_and_boolean(self):
        self.put([make_line(0, -20, 0, 20, "axis")] + make_rect(5, -10, 10, 20))
        Ask.answers = {"angle": 360}
        self.w.revolve()
        expect = math.pi * (15 ** 2 - 5 ** 2) * 20
        self.assertAlmostEqual(self.w.solid.volume, expect, delta=expect * 0.02)
        self.put([make_line(0, -20, 0, 20, "axis")] + make_rect(0, -30, 30, 25))
        Ask.answers = {"angle": 360, "op": "cut"}
        self.w.revolve()
        self.assertLess(self.w.solid.volume, expect * 0.8)
        # без осевой линии — понятная ошибка и никаких изменений
        n = len(self.w.project.features)
        self.put(make_rect(50, 0, 5, 5))
        Ask.answers = {"angle": 90}
        self.w.revolve()
        self.assertEqual(len(self.w.project.features), n)
        self.assertTrue(Ask.answers.get("_warnings"))

    def test_tree_edit_feature_and_sketch(self):
        v0 = self._plate()
        fid = self.w.project.features[0]["id"]
        Ask.answers = {"height": 20}
        self.w.edit_feature(fid)
        self.assertAlmostEqual(self.w.solid.volume, 2 * v0, delta=1)
        # редактирование эскиза операции: правка круга — модель перестраивается сразу
        self.w.edit_feature_sketch(fid)
        self.assertTrue(self.w.banner.isVisibleTo(self.w))
        circle = next(e for e in self.w.project.features[0]["sketch"] if e["type"] == "circle")
        self.w._set_field(circle["id"], "r", 4)
        self.assertAlmostEqual(self.w.solid.volume, (2400 - math.pi * 16) * 20, delta=20)
        # инструменты рисуют в эскиз операции
        v = self.tool("circle")
        v.click(10, 10)
        v.click(12, 10)
        self.assertEqual(len(self.w.project.features[0]["sketch"]), 6)
        self.assertEqual(self.w.project.entities, [])
        self.w.finish_sketch_edit()
        self.assertFalse(self.w.banner.isVisibleTo(self.w))
        # двойной щелчок по элементам дерева
        items = []

        def walk(it):
            items.append(it)
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.w.tree.topLevelItemCount()):
            walk(self.w.tree.topLevelItem(i))
        data = [it.data(0, 0x0100) for it in items]   # дерево пересобирается после каждого действия
        self.assertTrue({"feature", "fsketch", "project", "drawing", "sketch"} <= {k for k, _ in data})
        from PySide6.QtWidgets import QTreeWidgetItem
        for d in data:
            Ask.answers = {}
            it = QTreeWidgetItem(["x"])
            it.setData(0, 0x0100, d)
            self.w._on_tree_double(it, 0)
            self.w.finish_sketch_edit()

    def test_undo_redo_everything(self):
        self._plate()
        self.put([make_circle(10, 10, 3)])
        Ask.answers = {"through": True}
        self.w.cut()
        self.w.drawing_from_model()
        Ask.answers = {"name": "Плита"}
        self.w.edit_stamp()
        final = json.dumps(self.w.project.to_dict(), sort_keys=True)
        n = 0
        while self.w.history.undo():
            n += 1
        self.w.refresh()
        self.assertGreater(n, 5)
        self.assertEqual((self.w.project.features, self.w.project.entities, self.w.project.drawing), ([], [], []))
        while self.w.history.redo():
            pass
        self.w.refresh()
        self.assertEqual(json.dumps(self.w.project.to_dict(), sort_keys=True), final)

    def test_drawing_from_model_and_exports(self):
        self._plate()
        self.w.drawing_from_model()
        gen = [e for e in self.w.project.drawing if e.get("gen") == "views"]
        self.assertTrue(any(e.get("style") == "hidden" for e in gen), "отверстие на виде сверху/слева — штриховыми")
        self.assertTrue(any(e["type"] == "dim" for e in gen))
        self.assertEqual(self.w.work.currentIndex(), 1)
        for ext, fn in (("dxf", self.w.export_dxf), ("svg", self.w.export_svg), ("stl", lambda: self.w.export_mesh("stl")),
                        ("obj", lambda: self.w.export_mesh("obj"))):
            Ask.answers = {f"path.{ext}": str(TMP / f"t.{ext}")}
            fn()
            self.assertGreater((TMP / f"t.{ext}").stat().st_size, 500, ext)
        self.assertIn(b"HIDDEN", (TMP / "t.dxf").read_bytes())
        path = str(TMP / "p.k3d")
        self.w.save_project(path=path)
        before = json.dumps(self.w.project.to_dict(), sort_keys=True)
        self.w.new_project()
        self.w.open_project(path)
        self.assertEqual(json.dumps(self.w.project.to_dict(), sort_keys=True), before)
        self.assertGreater(self.w.solid.volume, 0)

    def test_ai_actions_apply(self):
        from cad import ops
        acts = [{"op": "add_rect", "x": 0, "y": 0, "w": 50, "h": 30}, {"op": "add_circle", "cx": 25, "cy": 15, "d": 10},
                {"op": "extrude", "height": 8}, {"op": "add_axis", "x1": -5, "y1": 0, "x2": -5, "y2": 10},
                {"op": "add_rect", "x": 0, "y": 0, "w": 3, "h": 3}, {"op": "revolve", "angle": 90},
                {"op": "fillet3d", "size": 0.5}, {"op": "add_dim", "x1": 0, "y1": 0, "x2": 50, "y2": 0, "tol": "h9"},
                {"op": "add_frame", "format": "A4", "orient": "portrait"}]
        log = ops.apply_actions(self.w.project, acts, self.w.sketch.target())
        self.assertTrue(all(s.startswith("✓") for s in log), log)
        prompt = ai.build_system_prompt(self.w.project, geo.build_solid(self.w.project.features), self.w.sketch.target())
        self.assertIn("revolve", prompt)
        self.assertIn("fillet3d", prompt)

    # ------------------------------------------------------------ ни одной пустой кнопки
    def test_every_ribbon_button_has_effect(self):
        w = self.w
        base = Project()
        base.entities = make_rect(0, 0, 60, 40) + [make_circle(30, 20, 8), make_line(-10, -10, -10, 50, "axis"),
                                                  make_line(100, 0, 120, 0), make_line(120.5, 0, 120.5, 20)]
        ops_mod = __import__("cad.ops", fromlist=["create_feature"])
        ops_mod.create_feature(base, "extrude", height=10)
        base.entities = make_rect(0, 0, 60, 40) + [make_circle(30, 20, 8), make_line(-10, -10, -10, 50, "axis"),
                                                  make_line(100, 0, 120, 0), make_line(120.5, 0, 120.5, 20)]
        snap = base.snapshot()
        for ext in ("dxf", "svg", "stl", "obj"):
            Ask.answers[f"path.{ext}"] = str(TMP / f"btn.{ext}")
        paths = dict(Ask.answers)

        def reset():
            w.project.restore(snap)
            w.history.reset() if hasattr(w.history, "reset") else None
            w.edit_fid = None
            w.ai_dock.hide()           # правые панели закрыты: «ИИ-помощник», «Каталог», «ЕСКД» открывают каждая свою
            w.library_dock.hide()
            w.eskd_dock.hide()
            w.sketch.iso = w.sheet.iso = False       # переключатели новых кнопок — в исходное состояние
            w.view3d.set_ortho(False)
            w.view3d.display, w.view3d.show_dims = "shaded", False
            w.library_panel.search.clear()
            w.library_panel.tree.setCurrentItem(None)
            w.work.setCurrentIndex(0)
            w.sketch.set_tool("frame")   # инструмент, которого нет на ленте эскиза: любая кнопка его сменит
            w.sheet.set_tool("line")
            w.refresh(fit3d=True)
            w.sketch.selected = [w.project.entities[4]["id"]]
            w.sketch.scale(1.7, 1.7)
            w.sheet.scale(1.7, 1.7)
            w.view3d.setCameraPosition(distance=777, elevation=45, azimuth=45)
            for ext in ("dxf", "svg", "stl", "obj"):
                (TMP / f"btn.{ext}").unlink(missing_ok=True)
            Ask.answers = dict(paths)

        def state():
            o = w.view3d.opts
            return (w.work.currentIndex(), w.sketch.tool, w.sheet.tool, json.dumps(w.project.to_dict(), sort_keys=True),
                    w.ai_dock.isVisible(), w.library_dock.isVisible(), w.library_panel.current_key(),
                    len(Ask.answers.get("_forms", [])), len(Ask.answers.get("_warnings", [])),
                    tuple(p.name for p in TMP.glob("btn.*")), round(o["azimuth"], 3), round(o["elevation"], 3), round(o["distance"], 3),
                    round(w.sketch.transform().m11(), 6), round(w.sheet.transform().m11(), 6),
                    w.eskd_dock.isVisible(), w.sheet.iso, w.view3d.ortho, w.view3d.display, w.view3d.show_dims)

        dead = []
        for name, b in w.ribbon_actions.items():
            if name == "Привязки":   # кнопка-меню: проверяется в test_snaps через её пункты
                self.assertEqual(len(b.menu().actions()), 7)
                continue
            reset()
            s0 = state()
            b.click()
            APP.processEvents()
            if state() == s0:
                dead.append(name)
        reset()
        self.assertEqual(dead, [], "кнопки без эффекта")
        self.assertGreaterEqual(len(w.ribbon_actions), 66)

    # ------------------------------------------------------------ формат полотна
    def _drawing_json(self):
        return json.dumps(self.w.project.drawing, sort_keys=True)

    def _desk_pixel(self):
        """Цвет левого верхнего угла окна листа: на листе — рабочий стол, на фрагменте — бумага."""
        self.w.sheet.viewport().update()
        APP.processEvents()
        return self.w.sheet.grab().toImage().pixelColor(3, 3).lightness()

    def test_canvas_fragment_a4_a3_fragment(self):
        w = self.w
        w.set_canvas("fragment")
        self.put(make_rect(30, 70, 100, 60) + [make_circle(80, 100, 15)], sheet=True)
        d = self.tool("dim_h", sheet=True)
        for pt in [(30, 70), (130, 70), (80, 60)]:
            d.click(*pt)
        Ask.answers = {"name": "Корпус", "people.Разраб.": "Иванов"}
        w.edit_stamp("name")
        before = self._drawing_json()
        self.assertEqual(len(w.project.drawing), 6)
        sheet_items = len(w.sheet.scene().items())

        # фрагмент: ни рамки, ни ограничения прокрутки, сетка во всё окно
        self.assertIsNone(w.sheet.sheet_bounds())
        self.assertGreater(w.sheet.sceneRect().width(), 1e5)
        self.assertGreater(self._desk_pixel(), 200, "фрагмент: бумага во всё окно")

        for mode, size in (("A4P", (210, 297)), ("A3L", (420, 297)), ("A4L", (297, 210)), ("A3P", (297, 420))):
            w.set_canvas(mode)
            b = w.sheet.sheet_bounds()
            self.assertEqual((b.width(), b.height()), size, mode)
            self.assertEqual(w.project.canvas_mode(), mode)
            self.assertEqual(w.canvas_box.currentData(), mode)
            self.assertTrue(w.canvas_actions[mode].isChecked())
            self.assertEqual(self._drawing_json(), before, "начерченное не меняется при смене формата")
            self.assertLess(w.sheet.sceneRect().width(), max(size) * 5, "прокрутка ограничена листом")
            self.assertGreater(len(w.sheet.scene().items()), sheet_items + 50, "рамка и штамп нарисованы")
            vis = w.sheet.mapToScene(w.sheet.viewport().rect()).boundingRect()
            self.assertTrue(vis.contains(b), "лист вписан в окно")
            self.assertLess(vis.width() * vis.height(), b.width() * b.height() * 4, "и занимает окно, а не точку")
            self.assertLess(self._desk_pixel(), 140, "вокруг листа — тёмный рабочий стол")
            for dx, dy in ((1e6, 0), (-1e6, 0), (0, 1e6), (0, -1e6)):
                w.sheet.scroll_by(dx, dy)
                on_screen = w.sheet.viewportTransform().mapRect(b).intersected(QRectF(w.sheet.viewport().rect()))
                self.assertGreaterEqual(min(on_screen.width(), on_screen.height()), 20, "лист не уходит из окна")
            w.sheet.fit_sheet()
            self.assertEqual(json.loads((TMP / "config.json").read_text(encoding="utf-8"))["canvas"], mode)
        from cad.stamp import frame_rect
        fx, fy, fw, fh = frame_rect(w.project.frame)
        self.assertEqual((fx, fy, fw, fh), (20, 5, 297 - 25, 420 - 10), "поля ГОСТ 2.104: 20 слева, 5 с остальных")

        w.set_canvas("fragment")
        self.assertIsNone(w.sheet.sheet_bounds())
        self.assertEqual(len(w.sheet.scene().items()), sheet_items, "рамка и штамп скрыты")
        self.assertEqual(self._drawing_json(), before)
        self.assertEqual((w.project.name, w.project.frame["people"]["Разраб."]), ("Корпус", "Иванов"), "данные штампа не потеряны")
        self.assertGreater(self._desk_pixel(), 200)

        # отмена возвращает прежний формат, выбор в списке и в меню работает так же
        w.undo()
        self.assertEqual(w.project.canvas_mode(), "A3P")
        w.canvas_box.setCurrentIndex(w.canvas_box.findData("A4L"))
        self.assertEqual(w.project.canvas_mode(), "A4L")
        w.canvas_actions["fragment"].trigger()
        self.assertEqual(w.project.canvas_mode(), "fragment")

        # формат хранится в .k3d; новый документ открывается с последним выбранным
        w.set_canvas("A3L")
        path = str(TMP / "canvas.k3d")
        w.save_project(path=path)
        w.new_project()
        self.assertEqual(w.project.canvas_mode(), "A3L", "последний режим из config.json")
        w.set_canvas("fragment")
        w.open_project(path)
        self.assertEqual((w.project.canvas_mode(), self._drawing_json()), ("A3L", before))

    def test_stamp_double_click_edits_field(self):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtTest import QTest
        from cad.stamp import stamp_cells
        w = self.w
        w.set_canvas("A4P")
        v = self.tool("select", sheet=True)
        cell = next(c for c in stamp_cells(w.project.frame) if c.field == "designation")
        pos = v.mapFromScene(QPointF(cell.x + cell.w / 2, cell.y + cell.h / 2))
        Ask.answers = {"designation": "АБВГ.301122.005", "material": "Сталь 45"}
        QTest.mouseDClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        self.assertEqual((w.project.designation, w.project.material), ("АБВГ.301122.005", "Сталь 45"))
        self.assertIn("Основная надпись (ГОСТ 2.104, форма 1)", Ask.answers["_forms"])
        path = str(TMP / "stamp.k3d")
        w.save_project(path=path)
        self.assertEqual(Project.load(path).designation, "АБВГ.301122.005")

    def test_export_with_and_without_frame(self):
        w = self.w
        w.set_canvas("A4P")
        self.put([make_circle(100, 150, 20)], sheet=True)
        stamp_text = "Разраб.".encode("cp1251")
        for with_frame in (True, False):
            Ask.answers = {"with_frame": with_frame, "path.dxf": str(TMP / f"f{with_frame}.dxf"), "path.svg": str(TMP / f"f{with_frame}.svg")}
            w.export_dxf()
            w.export_svg()
            self.assertEqual(stamp_text in (TMP / f"f{with_frame}.dxf").read_bytes(), with_frame)
            self.assertEqual("Разраб." in (TMP / f"f{with_frame}.svg").read_text(encoding="utf-8"), with_frame)
            self.assertIn("Экспорт в DXF", Ask.answers["_forms"])
        w.set_canvas("fragment")
        Ask.answers = {"path.dxf": str(TMP / "frag.dxf")}
        w.export_dxf()
        self.assertNotIn("_forms", Ask.answers, "на фрагменте вопроса о рамке нет")
        self.assertNotIn(stamp_text, (TMP / "frag.dxf").read_bytes())

    def test_ai_gets_canvas_and_writes_to_sheet(self):
        w = self.w
        w.set_canvas("A4P")
        w.work.setCurrentIndex(1)
        w._ai_layer = "drawing"
        prompt = ai.build_system_prompt(w.project, w.solid, w._ai_view().target(), "drawing")
        self.assertIn("свободно_над_штампом", prompt)
        self.assertIn("[25.0, 65.0, 200.0, 287.0]", prompt)
        from cad import ops
        ops.apply_actions(w.project, [{"op": "add_rect", "x": 40, "y": 100, "w": 50, "h": 30}], w._ai_view().target())
        self.assertEqual(len(w.project.drawing), 4)
        self.assertEqual(w.project.entities, [])
        w.set_canvas("fragment")
        self.assertIn("черти свободно от (0,0)", ai.build_system_prompt(w.project, w.solid, w.project.drawing, "drawing"))
        self.assertIn("эскиз для 3D", ai.build_system_prompt(w.project, w.solid, w.project.entities, "sketch"))

    # ------------------------------------------------------------ 3D-гизмо
    def test_gizmo_clicks_drag_and_buttons(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtTest import QTest
        from cad.view3d import AXIS_VIEW, VIEWS
        w = self.w
        w.work.setCurrentIndex(2)
        v, g = w.view3d, w.view3d.gizmo
        APP.processEvents()
        self.assertTrue(g.isVisible())
        self.assertGreater(g.x(), v.width() / 2, "гизмо в правом верхнем углу")
        self.assertLess(g.y(), 40)

        def cam():
            return round(v.opts["azimuth"] % 360, 3), round(v.opts["elevation"], 3)

        # шары осей: каждый открывает свой вид
        for axis, view in AXIS_VIEW.items():
            v.set_view("iso")
            ball = next(p for a, p, r, z in g.balls() if a == axis)
            QTest.mouseClick(g, Qt.LeftButton, Qt.NoModifier, ball.toPoint())
            self.assertTrue(v.animating(), "переход плавный, а не скачком")
            v.finish_animation()
            az, el = VIEWS[view]
            self.assertEqual(cam(), (round(az % 360, 3), el), view)

        # грани куба, видимые в изометрии
        v.set_view("iso")
        faces = [(n, poly) for n, poly, z in g.faces() if z > 0.3]
        self.assertEqual(len(faces), 3)
        for n, poly in faces:
            v.set_view("iso")
            c = poly.boundingRect().center()
            self.assertEqual(g.hit(c), n)
            QTest.mouseClick(g, Qt.LeftButton, Qt.NoModifier, c.toPoint())
            v.finish_animation()
            az, el = VIEWS[AXIS_VIEW[n]]
            self.assertEqual(cam(), (round(az % 360, 3), el))

        # настоящая анимация по таймеру доходит до конца
        v.set_view("iso")
        v.animate_to("top")
        QTest.qWait(v.anim_ms + 200)
        self.assertFalse(v.animating())
        self.assertEqual(cam()[1], 90)

        # куб вращается вместе со сценой
        v.set_view("iso")
        iso_balls = [(round(p.x()), round(p.y())) for _, p, _, _ in g.balls()]
        v.set_view("front")
        self.assertNotEqual(iso_balls, [(round(p.x()), round(p.y())) for _, p, _, _ in g.balls()])

        # перетаскивание за гизмо вращает орбиту и не считается щелчком
        v.set_view("iso")
        az0 = v.opts["azimuth"]
        start = QPointF(20, 20)
        QApplication.sendEvent(g, QMouseEvent(QEvent.MouseButtonPress, start, start, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        for i in range(1, 6):
            pt = QPointF(20 + i * 8, 20 + i * 2)
            QApplication.sendEvent(g, QMouseEvent(QEvent.MouseMove, pt, pt, Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        QApplication.sendEvent(g, QMouseEvent(QEvent.MouseButtonRelease, pt, pt, Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        self.assertFalse(v.animating())
        self.assertAlmostEqual(v.opts["azimuth"], az0 - 40 * 1.2, 3)
        self.assertNotEqual(v.opts["elevation"], 28)

        # перспектива / ортогональная проекция
        vp = (0, 0, v.width(), v.height())
        self.assertFalse(v.ortho)
        self.assertEqual(v.projectionMatrix(vp, vp).row(3).w(), 0, "перспектива")
        v.proj_btn.click()
        self.assertTrue(v.ortho and v.proj_btn.isChecked())
        self.assertEqual(v.projectionMatrix(vp, vp).row(3).w(), 1, "ортогональная")
        v.proj_btn.click()
        self.assertFalse(v.ortho)

        # центрировать модель
        self._plate()
        w.work.setCurrentIndex(2)
        from PySide6.QtGui import QVector3D
        v.opts["center"] = QVector3D(500, 500, 500)
        v.setCameraPosition(distance=5000)
        v.home_btn.click()
        c = v.opts["center"]
        self.assertEqual((round(c.x(), 3), round(c.y(), 3), round(c.z(), 3)), (30, 20, 5))
        self.assertLess(v.opts["distance"], 500)

    # ------------------------------------------------------------ зум колесом и тема
    @staticmethod
    def _wheel(widget, pos: QPointF, dy: int):
        ev = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, dy),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(widget, ev)

    def test_wheel_zoom_keeps_point_under_cursor(self):
        import random
        rnd = random.Random(7)
        w = self.w
        # фрагмент: любые точки окна, приближение и отдаление
        v = self.view(sheet=True)
        for pos, dy in [(QPointF(37.5, 61.25), 120), (QPointF(500, 300), -120), (QPointF(820, 40), 240), (QPointF(5, 600), -360)]:
            a = v.to_scene(pos)
            s0 = abs(v.transform().m11())
            self._wheel(v.viewport(), pos, dy)
            b = v.to_scene(pos)
            self.assertNotAlmostEqual(abs(v.transform().m11()), s0, 3, "масштаб изменился")
            self.assertLess(max(abs(a.x() - b.x()), abs(a.y() - b.y())), 1e-3, f"фрагмент {pos}")
        # листы с ограниченной прокруткой: случайные видимые точки листа
        for mode in ("A4P", "A3L"):
            w.set_canvas(mode)
            sb, vr = v.sheet_bounds(), v.viewport().rect()
            checked = 0
            for _ in range(120):
                pos = v.viewportTransform().map(QPointF(rnd.uniform(sb.left(), sb.right()), rnd.uniform(sb.top(), sb.bottom())))
                if not vr.contains(pos.toPoint()):
                    v.fit_sheet()
                    continue
                a = v.to_scene(pos)
                self._wheel(v.viewport(), pos, rnd.choice((120, -120, 240, -240)))
                b = v.to_scene(pos)
                self.assertLess(max(abs(a.x() - b.x()), abs(a.y() - b.y())), 1e-3, f"{mode} {pos}")
                checked += 1
            self.assertGreater(checked, 60, mode)
        # 3D: точка под курсором в плоскости центра остаётся на месте, вид не уходит в сторону
        w.work.setCurrentIndex(2)
        v3 = w.view3d
        v3.set_view("iso")
        APP.processEvents()
        for ortho in (False, True):
            v3.set_ortho(ortho)
            for pos, dy in ((QPointF(120, 90), 120), (QPointF(v3.width() - 40, v3.height() - 30), -240), (QPointF(300, 200), 360)):
                a, d0 = v3.point_under(pos), v3.opts["distance"]
                self._wheel(v3, pos, dy)
                self.assertNotAlmostEqual(v3.opts["distance"], d0, 3)
                self.assertLess(float(abs(v3.point_under(pos) - a).max()), 1e-3, f"3D {pos} орто={ortho}")
        v3.set_ortho(False)

    def test_theme_kept_across_tabs_canvas_and_restart(self):
        from cad.themes import qss
        w = self.w
        try:
            w.show_appearance()
            w.appearance_dlg.mode_buttons["classic-dark"].click()
            w.appearance_dlg.close()
            saved = json.loads((TMP / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["active_theme"], "classic-dark", "выбор темы сразу записан")
            self.assertEqual(saved["appearance"]["mode"], "classic-dark")
            dark = w.themes.theme
            for tab, mode in ((0, None), (2, None), (1, "A4P"), (1, "fragment"), (0, None), (2, None), (1, "A3L")):
                w.work.setCurrentIndex(tab)
                if mode:
                    w.set_canvas(mode)
                APP.processEvents()
                self.assertIs(w.themes.theme, dark, (tab, mode))
                for v in (w.sketch, w.sheet, w.view3d):
                    self.assertIs(v.theme, dark, f"{type(v).__name__} после {(tab, mode)}")
                self.assertLess(w.sheet.col["paper1"].lightness(), 80)
                self.assertEqual(APP.styleSheet(), qss(dark))
            # другое окно со старым снимком настроек пишет свой ключ — тема в файле остаётся
            stale = dict(w.cfg, appearance={"mode": "classic-light"}, active_theme="classic-light")
            w.cfg, real = stale, w.cfg
            w.cfg["export_frame"] = False
            w._save_cfg("export_frame")
            w.cfg = real
            saved = json.loads((TMP / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["active_theme"], "classic-dark", "чужой снимок не затёр тему")
            self.assertFalse(saved["export_frame"])
            # «перезапуск»: новое окно читает config.json и сразу тёмное, ещё до первого переключения
            w2 = MainWindow()
            try:
                self.assertEqual(w2.themes.mode, "classic-dark")
                self.assertLess(w2.sketch.col["paper1"].lightness(), 80)
                self.assertLess(w2.view3d.opts["bgcolor"][0], 0.3)
            finally:
                w2.dirty = False
                w2.close()
            # битый или неполный файл: тема по active_theme
            (TMP / "config.json").write_text(json.dumps({"active_theme": "classic-dark"}), encoding="utf-8")
            from cad.themes import ThemeManager
            cfg = ai.load_config()
            self.assertEqual(ThemeManager(cfg.get("appearance", {}), cfg.get("active_theme")).mode, "classic-dark")
        finally:
            w.themes.set(mode="classic-light")
            ai.update_config({"export_frame": True})


    def test_ai_and_library_open_their_own_panels(self):
        """«ИИ-помощник» (лента, меню, Ctrl+I) всегда выводит чат, а не соседнюю вкладку «Библиотека»; и наоборот."""
        w = self.w
        ai_btn, lib_btn = w.ribbon_actions["ИИпомощник"], w.ribbon_actions["Каталог элементов"]
        w.show_ai()
        self.assertIs(w.front_dock(), w.ai_dock)
        for press in (ai_btn.click, ai_btn.click, w.ai_action.trigger):   # повторное нажатие не прячет помощника
            press()
            APP.processEvents()
            self.assertIs(w.front_dock(), w.ai_dock, "впереди ИИ-помощник")
            self.assertIs(w.ai_dock.widget(), w.ai_panel)
        self.assertTrue(w.ai_panel.isAncestorOf(w.chat_input) and w.ai_panel.isAncestorOf(w.ai_settings_btn), "чат и настройки ключа")
        for press in (lib_btn.click, lib_btn.click):
            press()
            APP.processEvents()
            self.assertIs(w.front_dock(), w.library_dock, "впереди библиотека")
        menu = next(a.menu() for a in w.menuBar().actions() if a.text() == "&Библиотека")
        ai_menu = next(a.menu() for a in w.menuBar().actions() if a.text() == "&ИИ")
        ai_menu.actions()[[a.text() for a in ai_menu.actions()].index("ИИ-помощник")].trigger()
        self.assertIs(w.front_dock(), w.ai_dock)
        menu.actions()[0].trigger()                 # «Каталог элементов и шаблонов»
        self.assertIs(w.front_dock(), w.library_dock)
        w.ai_dock.hide()                            # закрыт крестиком — кнопка открывает снова
        ai_btn.click()
        self.assertIs(w.front_dock(), w.ai_dock)
        self.assertEqual(w.ai_action.shortcut(), QKeySequence("Ctrl+I"))

    def test_about_has_no_local_paths(self):
        w = self.w
        box = w.show_about(run=False)
        text = box.text()
        self.assertIn("Черчение 3D", text)
        self.assertIn("Черчение 3D", box.windowTitle())
        self.assertNotIn("ReCAD", text)
        for model in ("gemini-2.5-flash", "google/gemini-2.5-flash:free", "llama-4-scout", "Vision"):
            self.assertIn(model, text, "памятка о моделях с поддержкой фото")
        self.assertIn("Черчение 3D", w.windowTitle())
        from cad.dialogs import AISettingsDialog

        dlg = AISettingsDialog(w.cfg, w)
        for model in ("gemini-2.5-flash", "llama-4-scout"):
            self.assertIn(model, dlg.vision_note.text(), "памятка под полем модели")
        dlg.deleteLater()
        for bad in ("Файл настроек", "config.json", str(ai.config_path().parent), ":\\"):
            self.assertNotIn(bad, text)

    # ------------------------------------------------------------ библиотека ГОСТ / СПДС / ЕСКД
    def test_library_all_categories_icons_search(self):
        w = self.w
        panel = w.library_panel
        for sec in ("electro", "build", "mech"):
            blocks = [b for b in library.BLOCKS.values() if b.section == sec]
            tpls = [t for t in library.TEMPLATES.values() if t.section == sec]
            self.assertGreaterEqual(len(blocks), 10, sec)
            self.assertGreaterEqual(len(tpls), 2, sec)
        must = {"qf1", "qf3", "qs", "qd", "fu", "tm", "ta", "pi", "m", "pe", "socket_open", "socket_hidden", "switch_light",
                "lamp", "cable_joint", "pole_rc_plan", "pole_rc_side", "pole_wood_side", "traverse", "ins_pin", "ins_susp",
                "clamp_anchor", "clamp_support", "ground_loop", "axis_mark", "wall", "partition", "door", "window", "stair",
                "column", "level", "vent", "sink", "bolt_front", "bolt_top", "nut_front", "nut_top", "washer_front",
                "washer_top", "tube_sq", "channel", "angle", "ibeam", "bearing", "flange", "weld"}
        self.assertEqual(must - set(library.BLOCKS), set())
        for b in library.BLOCKS.values():
            it = panel.items[("block", b.id)]
            self.assertFalse(it.icon(0).isNull(), b.id)
            img = it.icon(0).pixmap(30, 30).toImage()
            inked = sum(img.pixelColor(x, y).alpha() > 60 for x in range(img.width()) for y in range(img.height()))
            self.assertGreater(inked, 3, f"значок {b.id} не пустой")
            for rot in (0, 90, 180, 270):
                ents = library.instantiate(b.id, 100, 50, rot, 2)
                self.assertEqual(len({e["blk"] for e in ents}), 1)
        for t in library.TEMPLATES.values():
            self.assertFalse(panel.items[("template", t.id)].icon(0).isNull())
            p = Project()
            library.load_template(p, t.id)
            self.assertEqual(p.canvas_mode(), t.canvas, t.id)
            from cad.stamp import frame_rect
            fx, fy, fw, fh = frame_rect(p.frame)
            x0, y0, x1, y1 = library.bounds(p.drawing)
            self.assertTrue(fx - 0.5 <= x0 and x1 <= fx + fw + 0.5 and fy - 0.5 <= y0 and y1 <= fy + fh + 0.5, f"{t.id} внутри рамки")
            texts = [e["text"] for e in p.drawing if e["type"] == "text"]
            self.assertTrue(texts, t.id)
        heads = {"single_line_a3": ["Группа", "Мощность,", "Ток,", "Кабель"], "spec_a4": ["Поз.", "Обозначение", "Наименование", "Кол."],
                 "arch_plan_a3": ["Экспликация помещений", "Площадь,"], "overhead_line_a3": ["Ведомость опор и проводов", "ОП-5"]}
        for tid, words in heads.items():
            p = Project()
            library.load_template(p, tid)
            texts = " ".join(e["text"] for e in p.drawing if e["type"] == "text")
            for word in words:
                self.assertIn(word, texts, tid)
        # поиск: строка панели фильтрует дерево
        for query, expect in (("автомат", {"qf1", "qf3"}), ("опора", {"pole_rc_plan", "pole_rc_side", "pole_wood_side"}),
                              ("изолятор", {"ins_pin", "ins_susp"}), ("дверь", {"door"}), ("швеллер", {"channel"})):
            panel.search.setText(query)
            shown = {k for kind, k in panel.visible_keys() if kind == "block"}
            self.assertTrue(expect <= shown, (query, shown))
            self.assertLess(len(shown), 8, f"«{query}» отбирает, а не показывает всё")
            self.assertIsNotNone(panel.current_key(), "первое найденное выделено")
        panel.search.setText("однолинейная")
        self.assertIn(("template", "single_line_a3"), panel.visible_keys())
        panel.search.clear()
        self.assertEqual(len(panel.visible_keys()), len(panel.items))

    def test_insert_block_with_rotation_scale_and_label(self):
        from PySide6.QtTest import QTest
        w = self.w
        w.set_canvas("A4P")
        w.insert_block("qf1")
        v = w.cur2d()
        self.assertIs(v, w.sheet)
        self.assertEqual(v.tool, "block")
        self.assertEqual(w.tool_panel.edits["blk_label"].text(), "QF1")
        w._hotkey(v, "rect")                          # R — поворот, не прямоугольник
        QTest.keyClick(v, Qt.Key_Space)               # Пробел — ещё 90°
        self.assertEqual(v.tool, "block")
        self.assertEqual(v.params["blk_rot"], 180)
        self.assertEqual(w.tool_panel.spins["blk_rot"].value(), 180)
        pos = QPointF(300, 250)
        self._wheel_ctrl(v, pos, 120)                 # Ctrl + колесо — масштаб элемента, а не вида
        self.assertAlmostEqual(v.params["blk_scale"], 1.1, 6)
        v.params["blk_scale"] = 2.0
        # призрак у курсора, привязка к сетке
        sp = v.mapFromScene(QPointF(80.3, 150.2))
        QTest.mouseMove(v.viewport(), sp)
        ghost = v.block_ghost()
        self.assertTrue(ghost)
        n0 = len(w.project.drawing)
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, sp)
        added = w.project.drawing[n0:]
        self.assertTrue(added)
        inst = added[0]["blk"]
        self.assertTrue(all(e["blk"] == inst for e in added))
        x, y = v.cursor
        ports = library.ports_world("qf1", x, y, 180, 2)
        self.assertAlmostEqual(ports["выход"][0], x, 6)
        self.assertAlmostEqual(ports["выход"][1], y + 40, 6, "повёрнут на 180° и вдвое крупнее: выход на 40 мм выше")
        ends = {(round(e[k1], 3), round(e[k2], 3)) for e in added if e["type"] == "line" for k1, k2 in (("x1", "y1"), ("x2", "y2"))}
        self.assertIn((round(x, 3), round(y + 40, 3)), ends, "выход нарисован там, где говорит каталог")
        self.assertEqual(library.label_of(w.project.drawing, inst), "QF1")
        self.assertEqual(v.params["blk_label"], "QF2", "следующий — со следующим номером")
        v.click(x + 30, y)
        second = w.project.drawing[n0 + len(added):]
        self.assertEqual(library.label_of(w.project.drawing, second[0]["blk"]), "QF2")
        # выбор щелчком — весь элемент; дерево — один узел; маркировка правится
        QTest.keyClick(v, Qt.Key_Escape)
        w.set_tool("select")
        v.mousePressEvent  # noqa: B018
        line = next(e for e in added if e["type"] == "line")
        v.select([])
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, v.mapFromScene(QPointF((line["x1"] + line["x2"]) / 2, (line["y1"] + line["y2"]) / 2)))
        self.assertEqual(set(v.selected), {e["id"] for e in added})
        nodes = [w.tree.topLevelItem(0)]
        texts = []
        while nodes:
            it = nodes.pop()
            texts.append(it.text(0))
            nodes += [it.child(i) for i in range(it.childCount())]
        self.assertTrue(any(t.startswith("⊞  Автоматический выключатель 1P  QF1") for t in texts), texts)
        Ask.answers = {"label": "QF7"}
        w.edit_entity(line["id"])
        self.assertEqual(library.label_of(w.project.drawing, inst), "QF7")
        w.delete_selected()
        self.assertFalse(any(e.get("blk") == inst for e in w.project.drawing), "удалён целиком")
        w.undo()
        self.assertTrue(any(e.get("blk") == inst for e in w.project.drawing))
        # экспорт: маркировка уходит в DXF текстом
        from cad.export2d import to_dxf
        self.assertIn("QF7".encode("cp1251"), to_dxf(w.project, with_frame=False))

    @staticmethod
    def _wheel_ctrl(widget, pos, dy):
        ev = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, dy),
                         Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(widget.viewport(), ev)

    def test_user_library_save_reuse_delete(self):
        w = self.w
        (TMP / "user_library.json").unlink(missing_ok=True)
        library.reload_user()
        w.library_panel.rebuild()
        self.put(make_rect(40, 30, 20, 10, "main") + [make_circle(50, 35, 3)], sheet=True)
        v = w.sheet
        v.select([e["id"] for e in w.project.drawing])
        Ask.answers = {"name": "Мой кронштейн", "keywords": "кронштейн опорный"}
        w.save_to_library()
        data = json.loads((TMP / "user_library.json").read_text(encoding="utf-8"))
        self.assertEqual([b["name"] for b in data["blocks"]], ["Мой кронштейн"])
        bid = data["blocks"][0]["id"]
        self.assertEqual(library.bounds(data["blocks"][0]["entities"])[:2], (0.0, 0.0), "точка вставки — левый нижний угол")
        self.assertIn(("block", bid), w.library_panel.items, "появился в «Моих элементах»")
        library.reload_user()                       # как после перезапуска: читается из файла
        self.assertEqual(library.get_block(bid).name, "Мой кронштейн")
        w.library_panel.search.setText("кронштейн")
        self.assertIn(("block", bid), w.library_panel.visible_keys())
        w.library_panel.search.clear()
        w.insert_block(bid)
        n0 = len(w.project.drawing)
        v.click(100, 100)
        placed = w.project.drawing[n0:]
        self.assertEqual(len(placed), 5)
        self.assertEqual(tuple(round(c, 3) for c in library.bounds(placed)[:2]), (100.0, 100.0))
        w.delete_user_block(bid)
        self.assertNotIn(bid, library.user_blocks())
        self.assertEqual(json.loads((TMP / "user_library.json").read_text(encoding="utf-8"))["blocks"], [])
        w.set_tool("select")
        w.sheet.select([])
        Ask.answers = {}
        w.save_to_library()
        self.assertIn("Выделите", " ".join(Ask.answers.get("_warnings", [])), "без выделения — подсказка")

    def test_templates_open_from_panel_and_menu(self):
        w = self.w
        w.library_panel.select("template", "arch_plan_a3")
        w.library_panel.go.click()
        self.assertEqual(w.project.canvas_mode(), "A3L")
        self.assertEqual(w.project.name, "План этажа")
        self.assertEqual(w.work.currentIndex(), 1)
        self.assertEqual(w.project.frame["scale"], "1:50")
        self.assertTrue(any(e.get("blk_id") == "axis_mark" for e in w.project.drawing))
        menu = next(a.menu() for a in w.menuBar().actions() if a.text() == "&Библиотека")
        titles = [a.text() for a in menu.actions()]
        self.assertIn("Шаблоны листов", titles)
        self.assertIn("Элементы и УГО", titles)
        self.assertIn("Сохранить выделенное в библиотеку…", titles)
        tm = next(a.menu() for a in menu.actions() if a.text() == "Шаблоны листов")
        count = sum(len(sm.menu().actions()) for sm in tm.actions())
        self.assertEqual(count, len(library.TEMPLATES))
        mech = next(a.menu() for a in tm.actions() if "Машиностроение" in a.text())
        mech.actions()[0].trigger()                  # «Чертёж детали в 3 проекциях — А4»
        self.assertEqual(w.project.canvas_mode(), "A4P")
        self.assertTrue(w.project.features, "деталь построена")
        self.assertGreater(sum(1 for e in w.project.drawing if e.get("gen") == "views"), 20, "три вида по модели")

    def test_ai_uses_library_blocks(self):
        w = self.w
        system = ai.build_system_prompt(w.project, w.solid, w.sketch.target(), "drawing")
        for word in ("insert_library_block", "load_template", "qf1:", "pole_rc_plan:", "door:", "single_line_a4"):
            self.assertIn(word, system)
        # «Однолинейная схема с вводным автоматом, счётчиком и 3 отходящими линиями»
        w.work.setCurrentIndex(1)
        w._ai_layer = "drawing"
        acts = [{"op": "load_template", "template_id": "single_line_a4"}, {"op": "insert_library_block", "block_id": "qf3", "x": 150, "y": 250, "label": "QF9"},
                {"op": "add_line", "x1": 150, "y1": 230, "x2": 150, "y2": 220}, {"op": "insert_library_block", "block_id": "m", "x": 150, "y": 220, "rotation": 0}]
        w._ai_done({"message": "Готово", "actions": acts, "raw": "{}"})
        self.assertEqual(w.project.canvas_mode(), "A4P")
        self.assertEqual(w.work.currentIndex(), 1)
        self.assertIn("QF9", [e["text"] for e in w.project.drawing if e["type"] == "text"])
        log = w.chat_view.toPlainText()
        self.assertNotIn("✗", log)
        # «Сделай схему участка ВЛ из 5 опор с пролётами по 35 метров»
        w.new_project()
        w.work.setCurrentIndex(1)
        acts = []
        for k in range(5):
            acts.append({"op": "insert_library_block", "block_id": "pole_rc_plan", "x": 20 + 35 * k, "y": 50, "label": f"ОП-{k + 1}"})
            if k:
                acts += [{"op": "add_line", "x1": 22 + 35 * (k - 1), "y1": 50, "x2": 18 + 35 * k, "y2": 50},
                         {"op": "add_text", "x": 2.5 + 35 * k, "y": 44, "text": "35 м", "align": "center"}]
        w._ai_done({"message": "ВЛ", "actions": acts, "raw": "{}"})
        poles = {e["blk"] for e in w.project.drawing if e.get("blk_id") == "pole_rc_plan"}
        self.assertEqual(len(poles), 5)
        self.assertEqual(sum(1 for e in w.project.drawing if e["type"] == "text" and e["text"] == "35 м"), 4)
        # «Нарисуй план гаража 6×4 м с воротами и окном» (М1:100: 1 м = 10 мм)
        w.new_project()
        w.work.setCurrentIndex(1)
        acts = [{"op": "add_wall", "x1": 0, "y1": 0, "x2": 15, "y2": 0}, {"op": "insert_library_block", "block_id": "gate", "x": 15, "y": 0},
                {"op": "add_wall", "x1": 45, "y1": 0, "x2": 60, "y2": 0}, {"op": "add_wall", "x1": 60, "y1": 0, "x2": 60, "y2": 40},
                {"op": "add_wall", "x1": 60, "y1": 40, "x2": 37.5, "y2": 40}, {"op": "insert_library_block", "block_id": "window", "x": 22.5, "y": 40},
                {"op": "add_wall", "x1": 22.5, "y1": 40, "x2": 0, "y2": 40}, {"op": "add_wall", "x1": 0, "y1": 40, "x2": 0, "y2": 0}]
        w._ai_done({"message": "Гараж", "actions": acts, "raw": "{}"})
        self.assertEqual(sum(1 for e in w.project.drawing if e["type"] == "hatch"), 6, "шесть участков стен со штриховкой")
        self.assertEqual({e.get("blk_id") for e in w.project.drawing if e.get("blk")}, {"gate", "window"})
        self.assertNotIn("✗", w.chat_view.toPlainText())
        bad = ops_log = __import__("cad.ops", fromlist=["apply_actions"]).apply_actions(
            w.project, [{"op": "insert_library_block", "block_id": "нет_такого"}, {"op": "load_template", "template_id": "x"}], w.project.drawing)
        self.assertTrue(all(s.startswith("✗") for s in bad), ops_log)


if __name__ == "__main__":
    unittest.main()
