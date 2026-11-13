"""Готовит иконку приложения: прозрачные углы за скруглённой рамкой, assets/icon.png и мультиразмерный assets/icon.ico.

Запуск: .venv\\Scripts\\python tools\\make_icon.py [исходник]   (по умолчанию assets/icon_source.webp)
Нужен Pillow (только для подготовки иконки, в саму программу не входит).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SIZES = [16, 32, 48, 64, 128, 256]
DARK = 40   # кант рамки ярче этого; темнее — чёрный фон за рамкой
BEVEL = 16  # нижняя фаска рамки темнее канта, но ярче фона


def brightness(px) -> float:
    r, g, b = px[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b


def find_frame(img: Image.Image) -> tuple[int, int, int, int, float]:
    """Границы скруглённой рамки и радиус углов — по первым светлым пикселям от края."""
    w, h = img.size
    px = img.load()
    cy, cx = h // 2, w // 2
    left = next(x for x in range(w) if brightness(px[x, cy]) > DARK)
    right = next(x for x in range(w - 1, -1, -1) if brightness(px[x, cy]) > DARK)
    top = next(y for y in range(h) if brightness(px[cx, y]) > DARK)
    # Низ рамки — тёмная фаска (яркость около 20), а не светлый кант: ищем её край по более низкому порогу.
    bottom = next(y for y in range(h - 1, -1, -1) if brightness(px[cx, y]) > BEVEL)
    # По диагонали от угла до дуги: t = r·(1 − 1/√2), отсюда радиус. Берём верхние углы — у них яркий кант.
    radii = []
    for (x0, y0, dx, dy) in ((left, top, 1, 1), (right, top, -1, 1)):
        t = next(t for t in range(min(w, h) // 2) if brightness(px[x0 + dx * t, y0 + dy * t]) > DARK)
        radii.append(t / (1 - 1 / math.sqrt(2)))
    return left, top, right, bottom, sum(radii) / len(radii)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ASSETS / "icon_source.webp"
    img = Image.open(src).convert("RGBA")
    left, top, right, bottom, radius = find_frame(img)
    print(f"рамка: x {left}..{right}, y {top}..{bottom}, радиус углов ≈ {radius:.0f} px")

    # Маска рисуется в 4 раза крупнее и уменьшается — край получается сглаженным.
    k = 4
    w, h = img.size
    mask = Image.new("L", (w * k, h * k), 0)
    ImageDraw.Draw(mask).rounded_rectangle((left * k, top * k, (right + 1) * k - 1, (bottom + 1) * k - 1), radius=radius * k, fill=255)
    mask = mask.resize((w, h), Image.LANCZOS)
    img.putalpha(mask)

    # Обрезаем по рамке и делаем квадрат — иконка занимает всё поле.
    side = max(right - left + 1, bottom - top + 1)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img.crop((left, top, right + 1, bottom + 1)), ((side - (right - left + 1)) // 2, (side - (bottom - top + 1)) // 2))

    ASSETS.mkdir(exist_ok=True)
    png = canvas.resize((512, 512), Image.LANCZOS)
    png.save(ASSETS / "icon.png")
    base = canvas.resize((256, 256), Image.LANCZOS)
    base.save(ASSETS / "icon.ico", sizes=[(s, s) for s in SIZES])
    print(f"готово: {ASSETS / 'icon.png'} и {ASSETS / 'icon.ico'} ({', '.join(f'{s}×{s}' for s in SIZES)})")


if __name__ == "__main__":
    main()
