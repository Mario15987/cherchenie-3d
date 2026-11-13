"""Образцы вложений для самопроверки сборки (--selftest) и автотестов: чертёж пластины и ТЗ в Word."""
from __future__ import annotations

import io
import math

# Пластина 120×80, центральное отверстие Ø30, четыре Ø8 по окружности Ø60 под 45°, толщина 10 мм.
PLATE = {"w": 120, "h": 80, "hole": 30, "small": 8, "pcd": 60, "count": 4, "t": 10}
SPEC_ROWS = [["Параметр", "Значение"], ["Длина, мм", "120"], ["Ширина, мм", "80"], ["Толщина, мм", "10"],
             ["Центральное отверстие, Ø мм", "30"], ["Отверстия крепления", "4 отв. Ø8 на Ø60"]]


def plate_image(width: int = 2400, height: int = 1800, fmt: str = "PNG", photo: bool = False) -> bytes:
    """Чертёж пластины на белом (как скан) или, при photo=True, серая деталь на тёмном столе."""
    from PIL import Image, ImageDraw, ImageFont

    k = width * 0.75 / PLATE["w"]                       # пикселей на мм: пластина — 3/4 ширины кадра
    cx, cy = width / 2, height / 2
    im = Image.new("RGB", (width, height), (40, 44, 52) if photo else "white")
    d = ImageDraw.Draw(im)
    ink = (20, 20, 20)
    lw = max(2, int(0.5 * k))
    x0, y0 = cx - PLATE["w"] * k / 2, cy - PLATE["h"] * k / 2
    x1, y1 = cx + PLATE["w"] * k / 2, cy + PLATE["h"] * k / 2
    if photo:
        d.rounded_rectangle((x0, y0, x1, y1), radius=int(2 * k), fill=(178, 182, 188))
    else:
        d.rectangle((x0, y0, x1, y1), outline=ink, width=lw)

    def circle(px, py, dia):
        r = dia * k / 2
        if photo:
            d.ellipse((px - r, py - r, px + r, py + r), fill=(40, 44, 52))
        else:
            d.ellipse((px - r, py - r, px + r, py + r), outline=ink, width=lw)
    circle(cx, cy, PLATE["hole"])
    for i in range(PLATE["count"]):
        a = math.radians(45 + 90 * i)
        circle(cx + PLATE["pcd"] / 2 * k * math.cos(a), cy - PLATE["pcd"] / 2 * k * math.sin(a), PLATE["small"])
    if not photo:                                        # осевые штрихпунктиром и размер длины
        dash = int(6 * k)
        for xa in range(int(cx - 20 * k), int(cx + 20 * k), dash):
            d.line((xa, cy, xa + dash * 0.7, cy), fill=ink, width=max(1, lw // 2))
        for ya in range(int(cy - 20 * k), int(cy + 20 * k), dash):
            d.line((cx, ya, cx, ya + dash * 0.7), fill=ink, width=max(1, lw // 2))
        try:
            font = ImageFont.load_default(size=int(5 * k))
        except TypeError:                               # Pillow < 10.1
            font = ImageFont.load_default()
        d.text((cx - 8 * k, y0 - 9 * k), "120", fill=ink, font=font)
        d.text((cx + 10 * k, cy - 14 * k), "Ø30", fill=ink, font=font)
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


def spec_docx() -> bytes:
    """ТЗ на пластину: заголовок, текст, таблица размеров, рисунок-эскиз."""
    from .attachments import write_docx

    return write_docx([
        ("h1", "Техническое задание на пластину опорную"),
        ("p", "Изготовить пластину опорную из стали Ст3 по размерам таблицы 1. Отверстия сквозные."),
        ("h2", "Таблица 1. Размеры"),
        ("table", SPEC_ROWS),
        ("p", "Эскиз детали:"),
        ("image", plate_image(800, 600)),
    ])
