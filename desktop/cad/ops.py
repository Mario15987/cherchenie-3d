"""Операции над проектом, общие для интерфейса и ИИ-помощника."""
from __future__ import annotations

from . import edit2d
from . import geometry as geo
from . import library
from . import params
from .dims import check_tolerance
from .model import (
    CANVAS_MODES, FEATURE_LABEL, FORMATS, Project, default_frame, make_arc, make_circle, make_diadim, make_dim, make_leader, make_line,
    make_raddim, make_rect, make_rough, make_text, new_id,
)

SKETCH_FEATURES = ("extrude", "cut", "revolve")


def create_feature(project: Project, kind: str, **params) -> dict:
    """Добавляет операцию в дерево. Операции по эскизу забирают текущий эскиз себе (как в КОМПАС):
    правка этого эскиза потом перестраивает модель."""
    if kind == "cut":
        kind, params = "extrude", {**params, "op": "cut"}
    if kind not in FEATURE_LABEL:
        raise ValueError(f"неизвестная операция {kind}")
    f = {"id": new_id(), "type": kind, "op": params.get("op", "add"), "sketch": []}
    if f["op"] not in ("add", "cut", "intersect"):
        raise ValueError("операция: add (объединение), cut (вычитание) или intersect (пересечение)")
    label = FEATURE_LABEL["cut" if kind == "extrude" and f["op"] == "cut" else kind]
    if kind in SKETCH_FEATURES:
        c = geo.contours(project.profile_entities())
        if not c.closed:
            hint = f" Незамкнутых цепочек: {c.open_chains} — используйте «Замкнуть контуры»." if c.open_chains else ""
            raise ValueError("В эскизе нет замкнутых контуров." + hint)
        if kind == "revolve":
            geo.revolve_axis({"sketch": project.entities})  # проверка: есть осевая линия
            angle = float(params.get("angle", 360))
            if not 0 < angle <= 360:
                raise ValueError("угол вращения от 0 до 360°")
            f["angle"] = angle
        elif f["op"] == "cut":
            through = bool(params.get("through", "depth" not in params))
            f.update(through=through, depth=float(params.get("depth", 5)))
            if not through and f["depth"] <= 0:
                raise ValueError("Глубина должна быть больше нуля")
        else:
            h = float(params.get("height", 10))
            if h <= 0:
                raise ValueError("Высота должна быть больше нуля")
            f.update(height=h, base="top" if params.get("base") == "top" else "plane")
        f["sketch"] = list(project.entities)
        project.entities.clear()
    elif kind == "shell":
        t = float(params.get("thickness", 2))
        if t <= 0:
            raise ValueError("Толщина стенки должна быть больше нуля")
        f.update(thickness=t, open_top=bool(params.get("open_top", True)))
    else:  # fillet3d, chamfer3d
        size = float(params.get("size", 2))
        if size <= 0:
            raise ValueError("Размер должен быть больше нуля")
        f["size"] = size
    if kind not in SKETCH_FEATURES and not any(x["type"] in SKETCH_FEATURES for x in project.features):
        raise ValueError("Сначала постройте тело выдавливанием или вращением")
    seq = 1 + sum(1 for x in project.features if x.get("name", "").startswith(label + ":"))
    f["name"] = f"{label}:{seq}"
    project.features.append(f)
    return f


def set_frame(project: Project, fmt="A3", orient="landscape", x=None, y=None, scale=None):
    if fmt not in FORMATS:
        raise ValueError(f"Формат {fmt} не поддерживается: {', '.join(FORMATS)}")
    if orient not in ("landscape", "portrait"):
        raise ValueError("ориентация: landscape (альбомная) или portrait (книжная)")
    fr = project.frame or default_frame()
    fr.update(format=fmt, orient=orient)
    if x is not None:
        fr["x"] = float(x)
    if y is not None:
        fr["y"] = float(y)
    if scale:
        fr["scale"] = str(scale)
    project.frame = fr
    project.canvas = "sheet"


def set_canvas(project: Project, mode: str):
    """Формат полотна: fragment — бесконечное поле, иначе лист (A4P, A4L, A3L, A3P…). Чертёж не трогается:
    на фрагменте рамка и штамп скрываются, но их данные остаются в проекте."""
    if mode not in CANVAS_MODES:
        raise ValueError(f"формат полотна: {', '.join(CANVAS_MODES)}")
    _, fmt, orient = CANVAS_MODES[mode]
    if fmt is None:
        project.canvas = "fragment"
    else:
        set_frame(project, fmt, orient)


NUMERIC = {"line": ("x1", "y1", "x2", "y2"), "circle": ("cx", "cy", "r"), "arc": ("cx", "cy", "r", "a0", "a1"),
           "dim": ("x1", "y1", "x2", "y2", "off"), "diadim": ("cx", "cy", "r", "ang"), "raddim": ("cx", "cy", "r", "ang"),
           "angdim": ("cx", "cy", "a1", "a2", "rad"), "leader": ("x1", "y1", "x2", "y2"), "rough": ("x", "y"),
           "hatch": ("step", "angle"), "text": ("x", "y", "h", "ang")}
from .model import STYLES as STYLE_OK  # noqa: E402 — все девять типов линий ГОСТ 2.303


def feature_value(f: dict) -> tuple | None:
    """Главное число операции — для панели «Параметры», быстрого ввода и 3D-ручки: (ключ, подпись, значение, мин, макс).
    У выреза «через всё» числа нет."""
    t = f["type"]
    if t == "cut" or (t == "extrude" and f.get("op") == "cut"):
        return None if f.get("through") else ("depth", "Глубина выреза, мм", float(f.get("depth", 5)), 0.01, 1e5)
    if t == "extrude":
        return ("height", "Высота выдавливания H, мм", float(f["height"]), 0.01, 1e5)
    if t == "revolve":
        return ("angle", "Угол вращения, °", float(f.get("angle", 360)), 0.1, 360)
    if t == "shell":
        return ("thickness", "Толщина стенки, мм", float(f["thickness"]), 0.01, 1e4)
    if t in ("fillet3d", "chamfer3d"):
        return ("size", "Радиус, мм" if t == "fillet3d" else "Катет фаски, мм", float(f["size"]), 0.01, 1e4)
    return None


def feature_from_layer(project: Project, ents: list, kind: str, kw: dict, region=None) -> tuple[dict, bool]:
    """Операция по эскизу из слоя, в котором работает ИИ. Эскиз: контуры уходят в операцию (region [x0, y0, x1, y1] —
    только кривые внутри прямоугольника). Лист: если задан region или в эскизе нет замкнутых контуров, кривые листа
    (основные и осевые, без элементов библиотеки и видов по модели) копируются в операцию — лист не меняется,
    как у «Выдавить в 3D» для выделенного на листе. Возвращает (операция, скопировано ли с листа)."""
    own = ents is project.entities
    if region is None and (own or geo.contours(project.profile_entities()).closed):
        return create_feature(project, kind, **kw), False
    pick = [e for e in ents if e["type"] in ("line", "circle", "arc") and not e.get("blk") and not e.get("gen")
            and (own or e.get("style") in ("main", "axis"))]
    if region is not None:
        x0, y0, x1, y1 = (float(v) for v in region)
        x0, x1, y0, y1 = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
        pick = [e for e in pick if _inside(library.bounds([e]), (x0 - 1e-6, y0 - 1e-6, x1 + 1e-6, y1 + 1e-6))]
    if not pick:
        raise ValueError("в выбранной области нет отрезков, дуг и окружностей" if region is not None else "на листе нет контуров")
    saved = project.entities
    ids = {e["id"] for e in pick}
    project.entities = [e for e in saved if e["id"] in ids] if own else [edit2d._copy(e) for e in pick]
    try:
        f = create_feature(project, kind, **kw)
    except ValueError:
        project.entities = saved
        raise
    project.entities = [e for e in saved if e["id"] not in ids] if own else saved
    return f, not own


def _inside(b, r) -> bool:
    return r[0] <= b[0] and r[1] <= b[1] and b[2] <= r[2] and b[3] <= r[3]


def apply_actions(project: Project, actions: list, target: list | None = None) -> list[str]:
    """Выполняет команды ИИ над эскизом target (по умолчанию — текущий эскиз). Каждая команда — отдельно:
    ошибка одной не отменяет остальные. Возвращает журнал."""
    ents = project.entities if target is None else target
    log = []
    for i, a in enumerate(actions if isinstance(actions, list) else []):
        op = a.get("op") if isinstance(a, dict) else None
        style = a.get("style") if isinstance(a, dict) and a.get("style") in STYLE_OK else "main"
        try:
            if op == "add_line":
                ents.append(make_line(a["x1"], a["y1"], a["x2"], a["y2"], style))
            elif op == "add_axis":
                ents.append(make_line(a["x1"], a["y1"], a["x2"], a["y2"], "axis"))
            elif op == "add_polyline":
                pts = a["points"]
                if len(pts) < 2:
                    raise ValueError("нужно хотя бы две точки")
                pairs = list(zip(pts, pts[1:])) + ([(pts[-1], pts[0])] if a.get("closed") else [])
                ents.extend(make_line(p[0], p[1], q[0], q[1], style) for p, q in pairs)
            elif op == "add_rect":
                ents.extend(make_rect(a["x"], a["y"], a["w"], a["h"], style))
            elif op == "add_circle":
                r = a["r"] if "r" in a else float(a["d"]) / 2
                ents.append(make_circle(a["cx"], a["cy"], r, style))
            elif op == "add_arc":
                ents.append(make_arc(a["cx"], a["cy"], a["r"], a["a0"], a["a1"], style))
            elif op == "add_dim":
                d = make_dim(a["x1"], a["y1"], a["x2"], a["y2"], a.get("off", 8), a.get("kind", "aligned"))
                d["tol"] = check_tolerance(a.get("tol", ""))
                project.drawing.append(params.attach_dim(project, d))
            elif op in ("add_diadim", "add_raddim"):
                mk = make_diadim if op == "add_diadim" else make_raddim
                d = mk(a["cx"], a["cy"], a["r"], a.get("ang", 45))
                d["tol"] = check_tolerance(a.get("tol", ""))
                project.drawing.append(params.attach_dim(project, d))
            elif op == "set_dim_value":
                d = project.find(a["id"])
                if d is None:
                    raise ValueError(f"нет размера {a['id']}")
                params.drive_dim(project, d, a["value"])
            elif op == "add_leader":
                project.drawing.append(make_leader(a["x1"], a["y1"], a["x2"], a["y2"], a["text"]))
            elif op == "add_rough":
                project.drawing.append(make_rough(a["x"], a["y"], a.get("value", "3,2"), a.get("param", "Ra")))
            elif op == "delete":
                if not project.remove(a.get("ids", [])):
                    raise ValueError("объекты не найдены")
            elif op == "update":
                e = project.find(a["id"])
                if e is None:
                    raise ValueError(f"нет объекта {a['id']}")
                lines = params.rect_lines(project.container_of(e["id"]) or [], e["id"])
                for k, v in a.items():
                    if lines and k in ("w", "h"):
                        params.set_rect_param(lines, k, v)
                    elif k in NUMERIC.get(e["type"], ()) or k in ("length", "angle", "d"):
                        params.set_param(e, k, v)
                    elif k == "axes" and e["type"] in ("circle", "arc"):
                        e["axes"] = bool(v)
                    elif k == "style" and v in STYLE_OK:
                        e[k] = v
                    elif k == "tol":
                        e[k] = check_tolerance(v)
                if e["type"] in ("circle", "arc") and e["r"] <= 0:
                    raise ValueError("радиус должен быть больше нуля")
            elif op == "move":
                dx, dy = float(a.get("dx", 0)), float(a.get("dy", 0))
                for eid in a.get("ids", []):
                    e = project.find(eid)
                    if e is not None:
                        edit2d._map_points(e, lambda p: (p[0] + dx, p[1] + dy))
            elif op == "clear_sketch":
                ents.clear()
            elif op == "close_contours":
                log.append(f"✓ close_contours: исправлено стыков {geo.fix_gaps(ents, float(a.get('tol', 1.0)))}")
                continue
            elif op == "fillet_corner":
                edit2d.fillet(ents, a["id1"], a["p1"], a["id2"], a["p2"], float(a["r"]))
            elif op == "chamfer_corner":
                edit2d.chamfer(ents, a["id1"], a["p1"], a["id2"], a["p2"], float(a["d"]), a.get("d2"))
            elif op == "mirror":
                edit2d.mirror(ents, a["ids"], a["p"], a["q"], bool(a.get("keep", True)))
            elif op == "pattern_circular":
                edit2d.pattern_circular(ents, a["ids"], a["center"], int(a["count"]), float(a.get("angle", 360)))
            elif op == "pattern_linear":
                edit2d.pattern_linear(ents, a["ids"], int(a.get("nx", 1)), int(a.get("ny", 1)), float(a.get("dx", 0)), float(a.get("dy", 0)))
            elif op in ("extrude", "cut", "cut_extrude", "revolve", "shell", "fillet3d", "chamfer3d"):
                kind = "cut" if op == "cut_extrude" else op
                kw = dict(a)
                kw.pop("op")
                region = kw.pop("region", None)
                if kw.get("op_mode") in ("add", "cut", "intersect"):
                    kw["op"] = kw.pop("op_mode")
                kw.pop("op_mode", None)
                if kind == "cut" and not kw.get("through") and "depth" not in kw:
                    kw["through"] = True
                if kind in SKETCH_FEATURES:
                    f, copied = feature_from_layer(project, ents, kind, kw, region)
                else:
                    f, copied = create_feature(project, kind, **kw), False
                log.append(f"✓ {f['name']}" + (" (контуры скопированы с листа)" if copied else ""))
                continue
            elif op == "add_frame":
                set_frame(project, a.get("format", "A3"), a.get("orient", "landscape"), a.get("x"), a.get("y"), a.get("scale"))
            elif op == "set_canvas":
                set_canvas(project, a.get("mode", "fragment"))
            elif op == "add_text":
                ents.append(make_text(a["x"], a["y"], a["text"], a.get("h", 3.5), a.get("ang", 0), a.get("align", "left")))
            elif op == "add_wall":
                ents.extend(library.wall_segment(float(a["x1"]), float(a["y1"]), float(a["x2"]), float(a["y2"]), float(a.get("t", library.WALL_T)),
                                                 bool(a.get("hatch", True))))
            elif op == "insert_library_block":
                ents.extend(library.instantiate(str(a["block_id"]), a.get("x", 0), a.get("y", 0), a.get("rotation", a.get("rot", 0)),
                                                a.get("scale", 1), a.get("label")))
            elif op == "load_template":
                library.load_template(project, str(a["template_id"]))
                ents = project.drawing    # дальше команды ложатся на лист шаблона
            elif op == "set_props":
                for k in ("name", "designation", "material"):
                    if k in a:
                        setattr(project, k, str(a[k]))
            else:
                raise ValueError(f"неизвестная команда {op!r}")
            log.append(f"✓ {op}")
        except (KeyError, TypeError, IndexError) as exc:
            log.append(f"✗ команда {i + 1} ({op}): не хватает или неверный параметр {exc}")
        except ValueError as exc:
            log.append(f"✗ команда {i + 1} ({op}): {exc}")
    params.sync_dims(project)   # размеры — за изменённой геометрией
    return log
