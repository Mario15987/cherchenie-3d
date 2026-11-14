"""ИИ-помощник: настройки (config.json рядом с программой), провайдеры, запрос в QThread, разбор ответа.

Ответ модели — JSON: {"message": "совет", "actions": [{"op": ..., ...}]}. Команды исполняет ops.apply_actions.
Сообщение пользователя — строка или, если приложены фото, список частей {"type": "text"} и {"type": "image"};
provider_messages переводит его в формат API: блоки image (Anthropic), image_url (OpenAI, OpenRouter, Groq),
inlineData (Gemini).
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import geometry as geo
from .model import CANVAS_MODES, sheet_size
from .stamp import W as STAMP_W, frame_rect, stamp_size

PROVIDERS = {
    "anthropic": "Anthropic Claude",
    "openai": "OpenAI-совместимый",
    "gemini": "Google Gemini",
    "openrouter": "OpenRouter",
    "groq": "Groq",
    "custom": "Свой Base URL (OpenAI-совместимый)",
}
DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "groq": "https://api.groq.com/openai/v1",
    "custom": "http://localhost:11434/v1",
    "anthropic": "",
}
# Модели Claude для выпадающего списка; поле редактируемое — можно вписать любую.
CLAUDE_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]
# Модели, которые принимают output_config.effort и серверный fallback при отказе.
_EFFORT = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5-5", "claude-fable-5")
_FALLBACK = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
MAX_IMAGES = 16            # картинок в одном запросе (Vision-модели Groq принимают 3–5, берём 3)
HISTORY_IMAGES = 1         # в переписке картинки остаются только у последнего сообщения с ними


def app_dir() -> Path:
    """Папка рядом с .exe (или с main.py при запуске из исходников)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return app_dir() / "config.json"


def load_config() -> dict:
    cfg = {"provider": "anthropic", "api_key": "", "model": CLAUDE_MODELS[0], "base_url": ""}
    try:
        cfg.update(json.loads(config_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    save_json(config_path(), cfg)


def save_json(path: Path, obj) -> None:
    """Запись через временный файл: при сбое посреди записи старый файл цел (битый config.json читался бы
    как пустой — и тема, и ключ сбросились бы). OneDrive и антивирус ненадолго держат файл — пробуем ещё раз."""
    tmp = path.with_name(path.name + ".tmp")
    data = json.dumps(obj, ensure_ascii=False, indent=2)
    for attempt in range(6):
        try:
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))


def update_config(changes: dict) -> dict:
    """Записать в config.json только эти ключи поверх того, что сейчас в файле: другое окно или вторая копия
    программы со старым снимком настроек не затирает чужие изменения (например, выбранную тему)."""
    cfg = load_config()
    cfg.update(changes)
    save_config(cfg)
    return cfg


# ---------------------------------------------------------------- промпт
SCHEMA_TEXT = """\
Ответь ТОЛЬКО одним JSON-объектом без пояснений вокруг:
{"message": "коротко по-русски: что сделано или совет", "actions": [ ...команды... ]}
Если ничего менять не нужно — "actions": [].

Единицы — миллиметры. Ось X вправо, ось Y вверх, начало координат (0,0). Углы — градусы, против часовой стрелки от оси X.
Команды (поле "op" обязательно):
Эскиз (у кривых необязательное поле "style": main|thin|hidden|axis|fold|wavy|axis_thick|open|zigzag — девять типов линий ГОСТ 2.303):
- {"op":"add_line","x1","y1","x2","y2"}            отрезок
- {"op":"add_polyline","points":[[x,y],...],"closed":true}  ломаная; closed замыкает контур
- {"op":"add_rect","x","y","w","h"}                прямоугольник, (x,y) — левый нижний угол
- {"op":"add_circle","cx","cy","r"}                окружность (можно "d" вместо "r")
- {"op":"add_arc","cx","cy","r","a0","a1"}         дуга от a0 до a1 против часовой стрелки
- {"op":"add_axis","x1","y1","x2","y2"}            осевая линия (в контуры не входит; ось для вращения)
- {"op":"fillet_corner","id1","p1":[x,y],"id2","p2":[x,y],"r"}   скругление угла двух отрезков (p — точка на нужной части)
- {"op":"chamfer_corner","id1","p1","id2","p2","d","d2"}         фаска угла (d2 необязательно)
- {"op":"mirror","ids":[...],"p":[x,y],"q":[x,y],"keep":true}    симметрия относительно прямой p-q
- {"op":"pattern_circular","ids":[...],"center":[x,y],"count":4,"angle":360}  массив по окружности
- {"op":"pattern_linear","ids":[...],"nx":3,"ny":1,"dx":20,"dy":0}             массив по сетке
- {"op":"update","id","поле":значение}             изменить числа объекта, "style" или "tol"; у отрезка "length"
  (от начала по тому же углу) и "angle" (поворот вокруг начала), у окружности "d" или "r", у прямоугольника "w"/"h"
  (id любой его стороны), "axes": true — центровые линии окружности
- {"op":"move","ids":[...],"dx","dy"}              сдвинуть объекты
- {"op":"delete","ids":[...]}                      удалить объекты
- {"op":"clear_sketch"}                            очистить текущий эскиз
- {"op":"close_contours","tol":1.0}                свести разрывы между концами отрезков в пределах tol мм
Чертёж (размеры и обозначения кладутся на лист):
- {"op":"add_dim","x1","y1","x2","y2","off":8,"kind":"aligned"|"horizontal"|"vertical","tol":"±0,1"|"H7"|"H7/g6"}
- {"op":"add_diadim","cx","cy","r","ang":45,"tol"} / {"op":"add_raddim","cx","cy","r","ang":45}  ⌀ и R
- {"op":"set_dim_value","id","value"}  управляющий размер: размер, поставленный на концы отрезка или на окружность,
  меняет саму геометрию (длину, диаметр, ширину прямоугольника)
- {"op":"add_leader","x1","y1","x2","y2","text"}   выноска с полкой
- {"op":"add_rough","x","y","value":"3,2","param":"Ra"|"Rz"}  шероховатость
- {"op":"add_frame","format":"A4"|"A3"|"A2"|"A1","orient":"landscape"|"portrait","scale":"1:1"}  рамка и штамп ГОСТ 2.104
- {"op":"set_canvas","mode":"fragment"|"A4P"|"A4L"|"A3L"|"A3P"}  формат полотна: бесконечное поле или лист
- {"op":"set_props","name","designation","material"} данные для штампа
- {"op":"add_text","x","y","text","h":3.5,"align":"left"|"center"|"right"}  надпись (x,y — линия основания)
Библиотека ГОСТ / СПДС / ЕСКД (каталог с выводами — ниже):
- {"op":"load_template","template_id"}  открыть шаблон листа: формат со штампом, таблицы; прежнее содержимое листа заменяется
- {"op":"insert_library_block","block_id","x","y","rotation":0,"scale":1,"label":"QF1"}  поставить готовый элемент:
  (x,y) — точка вставки = начало системы элемента; rotation — градусы против часовой; label — маркировка (QF1, ОП-12, А)
- {"op":"add_wall","x1","y1","x2","y2","t":3.8}  стена по оси со штриховкой кладки (t — толщина на листе, мм)
3D (операция забирает ВСЕ замкнутые контуры текущего эскиза; вложенные контуры — отверстия; после операции эскиз пуст):
- {"op":"extrude","height":10,"base":"plane"|"top","op_mode":"add"}   выдавливание (поле "op" занято — по умолчанию добавляет)
- {"op":"cut","depth":5} или {"op":"cut","through":true}  вырез сверху на глубину или насквозь ("cut_extrude" — то же)
  У extrude, cut, revolve необязательное "region":[x_min,y_min,x_max,y_max] — взять только кривые внутри прямоугольника
  (один вид детали, а не весь лист). Если активен лист чертежа, контуры листа копируются в операцию, лист не меняется.
- {"op":"revolve","angle":360}                     вращение профиля вокруг первой осевой линии эскиза
- {"op":"shell","thickness":2,"open_top":true}     оболочка
- {"op":"fillet3d","size":2} / {"op":"chamfer3d","size":1}  скругление / фаска всех внешних рёбер тела

Правила: контур должен быть замкнут — концы отрезков совпадают точно. Перед вырезом нарисуй в пустом эскизе только
контур выреза. Профиль вращения не должен пересекать ось. Не придумывай id — бери из списка.
Полотно — поле "полотно" в состоянии. Кривые ложатся в активный слой. Если активен лист А4/А3, каждая точка каждого
объекта и размера должна лежать внутри "рамка_область" и вне "штамп" (лучше — в "свободно_над_штампом" с отступом 5 мм).
Если бесконечное полотно или эскиз — черти свободно от начала координат (0,0).
Схемы, планы и узлы собирай из готовых элементов библиотеки, а не рисуй символы линиями: ставь insert_library_block,
соединяй выводы отрезками add_line. Вывод элемента в мире: (x,y) + поворот(rotation) × масштаб × вывод.
Схемные элементы (qf1, pi, fu…) стоят верхним выводом в точке вставки и идут вниз на 20 мм: следующий элемент цепи —
на 20 мм ниже. Однолинейная схема: ввод сверху, вводной автомат, счётчик, шина (две параллельные add_line),
отходящие линии — автоматы под шиной с шагом 25–30 мм, подписи групп add_text.
Трасса ВЛ: опоры pole_rc_plan по линии в масштабе листа (М1:1000 — 35 м = 35 мм), между ними add_line и подпись
пролёта add_text «35 м», маркировка опор ОП-1…ОП-n.
Строительные элементы в М1:100 (1 м = 10 мм): стены add_wall, двери door, окна window, ворота gate ставь в разрыв стены
(между концами двух add_wall), оси — axis_mark с марками 1, 2… и А, Б…; на листе М1:50 — scale 2.
Если пользователь просит готовый лист (однолинейная схема, план, спецификация) — начни с load_template,
затем добавь или замени элементы в его рабочем поле.
"""


ATTACH_TEXT = """\
Вложения. В сообщении могут быть фото и сканы, текст документа Word или файла (таблицы — в Markdown) и «локальный
анализ изображения» — сводка, посчитанная программой по пикселям: габарит объекта в кадре, пропорции, окружности,
дуги, массивы отверстий и прямые в долях габарита объекта (x вправо, y вверх, 0..1; диаметры — в долях ширины).
Сводка — для пропорций и взаимного расположения; числа размеров читай с самого изображения или бери из текста.
Перспектива и наклон снимка в сводке не учтены. Строй в координатах мм от (0,0) или внутри рамки листа.
Сценарий А — фото бумажного чертежа или эскиза от руки: прочитай все размерные числа (L, Ø, R, углы, фаски 2×45°,
«4 отв. Ø8»), распознай контур детали, осевые линии и отверстия; на схеме — УГО (ставь элементы библиотеки
insert_library_block, соединяй add_line). Построй чистовой чертёж в мм: контур — основной линией, оси — add_axis,
у окружностей "axes": true, все размеры (add_dim, add_diadim, add_raddim) ставь точно на концы отрезков и на окружности
— тогда они управляющие. Размер, которого нет на снимке, оцени по пропорциям из сводки и назови его в message.
Сценарий Б — фото реальной детали (фланец, кронштейн, пластина, втулка, крепёж): определи форму — внешний габарит,
симметрию, вырезы, фаски, число и расположение отверстий (по окружности — pattern_circular или по сводке).
Абсолютный размер бери из запроса, видимой линейки или известного предмета в кадре; иначе прими правдоподобный
типоразмер и перечисли принятые размеры в message. Начерти 2D в мм с размерами на геометрии (пользователь поправит их
двойным щелчком), затем, если просят 3D или деталь — тело, выдави extrude (высота — толщина детали); отверстия —
вложенные контуры того же эскиза или cut.
Сценарий В — документ Word или таблица (ТЗ, таблица размеров, ведомость опор, кабельный журнал, спецификация): вытащи
из текста и таблиц размеры и параметры. Деталь — чертёж по ним; электрическая схема — из элементов библиотеки
(однолинейная — шаблон single_line_*); строительный план — стены, двери, окна; таблица или спецификация — линиями и
add_text на листе А4/А3 (set_canvas или load_template). Не хватает данных — построй по тому, что есть, и перечисли
пробелы в message. Рисунки из документа приложены отдельными изображениями с подписью «из документа».
"""
# Быстрые кнопки над полем ввода: (ключ, надпись, какое вложение нужно, текст запроса).
ATTACH_PRESETS = [
    ("photo_drawing", "Оцифровать фото чертежа / эскиза", "image",
     "Сценарий А. На вложенном фото — бумажный чертёж или эскиз от руки. Прочитай все размеры (L, Ø, R, углы, фаски, число "
     "отверстий), распознай контур, осевые линии и отверстия (на схеме — УГО) и начерти чистовой чертёж в мм со всеми размерами."),
    ("photo_part", "Начертить деталь по фото", "image",
     "Сценарий Б. На вложенном фото — реальная деталь. Определи форму: габарит, симметрию, вырезы, фаски, число и расположение "
     "отверстий. Начерти 2D-чертёж в мм с управляющими размерами и выдави 3D-модель."),
    ("word_spec", "Построить чертеж / схему по ТЗ из Word", "doc",
     "Сценарий В. Во вложенном документе — техническое задание, таблица размеров или параметры схемы. Прочитай текст и "
     "таблицы и начерти по ним деталь, однолинейную схему или таблицу / спецификацию на листе А4/А3."),
]


def _round(v):
    return round(v, 3) if isinstance(v, float) else v


FEATURE_KEYS = ("op", "height", "base", "through", "depth", "angle", "thickness", "open_top", "size", "suppressed")


def canvas_context(project, layer: str = "sketch") -> dict:
    """Что помощнику знать о полотне: активный слой, режим, границы рабочей зоны и штампа в мм."""
    if layer != "drawing":
        return {"активный_слой": "эскиз для 3D", "правило": "черти от начала координат (0,0); рамки нет"}
    fr = project.sheet()
    if not fr:
        return {"активный_слой": "лист чертежа", "режим": CANVAS_MODES["fragment"][0],
                "правило": "рамки и штампа нет — черти свободно от (0,0)"}
    w, h = sheet_size(fr["format"], fr["orient"])
    fx, fy, fw, fh = frame_rect(fr)
    STAMP_H = stamp_size(fr)[1]
    r = lambda *v: [round(x, 1) for x in v]  # noqa: E731
    return {"активный_слой": "лист чертежа", "режим": CANVAS_MODES[project.canvas_mode()][0],
            "лист": r(fr["x"], fr["y"], fr["x"] + w, fr["y"] + h),
            "рамка_область": r(fx, fy, fx + fw, fy + fh),
            "штамп": r(fx + fw - STAMP_W, fy, fx + fw, fy + STAMP_H),
            "свободно_над_штампом": r(fx + 5, fy + STAMP_H + 5, fx + fw - 5, fy + fh - 5),
            "формат_прямоугольников": "[x_min, y_min, x_max, y_max], мм",
            "правило": "всё строго внутри рамки и не заходя на штамп"}


def build_system_prompt(project, solid, sketch: list | None = None, layer: str = "sketch") -> str:
    sketch = project.entities if sketch is None else sketch
    ents = [{k: _round(v) for k, v in e.items()} for e in sketch]
    c = geo.contours(project.profile_of(sketch))
    feats = [{"name": f["name"], "type": f["type"], **{k: f[k] for k in FEATURE_KEYS if k in f},
              "объектов_в_эскизе": len(f.get("sketch", [])), "status": solid.statuses.get(f["id"]) or "ok"} for f in project.features]
    drawing = [{k: _round(v) for k, v in e.items()} for e in project.drawing if e.get("gen") != "views"][:80]
    body = "нет тела"
    if not solid.empty:
        lo, hi = solid.bbox()
        body = f"габарит X {lo[0]:.1f}..{hi[0]:.1f}, Y {lo[1]:.1f}..{hi[1]:.1f}, Z {lo[2]:.1f}..{hi[2]:.1f} мм"
    state = {
        "деталь": {"наименование": project.name, "обозначение": project.designation, "материал": project.material},
        "эскиз": ents,
        "контуры": {"замкнутых": c.closed, "незамкнутых_цепочек": c.open_chains,
                    "свободные_концы": [[round(x, 3), round(y, 3)] for x, y in c.dangling[:40]]},
        "дерево_построения": feats,
        "лист_чертежа": drawing,
        "тело": body,
        "полотно": canvas_context(project, layer),
        "штамп_данные": project.frame,
    }
    from .library import catalog_text

    return ("Ты — помощник конструктора в САПР «Черчение 3D». Пользователь просит словами — ты чертишь и строишь модель командами.\n\n"
            + SCHEMA_TEXT + "\n" + ATTACH_TEXT + "\nКаталог библиотеки (block_id: название; габарит и выводы — в системе элемента, мм):\n" + catalog_text()
            + "\n\nТекущее состояние проекта (JSON):\n" + json.dumps(state, ensure_ascii=False))


def parse_reply(text: str) -> dict:
    """Достаёт JSON из ответа (терпимо к ```json и тексту вокруг)."""
    t = text.strip()
    if "```" in t:
        t = t.split("```", 2)[1]
        t = t[4:] if t.lower().startswith("json") else t
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < start:
        return {"message": text.strip(), "actions": []}
    try:
        data = json.loads(t[start:end + 1])
    except ValueError:
        return {"message": text.strip(), "actions": []}
    if not isinstance(data, dict):
        return {"message": text.strip(), "actions": []}
    acts = data.get("actions") if isinstance(data.get("actions"), list) else []
    clean = [a for a in acts if isinstance(a, dict) and all(not isinstance(v, float) or math.isfinite(v) for v in a.values())]
    return {"message": str(data.get("message", "")), "actions": clean}


# Памятка для «О программе» и «Настроек ИИ»: без модели с Vision фото до ИИ не доходят.
VISION_HINT_TITLE = "💡 Важный нюанс по выбору модели в настройках ИИ для работы с фото:"
VISION_HINT = ("Чтобы ИИ «видел» прикрепленные фотографии чертежей и деталей, в настройках программы должна быть прописана "
               "модель с поддержкой зрения (Vision) — например, бесплатная `gemini-2.5-flash` (через Google AI Studio или "
               "OpenRouter `google/gemini-2.5-flash:free`) или `llama-4-scout` (в Groq).")
VISION_MEMO = ("💡 Для фото нужна модель с Vision: `gemini-2.5-flash` (Google AI Studio или OpenRouter "
               "`google/gemini-2.5-flash:free`) или `llama-4-scout` (Groq).")


def hint_html(text: str) -> str:
    """`имя-модели` → моноширинно; остальное экранируется."""
    import html as _html
    import re as _re

    return _re.sub(r"`([^`]+)`", r"<code>\1</code>", _html.escape(text, quote=False))


# ---------------------------------------------------------------- вложения в запросе
def user_content(text: str, attachments: list) -> str | list:
    """Сообщение пользователя с вложениями (cad.attachments.Attachment). Без картинок — строка: документы идут текстом.
    С картинками — список частей: подпись и сводка анализа перед каждой картинкой, запрос пользователя — последним."""
    if not attachments:
        return text
    parts = [{"type": "text", "text": a.prompt_text()} for a in attachments if a.kind != "image"]
    images = [a for a in attachments if a.kind == "image"]
    for i, a in enumerate(images, 1):
        src = f", из документа «{a.parent}»" if a.parent else ""
        parts.append({"type": "text", "text": f"Изображение {i} «{a.name}»{src}, {a.size[0]}×{a.size[1]} px.\n{a.text}"})
        parts.append({"type": "image", "media_type": a.media_type, "data": a.b64, "name": a.name})
    parts.append({"type": "text", "text": "Запрос пользователя: " + text})
    if not images:
        return "\n\n".join(p["text"] for p in parts)
    return parts


def has_images(content) -> bool:
    return isinstance(content, list) and any(p.get("type") == "image" for p in content)


def compact_history(messages: list[dict], keep: int = HISTORY_IMAGES) -> list[dict]:
    """Картинки остаются только у последних keep сообщений с ними — у прежних вместо картинки строка-пометка
    (сводка анализа остаётся): переписка не пересылает одни и те же фото в каждом запросе."""
    out, seen = [], 0
    for m in reversed(messages):
        c = m["content"]
        if has_images(c):
            if seen >= keep:
                c = [p if p["type"] != "image" else {"type": "text", "text": f"[изображение «{p.get('name', '')}» было приложено ранее]"}
                     for p in c]
            seen += 1
        out.append({**m, "content": c})
    return out[::-1]


def image_limit(cfg: dict) -> int:
    groq = cfg.get("provider") == "groq" or "groq.com" in (cfg.get("base_url") or "")
    return 3 if groq else MAX_IMAGES


def _limit_images(messages: list[dict], limit: int) -> list[dict]:
    """Не больше limit картинок на запрос: лишние (самые ранние) — пометкой."""
    total = sum(1 for m in messages if has_images(m["content"]) for p in m["content"] if p["type"] == "image")
    drop = max(0, total - limit)
    out = []
    for m in messages:
        c = m["content"]
        if drop and has_images(c):
            new = []
            for p in c:
                if p["type"] == "image" and drop:
                    new.append({"type": "text", "text": f"[изображение «{p.get('name', '')}» не отправлено: не больше {limit} картинок за запрос]"})
                    drop -= 1
                else:
                    new.append(p)
            c = new
        out.append({**m, "content": c})
    return out


def provider_messages(provider: str, messages: list[dict], limit: int = MAX_IMAGES) -> list[dict]:
    """Переписка в формате API провайдера. Строки остаются строками (у Gemini — часть с текстом)."""
    out = []
    for m in _limit_images(messages, limit):
        c = m["content"]
        if provider == "gemini":
            role = "model" if m["role"] == "assistant" else "user"
            parts = [{"text": c}] if isinstance(c, str) else [
                {"text": p["text"]} if p["type"] == "text" else {"inlineData": {"mimeType": p["media_type"], "data": p["data"]}} for p in c]
            out.append({"role": role, "parts": parts})
        elif isinstance(c, str):
            out.append({"role": m["role"], "content": c})
        elif provider == "anthropic":
            out.append({"role": m["role"], "content": [
                {"type": "text", "text": p["text"]} if p["type"] == "text"
                else {"type": "image", "source": {"type": "base64", "media_type": p["media_type"], "data": p["data"]}} for p in c]})
        else:                                   # OpenAI, OpenRouter, Groq, свой сервер
            extra = {"detail": "high"} if provider == "openai" else {}
            out.append({"role": m["role"], "content": [
                {"type": "text", "text": p["text"]} if p["type"] == "text"
                else {"type": "image_url", "image_url": {"url": f"data:{p['media_type']};base64,{p['data']}", **extra}} for p in c]})
    return out


# ---------------------------------------------------------------- провайдеры
class AIError(Exception):
    pass


def _post_json(url: str, body: dict, headers: dict, timeout: float = 180.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        if e.code in (401, 403):
            raise AIError(f"Ключ не подошёл ({e.code}). Проверьте API-ключ в настройках ИИ.") from e
        if e.code == 429:
            raise AIError("Превышен лимит запросов (429). Подождите и повторите.") from e
        raise AIError(f"Сервер ответил {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise AIError(f"Нет связи с сервером: {e.reason}") from e
    except TimeoutError as e:
        raise AIError("Сервер не ответил вовремя") from e


def _call_anthropic(cfg, system, messages) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=cfg["api_key"], timeout=180.0, max_retries=2)
    model = cfg["model"] or CLAUDE_MODELS[0]
    kwargs = {"model": model, "max_tokens": 16000, "system": system, "messages": provider_messages("anthropic", messages, image_limit(cfg))}
    if model.startswith(_EFFORT):
        kwargs["output_config"] = {"effort": "medium"}
    try:
        if model in _FALLBACK:
            # При отказе по политике сервер сам повторит запрос на рекомендованной модели.
            resp = client.beta.messages.create(**kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            resp = client.messages.create(**kwargs)
    except anthropic.AuthenticationError as e:
        raise AIError("Ключ Anthropic не подошёл. Проверьте его в настройках ИИ.") from e
    except anthropic.PermissionDeniedError as e:
        raise AIError("У ключа нет доступа к этой модели.") from e
    except anthropic.NotFoundError as e:
        raise AIError(f"Модель {model} не найдена.") from e
    except anthropic.RateLimitError as e:
        raise AIError("Превышен лимит запросов Anthropic. Подождите и повторите.") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"Ошибка Anthropic API ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIError("Нет связи с Anthropic API. Проверьте интернет.") from e
    if resp.stop_reason == "refusal":
        raise AIError("Модель отказалась выполнять этот запрос.")
    return "".join(b.text for b in resp.content if b.type == "text")


def _call_openai_like(cfg, system, messages) -> str:
    base = (cfg.get("base_url") or DEFAULT_BASE[cfg["provider"]]).rstrip("/")
    headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}
    if cfg["provider"] == "openrouter":
        headers["X-Title"] = "Cherchenie 3D"   # заголовок HTTP — только латиница
    body = {"model": cfg["model"], "messages": [{"role": "system", "content": system},
                                                *provider_messages(cfg["provider"], messages, image_limit(cfg))],
            "response_format": {"type": "json_object"}}
    try:
        data = _post_json(base + "/chat/completions", body, headers)
    except AIError as e:
        if "response_format" not in str(e) and "json_object" not in str(e):
            raise
        body.pop("response_format")  # не все совместимые серверы понимают JSON-режим
        data = _post_json(base + "/chat/completions", body, headers)
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(f"Неожиданный ответ сервера: {str(data)[:300]}") from e


def _call_gemini(cfg, system, messages) -> str:
    base = (cfg.get("base_url") or DEFAULT_BASE["gemini"]).rstrip("/")
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": provider_messages("gemini", messages, image_limit(cfg)),
            "generationConfig": {"responseMimeType": "application/json"}}
    data = _post_json(f"{base}/models/{cfg['model']}:generateContent", body, {"x-goog-api-key": cfg["api_key"]})
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(f"Неожиданный ответ Gemini: {str(data)[:300]}") from e


def ask(cfg: dict, system: str, messages: list[dict]) -> dict:
    if not cfg.get("api_key") and cfg["provider"] != "custom":
        raise AIError("Не задан API-ключ. Откройте «ИИ → Настройки».")
    if not cfg.get("model"):
        raise AIError("Не выбрана модель. Откройте «ИИ → Настройки».")
    if cfg["provider"] == "anthropic":
        text = _call_anthropic(cfg, system, messages)
    elif cfg["provider"] == "gemini":
        text = _call_gemini(cfg, system, messages)
    else:
        text = _call_openai_like(cfg, system, messages)
    reply = parse_reply(text)
    reply["raw"] = text
    return reply


class AIWorker(QThread):
    """Запрос к ИИ в отдельном потоке: интерфейс и черчение не замирают."""
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, cfg: dict, system: str, messages: list[dict], parent=None):
        super().__init__(parent)
        self.cfg, self.system, self.messages = dict(cfg), system, list(messages)

    def run(self):
        try:
            self.done.emit(ask(self.cfg, self.system, self.messages))
        except AIError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 — любую ошибку показываем в чате, поток не должен падать
            self.failed.emit(f"Ошибка: {e}")
