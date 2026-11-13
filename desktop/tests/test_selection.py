"""Множественное выделение и ПКМ-редактор, как в КОМПАС-3D.

1. Shift/Ctrl+щелчок: набрать 3 отрезка, общая длина и стиль одним вводом; Ctrl+A, Esc.
2. Рамка: синяя слева направо берёт только целиком вложенные, зелёная штриховая справа налево — и пересечённые.
3. ПКМ-редактор на отрезке, окружности и группе: правки применяются сразу и откатываются Ctrl+Z; ПКМ во время
   черчения завершает команду; перенос группы мышью; Ctrl+C / Ctrl+V.
4. Прямоугольник через ПКМ «Разбить на отдельные линии» — затем правится одна сторона; элемент библиотеки и размер.

Запуск: .venv/Scripts/python -m unittest tests.test_selection
"""
from __future__ import annotations

import math
import unittest

from tests.env import APP, ERRORS  # noqa: F401  — окна без показа, временные config.json и user_library.json
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QAction, QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from cad import library, params  # noqa: E402
from cad.dialogs import Ask  # noqa: E402
from cad.mainwindow import MainWindow  # noqa: E402
from cad.model import make_circle, make_line, make_rect  # noqa: E402


class SelectionTest(unittest.TestCase):
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
        w.new_project()
        w.work.setCurrentIndex(0)
        w.set_tool("select")

    def tearDown(self):
        if self.w.ctx_editor is not None:
            self.w.ctx_editor.close()
        self.assertEqual(ERRORS, [], "исключения в обработчиках Qt")

    # ------------------------------------------------------------ помощники
    def put(self, ents):
        w = self.w
        w.history.push()
        w.project.entities += ents
        w.refresh()
        w.sketch.fit_all()
        return [e["id"] for e in ents]

    def at(self, x, y):
        return self.w.sketch.mapFromScene(QPointF(x, y))

    def click(self, x, y, button=Qt.LeftButton, mods=Qt.NoModifier):
        QTest.mouseClick(self.w.sketch.viewport(), button, mods, self.at(x, y))
        APP.processEvents()

    def drag(self, a, b, mods=Qt.NoModifier, inspect=None):
        vp = self.w.sketch.viewport()
        QTest.mousePress(vp, Qt.LeftButton, mods, self.at(*a))
        QTest.mouseMove(vp, self.at((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
        QTest.mouseMove(vp, self.at(*b))
        if inspect:
            inspect()
        QTest.mouseRelease(vp, Qt.LeftButton, mods, self.at(*b))
        APP.processEvents()

    def undo(self):
        act = next(a for a in self.w.findChildren(QAction) if a.shortcut() == QKeySequence(QKeySequence.Undo))
        act.trigger()
        APP.processEvents()

    def find(self, eid):
        return self.w.project.find(eid)

    @staticmethod
    def labels(widget) -> str:
        from PySide6.QtWidgets import QLabel
        return " | ".join(lab.text() for lab in widget.findChildren(QLabel) if lab.isVisibleTo(widget) or not widget.isVisible())

    def editor(self):
        ed = self.w.ctx_editor
        self.assertIsNotNone(ed, "ПКМ открыл редактор")
        self.assertTrue(ed.isVisible())
        return ed

    def set_field(self, ed, key, value):
        ed.fields[key].setValue(value)
        APP.processEvents()          # правка, затем панель перестраивается
        return self.w.ctx_editor

    # ------------------------------------------------------------ 1. Shift/Ctrl+щелчок
    def test_1_shift_click_three_lines_batch_length_and_style(self):
        w, v = self.w, self.w.sketch
        ids = self.put([make_line(0, 0, 40, 0), make_line(0, 20, 30, 50), make_line(60, 0, 60, 25), make_circle(120, 20, 10)])
        self.click(20, 0)
        self.assertEqual(v.selected, [ids[0]])
        self.click(15, 35, mods=Qt.ShiftModifier)
        self.click(60, 12, mods=Qt.ControlModifier)
        self.assertEqual(set(v.selected), set(ids[:3]), "Shift и Ctrl добавляют")
        self.click(15, 35, mods=Qt.ShiftModifier)
        self.assertEqual(set(v.selected), {ids[0], ids[2]}, "повторный Shift+щелчок снимает")
        self.click(15, 35, mods=Qt.ShiftModifier)
        self.assertIn("Выбрано объектов: 3", self.labels(w.props))
        angles = [params.line_angle(self.find(i)) for i in ids[:3]]
        starts = [(self.find(i)["x1"], self.find(i)["y1"]) for i in ids[:3]]
        w.prop_spins["length"].setValue(75)
        APP.processEvents()
        for i, a, s in zip(ids[:3], angles, starts):
            e = self.find(i)
            self.assertAlmostEqual(params.line_length(e), 75, 9)
            self.assertAlmostEqual(params.line_angle(e), a, 9, "углы — свои")
            self.assertEqual((e["x1"], e["y1"]), s, "начала на месте")
        self.assertAlmostEqual(self.find(ids[3])["r"], 10, 9, "окружность не выбрана — не тронута")
        combo = w.prop_rows.fields["style"]
        combo.setCurrentIndex(combo.findData("hidden"))
        APP.processEvents()
        self.assertEqual({self.find(i)["style"] for i in ids[:3]}, {"hidden"})
        self.undo()
        self.assertEqual({self.find(i)["style"] for i in ids[:3]}, {"main"})
        self.undo()
        self.assertAlmostEqual(params.line_length(self.find(ids[0])), 40, 9, "Ctrl+Z вернул длины")
        # Ctrl+A — всё, Esc — снять
        QTest.keyClick(v, Qt.Key_A, Qt.ControlModifier)
        self.assertEqual(set(v.selected), set(ids))
        QTest.keyClick(v, Qt.Key_Escape)
        self.assertEqual(v.selected, [])

    # ------------------------------------------------------------ 2. рамка: окно и секущая
    def test_2_window_vs_crossing_box(self):
        w, v = self.w, self.w.sketch
        inside, crossing, outside = self.put([make_line(10, 10, 30, 10), make_line(25, 25, 60, 25), make_line(80, 0, 90, 0)])
        tints = {}

        def tint(name):
            def grab():
                img = v.viewport().grab().toImage()
                c = self.at(20, 18)
                px = [img.pixelColor(c.x() + dx, c.y() + dy) for dx in range(-6, 7, 3) for dy in range(-6, 7, 3)]
                tints[name] = tuple(sum(getattr(p, ch)() for p in px) / len(px) for ch in ("red", "green", "blue"))
                tints[name + "_crossing"] = v._box["cur"][0] < v._box["start"][0]
            return grab
        # слева направо: синяя сплошная — только целиком внутри
        self.drag((5, 30), (40, 5), inspect=tint("window"))
        self.assertEqual(v.selected, [inside], "окно: пересечённый отрезок не взят")
        # справа налево: зелёная штриховая — и пересечённые
        self.drag((40, 5), (5, 30), inspect=tint("cross"))
        self.assertEqual(set(v.selected), {inside, crossing}, "секущая: взят и пересечённый")
        self.assertFalse(tints["window_crossing"])
        self.assertTrue(tints["cross_crossing"])
        r, g, b = tints["window"]
        self.assertGreater(b, r + 8, f"окно — синее {tints['window']}")
        r, g, b = tints["cross"]
        self.assertGreater(g, r + 8, f"секущая — зелёная {tints['cross']}")
        self.assertGreater(g, b, f"секущая — зелёная {tints['cross']}")
        # с Shift рамка прибавляет
        self.drag((75, -5), (95, 5), mods=Qt.ShiftModifier)
        self.assertEqual(set(v.selected), {inside, crossing, outside})
        # щелчок по пустому месту без Shift — снять
        self.click(150, 150)
        self.assertEqual(v.selected, [])
        # прямоугольник — один объект: окно берёт только целиком, секущая — за любую сторону
        rect = self.put(make_rect(100, 40, 30, 20))
        self.drag((95, 35), (120, 65))
        self.assertEqual(v.selected, [], "окно задело часть прямоугольника — не берёт")
        self.drag((120, 65), (95, 35))
        self.assertEqual(set(v.selected), set(rect))

    # ------------------------------------------------------------ 3. ПКМ-редактор: отрезок, окружность, группа
    def test_3_context_editor_line_circle_group_with_undo(self):
        w, v = self.w, self.w.sketch
        lid, cid, l2, l3 = self.put([make_line(0, 0, 100, 0), make_circle(150, 50, 20), make_line(0, 40, 50, 40), make_line(0, 80, 50, 80)])
        # отрезок: ПКМ по невыделенному — выделить и открыть редактор
        self.click(30, 0, Qt.RightButton)
        self.assertEqual(v.selected, [lid])
        ed = self.editor()
        self.assertEqual(set(ed.fields), {"length", "angle", "style"})
        self.assertTrue({"dim", "split", "perp", "move", "dup", "del"} <= set(ed.actions))
        ed = self.set_field(ed, "length", 150)
        self.assertAlmostEqual(params.line_length(self.find(lid)), 150, 9)
        self.assertAlmostEqual(self.w.ctx_editor.fields["length"].value(), 150, 2, "панель у курсора обновилась")
        ed.fields["style"].setCurrentIndex(ed.fields["style"].findData("axis"))
        APP.processEvents()
        self.assertEqual(self.find(lid)["style"], "axis")
        self.undo()
        self.assertEqual(self.find(lid)["style"], "main", "Ctrl+Z — стиль")
        self.undo()
        self.assertAlmostEqual(params.line_length(self.find(lid)), 100, 9, "Ctrl+Z — длина")
        self.w.ctx_editor.close()
        self.click(30, 0, Qt.RightButton)
        self.editor().actions["dim"].click()
        dim = w.project.entities[-1]
        self.assertEqual(dim["type"], "dim")
        self.assertEqual(dim["refs"], [[lid, "p1"], [lid, "p2"]], "размер сразу управляющий")
        self.click(30, 0, Qt.RightButton)
        self.editor().actions["split"].click()
        halves = [e for e in w.project.entities if e["type"] == "line" and e["y1"] == 0 == e["y2"]]
        self.assertEqual(sorted(params.line_length(e) for e in halves), [50, 50], "разделён пополам")
        self.undo()
        self.click(30, 0, Qt.RightButton)
        self.editor().actions["perp"].click()
        perp = w.project.entities[-1]
        self.assertEqual((perp["x1"], perp["y1"], perp["x2"], perp["y2"]), (50, 0, 50, 50))
        # окружность: Ø и R связаны, оси, размер
        self.click(150 + 20 * math.cos(0.7), 50 + 20 * math.sin(0.7), Qt.RightButton)
        ed = self.editor()
        self.assertEqual(v.selected, [cid])
        ed = self.set_field(ed, "d", 50)
        self.assertEqual(self.find(cid)["r"], 25)
        self.assertAlmostEqual(self.w.ctx_editor.fields["r"].value(), 25, 2, "R показывает новое значение")
        self.w.ctx_editor.fields["axes"].setChecked(True)
        APP.processEvents()
        self.assertTrue(self.find(cid).get("axes"))
        self.w.ctx_editor.actions["dim"].click()
        self.assertEqual(w.project.entities[-1].get("ref"), cid)
        self.undo()
        self.undo()
        self.undo()
        self.assertEqual(self.find(cid)["r"], 20, "три шага Ctrl+Z: размер, оси, диаметр")
        self.assertFalse(self.find(cid).get("axes"))
        # группа: выделение не сбрасывается, редактор группы
        v.select([lid, l2, l3])
        self.click(25, 40, Qt.RightButton)
        self.assertEqual(set(v.selected), {lid, l2, l3})
        ed = self.editor()
        self.assertIn("Редактор группы (3 шт.)", self.labels(ed))
        for key in ("length", "style", "dx", "dy", "rot"):
            self.assertIn(key, ed.fields)
        for key in ("align_h", "align_v", "close", "extrude", "save", "copy", "del"):
            self.assertIn(key, ed.actions)
        ed = self.set_field(ed, "length", 60)
        self.assertEqual({round(params.line_length(self.find(i)), 9) for i in (lid, l2, l3)}, {60})
        self.w.ctx_editor.fields["dx"].setValue(10)
        self.w.ctx_editor.fields["dy"].setValue(-5)
        self.w.ctx_editor.actions["move"].click()
        APP.processEvents()
        self.assertEqual((self.find(l2)["x1"], self.find(l2)["y1"]), (10, 35))
        self.undo()
        self.assertEqual((self.find(l2)["x1"], self.find(l2)["y1"]), (0, 40), "Ctrl+Z — сдвиг группы")
        self.undo()
        self.assertEqual(round(params.line_length(self.find(l2)), 9), 50, "Ctrl+Z — общая длина")
        # перенос группы мышью за любой выбранный объект
        v.select([lid, l2, l3])
        self.drag((25, 40), (35, 50))
        self.assertEqual((self.find(lid)["x1"], self.find(lid)["y1"]), (10, 10), "вся группа ушла на (10, 10)")
        self.assertEqual(set(v.selected), {lid, l2, l3})
        # Ctrl+C / Ctrl+V
        n = len(w.project.entities)
        QTest.keyClick(v, Qt.Key_C, Qt.ControlModifier)
        v.setAttribute(Qt.WA_UnderMouse, False)
        QTest.keyClick(v, Qt.Key_V, Qt.ControlModifier)
        self.assertEqual(len(w.project.entities), n + 3)
        self.assertEqual(len(v.selected), 3, "вставленное выделено")
        # ПКМ во время черчения завершает команду; повторный ПКМ по объекту — его редактор
        w.set_tool("line")
        v.click(200, 0)
        self.click(250, 50, Qt.RightButton)
        self.assertEqual((v.tool, v.points), ("select", []))
        self.assertEqual(w.tool_panel.view.tool, "select")
        self.click(150 + 20 * math.cos(0.7), 50 + 20 * math.sin(0.7), Qt.RightButton)
        self.assertEqual(v.selected, [cid])
        self.assertIn("d", self.editor().fields)

    # ------------------------------------------------------------ 4. разбить прямоугольник, блок, размер
    def test_4_explode_rectangle_then_edit_one_side(self):
        w, v = self.w, self.w.sketch
        rect = self.put(make_rect(0, 0, 80, 50))
        self.click(40, 50, Qt.RightButton)
        self.assertEqual(set(v.selected), set(rect), "ПКМ по стороне — весь прямоугольник")
        ed = self.editor()
        self.assertIn("w", ed.fields)
        ed = self.set_field(ed, "w", 70)
        self.assertEqual(params.rect_info([self.find(i) for i in rect]), (0.0, 0.0, 70.0, 50.0))
        self.w.ctx_editor.actions["explode"].click()
        APP.processEvents()
        self.assertTrue(all("rect" not in self.find(i) for i in rect), "разбит на отдельные отрезки")
        self.click(35, 50)
        self.assertEqual(len(v.selected), 1, "теперь выделяется одна сторона")
        top = v.selected[0]
        self.click(35, 50, Qt.RightButton)
        ed = self.editor()
        self.assertEqual(set(ed.fields), {"length", "angle", "style"}, "редактор отрезка, а не прямоугольника")
        ed = self.set_field(ed, "length", 30)
        self.assertAlmostEqual(params.line_length(self.find(top)), 30, 9)
        others = [self.find(i) for i in rect if i != top]
        self.assertEqual(sorted(round(params.line_length(e), 6) for e in others), [50, 50, 70], "остальные стороны не тронуты")
        self.undo()
        self.undo()
        self.assertTrue(all(self.find(i).get("rect") for i in rect), "Ctrl+Z собрал прямоугольник обратно")
        # элемент библиотеки: маркировка, поворот, разрушение
        w.work.setCurrentIndex(1)
        s = w.sheet
        w.insert_block("qf1")
        s.click(100, 100)
        w.set_tool("select")
        inst = w.project.drawing[-1]["blk"]
        s.right_click(100, 90, s.mapToGlobal(s.mapFromScene(QPointF(100, 90))))
        ed = self.editor()
        self.assertTrue({"label", "scale"} <= set(ed.fields))
        self.assertTrue({"rot_ccw", "rot_cw", "explode"} <= set(ed.actions))
        ed.fields["label"].setText("QF5")
        ed.fields["label"].editingFinished.emit()
        APP.processEvents()
        self.assertEqual(library.label_of(w.project.drawing, inst), "QF5")
        self.w.ctx_editor.actions["rot_ccw"].click()
        part = [e for e in w.project.drawing if e.get("blk") == inst]
        out = library.ports_world("qf1", 100, 100, 90)["выход"]
        self.assertTrue(any(abs(e.get("x2", 1e9) - out[0]) < 1e-6 and abs(e.get("y2", 1e9) - out[1]) < 1e-6 for e in part), "повёрнут вокруг точки вставки")
        lab = next(e for e in part if e.get("blk_role") == "label")
        self.assertEqual(lab["ang"], 0.0, "маркировка горизонтальна")
        s.right_click(110, 100, s.mapToGlobal(s.mapFromScene(QPointF(110, 100))))
        self.editor().actions["explode"].click()
        self.assertFalse(any(e.get("blk") == inst for e in w.project.drawing), "разрушен на примитивы")
        # размер: ПКМ → разрушить
        w.project.drawing.append({**__import__("cad.model", fromlist=["make_dim"]).make_dim(0, 0, 50, 0, 10)})
        w.refresh()
        d = w.project.drawing[-1]
        s.select([d["id"]])
        s.right_click(25, 10, s.mapToGlobal(s.mapFromScene(QPointF(25, 10))))
        ed = self.editor()
        self.assertTrue({"tol", "text"} <= set(ed.fields))
        ed.actions["explode"].click()
        self.assertIsNone(self.find(d["id"]))
        self.assertTrue(any(e["type"] == "text" and e["text"] == "50" for e in w.project.drawing))


if __name__ == "__main__":
    unittest.main()
