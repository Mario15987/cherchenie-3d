// Компоновка листа: формат, рамка, основная надпись (своё упрощённое оформление по ГОСТ 2.104),
// расположение видов по ГОСТ 2.305 (метод первого угла) и подбор стандартного масштаба (ГОСТ 2.302).
import type { DrawingDoc, Project, ViewKind } from '../model/types'
import type { ViewProjection } from '../kernel/protocol'

export const SHEETS = { A3: { w: 420, h: 297 }, A4: { w: 210, h: 297 } } as const
export const TITLE = { w: 185, h: 55 }
const MARGIN = { left: 20, other: 5 }
const GAP = 18

// Стандартный ряд масштабов: увеличения и уменьшения.
const SCALES = [10, 5, 4, 2.5, 2, 1, 1 / 2, 1 / 2.5, 1 / 4, 1 / 5, 1 / 10, 1 / 20, 1 / 50]

export function scaleLabel(s: number) {
  if (s >= 1) return `${Number(s.toFixed(2))}:1`
  return `1:${Number((1 / s).toFixed(2))}`
}

export interface PlacedView {
  view: ViewProjection
  /** Центр вида на листе, мм (ось Y листа вверх). */
  cx: number
  cy: number
}

export interface Layout {
  sheet: { w: number; h: number }
  frame: { x: number; y: number; w: number; h: number }
  scale: number
  views: PlacedView[]
  fits: boolean
}

const size = (v: ViewProjection | undefined) => (v ? [v.max[0] - v.min[0], v.max[1] - v.min[1]] : [0, 0])

export function layout(doc: DrawingDoc, views: ViewProjection[]): Layout {
  const sheet = SHEETS[doc.format]
  const frame = { x: MARGIN.left, y: MARGIN.other, w: sheet.w - MARGIN.left - MARGIN.other, h: sheet.h - 2 * MARGIN.other }
  const get = (k: ViewKind) => views.find((v) => v.kind === k)
  const [wf, hf] = size(get('front')), [wl, hl] = size(get('left')), [, ht] = size(get('top')), [wi, hi] = size(get('iso'))
  // Свободная область над основной надписью и слева от неё.
  const area = { x: frame.x + 10, y: frame.y + TITLE.h + 8, w: frame.w - 20, h: frame.h - TITLE.h - 18 }

  const need = (s: number) => {
    const colRight = Math.max(wl, wi)
    const width = s * (wf + colRight) + (colRight ? GAP : 0)
    const height = Math.max(s * hf + (ht ? GAP + s * ht : 0), s * (hl + (hi ? hi : 0)) + (hi ? GAP : 0))
    return { width, height }
  }
  const chosen = doc.scale === 'auto' ? SCALES.find((s) => { const n = need(s); return n.width <= area.w && n.height <= area.h }) ?? SCALES[SCALES.length - 1] : doc.scale
  const s = chosen
  const n = need(s)

  // Главный вид — сверху слева, вид слева — справа от него, вид сверху — под ним, аксонометрия — под видом слева.
  const left0 = area.x + (area.w - n.width) / 2
  const top0 = area.y + area.h - (area.h - n.height) / 2
  const out: PlacedView[] = []
  const front = get('front')
  const fcx = left0 + (s * wf) / 2
  const fcy = top0 - (s * hf) / 2
  if (front) out.push({ view: front, cx: fcx, cy: fcy })
  const rightX = left0 + s * wf + GAP
  const left = get('left')
  if (left) out.push({ view: left, cx: rightX + (s * wl) / 2, cy: fcy })
  const top = get('top')
  if (top) out.push({ view: top, cx: fcx, cy: fcy - (s * hf) / 2 - GAP - (s * ht) / 2 })
  const iso = get('iso')
  if (iso) out.push({ view: iso, cx: rightX + (s * wi) / 2, cy: fcy - (s * hf) / 2 - GAP - (s * hi) / 2 })
  return { sheet, frame, scale: s, views: out, fits: n.width <= area.w + 1e-6 && n.height <= area.h + 1e-6 }
}

/** Переводит точку вида в координаты листа. */
export function toSheet(p: PlacedView, s: number, x: number, y: number): [number, number] {
  const v = p.view
  const cx = (v.min[0] + v.max[0]) / 2, cy = (v.min[1] + v.max[1]) / 2
  return [p.cx + (x - cx) * s, p.cy + (y - cy) * s]
}

export interface TitleCell { x: number; y: number; w: number; h: number; label?: string; value?: string; big?: boolean }

/** Упрощённая основная надпись: своё оформление, без файлов оформления ASCON. */
export function titleBlock(l: Layout, project: Project): TitleCell[] {
  const x0 = l.frame.x + l.frame.w - TITLE.w, y0 = l.frame.y
  const cells: TitleCell[] = []
  const roles = ['Утв.', 'Н. контр.', 'Т. контр.', 'Пров.', 'Разраб.']
  roles.forEach((r, i) => {
    cells.push({ x: x0, y: y0 + i * 5, w: 17, h: 5, value: r })
    cells.push({ x: x0 + 17, y: y0 + i * 5, w: 23, h: 5 })
    cells.push({ x: x0 + 40, y: y0 + i * 5, w: 15, h: 5 })
    cells.push({ x: x0 + 55, y: y0 + i * 5, w: 10, h: 5 })
  })
  cells.push({ x: x0, y: y0 + 25, w: 65, h: 30 })
  cells.push({ x: x0 + 65, y: y0 + 25, w: 120, h: 30, label: 'Обозначение', value: project.part.props.designation || '—', big: true })
  cells.push({ x: x0 + 65, y: y0, w: 70, h: 25, label: 'Наименование', value: project.name, big: true })
  cells.push({ x: x0 + 135, y: y0 + 15, w: 17, h: 10, label: 'Лит.' })
  cells.push({ x: x0 + 152, y: y0 + 15, w: 18, h: 10, label: 'Масса' })
  cells.push({ x: x0 + 170, y: y0 + 15, w: 15, h: 10, label: 'Масштаб', value: scaleLabel(l.scale) })
  cells.push({ x: x0 + 135, y: y0 + 10, w: 25, h: 5, value: 'Лист 1' })
  cells.push({ x: x0 + 160, y: y0 + 10, w: 25, h: 5, value: 'Листов 1' })
  cells.push({ x: x0 + 135, y: y0, w: 50, h: 10, value: 'ReCAD' })
  return cells
}

/** DXF R12: виды (слои VISIBLE и HIDDEN), рамка и основная надпись (слой FRAME), в мм листа. */
export function drawingToDxf(project: Project, views: ViewProjection[]): string {
  const l = layout(project.drawing!, views)
  const out: string[] = ['0', 'SECTION', '2', 'ENTITIES']
  const f = (n: number) => String(Number(n.toFixed(4)))
  const line = (layer: string, a: [number, number], b: [number, number]) =>
    out.push('0', 'LINE', '8', layer, '10', f(a[0]), '20', f(a[1]), '30', '0', '11', f(b[0]), '21', f(b[1]), '31', '0')
  const rect = (x: number, y: number, w: number, h: number) => {
    line('FRAME', [x, y], [x + w, y]); line('FRAME', [x + w, y], [x + w, y + h]); line('FRAME', [x + w, y + h], [x, y + h]); line('FRAME', [x, y + h], [x, y])
  }
  rect(0, 0, l.sheet.w, l.sheet.h)
  rect(l.frame.x, l.frame.y, l.frame.w, l.frame.h)
  for (const c of titleBlock(l, project)) rect(c.x, c.y, c.w, c.h)
  for (const p of l.views) {
    for (const [layer, list] of [['VISIBLE', p.view.visible], ['HIDDEN', p.view.hidden]] as const) {
      for (const poly of list) {
        for (let i = 0; i + 3 < poly.length; i += 2) line(layer, toSheet(p, l.scale, poly[i], poly[i + 1]), toSheet(p, l.scale, poly[i + 2], poly[i + 3]))
      }
    }
  }
  out.push('0', 'ENDSEC', '0', 'EOF')
  return out.join('\n') + '\n'
}
