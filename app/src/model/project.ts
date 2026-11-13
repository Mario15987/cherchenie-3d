import { nanoid } from 'nanoid'
import type { ExtrudeNode, FeatureNode, Frame, Id, PlaneKey, PlaneNode, Project, SketchNode, Vec2, Vec3 } from './types'
import { migrateSketch } from './sketch'

// Базовые плоскости. Модель Y-вверх, как вид «Спереди» смотрит на XY.
// yDir = normal × xDir — то же соглашение, что у Plane в ядре.
export const PLANE_FRAMES: Record<PlaneKey, Frame> = {
  XY: { origin: [0, 0, 0], xDir: [1, 0, 0], yDir: [0, 1, 0], normal: [0, 0, 1] },
  ZX: { origin: [0, 0, 0], xDir: [1, 0, 0], yDir: [0, 0, -1], normal: [0, 1, 0] },
  ZY: { origin: [0, 0, 0], xDir: [0, 0, -1], yDir: [0, 1, 0], normal: [1, 0, 0] },
}

export const PLANE_LABEL: Record<PlaneKey, string> = {
  XY: 'Плоскость XY',
  ZX: 'Плоскость ZX',
  ZY: 'Плоскость ZY',
}

const TYPE_LABEL = { sketch: 'Эскиз', extrudeadd: 'Выдавливание', extrudecut: 'Вырез', fillet: 'Скругление', chamfer: 'Фаска' } as const
export type LabelKind = keyof typeof TYPE_LABEL

export function newProject(): Project {
  const now = new Date().toISOString()
  const planes: PlaneNode[] = (['XY', 'ZX', 'ZY'] as const).map((key, i) => ({
    id: `plane-${key}`, type: 'plane', key, name: PLANE_LABEL[key], seq: i + 1,
  }))
  return {
    schema: 'recad/1', id: nanoid(), name: 'Деталь', units: 'mm', createdAt: now, updatedAt: now,
    part: { props: { designation: '', title: 'Деталь' }, nodes: planes },
  }
}

export function nextSeq(nodes: FeatureNode[], kind: LabelKind): { seq: number; name: string } {
  const same = nodes.filter((n) => labelKind(n) === kind)
  const seq = same.reduce((m, n) => Math.max(m, n.seq), 0) + 1
  return { seq, name: `${TYPE_LABEL[kind]}:${seq}` }
}

function labelKind(n: FeatureNode): LabelKind | 'plane' {
  if (n.type === 'sketch') return 'sketch'
  if (n.type === 'extrude') return n.op === 'add' ? 'extrudeadd' : 'extrudecut'
  if (n.type === 'edgeop') return n.op
  return 'plane'
}

/** Система координат эскиза. Для эскиза на грани — то, что вернуло ядро при последнем перестроении. */
export function sketchFrame(nodes: FeatureNode[], sketch: SketchNode, resolved?: Record<Id, Frame>): Frame {
  if (sketch.support.kind === 'face') return resolved?.[sketch.id] ?? sketch.support.frame
  const planeId = sketch.support.planeId
  const plane = nodes.find((n) => n.id === planeId)
  return PLANE_FRAMES[plane && plane.type === 'plane' ? plane.key : 'XY']
}

export function getNode<T extends FeatureNode['type']>(nodes: FeatureNode[], id: Id | null | undefined, type: T) {
  const n = nodes.find((x) => x.id === id)
  return n && n.type === type ? (n as Extract<FeatureNode, { type: T }>) : undefined
}

/** Эскизы, на которые ссылается хотя бы одна операция. */
export function consumedSketches(nodes: FeatureNode[]): Set<Id> {
  return new Set(nodes.filter((n): n is ExtrudeNode => n.type === 'extrude').map((n) => n.sketchId))
}

/** Узлы, которые ссылаются на данный (напрямую или через грани и рёбра). */
export function dependents(nodes: FeatureNode[], id: Id): FeatureNode[] {
  const out = new Set<Id>()
  const visit = (target: Id) => {
    for (const n of nodes) {
      if (out.has(n.id)) continue
      const uses =
        (n.type === 'extrude' && n.sketchId === target) ||
        (n.type === 'sketch' && n.support.kind === 'face' && n.support.ref.feature === target) ||
        (n.type === 'edgeop' && n.edges.some((e) => e.faces.some((f) => f.feature === target)))
      if (uses) { out.add(n.id); visit(n.id) }
    }
  }
  visit(id)
  return nodes.filter((n) => out.has(n.id))
}

export function toWorld(f: Frame, p: Vec2, z = 0): Vec3 {
  return [0, 1, 2].map((i) => f.origin[i] + f.xDir[i] * p[0] + f.yDir[i] * p[1] + f.normal[i] * z) as Vec3
}

export function toLocal(f: Frame, w: Vec3): Vec2 {
  const d = [w[0] - f.origin[0], w[1] - f.origin[1], w[2] - f.origin[2]]
  const dot = (a: Vec3) => a[0] * d[0] + a[1] * d[1] + a[2] * d[2]
  return [dot(f.xDir), dot(f.yDir)]
}

export function isProject(x: unknown): x is Project {
  const p = x as Project
  return !!p && p.schema === 'recad/1' && Array.isArray(p.part?.nodes)
}

/** Приводит проект старых версий к текущей схеме. */
export function migrateProject(p: Project): Project {
  const nodes = p.part.nodes.map((n) => (n.type === 'sketch' ? migrateSketch(n) : n))
  return { ...p, part: { ...p.part, nodes } }
}

