// Решатель ограничений эскиза: FreeCAD PlaneGCS (WASM, LGPL) через @salusoft89/planegcs.
// Эскизы маленькие (десятки точек), решение занимает миллисекунды, поэтому работаем в
// основном потоке синхронно — так перетаскивание и ввод размеров отвечают сразу.
import { Algorithm, make_gcs_wrapper, type GcsWrapper, type SketchPrimitive } from '@salusoft89/planegcs'
import wasmUrl from '@salusoft89/planegcs/dist/planegcs_dist/planegcs.wasm?url'
import { ORIGIN_ID, type Id, type SketchConstraint, type SketchDimension, type SketchEntity, type SketchNode } from '../model/types'
import { points } from '../model/sketch'

let gcs: GcsWrapper | null = null
export async function initSolver() {
  gcs ??= await make_gcs_wrapper(wasmUrl)
}
export const solverReady = () => !!gcs

export interface SolveResult {
  entities: SketchEntity[]
  ok: boolean
  dof: number
  /** Ограничения и размеры, которые противоречат друг другу. */
  conflicting: Id[]
  /** Лишние: повторяют то, что уже задано. */
  redundant: Id[]
  /** Точки и окружности, у которых остались степени свободы. */
  free: Set<Id>
}

type Sk = Pick<SketchNode, 'entities' | 'constraints' | 'dimensions'>

function primitives(s: Sk, fixedPoint?: Id): SketchPrimitive[] {
  const pm = points(s)
  const out: SketchPrimitive[] = [{ id: ORIGIN_ID, type: 'point', x: 0, y: 0, fixed: true }]
  for (const e of s.entities) {
    if (e.kind === 'point') out.push({ id: e.id, type: 'point', x: e.x, y: e.y, fixed: e.id === fixedPoint })
  }
  for (const e of s.entities) {
    if (e.kind === 'line') out.push({ id: e.id, type: 'line', p1_id: e.a, p2_id: e.b })
    if (e.kind === 'circle') out.push({ id: e.id, type: 'circle', c_id: e.c, radius: e.r })
  }
  const kind = (id: Id) => (id === ORIGIN_ID ? 'point' : s.entities.find((e) => e.id === id)?.kind)
  const lineOf = (id: Id) => s.entities.find((e) => e.id === id && e.kind === 'line') as Extract<SketchEntity, { kind: 'line' }> | undefined

  for (const c of s.constraints) out.push(...constraint(c, kind, pm))
  for (const d of s.dimensions) out.push(...dimension(d, kind, lineOf, pm))
  return out
}

function constraint(c: SketchConstraint, kind: (id: Id) => string | undefined, pm: ReturnType<typeof points>): SketchPrimitive[] {
  const [a, b] = c.refs
  switch (c.kind) {
    case 'coincident': return [{ id: c.id, type: 'p2p_coincident', p1_id: a, p2_id: b }]
    case 'concentric': return []
    case 'horizontal': return kind(a) === 'line' ? [{ id: c.id, type: 'horizontal_l', l_id: a }] : [{ id: c.id, type: 'horizontal_pp', p1_id: a, p2_id: b }]
    case 'vertical': return kind(a) === 'line' ? [{ id: c.id, type: 'vertical_l', l_id: a }] : [{ id: c.id, type: 'vertical_pp', p1_id: a, p2_id: b }]
    case 'parallel': return [{ id: c.id, type: 'parallel', l1_id: a, l2_id: b }]
    case 'perpendicular': return [{ id: c.id, type: 'perpendicular_ll', l1_id: a, l2_id: b }]
    case 'tangent': {
      const [l, ci] = kind(a) === 'line' ? [a, b] : [b, a]
      return [{ id: c.id, type: 'tangent_lc', l_id: l, c_id: ci }]
    }
    case 'equal':
      return kind(a) === 'line' ? [{ id: c.id, type: 'equal_length', l1_id: a, l2_id: b }] : [{ id: c.id, type: 'equal_radius_cc', c1_id: a, c2_id: b } as SketchPrimitive]
    case 'pointOnLine':
      return kind(b) === 'line' ? [{ id: c.id, type: 'point_on_line_pl', p_id: a, l_id: b }] : [{ id: c.id, type: 'point_on_circle', p_id: a, c_id: b }]
    case 'fix': {
      // Фиксация = совпадение с неподвижной вспомогательной точкой (так конфликт сообщается с нашим id).
      const p = pm.get(a)
      if (!p) return []
      return [{ id: `${c.id}~pt`, type: 'point', x: p.x, y: p.y, fixed: true }, { id: c.id, type: 'p2p_coincident', p1_id: a, p2_id: `${c.id}~pt` }]
    }
  }
}

function dimension(d: SketchDimension, kind: (id: Id) => string | undefined, lineOf: (id: Id) => { a: Id; b: Id } | undefined, pm: ReturnType<typeof points>): SketchPrimitive[] {
  const ends = (): [Id, Id] | null => {
    if (d.refs.length === 1) { const l = lineOf(d.refs[0]); return l ? [l.a, l.b] : null }
    return [d.refs[0], d.refs[1]]
  }
  switch (d.kind) {
    case 'diameter': return [{ id: d.id, type: 'circle_diameter', c_id: d.refs[0], diameter: d.value }]
    case 'distance': { const e = ends(); return e ? [{ id: d.id, type: 'p2p_distance', p1_id: e[0], p2_id: e[1], distance: d.value }] : [] }
    case 'pointLine': return [{ id: d.id, type: 'p2l_distance', p_id: d.refs[0], l_id: d.refs[1], distance: d.value }]
    case 'hdistance':
    case 'vdistance': {
      const e = ends()
      if (!e) return []
      const prop = d.kind === 'hdistance' ? 'x' : 'y'
      const p1 = pm.get(e[0]), p2 = pm.get(e[1])
      // Знак сохраняем как сейчас на экране: размер не должен «перевернуть» фигуру.
      const sign = p1 && p2 && p2[prop] - p1[prop] < 0 ? -1 : 1
      return [{ id: d.id, type: 'difference', param1: { o_id: e[0], prop }, param2: { o_id: e[1], prop }, difference: sign * d.value }]
    }
  }
  void kind
}

function run(prims: SketchPrimitive[]) {
  const g = gcs!
  g.clear_data()
  g.push_primitives_and_params(prims)
  const status = g.solve(Algorithm.DogLeg)
  g.apply_solution()
  return status
}

const baseId = (id: string) => id.split('~')[0]

/** Решает эскиз и возвращает новые координаты, число степеней свободы и проблемные ограничения. */
export function solve(s: Sk): SolveResult {
  if (!gcs) return { entities: s.entities, ok: true, dof: -1, conflicting: [], redundant: [], free: new Set() }
  const status = run(primitives(s))
  const g = gcs
  const conflicting = [...new Set(g.get_gcs_conflicting_constraints().map(baseId))]
  const redundant = [...new Set(g.get_gcs_redundant_constraints().map(baseId))]
  const dof = g.gcs.dof()
  const solved = new Map(g.sketch_index.get_primitives().map((p) => [p.id, p]))
  const entities = s.entities.map((e): SketchEntity => {
    const p = solved.get(e.id)
    if (e.kind === 'point' && p?.type === 'point') return { ...e, x: p.x, y: p.y }
    if (e.kind === 'circle' && p?.type === 'circle') return { ...e, r: p.radius }
    return e
  })
  const next = { ...s, entities }

  // Свободные элементы: закрепляем точку и смотрим, уменьшилось ли число степеней свободы.
  const free = new Set<Id>()
  if (dof > 0) {
    for (const e of entities) {
      if (e.kind !== 'point') continue
      run(primitives(next, e.id))
      if (g.gcs.dof() < dof) free.add(e.id)
    }
    // Окружность свободна, если свободен центр или радиус не задан размером.
    for (const e of entities) {
      if (e.kind !== 'circle') continue
      const sized = s.dimensions.some((d) => d.kind === 'diameter' && d.refs[0] === e.id) || s.constraints.some((c) => (c.kind === 'equal' || c.kind === 'tangent') && c.refs.includes(e.id))
      if (free.has(e.c) || !sized) free.add(e.id)
    }
    for (const e of entities) if (e.kind === 'line' && (free.has(e.a) || free.has(e.b))) free.add(e.id)
  }
  return { entities, ok: status === 0 || status === 1, dof, conflicting, redundant, free }
}
