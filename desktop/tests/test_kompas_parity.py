"""Kompas-3D Parity Test: параметрическое редактирование так, как его ведёт КОМПАС-3D.

1. Отрезок: длина L от начала по прежнему углу, поворот α вокруг начала, Undo/Redo.
2. Окружность: Ø и R связаны, центр на месте, быстрый ввод по двойному щелчку.
3. Управляющие размеры и характерные точки: размер следует за геометрией и сам её меняет.
4. Сквозной цикл: пластина с отверстием на листе А4 → выдавливание → правка эскиза → перестроение 3D и видов.
5. Регрессия: тёмная тема, зум к курсору, куб ориентации, библиотека ГОСТ.

Запуск: .venv/Scripts/python -m unittest tests.test_kompas_parity
"""
from __future__ import annotations

import json
import math
import unittest

from tests.env import APP, ERRORS, TMP  # noqa: F401  — окна без показа, временные config.json и user_library.json
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QAction, QKeySequence, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from cad import library, params  # noqa: E402
from cad.dialogs import Ask, QuickEdit  # noqa: E402
from cad.dims import render  # noqa: E402
from cad.mainwindow import MainWindow  # noqa: E402
from cad.model import make_circle, make_line  # noqa: E402


def dim_text(d) -> str:
    return render(d).texts[0][3]


class KompasParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Ask.AUTO = True
        cls.w = MainWindow()
        cls.w.resize(1400, 900)
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
        w = self.w
        w.cfg["canvas"] = "fragment"
        w.themes.set(mode="classic-light")
        w.new_project()
        w.work.setCurrentIndex(0)
        w.set_tool("select")

    def tearDown(self):
        self.assertEqual(ERRORS, [], "исключения в обработчиках Qt")

    # ------------------------------------------------------------ помощники
    def shortcut(self, seq):
        """Действие меню по горячей клавише — как Ctrl+Z / Ctrl+Y с клавиатуры."""
        key = QKeySequence(seq)
        act = next(a for a in self.w.findChildren(QAction) if a.shortcut() == key)
        act.trigger()
        APP.processEvents()

    def prop(self, key, value):
        """Ввести число в панель параметров и подтвердить (как Enter в поле)."""
        spin = self.w.prop_spins[key]
        spin.setValue(value)
        APP.processEvents()   # панель перестраивается через deleteLater

    def at(self, v, x, y) -> QPoint:
        return v.mapFromScene(QPointF(x, y))

    def find(self, eid):
        return self.w.project.find(eid)

    # ------------------------------------------------------------ 1. отрезок
    def test_1_line_length_angle_undo_redo(self):
        w = self.w
        w.set_tool("line")
        tp = w.tool_panel
        for k, v in (("x1", 10), ("y1", 20), ("length", 100), ("angle", 30)):
            tp.spins[k].setValue(v)
        self.assertAlmostEqual(tp.spins["x2"].value(), round(10 + 100 * math.cos(math.radians(30)), 2), 2, "конец считается при создании")
        self.assertAlmostEqual(tp.spins["y2"].value(), 70.0, 2)
        tp.apply()
        lid = w.project.entities[-1]["id"]
        line = self.find(lid)
        self.assertAlmostEqual(params.line_length(line), 100, 9)
        self.assertAlmostEqual(params.line_angle(line), 30, 9)
        w.set_tool("select")
        w.sketch.select([lid])
        for k in ("length", "angle", "x1", "y1", "x2", "y2"):
            self.assertIn(k, w.prop_spins, "панель: L, α, начало, конец")
            self.assertEqual(w.prop_spins[k].decimals(), 2, "точность 0,01 мм")
        self.assertAlmostEqual(w.prop_spins["length"].value(), 100, 2)
        self.prop("length", 250)
        line = self.find(lid)
        self.assertAlmostEqual(params.line_angle(line), 30, 9, "угол остался 30°")
        self.assertEqual((line["x1"], line["y1"]), (10.0, 20.0), "начало на месте")
        self.assertEqual(f"{math.dist((line['x1'], line['y1']), (line['x2'], line['y2'])):.2f}", "250.00")
        self.assertAlmostEqual(w.prop_spins["length"].value(), 250, 2, "панель показывает новую длину")
        self.shortcut(QKeySequence.Undo)
        self.assertAlmostEqual(params.line_length(self.find(lid)), 100, 9, "Ctrl+Z вернул 100 мм")
        self.shortcut("Ctrl+Y")
        self.assertAlmostEqual(params.line_length(self.find(lid)), 250, 9, "Ctrl+Y вернул 250 мм")
        # угол: поворот вокруг начала с сохранением длины
        self.prop("angle", 45)
        line = self.find(lid)
        self.assertAlmostEqual(params.line_length(line), 250, 9)
        self.assertAlmostEqual(params.line_angle(line), 45, 9)
        self.assertEqual((line["x1"], line["y1"]), (10.0, 20.0))
        # конец: L и α пересчитываются
        self.prop("x2", 10)
        self.prop("y2", 120)
        line = self.find(lid)
        self.assertAlmostEqual(params.line_length(line), 100, 9)
        self.assertAlmostEqual(params.line_angle(line), 90, 9)
        # двойной щелчок по отрезку: быстрый ввод длины
        v = w.sketch
        v.fit_all()
        Ask.answers = {"length": 120}
        QTest.mouseDClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, self.at(v, 10, 45))
        self.assertIn("Отрезок", Ask.answers.get("_forms", []))
        line = self.find(lid)
        self.assertAlmostEqual(params.line_length(line), 120, 9)
        self.assertAlmostEqual(params.line_angle(line), 90, 9)
        self.assertEqual((line["x1"], line["y1"]), (10.0, 20.0))
        self.shortcut(QKeySequence.Undo)
        self.assertAlmostEqual(params.line_length(self.find(lid)), 100, 9, "быстрый ввод тоже отменяется")

    # ------------------------------------------------------------ 2. окружность
    def test_2_circle_diameter_radius(self):
        w = self.w
        w.set_tool("circle")
        tp = w.tool_panel
        tp.spins["cx"].setValue(100)
        tp.spins["cy"].setValue(100)
        tp.spins["d"].setValue(40)
        self.assertAlmostEqual(tp.spins["r"].value(), 20, 6, "Ø и R связаны уже при создании")
        tp.apply()
        cid = w.project.entities[-1]["id"]
        self.assertEqual(self.find(cid)["r"], 20)
        w.set_tool("select")
        w.sketch.select([cid])
        self.assertAlmostEqual(w.prop_spins["d"].value(), 40, 2)
        self.assertAlmostEqual(w.prop_spins["r"].value(), 20, 2)
        self.prop("d", 85)
        c = self.find(cid)
        self.assertEqual(c["r"], 42.5)
        self.assertEqual((c["cx"], c["cy"]), (100.0, 100.0), "центр на месте")
        self.assertAlmostEqual(w.prop_spins["r"].value(), 42.5, 2, "R сразу 42,5")
        item = next(it for it in w.sketch.scene().items() if it.data(0) == cid)
        self.assertAlmostEqual(item.path().boundingRect().width(), 85, 1, "контур на чертеже перерисован")
        self.prop("r", 10)
        self.assertAlmostEqual(w.prop_spins["d"].value(), 20, 2)
        self.shortcut(QKeySequence.Undo)
        self.assertEqual(self.find(cid)["r"], 42.5)
        # двойной щелчок по ободу: быстрый ввод Ø
        v = w.sketch
        Ask.answers = {"d": 85}
        self.find(cid)["r"] = 20.0
        w.refresh()
        v.fit_all()
        rim = (100 + 20 * math.cos(math.radians(45)), 100 + 20 * math.sin(math.radians(45)))
        QTest.mouseDClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, self.at(v, *rim))
        c = self.find(cid)
        self.assertEqual(c["r"], 42.5, "по двойному щелчку: Ø 85 → R 42,5")
        self.assertEqual((c["cx"], c["cy"]), (100.0, 100.0))
        # живое окно быстрого ввода: набрать «85», Enter — радиус уже 42,5
        dlg = QuickEdit(w, "Окружность", [("d", "Диаметр Ø", 40, 0.01, 1e5), ("r", "Радиус R", 20, 0.01, 1e5)], ("d", "r", 0.5))
        dlg.show()
        APP.processEvents()
        dlg.first.lineEdit().selectAll()
        QTest.keyClicks(dlg.first.lineEdit(), "85")
        self.assertAlmostEqual(dlg.spins["r"].value(), 42.5, 6, "R меняется, пока набираете Ø")
        QTest.keyClick(dlg.first.lineEdit(), Qt.Key_Return)
        self.assertEqual(dlg.result(), QDialog.Accepted)
        self.assertEqual(dlg.values(), {"d": 85.0, "r": 42.5})
        # осевые линии
        w.sketch.select([cid])
        w.prop_checks["axes"].setChecked(True)
        APP.processEvents()
        self.assertTrue(self.find(cid)["axes"])
        from cad.export2d import to_dxf
        self.assertIn(b"AXIS", to_dxf(w.project, w.project.entities, with_frame=False).split(b"ENTITIES")[1])

    # ------------------------------------------------------------ 3. управляющие размеры и характерные точки
    def test_3_driving_dimensions_and_grips(self):
        w = self.w
        w.history.push()
        w.project.entities += [make_line(0, 0, 100, 0), make_circle(200, 0, 20)]
        w.refresh()
        lid, cid = w.project.entities[0]["id"], w.project.entities[1]["id"]
        v = w.sketch
        v.fit_all()
        w.set_tool("dim_a")
        for pt in ((0, 0), (100, 0), (50, 12)):
            v.click(*pt)
        dim = w.project.entities[-1]
        self.assertEqual(dim["refs"], [[lid, "p1"], [lid, "p2"]], "размер привязан к концам отрезка")
        self.assertEqual(dim_text(dim), "100")
        # 1) длина отрезка меняется — текст размера сам
        w.set_tool("select")
        v.select([lid])
        self.prop("length", 130)
        dim = self.find(dim["id"])
        self.assertEqual(dim_text(dim), "130")
        # 2) двойной щелчок по размерной цифре — новое значение меняет отрезок
        x, y, h, *_ = render(dim).texts[0]
        Ask.answers = {"value": 150}
        v.select([])
        QTest.mouseDClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, self.at(v, x, y + h / 2))
        self.assertIn("Размер (управляющий)", Ask.answers.get("_forms", []))
        line = self.find(lid)
        self.assertAlmostEqual(params.line_length(line), 150, 9)
        self.assertEqual((line["x1"], line["y1"]), (0.0, 0.0), "первая точка размера неподвижна")
        self.assertEqual(dim_text(self.find(dim["id"])), "150")
        # диаметр: Ø40 → Ø65
        w.set_tool("dim_dia")
        v.click(220, 0)
        v.click(240, 25)
        dd = w.project.entities[-1]
        self.assertEqual(dd["ref"], cid)
        self.assertEqual(dim_text(dd), "⌀40")
        w.set_tool("select")
        x, y, h, *_ = render(dd).texts[0]
        Ask.answers = {"value": 65}
        QTest.mouseDClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, self.at(v, x, y + h / 2))
        self.assertEqual(self.find(cid)["r"], 32.5, "размер Ø65 изменил окружность")
        self.assertEqual(dim_text(self.find(dd["id"])), "⌀65")
        self.shortcut(QKeySequence.Undo)
        self.assertEqual(self.find(cid)["r"], 20)
        self.assertEqual(dim_text(self.find(dd["id"])), "⌀40")
        self.shortcut("Ctrl+Y")
        # прямоугольник: горизонтальный размер по углам меняет ширину, фигура остаётся прямоугольником
        w.set_tool("rect")
        w.tool_panel.spins["x"].setValue(0)
        w.tool_panel.spins["y"].setValue(100)
        w.tool_panel.spins["w"].setValue(60)
        w.tool_panel.spins["h"].setValue(40)
        w.tool_panel.apply()
        rect = w.project.entities[-4:]
        w.set_tool("dim_h")
        for pt in ((0, 100), (60, 100), (30, 90)):
            v.click(*pt)
        rd = w.project.entities[-1]
        w.set_tool("select")
        v.select([rd["id"]])
        self.prop("value", 90)
        self.assertEqual(params.rect_info([self.find(e["id"]) for e in rect]), (0.0, 100.0, 90.0, 40.0))
        self.assertEqual(dim_text(self.find(rd["id"])), "90")
        # щелчок по стороне выделяет прямоугольник целиком; W/H в панели
        v.select([])
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, self.at(v, 45, 140))
        self.assertEqual(set(v.selected), {e["id"] for e in rect})
        self.assertIn("w", w.prop_spins)
        self.prop("h", 55)
        self.assertEqual(params.rect_info([self.find(e["id"]) for e in rect])[3], 55.0)
        # характерные точки: отрезок — концы и середина; конец тянется — длина меняется, размер за ним
        v.select([lid])
        self.assertEqual([g[2] for g in v.grips()], ["p1", "p2", "mid"])
        end = self.at(v, 150, 0)
        target = self.at(v, 180, 0)
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, end)
        QTest.mouseMove(v.viewport(), target)
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, target)
        line = self.find(lid)
        self.assertAlmostEqual(params.line_length(line), 180, 0)
        self.assertEqual(dim_text(self.find(dim["id"])), f"{params.line_length(line):.2f}".rstrip("0").rstrip(".").replace(".", ","))
        self.shortcut(QKeySequence.Undo)
        self.assertAlmostEqual(params.line_length(self.find(lid)), 150, 9, "перетаскивание отменяется одним Ctrl+Z")
        # окружность: центр и 4 точки на ободе; точка обода — радиус, подсказка с Ø на лету
        v.select([cid])
        roles = [g[2] for g in v.grips()]
        self.assertEqual(roles, ["c", "q", "q", "q", "q"])
        hints = []
        v.hint.connect(hints.append)
        q = self.at(v, 232.5, 0)
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, q)
        QTest.mouseMove(v.viewport(), self.at(v, 240, 0))
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, self.at(v, 240, 0))
        v.hint.disconnect(hints.append)
        self.assertAlmostEqual(self.find(cid)["r"], 40, 0)
        self.assertTrue(any(s.startswith("Ø ") for s in hints), hints)
        self.assertEqual(self.find(dd["id"])["r"], self.find(cid)["r"], "размер Ø следует за ободом")

    # ------------------------------------------------------------ 4. 2D → 3D → лист ГОСТ
    def test_4_plate_with_hole_2d_3d_sheet(self):
        w = self.w
        w.set_canvas("A4P")
        w.work.setCurrentIndex(0)
        w.set_tool("rect")
        for k, val in (("x", 0), ("y", 0), ("w", 80), ("h", 50)):
            w.tool_panel.spins[k].setValue(val)
        w.tool_panel.apply()
        w.set_tool("circle")
        for k, val in (("cx", 40), ("cy", 25), ("d", 20)):
            w.tool_panel.spins[k].setValue(val)
        w.tool_panel.apply()
        Ask.answers = {"height": 10}
        w.extrude()
        fid = w.project.features[-1]["id"]
        lo, hi = w.solid.bbox()
        self.assertEqual([round(float(v), 3) for v in hi - lo], [80, 50, 10])
        self.assertAlmostEqual(w.solid.volume, (80 * 50 - math.pi * 100) * 10, delta=40)
        w.drawing_from_model()
        self.assertEqual(w.project.canvas_mode(), "A4P", "лист А4 по ГОСТ")
        def views_width():
            xs = [v for e in w.project.drawing if e.get("gen") == "views" and e["type"] == "line" for v in (e["x1"], e["x2"])]
            return max(xs) - min(xs)
        width0 = views_width()
        scale0 = w.project.frame["scale"]
        # правка эскиза операции: сторона пластины 80 → 100
        w.edit_feature_sketch(fid)
        v = w.sketch
        v.fit_all()
        w.set_tool("select")
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, self.at(v, 20, 0))
        self.assertEqual(len(v.selected), 4, "прямоугольник выделен целиком")
        self.prop("w", 100)
        lo, hi = w.solid.bbox()
        self.assertEqual([round(float(v), 3) for v in hi - lo], [100, 50, 10], "3D перестроено после правки эскиза")
        self.assertAlmostEqual(w.solid.volume, (100 * 50 - math.pi * 100) * 10, delta=40)
        self.assertNotAlmostEqual(views_width(), width0, 1, "виды на листе перестроены")
        if w.project.frame["scale"] == scale0:
            self.assertAlmostEqual(views_width() - width0, 20 * eval(scale0.replace(":", "/").replace(",", ".")), 1)
        gen_dims = [e for e in w.project.drawing if e.get("gen") == "views" and e["type"] == "dim" and e["kind"] == "horizontal"]
        self.assertIn("100", [dim_text(d) for d in gen_dims], "габарит на листе — новый")
        # диаметр отверстия 20 → 30
        hole = next(e for e in v.target() if e["type"] == "circle")
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, self.at(v, 40 + 10 * math.cos(0.8), 25 + 10 * math.sin(0.8)))
        self.assertEqual(v.selected, [hole["id"]])
        self.prop("d", 30)
        self.assertAlmostEqual(w.solid.volume, (100 * 50 - math.pi * 225) * 10, delta=40, msg="отверстие Ø30 вырезано")
        # характерная точка угла прямоугольника — габарит тела
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, self.at(v, 50, 50))
        corner, to = self.at(v, 100, 50), self.at(v, 110, 60)
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, corner)
        QTest.mouseMove(v.viewport(), to)
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, to)
        lo, hi = w.solid.bbox()
        self.assertEqual([round(float(v), 0) for v in (hi - lo)[:2]], [110, 60])
        # отмена по шагам: угол, отверстие, сторона
        self.shortcut(QKeySequence.Undo)
        self.shortcut(QKeySequence.Undo)
        self.assertAlmostEqual(w.solid.volume, (100 * 50 - math.pi * 100) * 10, delta=40)
        self.shortcut(QKeySequence.Undo)
        lo, hi = w.solid.bbox()
        self.assertEqual(round(float(hi[0] - lo[0]), 3), 80)
        w.finish_sketch_edit()

    # ------------------------------------------------------------ 5. регрессия
    def test_5_regression_theme_zoom_gizmo_library(self):
        w = self.w
        # тёмная тема переживает режимы и перезапуск
        w.show_appearance()
        w.appearance_dlg.mode_buttons["classic-dark"].click()
        w.appearance_dlg.close()
        for tab, mode in ((2, None), (1, "A4P"), (1, "fragment"), (0, None)):
            w.work.setCurrentIndex(tab)
            if mode:
                w.set_canvas(mode)
        self.assertEqual(json.loads((TMP / "config.json").read_text(encoding="utf-8"))["active_theme"], "classic-dark")
        w2 = MainWindow()
        try:
            self.assertEqual(w2.themes.mode, "classic-dark")
        finally:
            w2.dirty = False
            w2.close()
        w.themes.set(mode="classic-light")
        # зум к курсору на листе
        w.set_canvas("A4P")
        v = w.sheet
        pos = v.viewportTransform().map(QPointF(80.3, 140.7))
        before = v.to_scene(pos)
        ev = QWheelEvent(pos, QPointF(v.viewport().mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, 240),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(v.viewport(), ev)
        after = v.to_scene(pos)
        self.assertLess(max(abs(after.x() - before.x()), abs(after.y() - before.y())), 1e-3)
        # куб ориентации: +Z — вид сверху
        from cad.view3d import AXIS_VIEW
        w.work.setCurrentIndex(2)
        APP.processEvents()
        v3 = w.view3d
        v3.set_view("iso")
        ball = next(p for a, p, r, z in v3.gizmo.balls() if a == (0, 0, 1))
        QTest.mouseClick(v3.gizmo, Qt.LeftButton, Qt.NoModifier, ball.toPoint())
        v3.finish_animation()
        self.assertEqual(AXIS_VIEW[(0, 0, 1)], "top")
        self.assertEqual(round(v3.opts["elevation"]), 90)
        # библиотека ГОСТ: автомат с поворотом R
        w.work.setCurrentIndex(1)
        w.insert_block("qf1")
        w._hotkey(w.sheet, "rect")
        n0 = len(w.project.drawing)
        w.sheet.click(100, 150)
        placed = w.project.drawing[n0:]
        out = library.ports_world("qf1", 100, 150, 90)["выход"]
        self.assertTrue(any(abs(e.get("x2", 0) - out[0]) < 1e-6 and abs(e.get("y2", 0) - out[1]) < 1e-6 for e in placed))
        self.assertEqual(library.label_of(w.project.drawing, placed[0]["blk"]), "QF1")


if __name__ == "__main__":
    unittest.main()
