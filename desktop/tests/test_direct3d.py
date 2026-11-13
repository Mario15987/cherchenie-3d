"""Прямое редактирование в 3D (как в КОМПАС-3D): ручки граней, стрелка выдавливания, фантом, связь с панелью и деревом.

1. Ядро: ручки граней выдавливания и выреза, луч в сцену, пересчёт вершин меша при новой высоте.
2. Манипулятор программно: щелчок по грани → стрелка и «H: 10.0 мм»; перетаскивание к 25 — поле панели и фантом
   следуют, тело ещё прежнее; отпустили — вершины меша на новой высоте, виды на листе перестроены, Ctrl+Z.
3. Мышью: протяжка стрелки, Shift — шаг 0,1, Esc и ПКМ отменяют; дно выреза; боковая грань — без ручки.
4. Двойной щелчок по размеру на сцене и по операции в дереве — быстрый ввод точного значения.

Запуск: .venv/Scripts/python -m unittest tests.test_direct3d
"""
from __future__ import annotations

import math
import unittest

import numpy as np

from tests.env import APP, ERRORS  # noqa: F401  — окна без показа, временные config.json и user_library.json
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from cad import geometry as geo, ops  # noqa: E402
from cad.dialogs import Ask  # noqa: E402
from cad.mainwindow import MainWindow  # noqa: E402
from cad.model import Project, make_circle, make_rect  # noqa: E402

PLATE = (80 * 50 - math.pi * 100)          # площадь пластины 80×50 с отверстием Ø20


def z_levels(solid) -> list[float]:
    return sorted({round(float(z), 4) for z in solid.verts[:, 2]})


class MeshRecomputeTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.p.entities = make_rect(0, 0, 80, 50) + [make_circle(40, 25, 10)]
        ops.create_feature(self.p, "extrude", height=10)

    def test_handles_and_ray(self):
        s = geo.build_solid(self.p.features)
        self.assertEqual(len(s.handles), 1)
        h = s.handles[0]
        self.assertEqual((h["param"], h["z"], h["dir"], h["value"]), ("height", 10.0, 1, 10.0))
        hit = geo.ray_hit(s, (5, 5, 100), (0, 0, -1))
        np.testing.assert_allclose(hit["point"], [5, 5, 10], atol=1e-6)
        self.assertEqual(geo.handle_at(s, self.p.features, hit["point"], hit["normal"])["fid"], h["fid"])
        self.assertIsNone(geo.ray_hit(s, (40, 25, 100), (0, 0, -1)), "луч проходит сквозь отверстие")
        side = geo.ray_hit(s, (-50, 20, 5), (1, 0, 0))
        self.assertIsNone(geo.handle_at(s, self.p.features, side["point"], side["normal"]), "боковая грань — без ручки")
        tris = geo.face_triangles(s, self.p.features, h)
        area = sum(0.5 * np.linalg.norm(np.cross(*(s.verts[f[1:]] - s.verts[f[0]]))) for f in s.faces[tris])
        self.assertAlmostEqual(area, PLATE, delta=2, msg="подсвечивается вся верхняя грань")

    def test_vertices_follow_extrude_height(self):
        s0 = geo.build_solid(self.p.features)
        h = s0.handles[0]
        top0 = np.isclose(s0.verts[:, 2], 10)
        s1 = geo.build_solid(geo.with_handle_value(self.p.features, h, 25))
        self.assertEqual(z_levels(s1), [0.0, 25.0])
        self.assertEqual(int(np.isclose(s1.verts[:, 2], 25).sum()), int(top0.sum()), "вершины верха — те же, на новой высоте")
        np.testing.assert_allclose(np.sort(s1.verts[np.isclose(s1.verts[:, 2], 25), :2], axis=0),
                                   np.sort(s0.verts[top0, :2], axis=0), atol=1e-5)
        self.assertAlmostEqual(s1.volume, PLATE * 25, delta=30)
        self.assertEqual(self.p.features[0]["height"], 10, "фантом не трогает само дерево")
        ghost = geo.handle_tool(self.p.features, h, 7)
        self.assertEqual([round(float(v), 4) for v in ghost.bbox()[1] - ghost.bbox()[0]], [80, 50, 7])

    def test_cut_depth_handle(self):
        self.p.entities = [make_circle(15, 12, 5)]
        ops.create_feature(self.p, "cut", depth=4)
        s = geo.build_solid(self.p.features)
        cut = s.handles[1]
        self.assertEqual((cut["param"], cut["z"], cut["dir"], cut["base"]), ("depth", 6.0, -1, 10.0))
        hit = geo.ray_hit(s, (15, 12, 100), (0, 0, -1))
        self.assertAlmostEqual(float(hit["point"][2]), 6.0)
        self.assertEqual(geo.handle_at(s, self.p.features, hit["point"], hit["normal"])["param"], "depth")
        s2 = geo.build_solid(geo.with_handle_value(self.p.features, cut, 7))
        self.assertIn(3.0, z_levels(s2), "дно выреза опустилось на 10 − 7")
        self.assertEqual(geo.build_solid(geo.with_handle_value(self.p.features, s.handles[0], 20)).handles[1]["z"], 16.0,
                         "вырез идёт от верха: выше пластина — выше и дно")


class DirectEditUiTest(unittest.TestCase):
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
        w.project.entities += make_rect(0, 0, 80, 50) + [make_circle(40, 25, 10)]
        Ask.answers = {"height": 10}
        w.extrude()
        Ask.answers = {}
        w.work.setCurrentIndex(2)
        w.view3d.set_view("iso")
        w.view3d.home()
        APP.processEvents()
        self.fid = w.project.features[0]["id"]

    def tearDown(self):
        self.w.view3d.manip.detach()
        self.assertEqual(ERRORS, [], "исключения в обработчиках Qt")

    def click_face(self, p3):
        v = self.w.view3d
        QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, v.project(p3).toPoint())
        APP.processEvents()

    def test_programmatic_drag_rebuilds_mesh_and_sheet(self):
        w, v = self.w, self.w.view3d
        w.drawing_from_model()
        w.work.setCurrentIndex(2)
        self.click_face((10, 10, 10))
        m = v.manip
        self.assertIsNotNone(m.handle, "щелчок по верхней грани — стрелка")
        self.assertEqual(w.sel_feature, self.fid)
        self.assertEqual(m.text(), "H: 10.0 мм")
        self.assertTrue(m.badge.isVisible())
        self.assertEqual(w.prop_spins["height"].value(), 10)
        self.assertEqual(len(m.items), 5, "подсветка грани, ось, стрелка, конус, основание")
        top0 = int(np.isclose(w.solid.verts[:, 2], 10).sum())
        m.set_value(25)                                    # тянем: фантом и поле — сразу, тело — после отпускания
        self.assertEqual(w.prop_spins["height"].value(), 25, "поле «Высота» обновляется во время перетаскивания")
        self.assertEqual(m.text(), "H: 25.0 мм")
        self.assertTrue(v.ghost, "фантом будущей формы")
        self.assertFalse(v.mesh_item.visible(), "вместо граней тела — фантом")
        self.assertEqual(float(w.solid.bbox()[1][2]), 10.0)
        self.assertEqual(w.project.features[0]["height"], 10)
        m.end()
        self.assertEqual(w.project.features[0]["height"], 25)
        self.assertEqual(z_levels(w.solid), [0.0, 25.0], "вершины меша пересчитаны")
        self.assertEqual(int(np.isclose(w.solid.verts[:, 2], 25).sum()), top0)
        self.assertAlmostEqual(w.solid.volume, PLATE * 25, delta=30)
        self.assertEqual(v.ghost, [])
        self.assertTrue(v.mesh_item.visible())
        self.assertEqual(m.handle["z"], 25.0, "стрелка — на новой грани")
        self.assertIn("25", self.view_dims(), "виды на листе перестроены: габарит 25")
        w.undo()
        self.assertEqual(w.project.features[0]["height"], 10)
        self.assertEqual(z_levels(w.solid), [0.0, 10.0])
        self.assertEqual(v.manip.text(), "H: 10.0 мм")

    def view_dims(self) -> list[str]:
        """Тексты габаритных размеров на видах «Чертежа по модели»."""
        from cad.dims import render

        return [render(e).texts[0][3] for e in self.w.project.drawing if e.get("gen") == "views" and e["type"] == "dim"]

    def test_mouse_drag_shift_and_cancel(self):
        w, v = self.w, self.w.view3d
        self.click_face((70, 40, 10))
        m = v.manip
        a, b = m.screen_segment()
        start = ((a + b) / 2).toPoint()
        QTest.mouseMove(v, start)
        self.assertEqual(v.cursor().shape(), Qt.SizeVerCursor, "над стрелкой — курсор вверх-вниз")
        QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, start)
        seen = []
        for k in range(1, 5):
            QTest.mouseMove(v, start + QPoint(0, -15 * k))
            APP.processEvents()
            seen.append((m.value, w.prop_spins["height"].value()))
        self.assertTrue(all(a == b for a, b in seen), seen)
        self.assertGreater(seen[-1][0], seen[0][0] > 10 or seen[0][0], "вверх по экрану — выше")
        QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, start + QPoint(0, -60))
        APP.processEvents()
        h = w.project.features[0]["height"]
        self.assertGreater(h, 12)
        self.assertEqual(h, round(h), "шаг 1 мм")
        # Shift — шаг 0,1 мм. Пауза перед нажатием: иначе второе нажатие подряд — двойной щелчок (точный ввод)
        pause = APP.styleHints().mouseDoubleClickInterval() + 50
        a, b = m.screen_segment()
        start = ((a + b) / 2).toPoint()
        QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, start, pause)
        QTest.mouseMove(v, start + QPoint(0, 7))
        m.drag(start + QPoint(0, 7), Qt.ShiftModifier)            # QTest не передаёт модификатор в движение
        fine = m.value
        QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, start + QPoint(0, 7))
        self.assertAlmostEqual(w.project.features[0]["height"], fine)
        self.assertAlmostEqual(fine * 10, round(fine * 10), places=6)
        # Esc и ПКМ отменяют, дерево не меняется
        before = w.project.features[0]["height"]
        for cancel in ("esc", "rmb"):
            a, b = m.screen_segment()
            start = ((a + b) / 2).toPoint()
            QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, start, pause)
            QTest.mouseMove(v, start + QPoint(0, -40))
            self.assertNotEqual(m.value, before)
            if cancel == "esc":
                QTest.keyClick(v, Qt.Key_Escape)
            else:
                QTest.mousePress(v, Qt.RightButton, Qt.NoModifier, start)
            self.assertFalse(m.dragging)
            self.assertEqual(m.value, before)
            self.assertEqual(w.prop_spins["height"].value(), before)
            self.assertEqual(v.ghost, [])
            QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, start)
        self.assertEqual(w.project.features[0]["height"], before)

    def test_cut_floor_side_face_and_escape(self):
        w, v = self.w, self.w.view3d
        w.project.entities += [make_circle(15, 12, 5)]
        Ask.answers = {"through": False, "depth": 4}
        w.cut()
        w.work.setCurrentIndex(2)
        v.set_view("top")                         # сверху дно выреза видно целиком
        v.home()
        APP.processEvents()
        self.click_face((15, 12, 6))
        self.assertEqual(v.manip.handle["param"], "depth")
        self.assertEqual(v.manip.text(), "Глубина: 4.0 мм")
        self.assertEqual(w.prop_spins["depth"].value(), 4)
        v.manip.drag_to(7)
        self.assertEqual(w.project.features[1]["depth"], 7)
        self.assertIn(3.0, z_levels(w.solid))
        self.assertAlmostEqual(w.solid.volume, PLATE * 10 - math.pi * 25 * 7, delta=30)
        v.set_view("front")
        v.home()
        APP.processEvents()
        self.click_face((40, 0, 5))               # боковая грань: ручки нет, подсказка про эскиз
        self.assertIsNone(v.manip.handle)
        self.assertIn("эскизом", w.hint.text())
        v.set_view("iso")
        self.click_face((10, 10, 10))
        self.assertIsNotNone(v.manip.handle)
        QTest.keyClick(v, Qt.Key_Escape)
        self.assertIsNone(v.manip.handle, "Esc снимает выбор")
        self.assertIsNone(w.sel_feature)

    def test_double_click_size_and_tree(self):
        w, v = self.w, self.w.view3d
        self.click_face((10, 10, 10))
        Ask.answers = {"height": 33}
        QTest.mouseDClick(v.manip.badge, Qt.LeftButton)
        APP.processEvents()
        self.assertEqual(w.project.features[0]["height"], 33, "двойной щелчок по размеру — точный ввод")
        self.assertIn(w.project.features[0]["name"], Ask.answers["_forms"])
        self.assertEqual(v.manip.text(), "H: 33.0 мм")
        item = next(w.tree.topLevelItem(0).child(i) for i in range(w.tree.topLevelItem(0).childCount())
                    if w.tree.topLevelItem(0).child(i).data(0, Qt.UserRole) == ("feature", self.fid))
        Ask.answers = {"height": 12}
        w._on_tree_double(item, 0)
        self.assertEqual(w.project.features[0]["height"], 12, "двойной щелчок по операции в дереве")
        self.assertEqual(z_levels(w.solid), [0.0, 12.0])
        # выбор операции в дереве — та же ручка в 3D и поле в панели
        w._select_feature(None)
        self.assertIsNone(v.manip.handle)
        item = next(w.tree.topLevelItem(0).child(i) for i in range(w.tree.topLevelItem(0).childCount())
                    if w.tree.topLevelItem(0).child(i).data(0, Qt.UserRole) == ("feature", self.fid))
        w.tree.setCurrentItem(item)
        APP.processEvents()
        self.assertEqual(v.manip.text(), "H: 12.0 мм")
        w._set_feature_value(self.fid, "height", 15)      # поле панели → модель и стрелка
        self.assertEqual(v.manip.handle["z"], 15.0)

    def test_ghost_after_fillet_uses_operation_body(self):
        """За выдавливанием — скругление (долгий пересчёт): фантом — только тело операции, без пересборки всего дерева."""
        w, v = self.w, self.w.view3d
        Ask.answers = {"size": 1}
        w.edge3d("fillet3d")
        w.work.setCurrentIndex(2)
        APP.processEvents()
        w._select_feature(self.fid)
        self.assertIsNotNone(v.manip.handle)
        v.manip.set_value(20)
        self.assertTrue(v.ghost)
        lo, hi = (np.min(np.vstack([it.opts["meshdata"].vertexes() for it in v.ghost[:1]]), axis=0),
                  np.max(np.vstack([it.opts["meshdata"].vertexes() for it in v.ghost[:1]]), axis=0))
        self.assertEqual([round(float(x), 3) for x in hi - lo], [80, 50, 20], "фантом — призма операции")
        v.manip.cancel()
        self.assertEqual(w.project.features[0]["height"], 10)


if __name__ == "__main__":
    unittest.main()
