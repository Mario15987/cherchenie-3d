"""Инженерные модули по КОМПАС-3D и ЕСКД.

1. Динамический ввод у курсора: бейдж «L | ∠», «Ø (R)», «Ш × В», наведение, ввод цифр, Tab, Enter; бейдж в 3D.
2. Аксонометрия ГОСТ 2.317: оси и коэффициенты, эллипс отверстия, вид на листе, камера, режимы 3D, размеры на модели,
   изометрическая сетка в 2D.
3. Рамка выделения: Ctrl инвертирует попавшие объекты, Shift добавляет.
4. Основная надпись ГОСТ 2.104: формы 1 / 2 / 2а; масштабы ГОСТ 2.302; линии 2.303; штриховки 2.306; ТТ 2.316.
5. Спецификация ГОСТ 2.106, текстовый документ ГОСТ 2.105, шифр схемы ГОСТ 2.701.
6. Справочник ЕСКД, нормоконтроль, стартовый экран «Создать».

Запуск: .venv/Scripts/python -m unittest tests.test_eskd
"""
from __future__ import annotations

import math
import unittest

import numpy as np

from tests.env import APP, ERRORS  # noqa: F401  — окна без показа, временные config.json и user_library.json
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from cad import documents, edit2d, eskd, geometry as geo, library, ops, params, projection as pr  # noqa: E402
from cad.dialogs import Ask  # noqa: E402
from cad.dims import render  # noqa: E402
from cad.eskd_panel import NormDialog, SpecDialog, StartDialog  # noqa: E402
from cad.linestyles import STYLE_SPEC, shaped  # noqa: E402
from cad.mainwindow import MainWindow  # noqa: E402
from cad.model import (  # noqa: E402
    CANVAS_MODES, FORMATS, HATCH_PATTERNS, STYLES, Project, default_frame, make_circle, make_dim, make_hatch, make_line, make_rect,
    sheet_size,
)
from cad.stamp import frame_geometry, frame_rect, stamp_cells, stamp_size  # noqa: E402


def plate(height=20.0) -> tuple[Project, geo.Solid]:
    p = Project(name="Плита", designation="АБВГ.301412.001", material="Сталь 20")
    p.entities = make_rect(0, 0, 80, 50) + [make_circle(40, 25, 10)]
    ops.create_feature(p, "extrude", height=height)
    return p, geo.build_solid(p.features)


class EskdCoreTest(unittest.TestCase):
    # ------------------------------------------------------------ ГОСТ 2.317
    def test_axonometry_axes_and_coefficients(self):
        (_, ux, uy), k = pr.AXO["iso"]
        ang = {n: math.degrees(math.atan2(np.array(v) @ uy, np.array(v) @ ux)) for n, v in (("x", (1, 0, 0)), ("y", (0, 1, 0)), ("z", (0, 0, 1)))}
        self.assertAlmostEqual(ang["x"], -30, places=6)
        self.assertAlmostEqual(ang["y"], 30, places=6)
        self.assertAlmostEqual(ang["z"], 90, places=6)       # между осями 120°
        for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            self.assertAlmostEqual(float(np.hypot(np.array(v) @ ux, np.array(v) @ uy)), 0.8165, places=4)
        self.assertAlmostEqual(k, 1.2247, places=4)
        self.assertAlmostEqual(pr.ISO_ANGLES[1], 35.264, places=3)
        (_, ux, uy), _ = pr.AXO["dim"]
        coef = [float(np.hypot(np.array(v) @ ux, np.array(v) @ uy)) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
        self.assertAlmostEqual(coef[0], 0.9428, places=4)
        self.assertAlmostEqual(coef[1], 0.4714, places=4)
        self.assertAlmostEqual(coef[2], 0.9428, places=4)
        self.assertAlmostEqual(abs(math.degrees(math.atan2(np.array([1, 0, 0]) @ uy, np.array([1, 0, 0]) @ ux))), 7.18, places=2)    # 7°10′
        self.assertAlmostEqual(math.degrees(math.atan2(np.array([0, 1, 0]) @ uy, np.array([0, 1, 0]) @ ux)), 41.41, places=2)       # 41°25′

    def test_isometric_view_ellipse_and_hidden_removal(self):
        p, s = plate()
        vis, hid, box = pr.axo_view(s, "iso")
        self.assertEqual(hid, [], "невидимые линии убраны")
        (_, ux, uy), k = pr.AXO["iso"]
        c = np.array([40, 25, 20.0])
        cx, cy = c @ ux * k, c @ uy * k
        pts = np.array([(x, y) for sg in vis for x, y in ((sg[0], sg[1]), (sg[2], sg[3])) if math.hypot(x - cx, y - cy) < 13 * k])
        d = pts - [cx, cy]
        self.assertGreater(len(pts), 40)
        self.assertAlmostEqual(float(np.abs(d[:, 0]).max()), 1.2247 * 10, delta=0.1)     # большая ось 1,22d
        self.assertAlmostEqual(float(np.abs(d[:, 1]).max()), 0.7071 * 10, delta=0.1)     # малая ось 0,71d
        q = (d[:, 0] / 12.247) ** 2 + (d[:, 1] / 7.071) ** 2
        self.assertTrue(np.all(np.abs(q - 1) < 0.02), "точки отверстия лежат на эллипсе")
        along_x = [sg for sg in vis if abs(math.degrees(math.atan2(sg[3] - sg[1], sg[2] - sg[0])) % 180 - 150) < 0.01]
        self.assertAlmostEqual(max(math.hypot(sg[2] - sg[0], sg[3] - sg[1]) for sg in along_x), 80, delta=0.01)   # по осям — натуральные
        _, hid2, _ = pr.axo_view(s, "iso", hidden=True)
        self.assertTrue(hid2, "с hidden=True невидимые рёбра возвращаются")
        self.assertEqual(len(pr.axo_view(s, "iso", reduced=False)[0]), len(vis))

    def test_isometry_on_sheet(self):
        p, s = plate()
        ops.set_canvas(p, "A3L")
        info = pr.insert_axo(p, s)
        axo = [e for e in p.drawing if e.get("gen") == "axo"]
        self.assertEqual(len(axo), info["lines"])
        fx, fy, fw, fh = frame_rect(p.frame)
        x0, y0, x1, y1 = library.bounds(axo)
        self.assertTrue(fx <= x0 and x1 <= fx + fw and fy + 55 <= y0 and y1 <= fy + fh, "вид внутри рамки, над основной надписью")
        self.assertGreater(x0, fx + fw / 2, "в правой половине листа")
        n = len(axo)
        pr.insert_axo(p, s)
        self.assertEqual(sum(1 for e in p.drawing if e.get("gen") == "axo"), n, "повторная вставка заменяет вид")
        info = pr.make_drawing(p, s, iso=True)        # спереди + сверху + слева + изометрия
        self.assertTrue(info["iso"])
        views = [e for e in p.drawing if e.get("gen") == "views" and e["type"] == "line"]
        slanted = [e for e in views if abs(abs(math.degrees(math.atan2(e["y2"] - e["y1"], e["x2"] - e["x1"]))) % 180 - 30) < 0.5
                   or abs(abs(math.degrees(math.atan2(e["y2"] - e["y1"], e["x2"] - e["x1"]))) % 180 - 150) < 0.5]
        self.assertGreaterEqual(len(slanted), 6, "в составе чертежа есть изометрия")
        ortho = [e for e in views if e not in slanted and (abs(e["x2"] - e["x1"]) < 1e-6 or abs(e["y2"] - e["y1"]) < 1e-6)]
        self.assertGreater(min(min(e["x1"], e["x2"]) for e in slanted), max(max(e["x1"], e["x2"]) for e in ortho if e["style"] == "main" and
                                                                               max(e["y1"], e["y2"]) < min(min(s_["y1"], s_["y2"]) for s_ in slanted)) - 400)
        self.assertEqual(pr.make_drawing(p, s)["iso"], True, "изометрия остаётся при перестроении")
        self.assertFalse(pr.make_drawing(p, s, iso=False)["iso"])

    def test_model_dims_and_dashes(self):
        p, s = plate()
        dims = {d["kind"]: d for d in pr.model_dims(s, p.features)}
        self.assertEqual({k: d["text"] for k, d in dims.items()}, {"L": "L: 80", "W": "W: 50", "H": "H: 20", "D": "Ø20"})
        self.assertAlmostEqual(float(np.linalg.norm(dims["L"]["b"] - dims["L"]["a"])), 80)
        self.assertAlmostEqual(float(np.linalg.norm(dims["D"]["b"] - dims["D"]["a"])), 20)
        pairs = pr.view_edges(s, pr.AXO["iso"][0][0])
        chains = pr.edge_chains(pairs)
        self.assertEqual(sum(len(c) - 1 for c in chains), len(pairs), "каждое ребро — в одной цепочке")
        dash = pr.dash_chains(s.verts, chains, 3.0, 2.0)
        lens = np.linalg.norm(dash[1::2] - dash[0::2], axis=1)
        self.assertLessEqual(float(lens.max()), 3.0 + 1e-6)
        self.assertGreater(len(dash), len(pairs), "длинные рёбра разбиты на штрихи")

    # ------------------------------------------------------------ ГОСТ 2.104, 2.301–2.306
    def test_stamp_forms(self):
        for form, h, fields in (("1", 55.0, {"designation", "name", "material", "scale", "mass"}), ("2", 40.0, {"designation", "name", "sheet", "sheets"}),
                                ("2a", 15.0, {"designation", "sheet"})):
            fr = {**default_frame(), "format": "A4", "orient": "portrait", "form": form}
            self.assertEqual(stamp_size(fr), (185.0, h))
            cells = stamp_cells(fr)
            self.assertAlmostEqual(sum(c.w * c.h for c in cells), 185 * h, msg="графы покрывают надпись без зазоров")
            self.assertAlmostEqual(max(c.x + c.w for c in cells) - min(c.x for c in cells), 185)
            self.assertAlmostEqual(max(c.y + c.h for c in cells) - min(c.y for c in cells), h)
            self.assertTrue(fields <= {c.field for c in cells if c.field}, form)
            lines, _ = frame_geometry(fr, Project())
            fx, fy, fw, _ = frame_rect(fr)
            self.assertIn((fx + fw - 185, fy + h, fx + fw - 185 + 185, fy + h, "main")[:2], [(round(a, 6), round(b, 6)) for a, b, *_ in lines] +
                          [(round(c, 6), round(d, 6)) for _, _, c, d, _ in lines])
        self.assertNotIn("material", {c.field for c in stamp_cells({**default_frame(), "form": "2"})})
        self.assertEqual(stamp_size({**default_frame(), "form": "2а"})[1], 15.0, "кириллическая «а» в 2а")
        self.assertEqual(stamp_size({"form": "?"})[1], 55.0)

    def test_formats_scales_lines_hatches(self):
        self.assertEqual(FORMATS["A0"], (841.0, 1189.0))
        self.assertEqual(sheet_size("A4x3", "landscape"), (630.0, 297.0))
        self.assertIn("A0L", CANVAS_MODES)
        self.assertEqual(eskd.GOST_SCALES, ["1:100", "1:50", "1:20", "1:10", "1:5", "1:4", "1:2,5", "1:2", "1:1", "2:1", "2,5:1", "4:1", "5:1", "10:1"])
        self.assertAlmostEqual(eskd.scale_factor("1:2,5"), 0.4)
        self.assertAlmostEqual(eskd.scale_factor("2.5:1"), 2.5)
        self.assertTrue({lab for _, lab in pr.SCALES} >= set(eskd.GOST_SCALES) - {"1:100", "1:50"} and all(eskd.is_gost_scale(lab) for _, lab in pr.SCALES))
        with self.assertRaises(ValueError):
            eskd.scale_factor("крупно")
        self.assertEqual(len(STYLES), 9)
        self.assertEqual(set(STYLE_SPEC), set(STYLES))
        self.assertEqual(len(shaped("open", 0, 0, 100, 0)), 2, "разомкнутая — два штриха по концам")
        self.assertTrue(all(8 <= abs(a[0] - b[0]) <= 20 for a, b in shaped("open", 0, 0, 100, 0)))
        zz = shaped("zigzag", 0, 0, 100, 0)[0]
        self.assertTrue(any(abs(y) > 1 for _, y in zz) and zz[0] == (0, 0) and zz[-1] == (100, 0))
        self.assertIsNone(shaped("main", 0, 0, 1, 1))
        self.assertEqual(set(HATCH_PATTERNS), {"metal", "nonmetal", "concrete", "glass", "wood", "liquid", "ground"})
        b = [[(0, 0), (40, 0), (40, 30), (0, 30)]]
        for pat in HATCH_PATTERNS:
            self.assertGreater(len(edit2d.hatch_segments(make_hatch(b, pat, 2, 45))), 5, pat)
        liquid = edit2d.hatch_segments(make_hatch(b, "liquid", 2, 45))
        self.assertTrue(all(abs(y2 - y1) < 1e-9 for _, y1, _, y2 in liquid), "жидкость — горизонтальные штрихи")

    def test_sheet_scale_keeps_real_dimensions(self):
        p = Project()
        ops.set_canvas(p, "A3L")
        p.drawing += make_rect(100, 100, 80, 50) + [make_circle(140, 125, 10)]
        d = params.attach_dim(p, make_dim(100, 100, 180, 100, -10, "horizontal"))
        p.drawing.append(d)
        f = eskd.set_sheet_scale(p, "1:2")
        self.assertEqual(f, 0.5)
        self.assertAlmostEqual(abs(d["x2"] - d["x1"]), 40, msg="геометрия на листе вдвое меньше")
        self.assertEqual(render(d).texts[0][3], "80", "размерное число — натуральное")
        self.assertAlmostEqual(next(e for e in p.drawing if e["type"] == "circle")["r"], 5)
        self.assertEqual(p.frame["scale"], "1:2")
        eskd.set_sheet_scale(p, "2:1")
        self.assertAlmostEqual(abs(d["x2"] - d["x1"]), 160)
        self.assertEqual(render(d).texts[0][3], "80")
        params.drive_dim(p, d, 100)             # управляющий размер и в масштабе меняет натуральную длину
        self.assertEqual(render(d).texts[0][3], "100")
        self.assertAlmostEqual(abs(d["x2"] - d["x1"]), 200)
        with self.assertRaises(ValueError):
            eskd.set_sheet_scale(p, "1:3")

    def test_tech_requirements_above_stamp(self):
        p = Project()
        with self.assertRaises(ValueError):
            eskd.set_tech_requirements(p, ["x"])
        ops.set_canvas(p, "A3L")
        n = eskd.set_tech_requirements(p, ["Неуказанные предельные отклонения размеров: H14, h14, ±IT14/2.", "", "Острые кромки притупить. " * 12])
        self.assertEqual(n, 2)
        tt = [e for e in p.drawing if e.get("gen") == "tt"]
        self.assertTrue(tt[0]["text"].startswith("1 ") and any(e["text"].startswith("2 ") for e in tt))
        fx, fy, fw, _ = frame_rect(p.frame)
        x0, y0, x1, y1 = library.bounds(tt)
        self.assertGreaterEqual(x0, fx + fw - 185)
        self.assertLessEqual(x1, fx + fw + 1e-6, "колонка не шире 185 мм")
        self.assertGreaterEqual(y0, fy + 55, "строго над основной надписью")
        self.assertGreater(len(tt), 2, "длинный пункт перенесён по словам")
        eskd.set_tech_requirements(p, ["Одно требование"])
        tt = [e for e in p.drawing if e.get("gen") == "tt"]
        self.assertEqual([e["text"] for e in tt], ["Одно требование"], "блок заменяется; единственный пункт без номера")

    # ------------------------------------------------------------ ГОСТ 2.106, 2.105, 2.701
    def test_specification_sections_from_project(self):
        p, _ = plate()
        ops.set_canvas(p, "A3L")
        p.drawing += (library.instantiate("bolt_front", 50, 50) + library.instantiate("bolt_front", 60, 50) + library.instantiate("nut_top", 70, 50)
                      + library.instantiate("washer_front", 80, 50) + library.instantiate("qf1", 90, 200, label="QF1")
                      + library.instantiate("channel", 200, 200) + library.instantiate("weld", 250, 200))
        rows = eskd.collect_spec(p)
        sec = {}
        for r in rows:
            sec.setdefault(r["section"], []).append(r)
        self.assertEqual(list(sec), ["Документация", "Детали", "Стандартные изделия", "Прочие изделия", "Материалы"], "порядок разделов ГОСТ 2.106")
        self.assertEqual(sec["Документация"][0]["designation"], "АБВГ.301412.001 СБ")
        self.assertEqual((sec["Детали"][0]["name"], sec["Детали"][0]["designation"], sec["Детали"][0]["qty"]), ("Плита", "АБВГ.301412.002", "1"))
        std = {r["name"]: r["qty"] for r in sec["Стандартные изделия"]}
        self.assertEqual(std["Болт М10×40 ГОСТ 7798-70"], "2")
        self.assertEqual(len(std), 3)
        self.assertEqual(sec["Прочие изделия"][0]["note"], "QF1")
        self.assertEqual({r["name"] for r in sec["Материалы"]}, {"Сталь 20", "Швеллер 10П ГОСТ 8240-97"})
        self.assertEqual([r["pos"] for r in rows if r["pos"]], ["1", "2", "3", "4", "5"], "позиции по порядку")
        info = eskd.build_specification(p)
        self.assertTrue(info["beside"], "на листе уже чертёж — спецификация отдельным листом рядом")
        self.assertEqual((p.frame["format"], p.frame.get("form", "1")), ("A3", "1"), "чертёж не тронут")
        spec = [e for e in p.drawing if e.get("gen") == "spec"]
        texts = [e["text"] for e in spec if e["type"] == "text"]
        for word in ("Обозначение", "Наименование", "Документация", "Стандартные изделия", "Болт М10×40 ГОСТ 7798-70", "Лист", "Листов"):
            self.assertIn(word, texts)
        self.assertGreater(library.bounds(spec)[0], 420, "правее листа А3")
        self.assertEqual(len(p.eskd["pages"]["spec"]), 1)
        n = len(spec)
        eskd.build_specification(p)
        self.assertEqual(sum(1 for e in p.drawing if e.get("gen") == "spec"), n, "перестроение не дублирует таблицу")

    def test_specification_document_pages(self):
        q = Project(name="Узел")
        info = eskd.build_specification(q, [eskd.spec_row("Детали", f"Вал {i:02d}", f"АБВГ.{i:03d}", 2) for i in range(70)])
        self.assertEqual((q.frame["format"], q.frame["orient"], q.frame["form"]), ("A4", "portrait", "2"))
        self.assertEqual(info["sheets"], 3)
        self.assertEqual(q.frame["sheets"], "3")
        self.assertFalse(info["beside"])
        self.assertEqual(len(q.eskd["pages"]["spec"]), 2, "два листа-продолжения с формой 2а")
        self.assertEqual(sum(1 for e in q.drawing if e["type"] == "text" and e["text"].startswith("Вал ")), 70)
        widths = [w for _, _, w in eskd.SPEC_COLUMNS]
        self.assertEqual((widths, sum(widths)), ([6, 6, 8, 70, 63, 10, 22], 185))

    def test_text_document_and_scheme_code(self):
        p = Project()
        n = eskd.set_text_document(p, "# 1 Введение\n" + "Пояснительная записка к проекту. " * 150 + "\n# 2 Расчёт\n" + "Текст. " * 500)
        self.assertGreaterEqual(n, 2)
        self.assertEqual((p.frame["format"], p.frame["form"], p.frame["sheets"]), ("A4", "2", str(n)))
        text = [e for e in p.drawing if e.get("gen") == "textdoc" and e["type"] == "text"]
        heads = [e for e in text if e["text"] in ("1 Введение", "2 Расчёт")]
        self.assertEqual(len(heads), 2)
        self.assertTrue(all(e["h"] == 5.0 for e in heads))
        fx, fy, fw, fh = frame_rect(p.frame)
        first = [e for e in text if fx <= e["x"] <= fx + fw and e["text"] not in ("Лист", "Листов")]
        self.assertTrue(all(fy + 40 + 10 - 1e-6 <= e["y"] <= fy + fh - 10 for e in first), "текст не ближе 10 мм к рамке и надписи")
        self.assertEqual(eskd.set_scheme(p, "Э", "3"), "Э3")
        self.assertTrue(p.designation.endswith("Э3"))
        self.assertIn("Схема электрическая принципиальная", p.name)
        eskd.set_scheme(p, "Г", "1")
        self.assertTrue(p.designation.endswith("Г1") and "Э3" not in p.designation)
        self.assertIn("Схема гидравлическая структурная", p.name)
        self.assertNotIn("электрическая", p.name)
        self.assertEqual(len(eskd.SCHEME_KINDS), 10)
        with self.assertRaises(ValueError):
            eskd.scheme_code("Я", "3")

    # ------------------------------------------------------------ справочник и нормоконтроль
    def test_handbook(self):
        nums = [g["num"] for g in eskd.GOSTS]
        for need in ("2.102-2013", "2.104-2006", "2.105-95", "2.106-96", "2.109-73", "2.301-68", "2.302-68", "2.303-68", "2.304-81", "2.305-2008",
                     "2.306-68", "2.307-2011", "2.308-2011", "2.309-73", "2.311-68", "2.312-72", "2.316-2008", "2.317-2011", "2.701-2008",
                     "2.702-2011", "2.721-74", "2.755-87"):
            self.assertIn(need, nums)
        self.assertEqual(len(nums), len(set(nums)))
        self.assertEqual(eskd.search("2.104")[0]["num"], "2.104-2006")
        self.assertEqual(eskd.search("ГОСТ 2.317")[0]["num"], "2.317-2011")
        self.assertEqual(eskd.search("масштаб")[0]["num"], "2.302-68")
        self.assertEqual(eskd.search("шероховатость")[0]["num"], "2.309-73")
        self.assertEqual(eskd.search("такого нет"), [])
        self.assertEqual(len(eskd.search("")), len(eskd.GOSTS))
        g = eskd.by_num("2.104")
        self.assertEqual([r[1] for r in g["table"][1:]], ["185 × 55", "185 × 40", "185 × 15"])
        self.assertEqual(len(eskd.by_num("2.303")["table"]), 10, "девять типов линий и шапка")
        page = eskd.html_page(g)
        self.assertIn("Форма", page)
        self.assertIn("<table", page)
        for g in eskd.GOSTS:
            self.assertTrue(g["title"] and g["text"] and g["group"])

    def test_normcontrol(self):
        p = Project()
        f = eskd.normcontrol(p)
        self.assertTrue(any(x["level"] == "error" and "2.301" in x["gost"] for x in f), "бесконечное полотно — не лист")
        ops.set_canvas(p, "A3L")
        p.frame["scale"] = "1:3"
        p.eskd["s"] = 2.0
        fx, fy, fw, fh = frame_rect(p.frame)
        out = make_line(fx + fw - 10, fy + 100, fx + fw + 30, fy + 100)
        on_stamp = make_line(fx + fw - 100, fy + 20, fx + fw - 50, fy + 30)
        p.drawing += [out, on_stamp] + make_rect(60, 120, 40, 30)
        bad = {x["gost"]: x for x in eskd.normcontrol(p) if x["level"] == "error"}
        self.assertIn("ГОСТ 2.104-2006", bad)
        self.assertIn("ГОСТ 2.302-68", bad)
        self.assertIn("ГОСТ 2.303-68", bad)
        self.assertEqual(bad["ГОСТ 2.109-73"]["ids"], [out["id"]])
        f = eskd.normcontrol(p)
        self.assertTrue(any(x["ids"] == [on_stamp["id"]] for x in f), "линия на основной надписи")
        self.assertTrue(any(x["level"] == "warn" and "2.307" in x["gost"] for x in f), "нет размеров")
        p.drawing[:] = make_rect(60, 120, 40, 30) + [make_dim(60, 120, 100, 120, -10, "horizontal")]
        p.name, p.designation, p.material = "Плита", "АБВГ.301412.001", "Сталь 20"
        p.frame.update(scale="1:1", people={**p.frame["people"], "Разраб.": "Иванов", "Пров.": "Петров", "Н. контр.": "Сидоров", "Утв.": "Орлов"})
        p.eskd["s"] = 0.8
        f = eskd.normcontrol(p)
        self.assertEqual([x for x in f if x["level"] != "ok"], [])
        self.assertEqual(eskd.norm_summary(f), "замечаний нет")

    def test_documents_setup(self):
        for kind in documents.SETUP:
            p, ui = documents.make_project(kind)
            self.assertEqual(p.eskd["doc"], kind)
            self.assertIn(ui["tab"], (0, 1))
        self.assertEqual([k for k, *_ in documents.DOCS], ["part", "assembly", "drawing", "fragment", "text", "spec"])
        self.assertEqual([k for k, *_ in documents.PROFILES], ["steel", "cable", "vent", "pipe", "sheet_metal", "spds", "tech_assembly"])
        p, ui = documents.make_project("spec")
        self.assertEqual((p.frame["format"], p.frame["form"], ui["after"]), ("A4", "2", "spec"))
        p, ui = documents.make_project("drawing")
        self.assertEqual((p.canvas_mode(), p.frame["form"]), ("A3L", "1"))
        self.assertEqual(documents.make_project("fragment")[0].canvas_mode(), "fragment")
        p, ui = documents.make_project("pipe")
        self.assertTrue(ui["iso"])
        self.assertTrue(library.search(ui["library"], library.BLOCKS.values()), "в каталоге есть элементы профиля")
        self.assertTrue(documents.make_project("cable")[0].designation.endswith("Э4"))
        self.assertTrue(any("Ctrl" in t and "инвертирует" in t for t in documents.TIPS))
        with self.assertRaises(ValueError):
            documents.make_project("нет")


class EskdUiTest(unittest.TestCase):
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
        for v in (w.sketch, w.sheet):
            v.iso = False
            v.fit_all()
        w.view3d.set_ortho(False)
        w.view3d.display, w.view3d.show_dims = "shaded", False

    def tearDown(self):
        self.w.sketch.hud.stop_edit()
        self.w.view3d.manip.detach()
        self.assertEqual(ERRORS, [], "исключения в обработчиках Qt")

    def at(self, x, y, v=None):
        return (v or self.w.sketch).mapFromScene(QPointF(x, y))

    def move(self, x, y, v=None):
        v = v or self.w.sketch
        pt = QPointF(self.at(x, y, v))
        v.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, pt, QPointF(v.viewport().mapToGlobal(pt.toPoint())), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
        APP.processEvents()

    def click(self, x, y, mods=Qt.NoModifier, v=None):
        v = v or self.w.sketch
        QTest.mouseClick(v.viewport(), Qt.LeftButton, mods, self.at(x, y, v))
        APP.processEvents()

    def box(self, a, b, mods=Qt.NoModifier):
        vp = self.w.sketch.viewport()
        QTest.mousePress(vp, Qt.LeftButton, mods, self.at(*a))
        QTest.mouseMove(vp, self.at((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
        QTest.mouseMove(vp, self.at(*b))
        QTest.mouseRelease(vp, Qt.LeftButton, mods, self.at(*b))
        APP.processEvents()

    def keys(self, text):
        for ch in text:
            QTest.keyClick(APP.focusWidget(), ch)
        APP.processEvents()

    # ------------------------------------------------------------ 1. динамический ввод
    def test_hud_badges_follow_cursor(self):
        w, v = self.w, self.w.sketch
        hud = v.hud
        w.set_tool("line")
        self.click(0, 0)
        self.move(40, 30)
        self.assertTrue(hud.isVisible())
        self.assertEqual(hud.text(), "L: 50.00 мм | ∠: 36.9°")
        self.assertEqual(hud.pos() - self.at(40, 30), QPoint(16, 16), "смещение +16, +16 от перекрестия")
        self.move(0, 20)
        self.assertEqual(hud.text(), "L: 20.00 мм | ∠: 90.0°")
        w.set_tool("circle")
        self.click(100, 0)
        self.move(130, 0)
        self.assertEqual(hud.text(), "Ø: 60.00 мм (R: 30.00 мм)")
        w.set_tool("rect")
        self.click(0, -60)
        self.move(100, -10)
        self.assertEqual(hud.text(), "Ш: 100.00 мм × В: 50.00 мм")
        w.set_tool("arc")
        self.click(200, 0)
        self.move(220, 0)
        self.assertEqual(hud.text(), "Ø: 40.00 мм (R: 20.00 мм)")
        self.click(220, 0)
        self.move(200, 20)
        self.assertEqual(hud.text(), "R: 20.00 мм | ∠: 90.0°")
        # выбор: наведение на отрезок и окружность, пустое место — бейджа нет
        w.set_tool("select")
        w.project.entities[:] = [make_line(0, 0, 80, 60), make_circle(150, 0, 20)]
        w.refresh()
        self.move(40, 30)
        cx, cy = v.cursor                       # в режиме выбора — без привязки: точка под пикселем
        self.assertAlmostEqual(cx, 40, delta=0.3)
        self.assertEqual(hud.text(), f"L: 100.00 мм | ∠: 36.9° | (X: {cx:.2f}, Y: {cy:.2f})")
        self.move(170, 0)
        cx, cy = v.cursor
        self.assertEqual(hud.text(), f"Ø: 40.00 мм (R: 20.00 мм) | (X: {cx:.2f}, Y: {cy:.2f})")
        self.move(60, -40)
        self.assertFalse(hud.isVisible())
        # перемещение узла: бейдж показывает новый размер
        self.click(170, 0)
        vp = v.viewport()
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, self.at(170, 0))
        self.move(180, 0)
        v.drag_to(180, 0)
        v._hud_update()
        self.assertEqual(hud.text(), "Ø: 60.00 мм (R: 30.00 мм)")
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, self.at(180, 0))

    def test_hud_typing_tab_enter(self):
        w, v = self.w, self.w.sketch
        w.set_tool("line")
        self.click(0, 0)
        self.move(40, 30)
        v.setFocus()
        QTest.keyClick(v, Qt.Key_1)                      # цифра на холсте — фокус сразу в поле у курсора
        self.assertTrue(v.hud.editing)
        self.assertEqual(list(v.hud.fields), ["length", "angle"])
        self.assertIs(APP.focusWidget(), v.hud.fields["length"])
        self.keys("25")
        self.assertEqual(v.hud.fields["length"].text(), "125")
        self.move(40, 0)                                 # курсор ушёл: введённая длина заперта, угол следует за мышью
        self.assertEqual(v.hud.fields["length"].text(), "125")
        self.assertEqual(v.hud.fields["angle"].text(), "0.00")
        QTest.keyClick(APP.focusWidget(), Qt.Key_Tab)
        self.assertIs(APP.focusWidget(), v.hud.fields["angle"], "Tab: L ↔ ∠")
        self.keys("30")
        QTest.keyClick(APP.focusWidget(), Qt.Key_Tab)
        self.assertIs(APP.focusWidget(), v.hud.fields["length"])
        QTest.keyClick(APP.focusWidget(), Qt.Key_Return)
        e = w.project.entities[-1]
        self.assertAlmostEqual(params.line_length(e), 125)
        self.assertAlmostEqual(params.line_angle(e), 30)
        self.assertFalse(v.hud.editing)
        self.assertIs(APP.focusWidget(), v, "после Enter фокус снова на холсте — можно чертить дальше")
        self.assertEqual(len(v.points), 1, "цепочка продолжается от конца отрезка")
        w.undo()
        self.assertEqual(w.project.entities, [])
        # прямоугольник: Ш, Tab, В, Enter
        w.set_tool("rect")
        self.click(0, -60)
        self.move(30, -40)
        v.setFocus()
        QTest.keyClick(v, Qt.Key_1)
        self.keys("00")
        QTest.keyClick(APP.focusWidget(), Qt.Key_Tab)
        self.keys("50")
        QTest.keyClick(APP.focusWidget(), Qt.Key_Return)
        self.assertEqual(params.rect_info(w.project.entities[-4:]), (0.0, -60.0, 100.0, 50.0))
        # окружность: Ø с клавиатуры; Esc в поле возвращает к мыши
        w.set_tool("circle")
        self.click(200, 0)
        self.move(230, 0)
        v.setFocus()
        QTest.keyClick(v, Qt.Key_6)
        self.keys("0")
        QTest.keyClick(APP.focusWidget(), Qt.Key_Return)
        self.assertAlmostEqual(w.project.entities[-1]["r"], 30)
        self.click(300, 0)
        self.move(320, 0)
        v.setFocus()
        QTest.keyClick(v, Qt.Key_9)
        n = len(w.project.entities)
        QTest.keyClick(APP.focusWidget(), Qt.Key_Escape)
        self.assertFalse(v.hud.editing)
        self.assertEqual(len(w.project.entities), n)
        self.assertEqual(v.tool, "circle", "Esc в поле не сбрасывает инструмент")

    def test_hud_in_3d_drag(self):
        w = self.w
        w.project.entities += make_rect(0, 0, 80, 50)
        Ask.answers = {"height": 10}
        w.extrude()
        w.work.setCurrentIndex(2)
        v = w.view3d
        v.set_view("iso")
        v.home()
        APP.processEvents()
        w._select_feature(w.project.features[0]["id"])
        v._mouse_pos = QPointF(300, 200)
        v.manip.set_value(25)
        self.assertTrue(v.hud.isVisible())
        self.assertEqual(v.hud.text(), "Глубина H: 25.0 мм")
        self.assertEqual(v.hud.pos(), QPoint(316, 216))
        v.manip.end()
        self.assertFalse(v.hud.isVisible())

    # ------------------------------------------------------------ 3. рамка: Ctrl инвертирует, Shift добавляет
    def test_box_ctrl_inverts_shift_adds(self):
        w, v = self.w, self.w.sketch
        a, b, c = make_line(0, 0, 0, 20), make_line(20, 0, 20, 20), make_line(40, 0, 40, 20)
        w.project.entities[:] = [a, b, c]
        w.refresh()
        v.fit_all()
        self.box((-5, -5), (25, 25))
        self.assertEqual(set(v.selected), {a["id"], b["id"]})
        self.box((15, -5), (45, 25), Qt.ControlModifier)          # b выделен — снимется, c не выделен — добавится
        self.assertEqual(set(v.selected), {a["id"], c["id"]}, "Ctrl инвертирует выделение попавших объектов")
        self.box((15, -5), (45, 25), Qt.ControlModifier)
        self.assertEqual(set(v.selected), {a["id"], b["id"]})
        self.box((35, -5), (45, 25), Qt.ShiftModifier)            # Shift — только добавляет
        self.assertEqual(set(v.selected), {a["id"], b["id"], c["id"]})
        self.box((-5, -5), (45, 25), Qt.ShiftModifier)
        self.assertEqual(len(v.selected), 3, "Shift не снимает уже выделенное")
        self.box((45, 25), (-5, -5), Qt.ControlModifier)          # секущая справа налево с Ctrl — тоже инверсия
        self.assertEqual(v.selected, [])
        self.box((-5, -5), (5, 25))
        self.assertEqual(v.selected, [a["id"]], "без клавиш рамка заменяет выделение")

    # ------------------------------------------------------------ 2. изометрия в окне
    def test_gost_views_display_modes_and_dims(self):
        w, v = self.w, self.w.view3d
        w.project.entities += make_rect(0, 0, 80, 50) + [make_circle(40, 25, 10)]
        Ask.answers = {"height": 20}
        w.extrude()
        w.ribbon_actions["Изометрия ГОСТ"].click()
        self.assertEqual(w.work.currentIndex(), 2)
        self.assertTrue(v.ortho, "изометрия — ортогональная проекция")
        self.assertAlmostEqual(v.opts["elevation"], 35.264, places=3)
        self.assertAlmostEqual(v.opts["azimuth"], -45)
        p0, px, py, pz = (v.project(q) for q in ((0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 10)))
        ang = sorted(round(math.degrees(math.atan2(-(q.y() - p0.y()), q.x() - p0.x())) % 360) for q in (px, py, pz))
        self.assertEqual(ang, [30, 90, 330], "оси на экране под 120° друг к другу")
        lens = [math.hypot(q.x() - p0.x(), q.y() - p0.y()) for q in (px, py, pz)]
        self.assertAlmostEqual(max(lens) / min(lens), 1.0, places=3)
        w.ribbon_actions["Диметрия ГОСТ"].click()
        self.assertAlmostEqual(v.opts["elevation"], 19.471, places=3)
        self.assertAlmostEqual(v.opts["azimuth"], -69.295, places=3)
        w.ribbon_actions["Изометрия ГОСТ"].click()
        w.ribbon_actions["Технический"].click()
        self.assertEqual(v.display, "tech")
        self.assertIsNotNone(v.hidden_item, "невидимые рёбра — штриховой")
        self.assertGreater(len(v.tech_dashes), 2 * len(v.tech_pairs))
        self.assertEqual(v.edge_item.width, 2.6, "видимые — сплошная толстая")
        self.assertLess(v.hidden_item.width, v.edge_item.width)
        w.ribbon_actions["Каркас"].click()
        self.assertEqual(v.display, "wire")
        self.assertIsNone(v.mesh_item)
        self.assertIsNone(v.hidden_item)
        w.ribbon_actions["Тонированный"].click()
        self.assertIsNotNone(v.mesh_item)
        w.ribbon_actions["Размеры 3D"].click()
        self.assertTrue(v.show_dims)
        self.assertEqual(sorted(v.dim_texts()), ["H: 20", "L: 80", "W: 50", "Ø20"])
        w._set_feature_value(w.project.features[0]["id"], "height", 35)       # модель изменилась — размеры на ней тоже
        self.assertIn("H: 35", v.dim_texts())
        w.ribbon_actions["Размеры 3D"].click()
        self.assertEqual(v.dim_texts(), [])

    def test_insert_isometry_button_and_follow_model(self):
        w = self.w
        w.project.entities += make_rect(0, 0, 80, 50) + [make_circle(40, 25, 10)]
        Ask.answers = {"height": 20}
        w.extrude()
        w.set_canvas("A3L")
        w.ribbon_actions["Изометрия на лист"].click()
        self.assertEqual(w.work.currentIndex(), 1)
        axo = [e for e in w.project.drawing if e.get("gen") == "axo"]
        self.assertGreater(len(axo), 40)
        h0 = library.bounds(axo)[3] - library.bounds(axo)[1]
        w._set_feature_value(w.project.features[0]["id"], "height", 40)
        axo = [e for e in w.project.drawing if e.get("gen") == "axo"]
        self.assertAlmostEqual(library.bounds(axo)[3] - library.bounds(axo)[1], h0 + 20, delta=0.01, msg="изометрия перестроилась за моделью")
        w.undo()
        w.undo()
        self.assertFalse(any(e.get("gen") == "axo" for e in w.project.drawing))
        w.ribbon_actions["Виды + изометрия"].click()
        self.assertTrue(w.project.frame["views_iso"])
        self.assertGreater(sum(1 for e in w.project.drawing if e.get("gen") == "views"), 60)
        w.new_project()
        w.ribbon_actions["Изометрия на лист"].click()
        self.assertTrue(Ask.answers.get("_warnings"), "без тела — понятное предупреждение")

    def test_isometric_grid_drawing(self):
        w, v = self.w, self.w.sketch
        w.ribbon_actions["Изометр. сетка"].click()
        w.work.setCurrentIndex(0)
        self.assertTrue(v.iso and w.sheet.iso)
        w.set_tool("line")
        v.click(0.4, 0.3)
        self.assertEqual(v.points[0], (0.0, 0.0), "первая точка — в узел изометрической сетки")
        s = v.iso_step()
        v.click(40, 21)                                   # ближе всего к оси 30°
        e = w.project.entities[-1]
        self.assertAlmostEqual(params.line_angle(e), 30, places=6)
        self.assertAlmostEqual(params.line_length(e) / s, round(params.line_length(e) / s), places=6, msg="длина кратна шагу сетки")
        v.click(e["x2"] + 1, e["y2"] + 30)                # вверх — ось 90°
        self.assertAlmostEqual(params.line_angle(w.project.entities[-1]), 90, places=6)
        v.click(v.points[-1][0] - 30, v.points[-1][1] + 15)   # ось 150°
        self.assertAlmostEqual(params.line_angle(w.project.entities[-1]) % 360, 150, places=6)
        self.move(100, 100)
        self.assertIn("изометрия", v.snap_label)
        v.viewport().grab()                               # сетка рисуется без ошибок
        w.ribbon_actions["Изометр. сетка"].click()
        self.assertFalse(v.iso)

    # ------------------------------------------------------------ 4–6. ЕСКД в окне
    def test_stamp_form_buttons_and_tech_block_moves(self):
        w = self.w
        w.set_canvas("A3L")
        Ask.answers = {"tech": "Острые кромки притупить.\nПокрытие: Ц9.хр."}
        w.ribbon_actions["Техн. требования"].click()
        fy = frame_rect(w.project.frame)[1]
        y1 = min(e["y"] for e in w.project.drawing if e.get("gen") == "tt")
        self.assertAlmostEqual(y1, fy + 55 + 5)
        w.ribbon_actions["Форма 2"].click()
        self.assertEqual(stamp_size(w.project.frame), (185.0, 40.0))
        self.assertAlmostEqual(min(e["y"] for e in w.project.drawing if e.get("gen") == "tt"), fy + 40 + 5, msg="ТТ — над новой надписью")
        w.ribbon_actions["Форма 2а"].click()
        self.assertEqual(stamp_size(w.project.frame)[1], 15.0)
        w.sheet.viewport().grab()
        w.ribbon_actions["Форма 1"].click()
        self.assertEqual(w.project.frame["form"], "1")
        w.undo()
        self.assertEqual(w.project.frame["form"], "2a")
        w.cfg["canvas"] = "fragment"
        w.new_project()
        self.assertEqual(w.project.canvas_mode(), "fragment")
        w.ribbon_actions["Форма 2"].click()               # на фрагменте форма 2 сама выбирает лист А4
        self.assertEqual((w.project.canvas_mode(), w.project.frame["form"]), ("A4P", "2"))
        w.edit_stamp("name")
        self.assertIn("Основная надпись (ГОСТ 2.104, форма 2)", Ask.answers["_forms"])

    def test_scale_spec_text_scheme_norm_from_ribbon(self):
        w = self.w
        w.set_canvas("A3L")
        w.work.setCurrentIndex(1)
        w.project.drawing += make_rect(100, 100, 80, 50)
        d = make_dim(100, 100, 180, 100, -10, "horizontal")
        w.project.drawing.append(d)
        w.refresh()
        Ask.answers = {"gost_scale": "1:2"}
        w.ribbon_actions["Масштаб листа"].click()
        dim = next(e for e in w.project.drawing if e["type"] == "dim")
        self.assertAlmostEqual(abs(dim["x2"] - dim["x1"]), 40)
        self.assertEqual(render(dim).texts[0][3], "80")
        self.assertEqual(w.project.frame["scale"], "1:2")
        Ask.answers = {}
        w.ribbon_actions["Спецификация"].click()
        self.assertIn("Спецификация (ГОСТ 2.106-96)", Ask.answers["_forms"])
        self.assertTrue(any(e.get("gen") == "spec" for e in w.project.drawing))
        w.sheet.viewport().grab()                          # бумага под листом спецификации рисуется
        Ask.answers = {"scheme_kind": "Э", "scheme_type": "3"}
        w.ribbon_actions["Шифр схемы"].click()
        self.assertTrue(w.project.designation.endswith("Э3"))
        Ask.answers = {"s": 1.0}
        w.ribbon_actions["Толщина линий s"].click()
        self.assertEqual(w.project.eskd["s"], 1.0)
        self.assertEqual(w.sheet.line_k(), 2.0)
        Ask.answers = {"font": "A", "slant": False}
        w.ribbon_actions["Шрифт чертежа"].click()
        self.assertEqual((w.project.eskd["font"], w.project.eskd["slant"]), ("A", False))
        w.sheet.viewport().grab()
        Ask.answers = {}
        w.ribbon_actions["Нормоконтроль"].click()
        self.assertIn("Нормоконтроль ЕСКД", Ask.answers["_forms"])
        self.assertTrue(any(f["level"] == "error" and "2.104" in f["gost"] for f in w.norm_findings))
        self.assertIn("Нормоконтроль ЕСКД: ошибок", w.hint.text())
        dlg = NormDialog(w.norm_findings, w)
        self.assertEqual(dlg.tree.topLevelItemCount(), len(w.norm_findings))
        dlg.deleteLater()
        w.new_project()
        Ask.answers = {"text": "# 1 Назначение\nТекст записки."}
        w.ribbon_actions["Текстовый документ"].click()
        self.assertEqual((w.project.frame["format"], w.project.frame["form"]), ("A4", "2"))
        self.assertIn("1 Назначение", [e["text"] for e in w.project.drawing if e["type"] == "text"])

    def test_handbook_panel_and_menu(self):
        w = self.w
        menu = next(a.menu() for a in w.menuBar().actions() if "ЕСКД" in a.text())
        titles = [a.text() for a in menu.actions() if a.text()]
        for word in ("Справочник стандартов ЕСКД", "Нормоконтроль ЕСКД", "Спецификация (ГОСТ 2.106)…", "Технические требования (ГОСТ 2.316)…"):
            self.assertIn(word, titles)
        w.ribbon_actions["Справочник ГОСТ"].click()
        APP.processEvents()
        self.assertIs(w.front_dock(), w.eskd_dock)
        panel = w.eskd_panel
        self.assertEqual(len(panel.nums()), len(eskd.GOSTS))
        panel.search.setText("2.104")
        self.assertEqual(panel.nums(), ["2.104-2006"])
        self.assertIn("185 × 40", panel.page.toPlainText())
        labels = [b.text() for b in panel.action_btns]
        self.assertEqual(labels[:3], ["Форма 1 (185×55)", "Форма 2 (185×40)", "Форма 2а (185×15)"])
        w.set_canvas("A3L")
        panel.action_btns[1].click()
        self.assertEqual(w.project.frame["form"], "2", "кнопка под статьёй меняет основную надпись")
        panel.search.setText("аксонометрические")
        self.assertEqual(panel.current(), "2.317-2011")
        next(b for b in panel.action_btns if b.text() == "Изометрия ГОСТ в 3D").click()
        self.assertAlmostEqual(w.view3d.opts["elevation"], 35.264, places=3)
        panel.search.setText("ничего такого")
        self.assertEqual(panel.nums(), [])
        w.show_eskd("2.303")
        self.assertEqual(panel.current(), "2.303-68")
        next(b for b in panel.action_btns if b.text() == "Разомкнутая").click()
        self.assertEqual(w.cur2d().style, "open")
        self.assertEqual(w.cur2d().tool, "line")
        w.cur2d().click(0, 0)
        w.cur2d().click(100, 0)
        self.assertEqual(w.cur2d().target()[-1]["style"], "open")
        w.cur2d().viewport().grab()
        w.eskd_action("hatch:wood")
        self.assertEqual((w.cur2d().tool, w.cur2d().params["hatch_pattern"]), ("hatch", "wood"))
        w.style_box.setCurrentIndex(0)

    def test_start_screen_documents(self):
        w = self.w
        dlg = StartDialog(w)
        self.assertEqual([b.text() for b in dlg.mode_btns], ["Документ", "Документ по шаблону"])
        self.assertEqual(list(dlg.doc_btns), [k for k, *_ in documents.DOCS + documents.PROFILES])
        self.assertEqual(dlg.templates.count(), len(library.TEMPLATES))
        self.assertEqual((dlg.prev_btn.text(), dlg.next_btn.text()), ("<<", ">>"))
        t0 = dlg.tip.text()
        self.assertIn("Ctrl", t0)
        dlg.next_btn.click()
        self.assertNotEqual(dlg.tip.text(), t0)
        dlg.prev_btn.click()
        self.assertEqual(dlg.tip.text(), t0)
        dlg.mode_btns[1].click()
        self.assertEqual(dlg.stack.currentIndex(), 1)
        dlg.doc_btns["drawing"].click()
        self.assertEqual(dlg.choice, ("doc", "drawing"))
        dlg.deleteLater()
        Ask.answers = {"start.choice": ("doc", "drawing")}
        w.new_project()                                   # «Создать» → стартовый экран → Чертёж
        self.assertIn("Создать", Ask.answers["_forms"])
        self.assertEqual((w.project.canvas_mode(), w.project.eskd["doc"], w.work.currentIndex()), ("A3L", "drawing", 1))
        for kind in documents.SETUP:
            Ask.answers = {}
            w.dirty = False
            w.create_document(kind)
            self.assertEqual(w.project.eskd["doc"], kind)
            self.assertEqual(w.work.currentIndex(), documents.SETUP[kind]["tab"])
            self.assertEqual(w.sheet.iso, bool(documents.SETUP[kind].get("iso")), kind)
        w.dirty = False
        w.create_document("spec")
        self.assertTrue(any(e.get("gen") == "spec" for e in w.project.drawing), "спецификация сразу строится на листе")
        self.assertEqual(stamp_size(w.project.frame)[1], 40.0)
        w.dirty = False
        w.create_document("pipe")
        self.assertEqual(w.library_panel.search.text(), "трубопровод")
        self.assertIs(w.front_dock(), w.library_dock)
        self.assertTrue(w.library_panel.visible_keys(), "раздел каталога профиля не пуст")
        Ask.answers = {"start.choice": ("template", "spec_a4")}
        w.dirty = False
        w.new_project()
        self.assertEqual(w.project.canvas_mode(), "A4P")
        w.sheet.iso = w.sketch.iso = False
        sd = SpecDialog(eskd.collect_spec(w.project), lambda: eskd.collect_spec(w.project), w)
        sd.add_row({"section": "Детали", "name": "Втулка", "designation": "АБВГ.7", "qty": "4"})
        self.assertEqual(sd.rows()[-1]["name"], "Втулка")
        sd.fill_auto()
        self.assertEqual(len(sd.rows()), len(eskd.collect_spec(w.project)))
        sd.deleteLater()


if __name__ == "__main__":
    unittest.main()
