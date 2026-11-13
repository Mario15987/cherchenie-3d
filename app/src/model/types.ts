// Модель проекта: дерево построения. Схема описана в replica/architecture.md.
// Геометрия здесь не хранится — она всегда результат перестроения в ядре.

export type Id = string
export type Vec2 = [number, number]
export type Vec3 = [number, number, number]

export interface Frame {
  origin: Vec3
  xDir: Vec3
  yDir: Vec3
  normal: Vec3
}

export type PlaneKey = 'XY' | 'ZX' | 'ZY'

// Эскиз — точки и кривые, которые ссылаются на точки. Общая точка у двух
// отрезков и есть их совпадение: отдельное ограничение не нужно.
export type SketchEntity =
  | { id: Id; kind: 'point'; x: number; y: number }
  | { id: Id; kind: 'line'; a: Id; b: Id; construction?: boolean }
  | { id: Id; kind: 'circle'; c: Id; r: number; construction?: boolean }

/** Неподвижная точка начала координат эскиза. В entities не хранится. */
export const ORIGIN_ID = 'origin'

export type ConstraintKind =
  | 'coincident' | 'horizontal' | 'vertical' | 'parallel' | 'perpendicular'
  | 'tangent' | 'equal' | 'fix' | 'pointOnLine' | 'concentric'

export interface SketchConstraint {
  id: Id
  kind: ConstraintKind
  refs: Id[]
}

export type DimensionKind = 'distance' | 'hdistance' | 'vdistance' | 'diameter' | 'pointLine'

export interface SketchDimension {
  id: Id
  kind: DimensionKind
  refs: Id[]
  value: number
}

/** Устойчивая ссылка на грань по происхождению (fixes #8, architecture.md). */
export interface FaceRef {
  feature: Id
  role: 'cap-start' | 'cap-end' | 'side'
  source?: Id
}

export interface EdgeRef {
  faces: [FaceRef, FaceRef]
  hint: Vec3
}

export type SketchSupport =
  | { kind: 'plane'; planeId: Id }
  | { kind: 'face'; ref: FaceRef; frame: Frame }

export interface NodeBase {
  id: Id
  name: string
  seq: number
  hidden?: boolean
}

export interface PlaneNode extends NodeBase {
  type: 'plane'
  key: PlaneKey
}

export interface SketchNode extends NodeBase {
  type: 'sketch'
  support: SketchSupport
  entities: SketchEntity[]
  constraints: SketchConstraint[]
  dimensions: SketchDimension[]
}

export type ExtrudeDirection = 'forward' | 'reverse' | 'symmetric'
export type ExtrudeExtent = 'blind' | 'throughAll'

export interface ExtrudeParams {
  op: 'add' | 'cut'
  sketchId: Id
  direction: ExtrudeDirection
  extent: ExtrudeExtent
  distance: number
}

export interface ExtrudeNode extends NodeBase, ExtrudeParams {
  type: 'extrude'
}

export interface EdgeOpParams {
  op: 'fillet' | 'chamfer'
  edges: EdgeRef[]
  size: number
}

export interface EdgeOpNode extends NodeBase, EdgeOpParams {
  type: 'edgeop'
}

export type FeatureNode = PlaneNode | SketchNode | ExtrudeNode | EdgeOpNode

export type ViewKind = 'front' | 'top' | 'left' | 'iso'

export interface DrawingDoc {
  id: Id
  format: 'A4' | 'A3'
  scale: number | 'auto'
  views: ViewKind[]
}

export interface PartDoc {
  props: { designation: string; title: string }
  nodes: FeatureNode[]
}

export interface Project {
  schema: 'recad/1'
  id: Id
  name: string
  units: 'mm'
  createdAt: string
  updatedAt: string
  part: PartDoc
  drawing?: DrawingDoc
}
