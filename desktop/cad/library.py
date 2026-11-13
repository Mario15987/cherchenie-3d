"""Библиотека шаблонов и элементов: УГО электрических схем (ГОСТ 2.721, 2.755), элементы ВЛ, строительные элементы
планов (СПДС, ГОСТ Р 21.101), стандартные изделия и прокат (ЕСКД), готовые листы и «Мои элементы».

Элемент — функция, которая рисует примитивы в своей системе координат: (0, 0) — точка вставки, у схемных элементов это
верхний вывод, элемент идёт вниз. Вставка: масштаб, поворот, перенос; все примитивы экземпляра помечены общим "blk",
маркировка (QF1, ОП-12, марка оси) — надпись того же экземпляра. Строительные элементы нарисованы в М1:100 (1 мм на
листе = 100 мм), стандартные изделия — в натуральную величину.

Свои элементы хранятся в user_library.json рядом с программой.
"""
from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass, field
from typing import Callable

from .model import make_arc, make_circle, make_dim, make_hatch, make_leader, make_line, make_rect, make_text, new_id

SECTIONS = {
    "electro": "Электротехника и энергетика (ГОСТ 2.721, 2.755)",
    "build": "Строительство и архитектура (СПДС, ГОСТ Р 21.101)",
    "mech": "Машиностроение и металлоконструкции (ЕСКД)",
    "user": "Мои элементы",
}


@dataclass
class Block:
    id: str
    name: str
    section: str
    group: str
    build: Callable[[], list]
    ports: dict = field(default_factory=dict)   # имя вывода -> (x, y) в системе элемента
    label: str = ""                              # маркировка по умолчанию (QF1, ОП-1, 1…)
    label_at: tuple = (4.0, -10.0)               # линия основания маркировки
    label_align: str = "left"
    label_h: float = 3.5
    keywords: str = ""
    note: str = ""

    def entities(self) -> list[dict]:
        return self.build()


@dataclass
class Template:
    id: str
    name: str
    section: str
    canvas: str            # A4P, A3L…
    title: str             # наименование в штампе
    build: Callable        # build(project, area) — area = (x0, y0, x1, y1) рабочего поля над штампом
    keywords: str = ""
    scale: str = "1:1"


BLOCKS: dict[str, Block] = {}
CHAR_W = 0.8   # ширина знака курсива на экране и в SVG ≈ 0,8 высоты — по ней подгоняем надписи в графы
TEMPLATES: dict[str, Template] = {}


def block(bid, name, section, group, ports=None, label="", at=(4.0, -10.0), align="left", h=3.5, kw="", note=""):
    def deco(fn):
        BLOCKS[bid] = Block(bid, name, section, group, fn, ports or {}, label, at, align, h, kw, note)
        return fn
    return deco


def template(tid, name, section, canvas, title, kw="", scale="1:1"):
    def deco(fn):
        TEMPLATES[tid] = Template(tid, name, section, canvas, title, fn, kw, scale)
        return fn
    return deco


# ---------------------------------------------------------------- примитивы
def L(x1, y1, x2, y2, st="main"):
    return [make_line(x1, y1, x2, y2, st)]


def C(cx, cy, r, st="main"):
    return [make_circle(cx, cy, r, st)]


def A(cx, cy, r, a0, a1, st="main"):
    return [make_arc(cx, cy, r, a0, a1, st)]


def P(pts, st="main", closed=False):
    pairs = list(zip(pts, pts[1:])) + ([(pts[-1], pts[0])] if closed else [])
    return [make_line(*a, *b, st) for a, b in pairs]


def R(x, y, w, h, st="main"):
    return make_rect(x, y, w, h, st)


def T(x, y, s, h=3.5, align="left", ang=0.0):
    return [make_text(x, y, s, h, ang, align)]


def HATCH(polys, pattern="metal", step=1.5, angle=45.0):
    return [make_hatch(polys, pattern, step, angle)]


def rect_pts(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def hexagon(r, rot=0.0):
    return [(r * math.cos(math.radians(rot + 60 * k)), r * math.sin(math.radians(rot + 60 * k))) for k in range(6)]


def axis_cross(r, cx=0.0, cy=0.0):
    return L(cx - r, cy, cx + r, cy, "axis") + L(cx, cy - r, cx, cy + r, "axis")


def wall_segment(x1, y1, x2, y2, t=3.8, hatch=True):
    """Стена по оси (x1, y1)–(x2, y2) толщиной t: две грани, торцы и штриховка кладки 45°."""
    L_ = math.hypot(x2 - x1, y2 - y1)
    if L_ < 1e-9:
        raise ValueError("стена нулевой длины")
    nx, ny = -(y2 - y1) / L_ * t / 2, (x2 - x1) / L_ * t / 2
    pts = [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)]
    out = P(pts, "main", closed=True)
    if hatch:
        out += HATCH([pts], "metal", max(0.6, t / 3), 45.0)
    return out


# ---------------------------------------------------------------- электротехника: УГО схем
def _breaker_pole(x=0.0, kind="qf"):
    """Полюс коммутационного аппарата высотой 20 мм: выводы, подвижный контакт, знак у неподвижного контакта."""
    out = L(x, 0, x, -6) + L(x, -14, x, -20) + L(x, -14, x - 4.2, -6.6)
    if kind == "qf":     # автоматический выключатель — «×»
        out += L(x - 1.2, -7.2, x + 1.2, -4.8) + L(x - 1.2, -4.8, x + 1.2, -7.2)
    elif kind == "qs":   # разъединитель — поперечная черта
        out += L(x - 1.6, -6, x + 1.6, -6)
    elif kind == "km":   # контактор — полуокружность
        out += A(x, -5, 1, 180, 360)
    return out


@block("qf1", "Автоматический выключатель 1P", "electro", "УГО схем",
       {"вход": (0, 0), "выход": (0, -20)}, "QF1", kw="автомат выключатель 1p qf однополюсный")
def _qf1():
    return _breaker_pole()


@block("qf3", "Автоматический выключатель 3P", "electro", "УГО схем",
       {"L1": (0, 0), "L2": (6, 0), "L3": (12, 0), "L1_выход": (0, -20), "L2_выход": (6, -20), "L3_выход": (12, -20)},
       "QF1", at=(15, -10), kw="автомат выключатель 3p трёхполюсный qf")
def _qf3():
    out = []
    for x in (0, 6, 12):
        out += _breaker_pole(x)
    return out + L(-2.1, -10.3, 9.9, -10.3, "hidden")   # механическая связь полюсов


@block("qs", "Разъединитель", "electro", "УГО схем", {"вход": (0, 0), "выход": (0, -20)}, "QS1",
       kw="разъединитель рубильник qs")
def _qs():
    return _breaker_pole(kind="qs")


@block("qd", "УЗО / дифавтомат 2P", "electro", "УГО схем",
       {"L": (0, 0), "N": (6, 0), "L_выход": (0, -26), "N_выход": (6, -26)}, "QD1", at=(19, -10),
       kw="узо дифавтомат дифференциальный qd rcd утечки")
def _qd():
    out = []
    for x in (0, 6):
        out += _breaker_pole(x) + L(x, -20, x, -26)
    out += L(-2.1, -10.3, 10, -10.3, "hidden") + R(10, -13, 7, 5) + T(13.5, -11.8, "IΔ", 2.5, "center")
    out += C(3, -22, 5.2, "thin") + L(8.2, -22, 13.5, -22, "thin") + L(13.5, -22, 13.5, -13, "thin")
    return out


@block("fu", "Предохранитель плавкий", "electro", "УГО схем", {"вход": (0, 0), "выход": (0, -20)}, "FU1",
       kw="предохранитель плавкая вставка fu")
def _fu():
    return L(0, 0, 0, -20) + R(-2, -15, 4, 10)


@block("tm", "Трансформатор силовой", "electro", "УГО схем", {"ВН": (0, 0), "НН": (0, -26)}, "T1", at=(8, -13),
       kw="трансформатор силовой tm тп")
def _tm():
    return L(0, 0, 0, -4) + C(0, -9.5, 5.5) + C(0, -16.5, 5.5) + L(0, -22, 0, -26)


@block("ta", "Трансформатор тока", "electro", "УГО схем",
       {"вход": (0, 0), "выход": (0, -20), "И1": (7, -9), "И2": (7, -11)}, "TA1", at=(8, -15),
       kw="трансформатор тока ta тт")
def _ta():
    return L(0, 0, 0, -20) + C(0, -10, 3) + L(2.83, -9, 7, -9, "thin") + L(2.83, -11, 7, -11, "thin")


@block("pi", "Счётчик электроэнергии", "electro", "УГО схем", {"вход": (0, 0), "выход": (0, -20)}, "PI1", at=(9, -10),
       kw="счетчик счётчик электроэнергии pi wh учёт")
def _pi():
    return L(0, 0, 0, -5) + R(-7, -15, 14, 10) + T(0, -11.6, "Wh", 3.5, "center") + L(0, -15, 0, -20)


@block("m", "Электродвигатель", "electro", "УГО схем", {"вход": (0, 0)}, "M1", at=(9, -12),
       kw="двигатель электродвигатель мотор m асинхронный")
def _m():
    return L(0, 0, 0, -5) + C(0, -12, 7) + T(0, -13, "M", 5, "center") + T(0, -17.2, "3~", 2.5, "center")


@block("pe", "Заземление", "electro", "УГО схем", {"вывод": (0, 0)}, "", at=(6, -6), kw="заземление pe земля")
def _pe():
    return L(0, 0, 0, -6) + L(-5, -6, 5, -6) + L(-3.3, -8, 3.3, -8) + L(-1.6, -10, 1.6, -10)


@block("cable_joint", "Кабельная муфта соединительная", "electro", "УГО схем", {"слева": (-10, 0), "справа": (10, 0)}, "",
       at=(-4, 4), kw="муфта кабельная соединительная")
def _cable_joint():
    return L(-10, 0, -3, 0) + L(3, 0, 10, 0) + L(-3, 2.5, -3, -2.5) + L(3, 2.5, 3, -2.5) + L(-3, 2.5, 3, -2.5) + L(-3, -2.5, 3, 2.5)


@block("socket_open", "Розетка открытой установки", "electro", "Электрооборудование на плане", {"стена": (0, 0)}, "",
       at=(4, 3), kw="розетка открытая проводка штепсельная план")
def _socket_open():
    return A(0, 0, 3, 0, 180) + L(-3, 0, 3, 0) + L(0, 3, 0, 6)


@block("socket_hidden", "Розетка скрытой установки", "electro", "Электрооборудование на плане", {"стена": (0, 0)}, "",
       at=(4, 3), kw="розетка скрытая проводка штепсельная план")
def _socket_hidden():
    return A(0, 0, 3, 0, 180) + L(0, 3, 0, 6) + L(-1.6, 6, 1.6, 6)


@block("switch_light", "Выключатель освещения", "electro", "Электрооборудование на плане", {"центр": (0, 0)}, "",
       at=(3, -4), kw="выключатель освещения клавишный план sa")
def _switch_light():
    return C(0, 0, 1.5) + L(1.06, 1.06, 4.5, 4.5) + L(4.5, 4.5, 5.9, 3.1)


@block("lamp", "Светильник (лампа)", "electro", "Электрооборудование на плане", {"центр": (0, 0), "вывод": (0, 4)}, "EL1",
       at=(5, -5), kw="светильник лампа освещение el")
def _lamp():
    return C(0, 0, 4) + L(-2.83, -2.83, 2.83, 2.83) + L(-2.83, 2.83, 2.83, -2.83)


# ---------------------------------------------------------------- электротехника: ВЛ и монтаж
@block("pole_rc_plan", "Опора ВЛ железобетонная (знак на плане)", "electro", "Воздушные линии", {"центр": (0, 0)}, "ОП-1",
       at=(3, 3), kw="опора вл железобетонная жб план знак")
def _pole_rc_plan():
    return C(0, 0, 2) + C(0, 0, 0.8)


@block("pole_wood_plan", "Опора ВЛ деревянная (знак на плане)", "electro", "Воздушные линии", {"центр": (0, 0)}, "ОП-1",
       at=(3, 3), kw="опора вл деревянная план знак")
def _pole_wood_plan():
    return C(0, 0, 2) + L(-1.41, -1.41, 1.41, 1.41)


def _ground(x0, x1):
    out = L(x0, 0, x1, 0, "thin")
    x = x0 + 1.5
    while x < x1:
        if abs(x) > 2.5:
            out += L(x, 0, x - 1.5, -1.5, "thin")
        x += 3
    return out


@block("pole_rc_side", "Опора ВЛ железобетонная (вид, М1:100)", "electro", "Воздушные линии",
       {"земля": (0, 0), "провод_1": (-9, 84.1), "провод_2": (9, 84.1)}, "ОП-1", at=(4, 40),
       kw="опора вл железобетонная св-110 вид конструктивный")
def _pole_rc_side():
    out = _ground(-14, 14)
    out += L(-1.6, -25, -1.37, 0, "hidden") + L(1.6, -25, 1.37, 0, "hidden") + L(-1.6, -25, 1.6, -25, "hidden")
    out += L(-1.37, 0, -0.9, 85) + L(1.37, 0, 0.9, 85) + L(-0.9, 85, 0.9, 85)
    out += L(-10, 80, 10, 80) + L(-10, 80, -1.05, 74) + L(10, 80, 1.05, 74)
    for x in (-9, 9):
        out += L(x, 80, x, 82.5) + C(x, 83.3, 0.8)
    return out


@block("pole_wood_side", "Опора ВЛ деревянная с приставкой (вид, М1:100)", "electro", "Воздушные линии",
       {"земля": (0, 0), "провод_1": (4.8, 86), "провод_2": (-4.8, 82)}, "ОП-1", at=(5, 45),
       kw="опора вл деревянная приставка вид конструктивный")
def _pole_wood_side():
    out = _ground(-14, 14)
    out += R(1.2, -25, 2.4, 25, "hidden") + L(1.2, 0, 1.2, 15) + L(3.6, 0, 3.6, 15) + L(1.2, 15, 3.6, 15)
    out += L(-1.2, 5, -1.2, 90) + L(1.2, 15, 1.2, 90) + L(-1.2, 90, 1.2, 90) + L(-1.2, 5, 1.2, 5)
    out += L(-1.4, 8, 3.8, 8, "thin") + L(-1.4, 12, 3.8, 12, "thin")
    out += L(1.2, 86, 4, 86) + C(4.8, 86, 0.8) + L(-1.2, 82, -4, 82) + C(-4.8, 82, 0.8)
    return out


@block("traverse", "Траверса (вид спереди)", "electro", "Воздушные линии",
       {"центр": (0, 0), "штырь_1": (-26, 2), "штырь_2": (26, 2)}, "", at=(-30, 4), kw="траверса тм вл")
def _traverse():
    out = R(-30, -2, 60, 4)
    for x in (-26, 26):
        out += C(x, 0, 0.9)
    return out + C(-4, 0, 0.7) + C(4, 0, 0.7) + L(-20, -2, -2, -14) + L(20, -2, 2, -14) + R(-3, -16, 6, 2)


@block("ins_pin", "Изолятор штыревой", "electro", "Воздушные линии", {"штырь": (0, 0), "провод": (0, 13.5)}, "",
       at=(5, 6), kw="изолятор штыревой шф тф")
def _ins_pin():
    return (L(0, 0, 0, 6) + P([(-3, 6), (3, 6), (2, 12), (-2, 12)], closed=True) + L(-4.2, 8, 4.2, 8)
            + L(-4.2, 8, -3, 6) + L(4.2, 8, 3, 6) + C(0, 12.8, 0.8))


@block("ins_susp", "Изолятор подвесной (гирлянда)", "electro", "Воздушные линии", {"траверса": (0, 0), "провод": (0, -24)},
       "", at=(6, -12), kw="изолятор подвесной гирлянда тарельчатый пс")
def _ins_susp():
    out = L(0, 0, 0, -3)
    for y in (-3, -9, -15):
        out += P([(-1, y), (1, y), (5, y - 3), (-5, y - 3)], closed=True) + L(0, y - 3, 0, y - 6)
    return out + R(-1.5, -24, 3, 3) + C(0, -22.5, 0.6)


@block("clamp_anchor", "Зажим анкерный СИП (натяжной)", "electro", "Воздушные линии", {"кабель": (-20, 0), "крюк": (9, 0)},
       "", at=(-12, 5), kw="зажим анкерный сип натяжной клиновой")
def _clamp_anchor():
    return (L(-20, 0, -12, 0, "thin") + P([(-12, 1.5), (0, 3), (0, -3), (-12, -1.5)], closed=True)
            + L(0, 3, 6, 3) + L(0, -3, 6, -3) + A(6, 0, 3, 270, 90))


@block("clamp_support", "Зажим поддерживающий СИП", "electro", "Воздушные линии", {"кабель": (0, 0), "крюк": (0, 11)},
       "", at=(5, 4), kw="зажим поддерживающий сип подвесной")
def _clamp_support():
    return (C(0, 0, 2) + A(0, 0, 3.5, 180, 360) + L(-3.5, 0, -3.5, 3) + L(3.5, 0, 3.5, 3) + L(-3.5, 3, 3.5, 3)
            + L(0, 3, 0, 8) + C(0, 9.5, 1.5))


@block("ground_loop", "Контур заземления (план)", "electro", "Воздушные линии", {"вывод": (-10, 12)}, "Rз ≤ 4 Ом",
       at=(2, 27), kw="контур заземления заземлитель электрод план")
def _ground_loop():
    out = R(0, 0, 40, 24)
    for x, y in ((0, 0), (20, 0), (40, 0), (0, 24), (20, 24), (40, 24)):
        out += C(x, y, 1.2) + L(x - 0.85, y - 0.85, x + 0.85, y + 0.85) + L(x - 0.85, y + 0.85, x + 0.85, y - 0.85)
    return out + L(-10, 12, 0, 12)


# ---------------------------------------------------------------- строительство (М1:100)
WALL_T = 3.8   # 380 мм в М1:100


@block("axis_mark", "Координационная ось с маркой", "build", "Оси и отметки", {"марка": (0, 0), "конец_оси": (0, -54)},
       "1", at=(0, -2.5), align="center", h=5, kw="ось координационная марка кружок а б в 1 2 3")
def _axis_mark():
    return C(0, 0, 4) + L(0, -4, 0, -54, "axis")


@block("level", "Высотная отметка", "build", "Оси и отметки", {"уровень": (0, 0)}, "±0,000", at=(1, 3.3),
       kw="отметка высотная уровень ±0.000 стрелка")
def _level():
    return L(0, 0, -2.5, 2.5) + L(0, 0, 2.5, 2.5) + L(-2.5, 2.5, 15, 2.5)


@block("wall", "Участок капитальной стены 3 м (380 мм)", "build", "Стены и проёмы", {"начало": (0, 0), "конец": (30, 0)}, "",
       at=(0, 4), kw="стена капитальная кирпич кладка")
def _wall():
    return wall_segment(0, 0, 30, 0, WALL_T)


@block("partition", "Перегородка 3 м (120 мм)", "build", "Стены и проёмы", {"начало": (0, 0), "конец": (30, 0)}, "",
       at=(0, 3), kw="перегородка стена тонкая")
def _partition():
    return wall_segment(0, 0, 30, 0, 1.2, hatch=False)


@block("door", "Дверной проём 900 мм (открывание 90°)", "build", "Стены и проёмы", {"петля": (0, 0), "проём_конец": (9, 0)},
       "", at=(2, -4), kw="дверь дверной проём проем открывание")
def _door():
    t = WALL_T / 2
    return L(0, -t, 0, t) + L(9, -t, 9, t) + L(0, t, 0, t + 9) + A(0, t, 9, 0, 90, "thin")


@block("window", "Оконный проём 1500 мм", "build", "Стены и проёмы", {"начало": (0, 0), "конец": (15, 0)}, "",
       at=(2, -4.5), kw="окно оконный проём проем")
def _window():
    t = WALL_T / 2
    return (L(0, -t, 0, t) + L(15, -t, 15, t) + L(0, -t, 15, -t, "thin") + L(0, t, 15, t, "thin")
            + L(0, -0.45, 15, -0.45, "thin") + L(0, 0.45, 15, 0.45, "thin"))


@block("gate", "Ворота распашные 3000 мм", "build", "Стены и проёмы", {"начало": (0, 0), "конец": (30, 0)}, "",
       at=(10, -4.5), kw="ворота распашные гараж проём")
def _gate():
    t = WALL_T / 2
    return (L(0, -t, 0, t) + L(30, -t, 30, t) + L(0, t, 0, t + 15) + L(30, t, 30, t + 15)
            + A(0, t, 15, 0, 90, "thin") + A(30, t, 15, 90, 180, "thin"))


@block("stair", "Лестничный марш 1200×3000", "build", "Конструкции", {"низ": (0, 0)}, "", at=(13, 2),
       kw="лестница лестничный марш ступени")
def _stair():
    out = R(0, 0, 12, 30)
    for k in range(1, 10):
        out += L(0, 3 * k, 12, 3 * k, "thin")
    return out + L(6, 1.5, 6, 27, "thin") + L(6, 27, 5, 24.5, "thin") + L(6, 27, 7, 24.5, "thin") + L(0, 18, 12, 21, "thin")


@block("column", "Колонна железобетонная 400×400", "build", "Конструкции", {"центр": (0, 0)}, "", at=(3, 3),
       kw="колонна железобетонная жб")
def _column():
    return R(-2, -2, 4, 4) + HATCH([rect_pts(-2, -2, 4, 4)], "concrete", 0.8, 45)


@block("vent", "Вентиляционная шахта 600×600", "build", "Конструкции", {"угол": (0, 0)}, "", at=(7, 3),
       kw="вентиляционная шахта канал вентиляция")
def _vent():
    return R(0, 0, 6, 6) + R(0.8, 0.8, 4.4, 4.4, "thin") + L(0.8, 0.8, 5.2, 5.2, "thin") + L(0.8, 5.2, 5.2, 0.8, "thin")


@block("sink", "Мойка / умывальник", "build", "Сантехника", {"угол": (0, 0)}, "", at=(7, 1),
       kw="мойка умывальник раковина санузел")
def _sink():
    return R(0, 0, 6, 4.5) + R(0.6, 0.6, 4.8, 3.0, "thin") + C(3, 2.1, 0.4, "thin")


@block("wc", "Унитаз", "build", "Сантехника", {"стена": (2, 6.8)}, "", at=(5, 2), kw="унитаз санузел туалет")
def _wc():
    return R(0, 5, 4, 1.8) + L(0.4, 5, 0.4, 2) + L(3.6, 5, 3.6, 2) + A(2, 2, 1.6, 180, 360)


# ---------------------------------------------------------------- машиностроение (М1:1)
@block("bolt_front", "Болт М10×40 ГОСТ 7798-70 (вид спереди)", "mech", "Крепёж",
       {"опора": (0, 0), "конец": (0, -40)}, "", at=(11, -20), kw="болт м10 крепёж гост 7798")
def _bolt_front():
    out = R(-9.35, 0, 18.7, 7) + L(-4.7, 0, -4.7, 7) + L(4.7, 0, 4.7, 7)
    out += L(-5, 0, -5, -38.5) + L(5, 0, 5, -38.5) + L(-5, -38.5, -3.5, -40) + L(5, -38.5, 3.5, -40) + L(-3.5, -40, 3.5, -40)
    out += L(-5, -14, 5, -14) + L(-4.2, -14, -4.2, -40, "thin") + L(4.2, -14, 4.2, -40, "thin")
    return out + L(0, 9, 0, -43, "axis")


@block("bolt_top", "Болт М10 (вид сверху)", "mech", "Крепёж", {"центр": (0, 0)}, "", at=(11, 6), kw="болт м10 сверху шестигранник")
def _bolt_top():
    return P(hexagon(9.815), closed=True) + C(0, 0, 8.5, "thin") + axis_cross(12)


@block("nut_front", "Гайка М10 ГОСТ 5915-70 (вид спереди)", "mech", "Крепёж", {"опора": (0, 0), "верх": (0, 8)}, "",
       at=(11, 3), kw="гайка м10 крепёж гост 5915")
def _nut_front():
    return (R(-9.35, 0, 18.7, 8) + L(-4.7, 0, -4.7, 8) + L(4.7, 0, 4.7, 8)
            + L(-5, 0, -5, 8, "hidden") + L(5, 0, 5, 8, "hidden") + L(0, -3, 0, 11, "axis"))


@block("nut_top", "Гайка М10 (вид сверху)", "mech", "Крепёж", {"центр": (0, 0)}, "", at=(11, 6), kw="гайка м10 сверху резьба")
def _nut_top():
    return P(hexagon(9.815), closed=True) + C(0, 0, 8.5, "thin") + C(0, 0, 4.2) + A(0, 0, 5, 0, 270, "thin") + axis_cross(12)


@block("washer_front", "Шайба 10 ГОСТ 11371-78 (вид спереди)", "mech", "Крепёж", {"опора": (0, 0), "верх": (0, 2)}, "",
       at=(11, 0), kw="шайба плоская крепёж гост 11371")
def _washer_front():
    return R(-10, 0, 20, 2) + L(-5.25, 0, -5.25, 2, "hidden") + L(5.25, 0, 5.25, 2, "hidden") + L(0, -3, 0, 5, "axis")


@block("washer_top", "Шайба 10 (вид сверху)", "mech", "Крепёж", {"центр": (0, 0)}, "", at=(11, 6), kw="шайба плоская сверху")
def _washer_top():
    return C(0, 0, 10) + C(0, 0, 5.25) + axis_cross(13)


@block("tube_sq", "Труба профильная 40×40×2 (сечение)", "mech", "Металлопрокат", {"центр": (0, 0)}, "", at=(22, 15),
       kw="труба профильная квадратная сечение прокат")
def _tube_sq():
    o, i = rect_pts(-20, -20, 40, 40), rect_pts(-18, -18, 36, 36)
    return P(o, closed=True) + P(i, closed=True) + HATCH([o, i], "metal", 1.0)


@block("channel", "Швеллер 10П ГОСТ 8240-97 (сечение)", "mech", "Металлопрокат", {"низ": (0, 0)}, "", at=(48, 50),
       kw="швеллер сечение прокат гост 8240")
def _channel():
    pts = [(0, 0), (46, 0), (46, 7.6), (4.5, 7.6), (4.5, 92.4), (46, 92.4), (46, 100), (0, 100)]
    return P(pts, closed=True) + HATCH([pts], "metal", 2.0)


@block("angle", "Уголок 50×5 ГОСТ 8509-93 (сечение)", "mech", "Металлопрокат", {"угол": (0, 0)}, "", at=(10, 30),
       kw="уголок равнополочный сечение прокат гост 8509")
def _angle():
    pts = [(0, 0), (50, 0), (50, 5), (5, 5), (5, 50), (0, 50)]
    return P(pts, closed=True) + HATCH([pts], "metal", 1.5)


@block("ibeam", "Двутавр 10Б1 (сечение)", "mech", "Металлопрокат", {"низ": (0, 0)}, "", at=(30, 50),
       kw="двутавр балка сечение прокат")
def _ibeam():
    pts = [(-27.5, 0), (27.5, 0), (27.5, 5.7), (2.05, 5.7), (2.05, 94.3), (27.5, 94.3), (27.5, 100), (-27.5, 100),
           (-27.5, 94.3), (-2.05, 94.3), (-2.05, 5.7), (-27.5, 5.7)]
    return P(pts, closed=True) + HATCH([pts], "metal", 2.0)


@block("bearing", "Подшипник 6204 ГОСТ 8338-75 (разрез, упрощённо)", "mech", "Детали машин", {"центр": (0, 0)}, "",
       at=(10, 25), kw="подшипник шариковый 6204 разрез")
def _bearing():
    out = []
    for s in (1, -1):
        y0 = 10 if s > 0 else -23.5
        out += R(-7, y0, 14, 13.5) + C(0, s * 16.75, 3.97) + L(-7, s * 14, -3.6, s * 14, "thin") + L(3.6, s * 14, 7, s * 14, "thin")
        out += L(-7, s * 19.5, -3.6, s * 19.5, "thin") + L(3.6, s * 19.5, 7, s * 19.5, "thin")
    return out + L(-12, 0, 12, 0, "axis")


@block("flange", "Фланец Ду50 PN16 (вид сверху)", "mech", "Детали машин", {"центр": (0, 0)}, "", at=(60, 70),
       kw="фланец ду50 pn16 труба")
def _flange():
    out = C(0, 0, 82.5) + C(0, 0, 28.5) + C(0, 0, 62.5, "axis") + axis_cross(90)
    for a in (45, 135, 225, 315):
        out += C(62.5 * math.cos(math.radians(a)), 62.5 * math.sin(math.radians(a)), 9)
    return out


@block("weld", "Обозначение сварного шва (ГОСТ 2.312)", "mech", "Обозначения", {"шов": (0, 0)}, "ГОСТ 14771-76-Т3-◺5",
       kw="сварка сварной шов обозначение стрелка гост 2.312 5264 14771")
def _weld():
    return [make_leader(0, 0, 10, 10, "ГОСТ 14771-76-Т3-◺5")]


# ---------------------------------------------------------------- вставка
def _xf(scale, rot, x, y):
    r = math.radians(rot)
    cr, sr = math.cos(r), math.sin(r)
    return lambda p: (x + (p[0] * cr - p[1] * sr) * scale, y + (p[0] * sr + p[1] * cr) * scale)


def transform(entities: list[dict], x=0.0, y=0.0, rot=0.0, scale=1.0) -> list[dict]:
    """Масштаб, поворот против часовой и перенос (на месте). Надписи остаются горизонтальными — читаются снизу."""
    from .edit2d import _map_points

    f = _xf(scale, rot, x, y)
    for e in entities:
        _map_points(e, f)
        t = e["type"]
        if t in ("circle", "arc", "diadim", "raddim"):
            e["r"] *= scale
        if t == "arc":
            e["a0"], e["a1"] = (e["a0"] + rot) % 360, (e["a1"] + rot) % 360
        if t in ("diadim", "raddim"):
            e["ang"] = (e["ang"] + rot) % 360
        if t == "angdim":
            e["a1"], e["a2"], e["rad"] = (e["a1"] + rot) % 360, (e["a2"] + rot) % 360, e["rad"] * scale
        if t == "dim":
            e["off"] *= scale
        if t == "text":
            e["h"] *= scale
    return entities


def get_block(block_id: str) -> Block:
    b = BLOCKS.get(block_id) or user_blocks().get(block_id)
    if b is None:
        raise ValueError(f"нет элемента {block_id!r} в библиотеке")
    return b


def instantiate(block_id: str, x=0.0, y=0.0, rot=0.0, scale=1.0, label: str | None = None) -> list[dict]:
    """Готовые примитивы экземпляра элемента. label=None — маркировка по умолчанию, "" — без маркировки."""
    b = get_block(block_id)
    scale, rot = float(scale), float(rot)
    if not 0.01 <= scale <= 1000:
        raise ValueError("масштаб элемента от 0,01 до 1000")
    ents = b.entities()
    text = b.label if label is None else str(label)
    leaders = [e for e in ents if e["type"] == "leader"]
    if leaders:                     # обозначение шва и подобные: маркировка — текст на полке
        leaders[0]["text"] = text
    transform(ents, float(x), float(y), rot, scale)
    if text and not leaders:
        # маркировка не поворачивается: переносим середину строки и ставим надпись от неё горизонтально
        lx, ly = _xf(scale, rot, float(x), float(y))((b.label_at[0], b.label_at[1] + b.label_h / 2))
        ents += T(lx, ly - b.label_h * scale / 2, text, b.label_h * scale, b.label_align)
        ents[-1]["blk_role"] = "label"
    inst = new_id()
    for e in ents:   # blk_at — точка вставки, поворот, масштаб: вокруг неё поворачивает и масштабирует ПКМ-редактор
        e.update(blk=inst, blk_id=b.id, blk_at=[float(x), float(y), rot % 360, scale])
    return ents


def ports_world(block_id: str, x=0.0, y=0.0, rot=0.0, scale=1.0) -> dict:
    f = _xf(float(scale), float(rot), float(x), float(y))
    return {k: tuple(round(v, 3) for v in f(p)) for k, p in get_block(block_id).ports.items()}


def group_ids(entities: list[dict], eid: str) -> list[str]:
    """Все примитивы экземпляра элемента, к которому относится eid (или только eid)."""
    e = next((x for x in entities if x["id"] == eid), None)
    if e is None or not e.get("blk"):
        return [eid]
    return [x["id"] for x in entities if x.get("blk") == e["blk"]]


def label_of(entities: list[dict], inst: str) -> str:
    for e in entities:
        if e.get("blk") == inst and (e.get("blk_role") == "label" or e["type"] == "leader"):
            return e["text"]
    return ""


def set_label(entities: list[dict], inst: str, text: str) -> None:
    """Сменить маркировку экземпляра; если её не было — поставить справа от элемента."""
    part = [e for e in entities if e.get("blk") == inst]
    if not part:
        raise ValueError("элемент не найден")
    for e in part:
        if e.get("blk_role") == "label" or e["type"] == "leader":
            e["text"] = text
            return
    if not text:
        return
    x0, y0, x1, y1 = bounds(part)
    lab = make_text(x1 + 2, (y0 + y1) / 2 - 1.75, text)
    lab.update(blk=inst, blk_id=part[0].get("blk_id", ""), blk_role="label")
    entities.append(lab)


def next_label(label: str) -> str:
    """QF1 → QF2, ОП-12 → ОП-13, «Ось А» → «Ось Б» (буквы осей по ГОСТ 21.101, без Ё З Й О Х Ц Ч Щ Ъ Ы Ь)."""
    m = re.search(r"(\d+)(\D*)$", label)
    if m:
        n = m.group(1)
        return label[:m.start(1)] + str(int(n) + 1).zfill(len(n)) + m.group(2)
    letters = "АБВГДЕЖИКЛМНПРСТУФЭЮЯ"
    if label and label[-1] in letters[:-1]:
        return label[:-1] + letters[letters.index(label[-1]) + 1]
    return label


def bounds(entities: list[dict]) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for e in entities:
        t = e["type"]
        if t in ("circle", "arc"):
            xs += [e["cx"] - e["r"], e["cx"] + e["r"]]
            ys += [e["cy"] - e["r"], e["cy"] + e["r"]]
        elif t == "hatch":
            for poly in e["boundary"]:
                xs += [p[0] for p in poly]
                ys += [p[1] for p in poly]
        elif t == "text":   # прямоугольник строки, повёрнутый вокруг точки привязки
            w = CHAR_W * e["h"] * len(e["text"])
            dx = {"center": -w / 2, "right": -w}.get(e.get("align"), 0.0)
            a = math.radians(e.get("ang", 0.0))
            for u, v in ((dx, 0.0), (dx + w, 0.0), (dx, e["h"]), (dx + w, e["h"])):
                xs.append(e["x"] + u * math.cos(a) - v * math.sin(a))
                ys.append(e["y"] + u * math.sin(a) + v * math.cos(a))
        elif t == "line":
            xs += [e["x1"], e["x2"]]
            ys += [e["y1"], e["y2"]]
        else:   # размеры, выноски: по тому, что реально рисуется
            from .dims import render

            d = render(e)
            for x1, y1, x2, y2 in d.segs:
                xs += [x1, x2]
                ys += [y1, y2]
            for tx, ty, hh, s_, _, al in d.texts:
                w = CHAR_W * hh * len(s_)
                dx = {"center": -w / 2, "right": -w}.get(al, 0.0)
                xs += [tx + dx, tx + dx + w]
                ys += [ty, ty + hh]
    if not xs:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def search(query: str, items) -> list:
    """Поиск по названию, разделу и ключевым словам: все слова запроса должны найтись (ё = е, без регистра)."""
    words = [w for w in _norm(query).split() if w]
    out = []
    for it in items:
        hay = _norm(" ".join((it.name, SECTIONS.get(it.section, ""), getattr(it, "group", ""), it.keywords)))
        if all(w in hay for w in words):
            out.append(it)
    return out


def _norm(s: str) -> str:
    return s.lower().replace("ё", "е")


# ---------------------------------------------------------------- «Мои элементы»
def user_path():
    from .ai import app_dir

    return app_dir() / "user_library.json"


_user_cache: dict | None = None


def _user_data() -> dict:
    global _user_cache
    if _user_cache is None:
        try:
            data = json.loads(user_path().read_text(encoding="utf-8"))
            _user_cache = data if isinstance(data, dict) and isinstance(data.get("blocks"), list) else {"blocks": []}
        except (OSError, ValueError):
            _user_cache = {"blocks": []}
    return _user_cache


def reload_user():
    global _user_cache
    _user_cache = None


def user_blocks() -> dict[str, Block]:
    out = {}
    for d in _user_data()["blocks"]:
        ents = d.get("entities") or []
        out[d["id"]] = Block(d["id"], d.get("name", "Элемент"), "user", d.get("group", "Мои элементы"),
                             lambda ents=ents: _fresh(ents), {"база": (0, 0)}, "", (0, -5), "left", 3.5, d.get("keywords", ""))
    return out


def _fresh(ents):
    out = copy.deepcopy(ents)
    for e in out:
        e["id"] = new_id()
    return out


def _save_user():
    from .ai import save_json

    save_json(user_path(), _user_data())


def save_user_block(name: str, entities: list[dict], keywords: str = "") -> str:
    """Сохранить примитивы как свой элемент: точка вставки — левый нижний угол габарита. Возвращает id."""
    name = (name or "").strip()
    if not name:
        raise ValueError("укажите имя элемента")
    if not entities:
        raise ValueError("ничего не выделено")
    x0, y0, _, _ = bounds(entities)
    ents = copy.deepcopy(entities)
    transform(ents, -x0, -y0)
    for e in ents:
        for k in ("id", "blk", "blk_id", "gen"):
            e.pop(k, None)
    bid = "user_" + new_id()
    _user_data()["blocks"].append({"id": bid, "name": name, "keywords": keywords, "entities": ents})
    _save_user()
    return bid


def delete_user_block(bid: str) -> None:
    data = _user_data()
    before = len(data["blocks"])
    data["blocks"] = [d for d in data["blocks"] if d["id"] != bid]
    if len(data["blocks"]) == before:
        raise ValueError("нет такого элемента в «Моих элементах»")
    _save_user()


def all_blocks() -> list[Block]:
    return list(BLOCKS.values()) + list(user_blocks().values())


# ---------------------------------------------------------------- таблицы и шаблоны листов
def table(x, ytop, widths, headers, rows=0, row_h=8.0, head_h=15.0, data=None, h=3.5, vertical=()):
    """Таблица по ЕСКД: контур и линии граф — основные, строки — тонкие. Шапка по центру граф,
    содержимое — с отступом 1,5 мм; номера граф из vertical пишутся вертикально (узкие графы ГОСТ 2.106)."""
    W, H = sum(widths), head_h + rows * row_h
    out = P(rect_pts(x, ytop - H, W, H), "main", closed=True) + L(x, ytop - head_h, x + W, ytop - head_h)
    cx = x
    for w in widths[:-1]:
        cx += w
        out += L(cx, ytop, cx, ytop - H)
    for k in range(1, rows):
        out += L(x, ytop - head_h - k * row_h, x + W, ytop - head_h - k * row_h, "thin")
    cx = x
    for i, (w, head) in enumerate(zip(widths, headers)):
        lines = head.split("\n")
        if i in vertical:
            hh = min(2.5, (head_h - 2) / max(CHAR_W * len(head), 1))
            out += T(cx + w / 2 + hh / 2, ytop - head_h / 2, head, hh, "center", 90)
        else:
            hh = min(h, max(1.8, min((w - 3) / (CHAR_W * max(len(s) for s in lines)), (head_h - 2) / len(lines) / 1.5)))
            y0 = ytop - head_h / 2 + (len(lines) - 1) * hh * 0.75 - hh / 2
            for j, s in enumerate(lines):
                out += T(cx + w / 2, y0 - j * hh * 1.5, s, hh, "center")
        cx += w
    for r, row in enumerate(data or []):
        cx = x
        yb = ytop - head_h - (r + 1) * row_h + (row_h - h) / 2
        for w, cell in zip(widths, row):
            s = str(cell)
            if s:
                hh = min(h, max(1.8, (w - 3) / (CHAR_W * len(s))))
                centered = w <= 25 and CHAR_W * hh * len(s) < w * 0.7   # узкие графы (поз., кол.) — по центру
                out += T(cx + w / 2 if centered else cx + 1.5, yb, s, hh, "center" if centered else "left")
            cx += w
    return out


def place(block_id, x, y, rot=0.0, scale=1.0, label=None):
    return instantiate(block_id, x, y, rot, scale, label)


@template("single_line_a3", "Однолинейная схема электроснабжения — А3", "electro", "A3L", "Однолинейная схема электроснабжения",
          "однолинейная схема электроснабжения щит таблица нагрузок шина")
def _tpl_single_line_a3(project, area):
    _single_line(project, area, wide=True)


@template("single_line_a4", "Однолинейная схема электроснабжения — А4", "electro", "A4P", "Однолинейная схема электроснабжения",
          "однолинейная схема электроснабжения щит таблица нагрузок шина")
def _tpl_single_line_a4(project, area):
    _single_line(project, area, wide=False)


LOADS = [("Гр.1", "Освещение помещений", "1,5", "6,8", "ВВГнг(А)-LS 3×1,5"),
         ("Гр.2", "Розеточная сеть", "3,5", "15,9", "ВВГнг(А)-LS 3×2,5"),
         ("Гр.3", "Электродвигатель насоса", "4,0", "8,3", "ВВГнг(А)-LS 5×2,5")]


def _single_line(project, area, wide):
    x0, y0, x1, y1 = area
    d = project.drawing
    widths = [16, 60, 22, 18, 46]
    W = sum(widths)
    if wide:
        sx, top = x0 + 40, y1 - 25
        tx, ty = x1 - W - 5, y0 + 75
    else:
        sx, top = x0 + 35, y1 - 22
        tx, ty = x0 + (x1 - x0 - W) / 2, y0 + 20
    d += T((x0 + x1) / 2 if not wide else x0 + 10, y1 - 10, "Однолинейная схема электроснабжения ЩР-1", 5, "center" if not wide else "left")
    d += T(sx + 4, top + 3, "Ввод от ТП-1, ~380/220 В", 3.5)
    d += L(sx, top + 8, sx, top)
    d += place("qf1", sx, top, label="QF0  C63")
    d += place("pi", sx, top - 20, label="PI1")
    bus_y = top - 48
    d += L(sx, top - 40, sx, bus_y)
    step = 32 if wide else 26
    bx0, bx1 = sx - 12, sx + step * 2 + 18
    d += L(bx0, bus_y, bx1, bus_y) + L(bx0, bus_y - 1, bx1, bus_y - 1)    # шина — двойная основная
    d += T(bx1 + 3, bus_y - 2, "Шина ~380/220 В", 3.5)
    for i, (grp, name, p, cur, cable) in enumerate(LOADS):
        x = sx + i * step
        d += L(x, bus_y - 1, x, bus_y - 6)
        d += place("qf1", x, bus_y - 6, label=f"QF{i + 1}")
        d += L(x, bus_y - 26, x, bus_y - 46)
        d += T(x + 1.5, bus_y - 44, grp, 2.5)
    d += T(tx, ty + 16 + 8 * 5 + 4, "Таблица нагрузок", 5)
    d += table(tx, ty + 15 + 8 * 5, widths, ["Группа", "Наименование\nпотребителя", "Мощность,\nкВт", "Ток,\nА", "Кабель"],
               5, data=[*LOADS, ("", "Итого", "9,0", "", "")])


@template("overhead_line_a3", "Схема трассы ВЛ / кабельной линии на плане — А3", "electro", "A3L", "Схема трассы ВЛИ-0,4 кВ",
          "трасса вл кабельная линия план опоры пролёты ведомость", "1:1000")
def _tpl_overhead(project, area):
    x0, y0, x1, y1 = area
    d = project.drawing
    d += T(x0 + 10, y1 - 10, "Схема трассы ВЛИ-0,4 кВ   М 1:1000", 5)
    ty = y1 - 70
    d += R(x0 + 10, ty - 5, 14, 10) + T(x0 + 17, ty - 1.8, "ТП-1", 3.5, "center")
    px = x0 + 40
    d += L(x0 + 24, ty, px - 2, ty)
    for k in range(5):
        x = px + k * 35
        d += place("pole_rc_plan", x, ty, label=f"ОП-{k + 1}")
        if k < 4:
            d += L(x + 2, ty, x + 33, ty) + T(x + 17.5, ty - 6, "35 м", 3.5, "center")
    d += T(x0 + 10, y0 + 100, "Условные обозначения:", 3.5)
    d += place("pole_rc_plan", x0 + 16, y0 + 92, label="") + T(x0 + 26, y0 + 90.5, "— опора ВЛ железобетонная", 3.5)
    d += L(x0 + 10, y0 + 82, x0 + 22, y0 + 82) + T(x0 + 26, y0 + 80.5, "— ВЛИ-0,4 кВ, СИП-2 3×50+1×54,6", 3.5)
    widths = [20, 52, 20, 48, 36]
    W = sum(widths)
    rows = [("ОП-1", "А1 — анкерная концевая", "—", "СИП-2 3×50+1×54,6", "отпайка от ТП"),
            ("ОП-2", "П1 — промежуточная", "35", "СИП-2 3×50+1×54,6", ""),
            ("ОП-3", "П1 — промежуточная", "35", "СИП-2 3×50+1×54,6", ""),
            ("ОП-4", "П1 — промежуточная", "35", "СИП-2 3×50+1×54,6", ""),
            ("ОП-5", "А1 — анкерная концевая", "35", "СИП-2 3×50+1×54,6", "заземление")]
    tx, ttop = x1 - W - 5, y0 + 15 + 15 + 8 * 6
    d += T(tx, ttop + 4, "Ведомость опор и проводов", 5)
    d += table(tx, ttop, widths, ["№ опоры", "Тип опоры", "Пролёт,\nм", "Марка провода", "Примечание"], 6, data=rows)


@template("service_a4", "График ТО, ведомость работ и спецификация оборудования — А4", "electro", "A4P",
          "График ТО и спецификация оборудования", "график технического обслуживания то ведомость работ спецификация оборудования")
def _tpl_service(project, area):
    x0, y0, x1, y1 = area
    d = project.drawing
    d += T((x0 + x1) / 2, y1 - 10, "График технического обслуживания электрооборудования", 3.5, "center")
    widths = [8, 40, 33, 22] + [6] * 12 + [10]
    heads = ["№", "Оборудование", "Вид работ", "Перио-\nдичность"] + [str(m) for m in range(1, 13)] + ["Отв."]
    rows = [("1", "Вводной автомат QF0", "Осмотр, протяжка", "1 раз в 6 мес", "×", "", "", "", "", "", "×"),
            ("2", "Счётчик PI1", "Проверка пломб", "1 раз в 12 мес", "", "", "", "×"),
            ("3", "Автоматы QF1–QF3", "Осмотр, протяжка", "1 раз в 6 мес", "", "×", "", "", "", "", "", "×"),
            ("4", "Кабельные линии", "Измерение изоляции", "1 раз в 12 мес", "", "", "", "", "×"),
            ("5", "Контур заземления", "Измерение Rз", "1 раз в 12 мес", "", "", "", "", "", "×")]
    top = y1 - 15
    d += table(x0, top, widths, heads, 8, data=rows, h=2.5)
    d += T((x0 + x1) / 2, top - 15 - 64 - 10, "Ведомость работ и спецификация оборудования", 3.5, "center")
    w2 = [15, 72, 45, 15, 38]
    spec = [("1", "Выключатель автоматический 3P C63, 6 кА", "ВА47-29", "1", "QF0"),
            ("2", "Счётчик электроэнергии трёхфазный", "Меркурий 234", "1", "PI1"),
            ("3", "Выключатель автоматический 1P C16", "ВА47-29", "3", "QF1–QF3"),
            ("4", "Кабель силовой", "ВВГнг(А)-LS 3×2,5", "50 м", "")]
    d += table(x0, top - 15 - 64 - 14, w2, ["Поз.", "Наименование и техническая\nхарактеристика", "Тип, марка", "Кол.", "Примечание"],
               8, data=spec)


@template("arch_plan_a3", "Архитектурный план помещения / этажа — А3", "build", "A3L", "План этажа",
          "архитектурный план помещения этажа экспликация оси стены", "1:50")
def _tpl_arch_plan(project, area):
    x0, y0, x1, y1 = area
    d = project.drawing
    k = 2.0                            # элементы библиотеки — в М1:100, лист — в М1:50
    W, H, t = 60.0 * k, 40.0 * k, WALL_T * k    # помещение 6 × 4 м по осям
    ox, oy = x0 + 45, y0 + 70          # пересечение осей 1 и А
    for ax, mark in ((ox, "1"), (ox + W, "2")):
        d += place("axis_mark", ax, oy + H + 18, label=mark) + L(ax, oy + H - 30, ax, oy - 12, "axis")
    for ay, mark in ((oy, "А"), (oy + H, "Б")):
        d += place("axis_mark", ox - 18, ay, rot=90, label=mark) + L(ox + 30, ay, ox + W + 12, ay, "axis")
    door_x, win_x = ox + 25, ox + W / 2 - 7.5 * k
    d += wall_segment(ox - t / 2, oy, door_x, oy, t) + wall_segment(door_x + 9 * k, oy, ox + W + t / 2, oy, t)
    d += place("door", door_x, oy, scale=k, label="")
    d += wall_segment(ox + W, oy, ox + W, oy + H, t) + wall_segment(ox, oy, ox, oy + H, t)
    d += wall_segment(ox - t / 2, oy + H, win_x, oy + H, t) + wall_segment(win_x + 15 * k, oy + H, ox + W + t / 2, oy + H, t)
    d += place("window", win_x, oy + H, scale=k, label="")
    for e in (make_dim(ox, oy - 12, ox + W, oy - 12, -8, "horizontal"), make_dim(ox + W + 12, oy, ox + W + 12, oy + H, 8, "vertical")):
        e["k"] = 50.0
        d.append(e)
    s = f"{(W - t) * (H - t) / k / k / 100:.1f}".replace(".", ",")
    d += C(ox + W / 2, oy + H / 2 + 2.5, 4, "thin") + T(ox + W / 2, oy + H / 2, "1", 5, "center")
    d += T(ox + W / 2, oy + H / 2 - 8, s, 3.5, "center")
    d += place("level", ox + W - 40, oy + H - 15, label="±0,000")
    d += T(ox + W / 2, oy - 32, "План этажа  М 1:50", 5, "center")
    widths = [12, 60, 28]
    tx, ttop = x1 - sum(widths) - 5, y0 + 15 + 15 + 8 * 5
    d += T(tx, ttop + 4, "Экспликация помещений", 5)
    d += table(tx, ttop, widths, ["№", "Наименование", "Площадь,\nм²"], 5, data=[("1", "Помещение", s), ("", "Итого", s)])


@template("foundation_a4", "Строительный узел / схема фундамента — А4", "build", "A4P", "Узел ленточного фундамента",
          "строительный узел фундамент ленточный схема разрез", "1:20")
def _tpl_foundation(project, area):
    x0, y0, x1, y1 = area
    d = project.drawing
    bx, by = x0 + 55, y0 + 110          # низ подушки по оси стены, М1:20
    pad = rect_pts(bx - 15, by, 30, 15)
    fbs = rect_pts(bx - 10, by + 15, 20, 60)
    brick = rect_pts(bx - 10, by + 75, 20, 30)
    for poly, pat, step in ((pad, "concrete", 2.0), (fbs, "concrete", 2.5), (brick, "metal", 1.5)):
        d += P(poly, closed=True) + HATCH([poly], pat, step, 45)
    d += L(bx - 10, by + 15.6, bx + 10, by + 15.6, "thin") + L(bx - 10, by + 75.6, bx + 10, by + 75.6, "thin")   # гидроизоляция
    gy = by + 45
    for a, b in ((bx - 45, bx - 10), (bx + 10, bx + 45)):
        d += L(a, gy, b, gy, "thin")
        x = a + 2
        while x < b:
            d += L(x, gy, x - 2, gy - 2, "thin")
            x += 4
    d += place("level", bx + 22, by + 75, label="±0,000") + place("level", bx + 22, gy, label="-0,600")
    d += place("level", bx + 22, by, label="-1,500")
    for e in (make_dim(bx - 15, by, bx + 15, by, -10, "horizontal"), make_dim(bx - 10, by + 105, bx + 10, by + 105, 8, "horizontal"),
              make_dim(bx - 15, by, bx - 15, by + 15, -12, "vertical"), make_dim(bx - 10, by + 15, bx - 10, by + 75, -17, "vertical")):
        e["k"] = 20.0
        d.append(e)
    d += T(bx, by - 25, "Узел 1. Ленточный фундамент  М 1:20", 3.5, "center")
    px, py = x0 + 110, y0 + 150
    d += T(px, py + 60, "Схема фундамента  М 1:200", 3.5)
    d += R(px, py, 60, 40) + R(px + 3, py + 3, 54, 34)
    for ax, mark in ((px + 1.5, "1"), (px + 58.5, "2")):
        d += place("axis_mark", ax, py + 50, scale=0.6, label=mark) + L(ax, py + 25, ax, py - 5, "axis")
    for ay, mark in ((py + 1.5, "А"), (py + 38.5, "Б")):
        d += place("axis_mark", px - 10, ay, rot=90, scale=0.6, label=mark) + L(px + 15, ay, px + 65, ay, "axis")
    notes = ["1. Подушка — бетон класса B15 по щебёночной подготовке 100 мм.",
             "2. Стеновые блоки ФБС по ГОСТ 13579-2018.",
             "3. Горизонтальная гидроизоляция — 2 слоя рулонного материала.",
             "4. Обратная засыпка — непучинистым грунтом с уплотнением."]
    for k, s in enumerate(notes):
        d += T(x0 + 8, y0 + 40 - k * 6, s, 3.5)


def _part_views(project, area):
    from . import geometry as geo
    from . import ops
    from .projection import make_drawing

    if not project.features:
        project.entities = make_rect(0, 0, 80, 50) + [make_circle(40, 25, 10), make_circle(12, 12, 4), make_circle(68, 12, 4),
                                                     make_circle(12, 38, 4), make_circle(68, 38, 4)]
        ops.create_feature(project, "extrude", height=20)
        project.name, project.material = "Плита", "Сталь 45 ГОСТ 1050-2013"
    make_drawing(project, geo.build_solid(project.features))
    x0, y0, _, _ = area
    req = ["Технические требования", "1. Неуказанные предельные отклонения: H14, h14, ±IT14/2.",
           "2. Острые кромки притупить.", "3. Покрытие: Хим. Окс. прм."]
    for k, s in enumerate(req):
        project.drawing += T(x0 + 5, y0 + 28 - k * 6, s, 3.5)


@template("part_views_a4", "Чертёж детали в 3 проекциях — А4", "mech", "A4P", "Плита",
          "чертеж детали три проекции виды спереди сверху слева")
def _tpl_part_a4(project, area):
    _part_views(project, area)


@template("part_views_a3", "Чертёж детали в 3 проекциях — А3", "mech", "A3L", "Плита",
          "чертеж детали три проекции виды спереди сверху слева")
def _tpl_part_a3(project, area):
    _part_views(project, area)


@template("spec_a4", "Спецификация по ГОСТ 2.106-96 — А4", "mech", "A4P", "Сборочная единица",
          "спецификация гост 2.106 поз обозначение наименование кол")
def _tpl_spec(project, area):
    x0, y0, x1, y1 = area
    d = project.drawing
    widths = [6, 6, 8, 70, 63, 10, 22]
    rows = int((y1 - y0 - 15) // 8)
    des = project.designation or "АБВГ.000000.001"
    data = [("", "", "", "", "", "", "")] * rows
    data[1] = ("", "", "", "", "Документация", "", "")
    data[3] = ("А4", "", "", f"{des} СБ", "Сборочный чертёж", "", "")
    data[5] = ("", "", "", "", "Детали", "", "")
    data[7] = ("А4", "", "1", f"{des[:-1]}2", "Плита", "1", "")
    data[9] = ("", "", "", "", "Стандартные изделия", "", "")
    data[11] = ("", "", "2", "", "Болт М10×40 ГОСТ 7798-70", "4", "")
    data[12] = ("", "", "3", "", "Гайка М10 ГОСТ 5915-70", "4", "")
    data[13] = ("", "", "4", "", "Шайба 10 ГОСТ 11371-78", "4", "")
    d += table(x0, y1, widths, ["Формат", "Зона", "Поз.", "Обозначение", "Наименование", "Кол.", "Приме-\nчание"], rows,
               data=data, vertical=(0, 1, 2, 5))
    nx = x0 + sum(widths[:4]) + widths[4] / 2
    sections = {data[r][4] for r in (1, 5, 9)}
    for e in [e for e in d if e["type"] == "text" and e["text"] in sections]:   # разделы — по центру графы, подчёркнуты
        w = CHAR_W * e["h"] * len(e["text"])
        e.update(x=nx, align="center")
        d += L(nx - w / 2, e["y"] - 0.8, nx + w / 2, e["y"] - 0.8, "thin")


def load_template(project, tid: str) -> Template:
    """Открыть шаблон в проекте: формат листа со штампом, наименование, содержимое листа заменяется шаблоном."""
    from .ops import set_canvas
    from .stamp import H as STAMP_H, frame_rect

    t = TEMPLATES.get(tid)
    if t is None:
        raise ValueError(f"нет шаблона {tid!r}; есть: {', '.join(TEMPLATES)}")
    set_canvas(project, t.canvas)
    project.frame["scale"] = t.scale
    project.name = t.title
    project.drawing.clear()
    fx, fy, fw, fh = frame_rect(project.frame)
    t.build(project, (fx, fy + STAMP_H, fx + fw, fy + fh))
    return t


def catalog_text() -> str:
    """Каталог для ИИ-помощника: id, название, выводы в системе элемента."""
    lines = []
    for sec, title in SECTIONS.items():
        items = [b for b in all_blocks() if b.section == sec]
        if not items:
            continue
        lines.append(f"[{title}]")
        for b in items:
            x0, y0, x1, y1 = bounds(b.entities())
            ports = ", ".join(f"{k} ({p[0]:g},{p[1]:g})" for k, p in b.ports.items())
            lines.append(f"- {b.id}: {b.name}; габарит x {x0:g}..{x1:g}, y {y0:g}..{y1:g}; выводы: {ports}"
                         + (f"; маркировка по умолчанию «{b.label}»" if b.label else ""))
    lines.append("Шаблоны листов (load_template): " + "; ".join(f"{t.id} — {t.name}" for t in TEMPLATES.values()))
    return "\n".join(lines)
