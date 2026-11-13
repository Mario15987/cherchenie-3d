/// <reference lib="webworker" />
// Ядро геометрии в отдельном потоке: OpenCascade (WASM) через replicad.
// Булевы операции не блокируют интерфейс. Протокол — protocol.ts.
import * as Comlink from 'comlink'
import opencascade from 'replicad-opencascadejs'
import wasmUrl from 'replicad-opencascadejs/wasm?url'
import {
  Plane, ProjectionCamera, draw, drawCircle, makeProjectedEdges, setOC,
  type Drawing, type Edge, type Face, type Shape3D,
} from 'replicad'
import type { EdgeOpNode, EdgeRef, ExtrudeNode, FaceRef, FeatureNode, Frame, Id, SketchNode, Vec2, Vec3, ViewKind } from '../model/types'
import { getNode, sketchFrame, toWorld } from '../model/project'
import { profile as sketchProfile } from '../model/sketch'
import type { KernelApi, MeshData, NodeStatus, ViewProjection } from './protocol'

let ready: Promise<void> | null = null
const EPS = 1e-4

// ---------- векторная мелочь ----------
const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k]
const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
const len = (a: Vec3) => Math.hypot(a[0], a[1], a[2])
const norm = (a: Vec3): Vec3 => scale(a, 1 / (len(a) || 1))

// ---------- кэш тел ----------
const cache = new Map<string, Shape3D>()
const CACHE_MAX = 48
function remember(key: string, shape: Shape3D) {
  cache.set(key, shape)
  while (cache.size > CACHE_MAX) {
    const [oldKey, old] = cache.entries().next().value as [string, Shape3D]
    cache.delete(oldKey)
    old.delete()
  }
}
function hash(s: string) {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 0x01000193)
  return (h >>> 0).toString(36)
}

// ---------- происхождение граней ----------
/** Что операция выдавливания знает о своих гранях: торцы, боковые плоскости, цилиндры. */
interface FeatureGeom {
  n: Vec3
  caps: { role: 'cap-start' | 'cap-end'; point: Vec3 }[]
  sides: { source: Id; kind: 'plane'; normal: Vec3; point: Vec3 }[]
  cyls: { source: Id; axis: Vec3; center: Vec3; r: number }[]
}

interface Run {
  statuses: NodeStatus[]
  body: Shape3D | null
  frames: Record<Id, Frame>
  geoms: Map<Id, FeatureGeom>
}

function classifyFace(face: Face, geoms: Map<Id, FeatureGeom>, order: Id[]): FaceRef | null {
  const type = face.geomType
  if (type === 'PLANE') {
    const nf = norm(face.normalAt().toTuple())
    const pf = face.center.toTuple()
    for (const fid of [...order].reverse()) {
      const g = geoms.get(fid)!
      for (const c of g.caps) if (Math.abs(dot(nf, g.n)) > 1 - EPS && Math.abs(dot(g.n, sub(pf, c.point))) < EPS) return { feature: fid, role: c.role }
      for (const s of g.sides) if (Math.abs(dot(nf, s.normal)) > 1 - EPS && Math.abs(dot(s.normal, sub(pf, s.point))) < EPS) return { feature: fid, role: 'side', source: s.source }
    }
  } else if (type === 'CYLINDRE') {
    const { uMin, uMax, vMin, vMax } = face.UVBounds
    const samples = [face.pointOnSurface(uMin, vMin), face.pointOnSurface((uMin + uMax) / 2, (vMin + vMax) / 2)].map((v) => v.toTuple())
    for (const fid of [...order].reverse()) {
      for (const c of geoms.get(fid)!.cyls) {
        const ok = samples.every((p) => {
          const d = sub(p, c.center)
          return Math.abs(len(sub(d, scale(c.axis, dot(d, c.axis)))) - c.r) < EPS * 10
        })
        if (ok) return { feature: fid, role: 'side', source: c.source }
      }
    }
  }
  return null
}

const sameRef = (a: FaceRef | null, b: FaceRef) => !!a && a.feature === b.feature && a.role === b.role && (a.source ?? '') === (b.source ?? '')

function findFaces(body: Shape3D, ref: FaceRef, run: Run, order: Id[]): Face[] {
  return body.faces.filter((f) => sameRef(classifyFace(f, run.geoms, order), ref))
}

/** Система координат эскиза на плоской грани: начало — проекция начала координат, X — проекция мировой оси. */
function faceFrame(face: Face): Frame {
  const normal = norm(face.normalAt().toTuple())
  const pf = face.center.toTuple()
  const origin = sub([0, 0, 0], scale(normal, dot(normal, sub([0, 0, 0], pf))))
  let x: Vec3 = [1, 0, 0]
  if (Math.abs(dot(x, normal)) > 0.9) x = [0, 0, -1]
  const xDir = norm(sub(x, scale(normal, dot(x, normal))))
  return { origin, xDir, yDir: cross(normal, xDir), normal }
}

// ---------- построение ----------
function profileDrawing(sketch: SketchNode): Drawing | null {
  const p = sketchProfile(sketch)
  const box = (pts: Vec2[]) => [Math.min(...pts.map((q) => q[0])), Math.min(...pts.map((q) => q[1])), Math.max(...pts.map((q) => q[0])), Math.max(...pts.map((q) => q[1]))]
  const area = (pts: Vec2[]) => Math.abs(pts.reduce((a, q, i) => { const r = pts[(i + 1) % pts.length]; return a + q[0] * r[1] - r[0] * q[1] }, 0) / 2)
  const items = [
    ...p.polygons.map((poly) => {
      let pen = draw(poly[0])
      for (const q of poly.slice(1)) pen = pen.lineTo(q)
      return { d: pen.close(), area: area(poly), box: box(poly) }
    }),
    ...p.circles.map((c) => ({ d: drawCircle(c.r).translate(c.c[0], c.c[1]), area: Math.PI * c.r * c.r, box: [c.c[0] - c.r, c.c[1] - c.r, c.c[0] + c.r, c.c[1] + c.r] })),
  ].sort((a, b) => b.area - a.area)

  let result: Drawing | null = null
  const outers: number[][] = []
  for (const it of items) {
    const inside = outers.some((o) => it.box[0] >= o[0] - EPS && it.box[1] >= o[1] - EPS && it.box[2] <= o[2] + EPS && it.box[3] <= o[3] + EPS)
    if (!result) { result = it.d; outers.push(it.box); continue }
    if (inside) result = result.cut(it.d)
    else { result = result.fuse(it.d); outers.push(it.box) }
  }
  return result
}

function extrudeGeom(sketch: SketchNode, f: Frame, node: ExtrudeNode, start: number, dist: number, dir: Vec3): FeatureGeom {
  const p = sketchProfile(sketch)
  const o = add(f.origin, scale(f.normal, start))
  const n = f.normal
  const sides: FeatureGeom['sides'] = []
  p.polygons.forEach((poly, i) => poly.forEach((q, j) => {
    const a = toWorld(f, q), b = toWorld(f, poly[(j + 1) % poly.length])
    sides.push({ source: p.polygonLines[i][j], kind: 'plane', normal: norm(cross(sub(b, a), n)), point: a })
  }))
  return {
    n,
    caps: [{ role: 'cap-start', point: o }, { role: 'cap-end', point: add(o, scale(dir, dist)) }],
    sides,
    cyls: p.circles.map((c) => ({ source: c.id, axis: n, center: toWorld(f, c.c), r: c.r })),
  }
  void node
}

function tool(nodes: FeatureNode[], node: ExtrudeNode, body: Shape3D | null, frames: Record<Id, Frame>) {
  const sketch = getNode(nodes, node.sketchId, 'sketch')
  if (!sketch) throw new Error('Эскиз операции удалён')
  const prof = profileDrawing(sketch)
  if (!prof) throw new Error(sketchProfile(sketch).open ? 'Контур эскиза не замкнут' : 'В эскизе нет замкнутого контура')
  const f = sketchFrame(nodes, sketch, frames)
  let distance = node.distance
  let offset = 0
  let dir: Vec3 = f.normal
  if (node.extent === 'throughAll') {
    let span = 1000
    if (body) { const b = body.boundingBox; span = 2 * (b.width + b.height + b.depth) + 100 }
    distance = span
    offset = -span / 2
  } else {
    if (!(distance > 0)) throw new Error('Расстояние должно быть больше нуля')
    if (node.direction === 'reverse') dir = scale(f.normal, -1)
    if (node.direction === 'symmetric') offset = -distance / 2
  }
  const origin = add(f.origin, scale(f.normal, offset))
  const plane = new Plane(origin, f.xDir, f.normal)
  const sketched = prof.sketchOnPlane(plane) as { extrude: (d: number, o?: { extrusionDirection?: Vec3 }) => Shape3D }
  const shape = sketched.extrude(distance, { extrusionDirection: dir })
  return { shape, geom: extrudeGeom(sketch, f, node, offset, distance, dir) }
}

function resolveEdges(body: Shape3D, refs: EdgeRef[], run: Run, order: Id[]): Edge[] {
  const out: Edge[] = []
  for (const ref of refs) {
    const a = findFaces(body, ref.faces[0], run, order)
    const b = findFaces(body, ref.faces[1], run, order)
    const bEdges = b.flatMap((f) => f.edges)
    const shared = a.flatMap((f) => f.edges).filter((e) => bEdges.some((x) => x.isSame(e)))
    if (!shared.length) throw new Error('Ребро, на которое ссылалась операция, исчезло после изменения модели')
    shared.sort((e1, e2) => len(sub(e1.pointAt(0.5).toTuple(), ref.hint)) - len(sub(e2.pointAt(0.5).toTuple(), ref.hint)))
    if (!out.some((e) => e.isSame(shared[0]))) out.push(shared[0])
  }
  return out
}

function edgeOp(body: Shape3D, node: EdgeOpNode, run: Run, order: Id[]): Shape3D {
  if (!node.edges.length) throw new Error('Не выбрано ни одного ребра')
  if (!(node.size > 0)) throw new Error(node.op === 'fillet' ? 'Радиус должен быть больше нуля' : 'Катет должен быть больше нуля')
  const edges = resolveEdges(body, node.edges, run, order)
  try {
    return node.op === 'fillet'
      ? body.fillet(node.size, (e) => e.inList(edges))
      : body.chamfer(node.size, (e) => e.inList(edges))
  } catch {
    throw new Error(node.op === 'fillet' ? 'Скругление не строится: радиус слишком большой для этих рёбер' : 'Фаска не строится: катет слишком большой для этих рёбер')
  }
}

/** Проходит историю. Тело — после последнего успешного узла. */
function run(nodes: FeatureNode[], upTo: Id | null): Run & { order: Id[] } {
  const r: Run & { order: Id[] } = { statuses: [], body: null, frames: {}, geoms: new Map(), order: [] }
  let key = 'root'
  for (const node of nodes) {
    if (node.type === 'sketch' && node.support.kind === 'face') {
      // Грань ищем на текущем теле: если её больше нет — эскиз остаётся там, где был.
      const faces = r.body ? findFaces(r.body, node.support.ref, r, r.order) : []
      if (faces[0]) r.frames[node.id] = faceFrame(faces[0])
      else r.statuses.push({ id: node.id, status: 'error', error: 'Грань, на которой лежит эскиз, исчезла. Эскиз остался на прежнем месте' })
    }
    if ((node.type === 'extrude' || node.type === 'edgeop') && !node.hidden) {
      const sketch = node.type === 'extrude' ? getNode(nodes, node.sketchId, 'sketch') : undefined
      key = hash(key + JSON.stringify(node) + JSON.stringify(sketch ?? '') + JSON.stringify(sketch ? r.frames[sketch.id] ?? '' : ''))
      try {
        let next: Shape3D
        const hit = cache.get(key)
        if (node.type === 'extrude') {
          const { shape: t, geom } = tool(nodes, node, r.body, r.frames)
          r.geoms.set(node.id, geom)
          r.order.push(node.id)
          if (hit) { t.delete(); next = hit } else {
            if (node.op === 'add') next = r.body ? r.body.fuse(t) : t
            else {
              if (!r.body) throw new Error('Нечего вырезать: в детали ещё нет тела')
              next = r.body.cut(t)
              if (Math.abs(next.faces.length - r.body.faces.length) === 0 && sameBox(next, r.body)) throw new Error('Вырез не пересекает тело')
            }
            if (next !== t) t.delete()
          }
        } else {
          if (!r.body) throw new Error('Нет тела для обработки')
          next = hit ?? edgeOp(r.body, node, r, r.order)
        }
        if (!hit) remember(key, next)
        r.body = next
        r.statuses.push({ id: node.id, status: 'ok' })
      } catch (err) {
        r.statuses.push({ id: node.id, status: 'error', error: message(err) })
      }
    }
    if (node.id === upTo) break
  }
  return r
}

function sameBox(a: Shape3D, b: Shape3D) {
  const x = a.boundingBox.bounds, y = b.boundingBox.bounds
  return x.every((p, i) => p.every((v, j) => Math.abs(v - y[i][j]) < 1e-6))
}

function message(err: unknown) {
  if (err instanceof Error) return err.message
  return typeof err === 'number' ? 'Ядро не смогло построить операцию' : String(err)
}

// ---------- сетки ----------
function toMesh(shape: Shape3D): MeshData {
  const m = shape.mesh({ tolerance: 0.05, angularTolerance: 15 })
  const e = shape.meshEdges({ tolerance: 0.05, angularTolerance: 15 })
  const b = shape.boundingBox
  return {
    position: new Float32Array(m.vertices),
    normal: new Float32Array(m.normals),
    index: new Uint32Array(m.triangles),
    edges: new Float32Array(e.lines),
    faceGroups: groups(m.faceGroups.map((g) => [g.start, g.count, g.faceId]), m.triangles.length),
    edgeGroups: groups(e.edgeGroups.map((g) => [g.start, g.count, g.edgeId]), e.lines.length / 3),
    bbox: { min: b.bounds[0] as [number, number, number], max: b.bounds[1] as [number, number, number] },
  }
}
/** Группы [start, count, id] в единицах буфера: индексы треугольников для граней, вершины для рёбер. */
function groups(raw: number[][], total: number): Uint32Array {
  const sum = raw.reduce((a, g) => a + g[1], 0) || 1
  const unit = Math.round(total / sum) || 1
  return new Uint32Array(raw.flatMap(([start, count, id]) => [start * unit, count * unit, id]))
}
const buffers = (m: MeshData | null) => (m ? [m.position.buffer, m.normal.buffer, m.index.buffer, m.edges.buffer, m.faceGroups.buffer, m.edgeGroups.buffer] : [])

function edgeLines(edges: Edge[]): Float32Array {
  const out: number[] = []
  for (const e of edges) {
    const N = e.geomType === 'LINE' ? 1 : 32
    for (let i = 0; i < N; i++) out.push(...e.pointAt(i / N).toTuple(), ...e.pointAt((i + 1) / N).toTuple())
  }
  return new Float32Array(out)
}

// ---------- виды чертежа (HLR) ----------
// Расположение видов по ЕСКД (метод первого угла): «вид сверху» под главным, «вид слева» справа от него.
const VIEW_CAMERAS: Record<ViewKind, { dir: Vec3; x: Vec3 }> = {
  front: { dir: [0, 0, 1], x: [1, 0, 0] },
  top: { dir: [0, 1, 0], x: [1, 0, 0] },
  left: { dir: [-1, 0, 0], x: [0, 0, 1] },
  iso: { dir: norm([1, 1, 1]), x: norm([1, 0, -1]) },
}

function project(body: Shape3D, kind: ViewKind): ViewProjection {
  const cam = VIEW_CAMERAS[kind]
  const camera = new ProjectionCamera([0, 0, 0], cam.dir, cam.x)
  const { visible, hidden } = makeProjectedEdges(body, camera, kind !== 'iso')
  const min: [number, number] = [Infinity, Infinity], max: [number, number] = [-Infinity, -Infinity]
  const poly = (e: Edge) => {
    const N = e.geomType === 'LINE' ? 1 : 48
    const pts: number[] = []
    for (let i = 0; i <= N; i++) {
      // Рёбра после HLR уже в двумерных координатах камеры: X вдоль cam.x, Y вдоль dir × x.
      const [x, y] = e.pointAt(i / N).toTuple()
      pts.push(x, y)
      min[0] = Math.min(min[0], x); min[1] = Math.min(min[1], y); max[0] = Math.max(max[0], x); max[1] = Math.max(max[1], y)
    }
    return pts
  }
  const res = { kind, visible: visible.map(poly), hidden: hidden.map(poly), min, max }
  camera.delete()
  return res
}

const api: KernelApi = {
  async init() {
    const t0 = performance.now()
    ready ??= opencascade({ locateFile: () => wasmUrl }).then((oc) => { setOC(oc as never) })
    await ready
    return { ms: Math.round(performance.now() - t0) }
  },

  async rebuild(nodes, upTo, gen) {
    await ready
    const t0 = performance.now()
    const r = run(nodes, upTo)
    const body = r.body ? toMesh(r.body) : null
    return Comlink.transfer({ gen, statuses: r.statuses, body, frames: r.frames, ms: Math.round(performance.now() - t0) }, buffers(body))
  },

  async preview(nodes, node, gen) {
    await ready
    const idx = nodes.findIndex((n) => n.id === node.id)
    const all = idx === -1 ? [...nodes, node] : nodes.map((n) => (n.id === node.id ? node : n))
    const at = idx === -1 ? all.length - 1 : idx
    const before = at > 0 ? all[at - 1].id : null
    const base = run(all, before)
    try {
      if (node.type === 'extrude') {
        const { shape } = tool(all, node, base.body, base.frames)
        const mesh = toMesh(shape)
        shape.delete()
        return Comlink.transfer({ gen, mesh }, buffers(mesh))
      }
      if (!base.body) return { gen, mesh: null, error: 'Нет тела для обработки' }
      const edges = node.edges.length ? edgeLines(resolveEdges(base.body, node.edges, base, base.order)) : new Float32Array()
      if (!node.edges.length || !(node.size > 0)) return Comlink.transfer({ gen, mesh: null, edges }, [edges.buffer])
      const result = edgeOp(base.body, node, base, base.order)
      const mesh = toMesh(result)
      result.delete()
      return Comlink.transfer({ gen, mesh, edges }, [...buffers(mesh), edges.buffer])
    } catch (err) {
      return { gen, mesh: null, error: message(err) }
    }
  },

  async pickFace(nodes, upTo, faceId) {
    await ready
    const r = run(nodes, upTo)
    // faceId из сетки — хэш формы OCCT, а не номер.
    const face = r.body?.faces.find((f) => f.hashCode === faceId)
    if (!face) return { error: 'Грань не найдена' }
    if (face.geomType !== 'PLANE') return { error: 'Эскиз можно создать только на плоской грани' }
    const ref = classifyFace(face, r.geoms, r.order)
    if (!ref) return { error: 'Не удалось определить происхождение грани' }
    return { ref, frame: faceFrame(face) }
  },

  async pickEdge(nodes, upTo, edgeId) {
    await ready
    const r = run(nodes, upTo)
    if (!r.body) return { error: 'Нет тела' }
    const edge = r.body.edges.find((e) => e.hashCode === edgeId)
    if (!edge) return { error: 'Ребро не найдено' }
    const adjacent = r.body.faces.filter((f) => f.edges.some((e) => e.isSame(edge)))
    if (adjacent.length !== 2) return { error: 'У ребра должно быть ровно две грани' }
    const refs = adjacent.map((f) => classifyFace(f, r.geoms, r.order))
    if (!refs[0] || !refs[1]) return { error: 'Не удалось определить происхождение граней ребра' }
    return { ref: { faces: [refs[0], refs[1]], hint: edge.pointAt(0.5).toTuple() } }
  },

  async exportBody(nodes, kind) {
    await ready
    const r = run(nodes, null)
    if (!r.body) return null
    return kind === 'stl' ? r.body.blobSTL({ binary: true }) : r.body.blobSTEP()
  },

  async project(nodes, views) {
    await ready
    const r = run(nodes, null)
    if (!r.body) return []
    return views.map((v) => project(r.body!, v))
  },
}

Comlink.expose(api)
