// Геометрия эскиза: точки, контуры, построение фигур, удаление с зависимостями, миграция старого формата.
import { nanoid } from 'nanoid'
import { ORIGIN_ID, type Id, type SketchConstraint, type SketchDimension, type SketchEntity, type SketchNode, type Vec2 } from './types'

export type Point = Extract<SketchEntity, { kind: 'point' }>
export type Line = Extract<SketchEntity, { kind: 'line' }>
export type Circle = Extract<SketchEntity, { kind: 'circle' }>

export const sid = () => nanoid(8)

export function points(s: Pick<SketchNode, 'entities'>): Map<Id, Point> {
  const m = new Map<Id, Point>([[ORIGIN_ID, { id: ORIGIN_ID, kind: 'point', x: 0, y: 0 }]])
  for (const e of s.entities) if (e.kind === 'point') m.set(e.id, e)
  return m
}

export const pt = (m: Map<Id, Point>, id: Id): Vec2 => {
  const p = m.get(id)
  return p ? [p.x, p.y] : [0, 0]
}

export interface Profile {
  /** Замкнутые многоугольники из отрезков, в порядке обхода. */
  polygons: Vec2[][]
  /** Ид отрезков каждого многоугольника, для ссылок на боковые грани. */
  polygonLines: Id[][]
  circles: { id: Id; c: Vec2; r: number }[]
  /** Цепочки отрезков, которые не замкнуты. */
  open: number
}

/** Ищет замкнутые контуры: компоненты графа отрезков, где у каждой точки ровно два отрезка. */
export function profile(s: Pick<SketchNode, 'entities'>): Profile {
  const pm = points(s)
  const lines = s.entities.filter((e): e is Line => e.kind === 'line' && !e.construction)
  const adj = new Map<Id, Line[]>()
  for (const l of lines) for (const p of [l.a, l.b]) adj.set(p, [...(adj.get(p) ?? []), l])

  const seen = new Set<Id>()
  const polygons: Vec2[][] = []
  const polygonLines: Id[][] = []
  let open = 0
  for (const start of lines) {
    if (seen.has(start.id)) continue
    // Компонента связности.
    const comp: Line[] = []
    const stack = [start]
    seen.add(start.id)
    while (stack.length) {
      const l = stack.pop()!
      comp.push(l)
      for (const p of [l.a, l.b]) for (const n of adj.get(p) ?? []) if (!seen.has(n.id)) { seen.add(n.id); stack.push(n) }
    }
    const closed = comp.length >= 3 && comp.every((l) => adj.get(l.a)!.length === 2 && adj.get(l.b)!.length === 2)
    if (!closed) { open++; continue }
    // Обход цикла.
    const order: Id[] = []
    const ids: Id[] = []
    let cur = comp[0]
    let at = cur.a
    for (let i = 0; i < comp.length; i++) {
      order.push(at)
      ids.push(cur.id)
      const next = at === cur.a ? cur.b : cur.a
      at = next
      const nl = adj.get(next)!.find((x) => x.id !== cur.id)!
      cur = nl
    }
    polygons.push(order.map((id) => pt(pm, id)))
    polygonLines.push(ids)
  }
  const circles = s.entities
    .filter((e): e is Circle => e.kind === 'circle' && !e.construction && e.r > 0)
    .map((c) => ({ id: c.id, c: pt(pm, c.c), r: c.r }))
  return { polygons, polygonLines, circles, open }
}

export function contourCount(s: Pick<SketchNode, 'entities'>) {
  const p = profile(s)
  return { closed: p.polygons.length + p.circles.length, open: p.open }
}

function polyArea(poly: Vec2[]) {
  let a = 0
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length]
    a += x1 * y2 - x2 * y1
  }
  return a / 2
}

/** Центр масс контуров (для ручки выдавливания). */
export function centroid(s: Pick<SketchNode, 'entities'>): Vec2 {
  const p = profile(s)
  let ax = 0, ay = 0, aw = 0
  for (const poly of p.polygons) {
    const a = Math.abs(polyArea(poly))
    const cx = poly.reduce((m, q) => m + q[0], 0) / poly.length
    const cy = poly.reduce((m, q) => m + q[1], 0) / poly.length
    ax += cx * a; ay += cy * a; aw += a
  }
  for (const c of p.circles) {
    const a = Math.PI * c.r * c.r
    ax += c.c[0] * a; ay += c.c[1] * a; aw += a
  }
  return aw > 0 ? [ax / aw, ay / aw] : [0, 0]
}

export interface Built {
  entities: SketchEntity[]
  constraints: SketchConstraint[]
  dimensions: SketchDimension[]
}

/** Прямоугольник как КОМПАС: четыре отрезка, горизонтальность, вертикальность, два размера. */
export function makeRect(p0: Vec2, p1: Vec2, reuse: { a?: Id } = {}): Built {
  const [x0, y0] = p0, [x1, y1] = p1
  const ids = [reuse.a ?? sid(), sid(), sid(), sid()]
  const pts: Vec2[] = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
  const entities: SketchEntity[] = []
  pts.forEach((p, i) => { if (!(i === 0 && reuse.a)) entities.push({ id: ids[i], kind: 'point', x: p[0], y: p[1] }) })
  const lines = [0, 1, 2, 3].map((i) => ({ id: sid(), kind: 'line' as const, a: ids[i], b: ids[(i + 1) % 4] }))
  entities.push(...lines)
  return {
    entities,
    constraints: [
      { id: sid(), kind: 'horizontal', refs: [lines[0].id] },
      { id: sid(), kind: 'horizontal', refs: [lines[2].id] },
      { id: sid(), kind: 'vertical', refs: [lines[1].id] },
      { id: sid(), kind: 'vertical', refs: [lines[3].id] },
    ],
    dimensions: [
      { id: sid(), kind: 'hdistance', refs: [ids[0], ids[1]], value: Math.abs(x1 - x0) },
      { id: sid(), kind: 'vdistance', refs: [ids[1], ids[2]], value: Math.abs(y1 - y0) },
    ],
  }
}

export function makeCircle(c: Vec2, r: number, reuse: { c?: Id } = {}): Built {
  const cid = reuse.c ?? sid()
  const circle: Circle = { id: sid(), kind: 'circle', c: cid, r }
  return {
    entities: [...(reuse.c ? [] : [{ id: cid, kind: 'point' as const, x: c[0], y: c[1] }]), circle],
    constraints: [],
    dimensions: [{ id: sid(), kind: 'diameter', refs: [circle.id], value: 2 * r }],
  }
}

/** Удаляет объекты и всё, что на них ссылается; точки без кривых тоже уходят. */
export function removeIds(s: Built, ids: Id[]): Built {
  const gone = new Set(ids)
  let entities = s.entities.filter((e) => !gone.has(e.id))
  // Кривые, у которых удалили точку.
  entities = entities.filter((e) => {
    const dead = (e.kind === 'line' && (gone.has(e.a) || gone.has(e.b))) || (e.kind === 'circle' && gone.has(e.c))
    if (dead) gone.add(e.id)
    return !dead
  })
  const used = new Set<Id>()
  for (const e of entities) {
    if (e.kind === 'line') { used.add(e.a); used.add(e.b) }
    if (e.kind === 'circle') used.add(e.c)
  }
  entities = entities.filter((e) => {
    const orphan = e.kind === 'point' && !used.has(e.id)
    if (orphan) gone.add(e.id)
    return !orphan
  })
  return {
    entities,
    constraints: s.constraints.filter((c) => !gone.has(c.id) && c.refs.every((r) => !gone.has(r))),
    dimensions: s.dimensions.filter((d) => !gone.has(d.id) && d.refs.every((r) => !gone.has(r))),
  }
}

export const CONSTRAINT_LABEL: Record<SketchConstraint['kind'], string> = {
  coincident: 'Совпадение', horizontal: 'Горизонтальность', vertical: 'Вертикальность', parallel: 'Параллельность',
  perpendicular: 'Перпендикулярность', tangent: 'Касание', equal: 'Равенство', fix: 'Фиксация',
  pointOnLine: 'Точка на кривой', concentric: 'Концентричность',
}

export const CONSTRAINT_GLYPH: Record<SketchConstraint['kind'], string> = {
  coincident: '●', horizontal: '—', vertical: '|', parallel: '∥', perpendicular: '⊥', tangent: '◡', equal: '=', fix: '⚓', pointOnLine: '•', concentric: '◎',
}

export function describeEntity(e: SketchEntity, pm: Map<Id, Point>): string {
  if (e.kind === 'point') return e.id === ORIGIN_ID ? 'Начало координат' : `Точка (${fmt(e.x)}; ${fmt(e.y)})`
  if (e.kind === 'circle') return `Окружность Ø${fmt(e.r * 2)}`
  const [a, b] = [pt(pm, e.a), pt(pm, e.b)]
  return `Отрезок ${fmt(Math.hypot(b[0] - a[0], b[1] - a[1]))}`
}

export const fmt = (n: number) => String(Number(n.toFixed(3)))

/** Старый формат M1 (rect/circle с координатами) → точки, отрезки, ограничения. */
export function migrateSketch(s: SketchNode & { entities: unknown[] }): SketchNode {
  const legacy = s.entities as Array<{ id: string; kind: string; p0?: Vec2; w?: number; h?: number; c?: unknown; r?: number }>
  if (!legacy.some((e) => e.kind === 'rect' || (e.kind === 'circle' && Array.isArray(e.c)))) {
    return { ...s, constraints: s.constraints ?? [], dimensions: s.dimensions ?? [] }
  }
  const out: Built = { entities: [], constraints: [], dimensions: [] }
  for (const e of legacy) {
    let b: Built | null = null
    if (e.kind === 'rect' && e.p0 && e.w && e.h) b = makeRect(e.p0, [e.p0[0] + e.w, e.p0[1] + e.h])
    if (e.kind === 'circle' && Array.isArray(e.c) && e.r) b = makeCircle(e.c as Vec2, e.r)
    if (b) { out.entities.push(...b.entities); out.constraints.push(...b.constraints); out.dimensions.push(...b.dimensions) }
  }
  return { ...s, ...out }
}

/** Минимальный DXF R12: LINE и CIRCLE в координатах эскиза. */
export function sketchToDxf(s: SketchNode): string {
  const pm = points(s)
  const out: string[] = ['0', 'SECTION', '2', 'ENTITIES']
  for (const e of s.entities) {
    if (e.kind === 'line') {
      const [a, b] = [pt(pm, e.a), pt(pm, e.b)]
      out.push('0', 'LINE', '8', e.construction ? 'CONSTRUCTION' : '0', '10', fmt(a[0]), '20', fmt(a[1]), '30', '0', '11', fmt(b[0]), '21', fmt(b[1]), '31', '0')
    } else if (e.kind === 'circle') {
      const c = pt(pm, e.c)
      out.push('0', 'CIRCLE', '8', e.construction ? 'CONSTRUCTION' : '0', '10', fmt(c[0]), '20', fmt(c[1]), '30', '0', '40', fmt(e.r))
    }
  }
  out.push('0', 'ENDSEC', '0', 'EOF')
  return out.join('\n') + '\n'
}
