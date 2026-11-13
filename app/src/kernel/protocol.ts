import type { EdgeOpNode, EdgeRef, ExtrudeNode, FaceRef, FeatureNode, Frame, Id, ViewKind } from '../model/types'

export interface MeshData {
  position: Float32Array
  normal: Float32Array
  index: Uint32Array
  edges: Float32Array
  /** Тройки [start, count, faceId]: диапазон в index для каждой грани. */
  faceGroups: Uint32Array
  /** Тройки [start, count, edgeId]: диапазон вершин в edges для каждого ребра. */
  edgeGroups: Uint32Array
  bbox: { min: [number, number, number]; max: [number, number, number] }
}

export interface NodeStatus {
  id: Id
  status: 'ok' | 'error'
  error?: string
}

export interface RebuildResult {
  gen: number
  statuses: NodeStatus[]
  body: MeshData | null
  /** Системы координат эскизов на гранях после перестроения. */
  frames: Record<Id, Frame>
  ms: number
}

export interface PreviewResult {
  gen: number
  mesh: MeshData | null
  /** Подсветка выбранных рёбер (пары точек). */
  edges?: Float32Array
  error?: string
}

export interface ViewProjection {
  kind: ViewKind
  /** Полилинии в мм в плоскости вида: [x0, y0, x1, y1, ...]. */
  visible: number[][]
  hidden: number[][]
  min: [number, number]
  max: [number, number]
}

export interface KernelApi {
  init(): Promise<{ ms: number }>
  /** Перестраивает историю до узла upTo включительно (null — до конца). */
  rebuild(nodes: FeatureNode[], upTo: Id | null, gen: number): Promise<RebuildResult>
  /** Фантом: инструмент выдавливания или результат скругления/фаски. */
  preview(nodes: FeatureNode[], node: ExtrudeNode | EdgeOpNode, gen: number): Promise<PreviewResult>
  /** Устойчивая ссылка на грань тела, построенного до upTo. */
  pickFace(nodes: FeatureNode[], upTo: Id | null, faceId: number): Promise<{ ref: FaceRef; frame: Frame } | { error: string }>
  pickEdge(nodes: FeatureNode[], upTo: Id | null, edgeId: number): Promise<{ ref: EdgeRef } | { error: string }>
  exportBody(nodes: FeatureNode[], kind: 'stl' | 'step'): Promise<Blob | null>
  project(nodes: FeatureNode[], views: ViewKind[]): Promise<ViewProjection[]>
}
