"""«Черчение 3D» для Windows: точка входа."""
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from cad.mainwindow import MainWindow
from cad.resources import APP_NAME, icon_path, set_windows_app_id

# Оформление (QSS, палитра, цвета чертежа) задаёт cad.themes.ThemeManager при создании окна.


def selftest() -> int:
    """Проверка собранной программы: все модули грузятся, геометрия строится. Пишет selftest.txt рядом с .exe."""
    from pathlib import Path

    lines, ok = [], True
    from cad import ai

    cfg_path = ai.config_path()
    cfg_backup = cfg_path.read_bytes() if cfg_path.exists() else None   # проверка темы пишет в config.json — вернём как было
    try:
        import anthropic  # noqa: F401
        import manifold3d  # noqa: F401
        import numpy
        import OpenGL.GL  # noqa: F401
        import pyqtgraph.opengl  # noqa: F401
        from cad import ai, geometry, ops
        from cad.export2d import to_dxf
        from cad.model import Project, make_circle, make_rect

        p = Project()
        p.entities = make_rect(0, 0, 40, 30) + [make_circle(20, 15, 5)]
        ops.create_feature(p, "extrude", height=8)
        s = geometry.build_solid(p.features)
        from anthropic.types import Message  # noqa: F401 — модели pydantic в сборке

        anthropic.Anthropic(api_key="selftest")  # клиент создаётся без сетевого запроса
        lines.append(f"anthropic {anthropic.__version__}, manifold3d ok, тело: {len(s.faces)} треугольников, DXF {len(to_dxf(p))} байт")
        from cad.model import make_line
        from cad.projection import make_drawing

        ops.create_feature(p, "fillet3d", size=1)
        p.entities = [make_line(-5, 0, -5, 10, "axis")] + make_rect(0, 0, 4, 10)
        ops.create_feature(p, "revolve", angle=180)
        s = geometry.build_solid(p.features)
        bad = {k: v for k, v in s.statuses.items() if v}
        info = make_drawing(p, s)
        ok = ok and not bad and info["lines"] > 10
        lines.append(f"скругление и вращение: {'ok' if not bad else bad}, чертёж по модели: {info['lines']} линий, М {info['scale']}")
        lines.append(f"config: {ai.config_path()}")
        set_windows_app_id()
        # Самопроверка открывает второе окно: без общих GL-ресурсов его 3D-поле рисовало бы шейдерами первого окна.
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationDisplayName(APP_NAME)
        icon = QIcon(str(icon_path()))
        if icon.isNull():
            raise RuntimeError(f"иконка не загрузилась: {icon_path()}")
        app.setWindowIcon(icon)
        win = MainWindow()
        win.show()
        app.processEvents()
        from cad.themes import PRESETS

        # Все темы применяются без ошибок; выбранная пользователем тема потом возвращается.
        before = win.themes.settings()
        for pid in PRESETS:
            win.themes.set(mode="preset" if not pid.startswith("classic") else pid, preset_id=pid)
        win.show_appearance()
        app.processEvents()
        win.appearance_dlg.close()
        win.themes.set(mode=before["mode"], preset_id=before["preset"], classic_canvas=before["classic_canvas"])
        lines.append(f"тем проверено: {len(PRESETS)}, окно оформления открывается, тема восстановлена: {win.themes.theme.name}")
        from cad import ops as _ops
        from cad.view3d import AXIS_VIEW, VIEWS

        mode0 = win.project.canvas_mode()
        win.project.drawing.extend(make_rect(40, 80, 60, 40))
        seen = []
        for mode in ("fragment", "A4P", "A3L", "fragment"):
            _ops.set_canvas(win.project, mode)
            win.sheet.rebuild()
            b = win.sheet.sheet_bounds()
            seen.append("∞" if b is None else f"{b.width():.0f}×{b.height():.0f}")
        ok = ok and seen == ["∞", "210×297", "420×297", "∞"] and len(win.project.drawing) == 4
        _ops.set_canvas(win.project, mode0)
        v3 = win.view3d
        v3.set_view("iso")
        ball = next(p for a, p, r, z in v3.gizmo.balls() if a == (0, 0, 1))
        v3.animate_to(AXIS_VIEW[v3.gizmo.hit(ball)])
        v3.finish_animation()
        ok = ok and round(v3.opts["elevation"]) == VIEWS["top"][1]
        v3.set_ortho(True)
        ok = ok and v3.ortho
        v3.set_ortho(False)
        lines.append(f"полотно: {' → '.join(seen)}; гизмо: +Z → вид сверху {'ok' if round(v3.opts['elevation']) == 90 else 'НЕТ'}; орто ok")

        # Зум колесом: мировая точка под курсором до и после совпадает (фрагмент и лист А4).
        from PySide6.QtCore import QPoint, QPointF
        from PySide6.QtGui import QWheelEvent

        def wheel_drift(view, mode):
            _ops.set_canvas(win.project, mode)
            win.work.setCurrentIndex(1)
            view.rebuild()
            view.fit_sheet()
            app.processEvents()
            b = view.sheet_bounds()
            pos = view.viewportTransform().map(b.center() + QPointF(31.7, -12.3)) if b is not None else QPointF(173.4, 121.6)
            worst = 0.0
            for dy in (120, 120, 240, -120, -360, 120):
                before = view.to_scene(pos)
                ev = QWheelEvent(pos, QPointF(view.viewport().mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, dy),
                                 Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
                QApplication.sendEvent(view.viewport(), ev)
                after = view.to_scene(pos)
                worst = max(worst, abs(after.x() - before.x()), abs(after.y() - before.y()))
            return worst

        drift = {m: wheel_drift(win.sheet, m) for m in ("fragment", "A4P")}
        ok = ok and all(d < 1e-3 for d in drift.values())
        lines.append("зум к курсору: " + ", ".join(f"{m} сдвиг {d:.1e} мм" for m, d in drift.items())
                     + (" ok" if all(d < 1e-3 for d in drift.values()) else " ОШИБКА"))

        # Тёмная тема переживает 2D → 3D → 2D (А4 → фрагмент) и перезагрузку config.json.
        from cad.themes import ThemeManager, qss

        win.themes.set(mode="classic-dark")
        for tab, mode in ((0, None), (2, None), (1, "A4P"), (1, "fragment"), (0, None)):
            win.work.setCurrentIndex(tab)
            if mode:
                win.set_canvas(mode)
            app.processEvents()
        views_dark = all(v.theme is win.themes.theme for v in (win.sketch, win.sheet, win.view3d)) and app.styleSheet() == qss(win.themes.theme)
        saved = ai.load_config()
        reloaded = ThemeManager(saved.get("appearance", {}), saved.get("active_theme"))
        win.dirty = False
        win.close()
        win2 = MainWindow()   # «перезапуск»: новое окно читает config.json заново
        win2.show()
        app.processEvents()
        restart_dark = win2.themes.mode == "classic-dark" and win2.sketch.col["paper1"].lightness() < 80
        frozen_ok = not getattr(sys, "frozen", False) or cfg_path == Path(sys.executable).resolve().parent / "config.json"
        theme_ok = views_dark and reloaded.active_id() == "classic-dark" and saved.get("active_theme") == "classic-dark" and restart_dark and frozen_ok
        ok = ok and theme_ok
        lines.append(f"тема: тёмная после 2D → 3D → 2D (А4 → фрагмент) и перезапуска — {'ok' if theme_ok else 'ОШИБКА'}"
                     f" (поля {views_dark}, config {saved.get('active_theme')}, новое окно {win2.themes.theme.name}, config рядом с exe {frozen_ok})")

        # Параметрика как в КОМПАС: длина от начала по прежнему углу, Ø ↔ R, управляющий размер, перестроение 3D.
        import math

        from cad import params
        from cad.model import make_dim, make_line

        win2._replace_project(Project(), None)
        ln = make_line(10, 20, 10 + 100 * math.cos(math.radians(30)), 20 + 50)
        circ = make_circle(100, 100, 20)
        win2.project.entities += [ln, circ]
        win2.refresh()
        win2.sketch.select([ln["id"]])
        win2.prop_spins["length"].setValue(250)
        app.processEvents()
        e = win2.project.find(ln["id"])
        line_ok = abs(params.line_length(e) - 250) < 1e-9 and abs(params.line_angle(e) - 30) < 1e-9 and (e["x1"], e["y1"]) == (10, 20)
        win2.undo()
        undo_ok = abs(params.line_length(win2.project.find(ln["id"])) - 100) < 1e-9
        win2.redo()
        win2.sketch.select([circ["id"]])
        win2.prop_spins["d"].setValue(85)
        app.processEvents()
        c = win2.project.find(circ["id"])
        circle_ok = c["r"] == 42.5 and (c["cx"], c["cy"]) == (100, 100)
        e = win2.project.find(ln["id"])
        dim = params.attach_dim(win2.project, make_dim(e["x1"], e["y1"], e["x2"], e["y2"], 10))
        win2.project.drawing.append(dim)
        win2._edit(lambda: params.drive_dim(win2.project, dim, 150))
        drive_ok = abs(params.line_length(win2.project.find(ln["id"])) - 150) < 1e-9
        win2._replace_project(Project(), None)
        win2.project.entities = make_rect(0, 0, 80, 50) + [make_circle(40, 25, 10)]
        ops.create_feature(win2.project, "extrude", height=10)
        win2.refresh()
        sk = win2.project.features[0]["sketch"]
        sides = params.rect_lines(sk, sk[0]["id"])
        win2._edit(lambda: params.set_rect_param(sides, "w", 100))
        lo, hi = win2.solid.bbox()
        rebuild_ok = abs(float(hi[0] - lo[0]) - 100) < 1e-6
        par_ok = line_ok and undo_ok and circle_ok and drive_ok and rebuild_ok
        ok = ok and par_ok
        checks = {"L 100→250, α 30°": line_ok, "Ctrl+Z": undo_ok, "Ø85 → R42,5": circle_ok, "размер → длина": drive_ok,
                  "3D после правки эскиза": rebuild_ok}
        lines.append("параметрика КОМПАС: " + "; ".join(f"{k} {'ok' if v else 'ОШИБКА'}" for k, v in checks.items()))
        win2.dirty = False

        # Выделение как в КОМПАС: окно и секущая рамка, общая длина группы, ПКМ-редактор, разбиение прямоугольника.
        win2._replace_project(Project(), None)
        ls = [make_line(0, 0, 40, 0), make_line(0, 20, 30, 50), make_line(60, 0, 60, 25)]
        win2.project.entities += ls + make_rect(100, 0, 30, 20)
        win2.refresh()
        v = win2.sketch
        v.fit_all()
        lid = [x["id"] for x in ls]
        v._box = {"start": (-5, -5), "cur": (45, 30), "add": False}
        v.finish_box(False)
        window_ok = v.selected == [lid[0]]
        v._box = {"start": (45, 30), "cur": (-5, -5), "add": False}
        v.finish_box(False)
        crossing_ok = set(v.selected) == {lid[0], lid[1]}
        v.select(lid)
        win2.prop_spins["length"].setValue(75)
        app.processEvents()
        win2._group_style(v, "thin")
        group_ok = all(abs(params.line_length(win2.project.find(i)) - 75) < 1e-9 and win2.project.find(i)["style"] == "thin" for i in lid)
        v.select([])
        v.right_click(20, 0, QPoint(400, 300))
        win2.ctx_editor.fields["length"].setValue(90)
        app.processEvents()
        rmb_ok = abs(params.line_length(win2.project.find(lid[0])) - 90) < 1e-9
        win2.undo()
        rmb_ok = rmb_ok and abs(params.line_length(win2.project.find(lid[0])) - 75) < 1e-9
        win2.ctx_editor.close()
        v.select([])
        v.right_click(115, 20, QPoint(400, 300))
        rect_ids = list(v.selected)
        win2.ctx_editor.actions["explode"].click()
        app.processEvents()
        explode_ok = len(rect_ids) == 4 and all("rect" not in win2.project.find(i) for i in rect_ids)
        sel_checks = {"окно": window_ok, "секущая": crossing_ok, "группа L/стиль": group_ok, "ПКМ + Ctrl+Z": rmb_ok,
                      "разбить прямоугольник": explode_ok}
        ok = ok and all(sel_checks.values())
        lines.append("выделение и ПКМ: " + "; ".join(f"{k} {'ok' if val else 'ОШИБКА'}" for k, val in sel_checks.items()))
        win2.dirty = False

        # Библиотека: все элементы во всех поворотах, все шаблоны, вставка с поворотом, свой элемент.
        import tempfile

        from cad import library

        real_user_path = library.user_path
        tmp_lib = Path(tempfile.mkdtemp(prefix="recad_selftest_")) / "user_library.json"
        library.user_path = lambda: tmp_lib   # «Мои элементы» пользователя не трогаем
        library.reload_user()
        try:
            for b in library.BLOCKS.values():
                for rot in (0, 90, 180, 270):
                    assert len({e["blk"] for e in library.instantiate(b.id, 10, 10, rot, 1.5)}) == 1, b.id
            for tid in library.TEMPLATES:
                library.load_template(Project(), tid)
            win2.open_template("single_line_a4")
            win2.insert_block("qf1")
            v = win2.sheet
            win2._hotkey(v, "rect")               # R — поворот на 90°
            n0 = len(win2.project.drawing)
            v.click(100, 150)
            placed = win2.project.drawing[n0:]
            out = library.ports_world("qf1", 100, 150, 90)["выход"]
            rotated = any(abs(e.get("x2", 0) - out[0]) < 1e-6 and abs(e.get("y2", 0) - out[1]) < 1e-6 for e in placed)
            v.select([e["id"] for e in placed])
            library.save_user_block("Самопроверка", placed)
            reused = len(library.instantiate(next(iter(library.user_blocks())), 0, 0)) == len(placed)
            lib_ok = rotated and reused and tmp_lib.exists() and len(win2.library_panel.items) >= len(library.BLOCKS) + len(library.TEMPLATES)
        finally:
            library.user_path = real_user_path
            library.reload_user()
        ok = ok and lib_ok
        lines.append(f"библиотека: элементов {len(library.BLOCKS)}, шаблонов {len(library.TEMPLATES)}, вставка с поворотом "
                     f"{'ok' if rotated else 'ОШИБКА'}, «Мои элементы» {'ok' if reused else 'ОШИБКА'}")

        # Вложения ИИ: Word (текст, таблица, рисунок); фото → сжатие, анализ, Vision-запрос в Base64 в форматах
        # Anthropic / OpenAI / Gemini; ответные команды строят деталь. Серверы подменены — без сети и без ключа.
        import json as _json
        import shutil
        from types import SimpleNamespace

        from cad import attachments as att_mod, samples

        tmp_att = Path(tempfile.mkdtemp(prefix="recad_attach_"))
        real_post, real_client, cfg_mem = ai._post_json, anthropic.Anthropic, dict(win2.cfg)
        sent, built = {}, {}
        try:
            doc = att_mod.docx_attachments(samples.spec_docx(), "ТЗ.docx")
            docx_ok = ("# Техническое задание" in doc[0].text and "| Длина, мм | 120 |" in doc[0].text
                       and doc[0].tables == [samples.SPEC_ROWS] and [a.kind for a in doc] == ["docx", "image"])
            (tmp_att / "plate.jpg").write_bytes(samples.plate_image(3200, 2400, "JPEG"))
            (tmp_att / "ТЗ.docx").write_bytes(samples.spec_docx())
            win2.attach_files([str(tmp_att / "plate.jpg"), str(tmp_att / "ТЗ.docx")])
            win2.wait_attachments()
            loaded = list(win2.attachments)
            pic = next(a for a in loaded if a.name == "plate.jpg")
            holes = [g for g in pic.info.get("массивы_отверстий", []) if g["число"] == 4]
            vision_ok = (pic.size == (1600, 1200) and pic.data[:2] == b"\xff\xd8" and bool(holes)
                         and len(win2.attach_bar.chips) == 3)
            reply = _json.dumps({"message": "Пластина", "actions": [
                {"op": "add_rect", "x": 0, "y": 0, "w": 120, "h": 80}, {"op": "add_circle", "cx": 60, "cy": 40, "d": 30},
                {"op": "add_dim", "x1": 0, "y1": 0, "x2": 120, "y2": 0, "off": -10, "kind": "horizontal"},
                {"op": "extrude", "height": 10}]})

            class FakeClaude:
                def __init__(self, **kw):
                    self.messages = self.beta = self

                def create(self, **kw):
                    sent["anthropic"] = kw["messages"][-1]["content"]
                    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=reply)])

            def fake_post(url, body, headers, timeout=0):
                if ":generateContent" in url:
                    sent["gemini"] = body["contents"][-1]["parts"]
                    return {"candidates": [{"content": {"parts": [{"text": reply}]}}]}
                sent["openai"] = body["messages"][-1]["content"]
                return {"choices": [{"message": {"content": reply}}]}
            ai._post_json, anthropic.Anthropic = fake_post, FakeClaude
            for prov, model in (("anthropic", "claude-opus-5-5"), ("openai", "gpt-selftest"), ("gemini", "gemini-selftest")):
                win2._replace_project(Project(), None)
                win2.work.setCurrentIndex(0)
                win2.attachments = list(loaded)
                win2.attach_bar.set_items(win2.attachments)
                win2.cfg.update(provider=prov, api_key="selftest", model=model)
                win2.ai_preset("photo_part")
                if win2.worker is not None:
                    win2.worker.wait(20000)
                app.processEvents()
                app.processEvents()
                lo, hi = (win2.solid.bbox() if not win2.solid.empty else ((0, 0, 0), (0, 0, 0)))
                built[prov] = [round(float(h - l), 3) for l, h in zip(lo, hi)] == [120, 80, 10]
            fmt_ok = (any(b.get("type") == "image" and b["source"]["type"] == "base64" and b["source"]["media_type"] == "image/jpeg"
                          for b in sent.get("anthropic", []))
                      and any(b.get("type") == "image_url" and b["image_url"]["url"].startswith("data:image/jpeg;base64,")
                              for b in sent.get("openai", []))
                      and any("inlineData" in b for b in sent.get("gemini", []))
                      and any("| Длина, мм | 120 |" in b.get("text", "") for b in sent.get("openai", [])))
        finally:
            ai._post_json, anthropic.Anthropic = real_post, real_client
            win2.cfg.clear()
            win2.cfg.update(cfg_mem)
            win2.attachments = []
            win2.attach_bar.set_items([])
            shutil.rmtree(tmp_att, ignore_errors=True)
        attach_ok = docx_ok and vision_ok and fmt_ok and all(built.values()) and len(built) == 3
        ok = ok and attach_ok
        lines.append(f"вложения: Word — текст, таблица, рисунок {'ok' if docx_ok else 'ОШИБКА'}; фото 3200×2400 → {pic.size[0]}×{pic.size[1]} "
                     f"JPEG, 4 отверстия по окружности {'ok' if vision_ok else 'ОШИБКА'}; Vision-запрос Base64 (Anthropic image, "
                     f"OpenAI image_url, Gemini inlineData) {'ok' if fmt_ok else 'ОШИБКА'}; ответ ИИ → деталь 120×80×10 "
                     + ", ".join(f"{k} {'ok' if v else 'ОШИБКА'}" for k, v in built.items()))

        # Прямое редактирование в 3D: щелчок по грани — стрелка «H: 10.0 мм»; перетаскивание к 25 — поле панели и фантом,
        # тело ещё прежнее; отпускание — вершины меша на новой высоте, виды на листе перестроены; Ctrl+Z — обратно.
        from cad.dims import render as _render

        win2._replace_project(Project(), None)
        win2.project.entities += make_rect(0, 0, 80, 50) + [make_circle(40, 25, 10)]
        ops.create_feature(win2.project, "extrude", height=10)
        win2.refresh(fit3d=True)
        win2.drawing_from_model()
        win2.work.setCurrentIndex(2)
        v3 = win2.view3d
        v3.set_view("iso")
        v3.home()
        app.processEvents()
        v3.pick(v3.project((10, 10, 10)))
        m3 = v3.manip
        top0 = int(numpy.isclose(win2.solid.verts[:, 2], 10).sum())
        d3 = {"грань → стрелка H: 10.0 мм": m3.handle is not None and m3.text() == "H: 10.0 мм"}
        m3.set_value(25)
        spin = win2.prop_spins.get("height")
        d3["поле панели и фантом во время перетаскивания"] = (spin is not None and spin.value() == 25 and bool(v3.ghost)
                                                             and float(win2.solid.bbox()[1][2]) == 10.0)
        m3.end()
        zs = sorted({round(float(z), 4) for z in win2.solid.verts[:, 2]})
        dims = [_render(e).texts[0][3] for e in win2.project.drawing if e.get("gen") == "views" and e["type"] == "dim"]
        d3["меш: вершины на 25 мм"] = zs == [0.0, 25.0] and int(numpy.isclose(win2.solid.verts[:, 2], 25).sum()) == top0
        d3["виды на листе перестроены"] = "25" in dims
        win2.undo()
        d3["Ctrl+Z"] = win2.project.features[0]["height"] == 10 and m3.text() == "H: 10.0 мм"
        m3.detach()
        ok = ok and all(d3.values())
        lines.append("3D-манипулятор: " + "; ".join(f"{k} {'ok' if v else 'ОШИБКА'}" for k, v in d3.items()))
        win2.dirty = False

        # «ИИ-помощник» открывает чат, а не соседнюю вкладку «Библиотека»; в «О программе» нет путей пользователя.
        fronts = []
        win2.ai_action.trigger()
        app.processEvents()
        fronts.append(win2.front_dock() is win2.ai_dock)
        win2.ribbon_actions["ИИпомощник"].click()          # повторное нажатие не прячет помощника
        app.processEvents()
        fronts.append(win2.front_dock() is win2.ai_dock)
        win2.ribbon_actions["Каталог элементов"].click()
        app.processEvents()
        fronts.append(win2.front_dock() is win2.library_dock)
        win2.ribbon_actions["ИИпомощник"].click()
        app.processEvents()
        fronts.append(win2.front_dock() is win2.ai_dock and win2.ai_dock.widget() is win2.ai_panel)
        box = win2.show_about(run=False)
        about = box.text()
        about_ok = "Файл настроек" not in about and "config.json" not in about and str(cfg_path.parent) not in about
        # Название «Черчение 3D» в окне, справке и приложении; памятка о Vision-моделях — в справке и в «Настройках ИИ».
        from cad.dialogs import AISettingsDialog

        dlg = AISettingsDialog(win2.cfg, win2)
        memo = dlg.vision_note.text()
        dlg.deleteLater()
        names = {"окно": "Черчение 3D" in win2.windowTitle(), "справка": "Черчение 3D" in box.windowTitle() and "Черчение 3D" in about,
                 "приложение": app.applicationDisplayName() == app.applicationName() == "Черчение 3D",
                 "без ReCAD": "ReCAD" not in win2.windowTitle() + about}
        vision = all(m in t for m in ("gemini-2.5-flash", "llama-4-scout") for t in (about, memo)) and "Vision" in about
        box.deleteLater()
        ok = ok and all(fronts) and about_ok and all(names.values()) and vision
        lines.append(f"панели: ИИ-помощник → чат {'ok' if all(fronts) else 'ОШИБКА ' + str(fronts)}; "
                     f"«О программе» без путей {'ok' if about_ok else 'ОШИБКА'}")
        lines.append("название «Черчение 3D»: " + ", ".join(f"{k} {'ok' if v else 'ОШИБКА'}" for k, v in names.items())
                     + f"; памятка о Vision-моделях (gemini-2.5-flash, llama-4-scout) в справке и «Настройках ИИ» {'ok' if vision else 'ОШИБКА'}")
        win2.dirty = False
        win2.close()
        lines.append(f"иконка окна: {'есть' if not win.windowIcon().isNull() else 'НЕТ'}, размеры {sorted(s.width() for s in icon.availableSizes())}")
        lines.append("окно создано и закрыто")
    except Exception as exc:  # noqa: BLE001
        ok = False
        lines.append(f"ОШИБКА: {exc!r}")
    finally:
        try:
            if cfg_backup is None:
                cfg_path.unlink(missing_ok=True)
            else:
                cfg_path.write_bytes(cfg_backup)
        except OSError as exc:
            ok = False
            lines.append(f"не удалось вернуть config.json: {exc!r}")
    out =(Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent) / "selftest.txt"
    out.write_text(("OK\n" if ok else "FAIL\n") + "\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    set_windows_app_id()  # до QApplication: иначе на панели задач значок Python
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(QIcon(str(icon_path())))
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    win = MainWindow()
    win.show()
    # Двойной щелчок по .k3d в Проводнике передаёт путь первым аргументом.
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".k3d"):
        win.open_project(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
