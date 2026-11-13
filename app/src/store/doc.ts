// Состояние приложения. Документ (дерево построения) + undo/redo + режимы UI.
import { create } from 'zustand'
import { del as idbDel, get as idbGet, set as idbSet } from 'idb-keyval'
import { nanoid } from 'nanoid'
import type {
  ConstraintKind, DimensionKind, EdgeOpNode, EdgeOpParams, EdgeRef, ExtrudeNode, ExtrudeParams, FaceRef, FeatureNode, Frame, Id, Project, SketchEntity, SketchNode,
} from '../model/types'
import { dependents, getNode, isProject, migrateProject, newProject, nextSeq, sketchFrame } from '../model/project'
import { contourCount, removeIds, sid, type Built } from '../model/sketch'
import { isLatest, kernel, nextGen } from '../kernel/client'
import type { MeshData, NodeStatus, ViewProjection } from '../kernel/protocol'
import { initSolver, solve, type SolveResult } from '../sketch/solver'

export type Theme = 'dark' | 'light'
export type SketchTool = 'line' | 'rect' | 'circle' | null
export type ViewName = 'iso' | 'front' | 'top' | 'right'
export type Workspace = 'part' | 'drawing'

export type Selection =
  | { kind: 'node'; id: Id }
  | { kind: 'face'; faceId: number; ref: FaceRef; frame: Frame }
  | null

export type Mode =
  | { kind: 'model' }
  | { kind: 'sketch'; nodeId: Id; isNew: boolean; tool: SketchTool; before: SketchNode }
  | { kind: 'extrude'; nodeId: Id | null; params: ExtrudeParams }
  | { kind: 'edgeop'; nodeId: Id | null; params: EdgeOpParams }

export type CameraInput =
  | { kind: 'view'; view: ViewName }
  | { kind: 'normal'; frame: Frame }
  | { kind: 'fit' }
export type CameraRequest = CameraInput & { n: number }

interface KernelState {
  ready: boolean
  busy: boolean
  error: string | null
  body: MeshData | null
  /** Узел, до которого построено показанное тело (null — вся история). Номера граней и рёбер — от него. */
  bodyUpTo: Id | null
  preview: MeshData | null
  previewEdges: Float32Array | null
  previewError: string | null
  statuses: Record<Id, NodeStatus>
  frames: Record<Id, Frame>
  lastMs: number | null
}

export type SketchInfo = Omit<SolveResult, 'entities'>

export interface RecentItem { id: Id; name: string; updatedAt: string }

interface State {
  project: Project
  past: FeatureNode[][]
  future: FeatureNode[][]
  selection: Selection
  hover: Id | null
  mode: Mode
  workspace: Workspace
  startOpen: boolean
  recent: RecentItem[]
  theme: Theme
  hint: string
  cursor: [number, number] | null
  camera: CameraRequest | null
  savedAt: string | null
  toast: { n: number; kind: 'info' | 'error'; text: string } | null
  kernel: KernelState
  sketchSel: Id[]
  sketchInfo: SketchInfo | null
  views: ViewProjection[] | null

  select(sel: Selection): void
  setHover(id: Id | null): void
  setHint(h: string): void
  setCursor(c: [number, number] | null): void
  setTheme(t: Theme): void
  requestCamera(r: CameraInput): void
  notify(kind: 'info' | 'error', text: string): void

  pickFace(faceId: number): void
  startSketch(planeId: Id): void
  startSketchOnFace(): void
  editSketch(id: Id): void
  setSketchTool(tool: SketchTool): void
  applySketch(fn: (s: Built) => Built): void
  addBuilt(b: Built): void
  setDimension(id: Id, value: number): void
  addConstraint(kind: ConstraintKind, refs?: Id[]): void
  addDimension(): void
  removeSketchItems(ids: Id[]): void
  setSketchSel(ids: Id[]): void
  finishSketch(): void
  cancelSketch(): void

  startExtrude(op: 'add' | 'cut', sketchId?: Id): void
  editExtrude(id: Id): void
  setExtrudeParams(p: Partial<ExtrudeParams>): void
  commitExtrude(): void
  cancelExtrude(): void

  startEdgeOp(op: 'fillet' | 'chamfer'): void
  editEdgeOp(id: Id): void
  toggleEdge(edgeId: number): void
  setEdgeOpParams(p: Partial<EdgeOpParams>): void
  commitEdgeOp(): void
  cancelEdgeOp(): void

  editNode(id: Id): void
  deleteNode(id: Id): void
  toggleHidden(id: Id): void
  undo(): void
  redo(): void
  loadProject(p: Project): void
  rebuild(): void
  setWorkspace(w: Workspace): void
  refreshViews(): void
  setDrawing(p: Partial<NonNullable<Project['drawing']>>): void
  setStartOpen(open: boolean): void
  openRecent(id: Id): Promise<void>
}

const HISTORY = 100
const LEGACY_AUTOSAVE = 'recad:autosave'
const LAST_KEY = 'recad:last'
const RECENT_KEY = 'recad:recent'
const projectKey = (id: Id) => `recad:project:${id}`

function systemTheme(): Theme {
  try {
    const t = localStorage.getItem('recad:theme')
    if (t === 'dark' || t === 'light') return t
  } catch { /* приватный режим */ }
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

let camN = 0
let toastN = 0
let previewQueued = false

export const useDoc = create<State>((set, get) => {
  /** Фиксирует изменение истории: снимок для undo, перестроение, автосохранение. */
  const commit = (nodes: FeatureNode[], extra: Partial<State> = {}) => {
    const { project, past } = get()
    set({
      project: { ...project, updatedAt: new Date().toISOString(), part: { ...project.part, nodes } },
      past: [...past, project.part.nodes].slice(-HISTORY),
      future: [],
      ...extra,
    })
    get().rebuild()
  }

  const nodes = () => get().project.part.nodes
  const setNodes = (n: FeatureNode[]) => set({ project: { ...get().project, part: { ...get().project.part, nodes: n } } })

  const enterSketch = (sketch: SketchNode, isNew: boolean, before: SketchNode) => {
    set({
      mode: { kind: 'sketch', nodeId: sketch.id, isNew, tool: isNew ? 'line' : null, before },
      selection: { kind: 'node', id: sketch.id },
      sketchSel: [],
    })
    resolveSketch()
    get().requestCamera({ kind: 'normal', frame: sketchFrame(nodes(), sketch, get().kernel.frames) })
  }

  return {
    project: newProject(),
    past: [],
    future: [],
    selection: null,
    hover: null,
    mode: { kind: 'model' },
    workspace: 'part',
    startOpen: false,
    recent: [],
    theme: systemTheme(),
    hint: 'Выберите плоскость или плоскую грань и нажмите «Эскиз» (S)',
    cursor: null,
    camera: null,
    savedAt: null,
    toast: null,
    kernel: { ready: false, busy: false, error: null, body: null, bodyUpTo: null, preview: null, previewEdges: null, previewError: null, statuses: {}, frames: {}, lastMs: null },
    sketchSel: [],
    sketchInfo: null,
    views: null,

    select: (selection) => set({ selection }),
    setHover: (hover) => set({ hover }),
    setHint: (hint) => set({ hint }),
    setCursor: (cursor) => set({ cursor }),
    setTheme: (theme) => {
      try { localStorage.setItem('recad:theme', theme) } catch { /* приватный режим */ }
      set({ theme })
    },
    requestCamera: (r) => set({ camera: { ...r, n: ++camN } }),
    notify: (kind, text) => set({ toast: { n: ++toastN, kind, text } }),

    pickFace: (faceId) => {
      const k = get().kernel
      kernel.pickFace(nodes(), k.bodyUpTo, faceId).then((r) => {
        if ('error' in r) { get().notify('info', r.error); return }
        set({ selection: { kind: 'face', faceId, ref: r.ref, frame: r.frame }, hint: 'Грань выбрана. «Эскиз» (S) — начать эскиз на ней' })
      })
    },

    startSketch: (planeId) => {
      const plane = getNode(nodes(), planeId, 'plane')
      if (!plane) { get().notify('error', 'Сначала выберите плоскость или плоскую грань'); return }
      const { seq, name } = nextSeq(nodes(), 'sketch')
      const sketch: SketchNode = { id: nanoid(10), type: 'sketch', name, seq, support: { kind: 'plane', planeId }, entities: [], constraints: [], dimensions: [] }
      setNodes([...nodes(), sketch])
      enterSketch(sketch, true, sketch)
    },

    startSketchOnFace: () => {
      const sel = get().selection
      if (sel?.kind !== 'face') return
      const { seq, name } = nextSeq(nodes(), 'sketch')
      const sketch: SketchNode = { id: nanoid(10), type: 'sketch', name, seq, support: { kind: 'face', ref: sel.ref, frame: sel.frame }, entities: [], constraints: [], dimensions: [] }
      setNodes([...nodes(), sketch])
      set({ kernel: { ...get().kernel, frames: { ...get().kernel.frames, [sketch.id]: sel.frame } } })
      enterSketch(sketch, true, sketch)
    },

    editSketch: (id) => {
      const s = getNode(nodes(), id, 'sketch')
      if (s) enterSketch(s, false, s)
    },

    setSketchTool: (tool) => {
      const m = get().mode
      if (m.kind === 'sketch') set({ mode: { ...m, tool }, sketchSel: [] })
    },

    applySketch: (fn) => mutateSketch(fn),
    addBuilt: (b) => mutateSketch((s) => ({ entities: [...s.entities, ...b.entities], constraints: [...s.constraints, ...b.constraints], dimensions: [...s.dimensions, ...b.dimensions] })),
    setDimension: (id, value) => {
      if (!(value > 0)) return
      mutateSketch((s) => ({ ...s, dimensions: s.dimensions.map((d) => (d.id === id ? { ...d, value } : d)) }))
    },

    addConstraint: (kind, refs) => {
      const r = refs ?? get().sketchSel
      const s = currentSketch()
      if (!s) return
      const kindOf = (id: Id) => (id === 'origin' ? 'point' : s.entities.find((e) => e.id === id)?.kind)
      const k = r.map(kindOf)
      const ok =
        (['horizontal', 'vertical'].includes(kind) && ((r.length === 1 && k[0] === 'line') || (r.length === 2 && k.every((x) => x === 'point')))) ||
        (['parallel', 'perpendicular'].includes(kind) && r.length === 2 && k.every((x) => x === 'line')) ||
        (kind === 'equal' && r.length === 2 && (k.every((x) => x === 'line') || k.every((x) => x === 'circle'))) ||
        (kind === 'tangent' && r.length === 2 && k.includes('line') && k.includes('circle')) ||
        (kind === 'coincident' && r.length === 2 && k.every((x) => x === 'point')) ||
        (kind === 'pointOnLine' && r.length === 2 && k[0] === 'point' && (k[1] === 'line' || k[1] === 'circle')) ||
        (kind === 'fix' && r.length === 1 && k[0] === 'point')
      if (!ok) { get().notify('info', CONSTRAINT_HELP[kind]); return }
      mutateSketch((sk) => ({ ...sk, constraints: [...sk.constraints, { id: sid(), kind, refs: r }] }))
      set({ sketchSel: [] })
    },

    addDimension: () => {
      const r = get().sketchSel
      const s = currentSketch()
      if (!s) return
      const ent = (id: Id) => s.entities.find((e) => e.id === id)
      const pts = new Map(s.entities.filter((e) => e.kind === 'point').map((e) => [e.id, e as { x: number; y: number }]))
      pts.set('origin', { x: 0, y: 0 })
      let dim: { kind: DimensionKind; refs: Id[]; value: number } | null = null
      const a = r.length ? ent(r[0]) ?? (r[0] === 'origin' ? { kind: 'point' as const } : undefined) : undefined
      const b = r.length > 1 ? ent(r[1]) ?? (r[1] === 'origin' ? { kind: 'point' as const } : undefined) : undefined
      if (r.length === 1 && a?.kind === 'line') {
        const p = pts.get(a.a)!, q = pts.get(a.b)!
        dim = { kind: 'distance', refs: [a.id], value: Math.hypot(q.x - p.x, q.y - p.y) }
      } else if (r.length === 1 && a?.kind === 'circle') {
        dim = { kind: 'diameter', refs: [a.id], value: a.r * 2 }
      } else if (r.length === 2 && a?.kind === 'point' && b?.kind === 'point') {
        const p = pts.get(r[0])!, q = pts.get(r[1])!
        dim = { kind: 'distance', refs: r, value: Math.hypot(q.x - p.x, q.y - p.y) }
      } else if (r.length === 2 && a?.kind === 'point' && b?.kind === 'line') {
        const p = pts.get(r[0])!, l1 = pts.get(b.a)!, l2 = pts.get(b.b)!
        const L = Math.hypot(l2.x - l1.x, l2.y - l1.y) || 1
        dim = { kind: 'pointLine', refs: r, value: Math.abs((l2.x - l1.x) * (l1.y - p.y) - (l1.x - p.x) * (l2.y - l1.y)) / L }
      }
      if (!dim || !(dim.value > 0)) { get().notify('info', 'Размер: выберите отрезок, окружность, две точки или точку и отрезок'); return }
      const d = { id: sid(), ...dim }
      mutateSketch((sk) => ({ ...sk, dimensions: [...sk.dimensions, d] }))
      set({ sketchSel: [] })
    },

    removeSketchItems: (ids) => {
      if (!ids.length) return
      mutateSketch((s) => removeIds(s, ids))
      set({ sketchSel: [] })
    },

    setSketchSel: (sketchSel) => set({ sketchSel }),

    finishSketch: () => {
      const m = get().mode
      if (m.kind !== 'sketch') return
      const s = getNode(nodes(), m.nodeId, 'sketch')
      const after = nodes()
      if (s && m.isNew && s.entities.length === 0) {
        // Пустой эскиз не сохраняем: выход равен отмене.
        setNodes(after.filter((n) => n.id !== s.id))
        set({ mode: { kind: 'model' }, selection: null, sketchInfo: null })
        return
      }
      // В истории undo — состояние до входа в эскиз.
      const before = m.isNew ? after.filter((n) => n.id !== m.nodeId) : after.map((n) => (n.id === m.nodeId ? m.before : n))
      setNodes(before)
      const cc = s ? contourCount(s) : { closed: 0, open: 0 }
      commit(after, {
        mode: { kind: 'model' }, selection: { kind: 'node', id: m.nodeId }, sketchInfo: null,
        hint: cc.closed ? 'Эскиз готов. «Выдавливание» (E) превратит его в тело' : 'В эскизе нет замкнутого контура — выдавить его нельзя',
      })
      get().requestCamera({ kind: 'view', view: 'iso' })
    },

    cancelSketch: () => {
      const m = get().mode
      if (m.kind !== 'sketch') return
      setNodes(m.isNew ? nodes().filter((n) => n.id !== m.nodeId) : nodes().map((n) => (n.id === m.nodeId ? m.before : n)))
      set({ mode: { kind: 'model' }, sketchInfo: null })
      get().requestCamera({ kind: 'view', view: 'iso' })
    },

    startExtrude: (op, sketchId) => {
      const sel = get().selection
      const id = sketchId ?? (sel?.kind === 'node' ? sel.id : undefined)
      const used = new Set(nodes().flatMap((n) => (n.type === 'extrude' ? [n.sketchId] : [])))
      const sketch = getNode(nodes(), id, 'sketch') ?? [...nodes()].reverse().find((n): n is SketchNode => n.type === 'sketch' && !used.has(n.id))
      if (!sketch) { get().notify('error', 'Нет эскиза для операции. Создайте эскиз на плоскости или грани'); return }
      const cc = contourCount(sketch)
      if (!cc.closed) { get().notify('error', cc.open ? 'Контур эскиза не замкнут: соедините концы отрезков' : 'В эскизе нет замкнутого контура'); return }
      if (op === 'cut' && !get().kernel.body) { get().notify('error', 'Нечего вырезать: сначала создайте тело выдавливанием'); return }
      const onFace = sketch.support.kind === 'face'
      set({
        mode: { kind: 'extrude', nodeId: null, params: { op, sketchId: sketch.id, direction: op === 'cut' && onFace ? 'reverse' : 'forward', extent: op === 'cut' ? 'throughAll' : 'blind', distance: 20 } },
        selection: { kind: 'node', id: sketch.id },
        hint: 'Перетащите стрелку или введите расстояние. Enter — создать, Esc — отмена',
      })
      refreshPreview()
    },

    editExtrude: (id) => {
      const n = getNode(nodes(), id, 'extrude')
      if (!n) return
      const { op, sketchId, direction, extent, distance } = n
      set({ mode: { kind: 'extrude', nodeId: id, params: { op, sketchId, direction, extent, distance } }, selection: { kind: 'node', id }, hint: 'Измените параметры. Enter — применить, Esc — отмена' })
      showBodyBefore(id)
      refreshPreview()
    },

    setExtrudeParams: (p) => {
      const m = get().mode
      if (m.kind !== 'extrude') return
      set({ mode: { ...m, params: { ...m.params, ...p } } })
      refreshPreview()
    },

    commitExtrude: () => {
      const m = get().mode
      if (m.kind !== 'extrude') return
      if (m.params.extent === 'blind' && !(m.params.distance > 0)) { get().notify('error', 'Расстояние должно быть больше нуля'); return }
      if (m.nodeId) {
        commit(nodes().map((n) => (n.id === m.nodeId && n.type === 'extrude' ? { ...n, ...m.params } : n)), { mode: { kind: 'model' } })
      } else {
        const { seq, name } = nextSeq(nodes(), m.params.op === 'add' ? 'extrudeadd' : 'extrudecut')
        const node: ExtrudeNode = { id: nanoid(10), type: 'extrude', name, seq, ...m.params }
        commit([...nodes(), node], { mode: { kind: 'model' }, selection: { kind: 'node', id: node.id }, hint: 'Готово. Выберите плоскость или грань для следующего эскиза' })
      }
      clearPreview()
    },

    cancelExtrude: () => {
      if (get().mode.kind !== 'extrude') return
      set({ mode: { kind: 'model' } })
      clearPreview()
      get().rebuild()
    },

    startEdgeOp: (op) => {
      if (!get().kernel.body) { get().notify('error', 'Нет тела: сначала создайте выдавливание'); return }
      set({
        mode: { kind: 'edgeop', nodeId: null, params: { op, edges: [], size: op === 'fillet' ? 3 : 2 } },
        selection: null,
        hint: 'Щёлкните рёбра тела (повторный щелчок снимает выбор). Enter — создать, Esc — отмена',
      })
      refreshPreview()
    },

    editEdgeOp: (id) => {
      const n = getNode(nodes(), id, 'edgeop')
      if (!n) return
      set({ mode: { kind: 'edgeop', nodeId: id, params: { op: n.op, edges: n.edges, size: n.size } }, selection: { kind: 'node', id }, hint: 'Добавьте или снимите рёбра, измените размер. Enter — применить' })
      showBodyBefore(id)
      refreshPreview()
    },

    toggleEdge: (edgeId) => {
      const m = get().mode
      if (m.kind !== 'edgeop') return
      kernel.pickEdge(nodes(), get().kernel.bodyUpTo, edgeId).then((r) => {
        const cur = get().mode
        if (cur.kind !== 'edgeop') return
        if ('error' in r) { get().notify('info', r.error); return }
        const same = (e: EdgeRef) => JSON.stringify(e.faces) === JSON.stringify(r.ref.faces)
        const edges = cur.params.edges.some(same) ? cur.params.edges.filter((e) => !same(e)) : [...cur.params.edges, r.ref]
        set({ mode: { ...cur, params: { ...cur.params, edges } } })
        refreshPreview()
      })
    },

    setEdgeOpParams: (p) => {
      const m = get().mode
      if (m.kind !== 'edgeop') return
      set({ mode: { ...m, params: { ...m.params, ...p } } })
      refreshPreview()
    },

    commitEdgeOp: () => {
      const m = get().mode
      if (m.kind !== 'edgeop') return
      if (!m.params.edges.length) { get().notify('error', 'Выберите хотя бы одно ребро'); return }
      if (m.nodeId) commit(nodes().map((n) => (n.id === m.nodeId && n.type === 'edgeop' ? { ...n, ...m.params } : n)), { mode: { kind: 'model' } })
      else {
        const { seq, name } = nextSeq(nodes(), m.params.op)
        const node: EdgeOpNode = { id: nanoid(10), type: 'edgeop', name, seq, ...m.params }
        commit([...nodes(), node], { mode: { kind: 'model' }, selection: { kind: 'node', id: node.id } })
      }
      set({ hint: 'Готово. Рёбра запомнены по происхождению граней — правка размеров их не потеряет' })
      clearPreview()
    },

    cancelEdgeOp: () => {
      if (get().mode.kind !== 'edgeop') return
      set({ mode: { kind: 'model' }, hint: 'Отменено' })
      clearPreview()
      get().rebuild()
    },

    editNode: (id) => {
      const n = nodes().find((x) => x.id === id)
      if (!n || get().mode.kind !== 'model') return
      if (n.type === 'sketch') get().editSketch(id)
      else if (n.type === 'extrude') get().editExtrude(id)
      else if (n.type === 'edgeop') get().editEdgeOp(id)
    },

    deleteNode: (id) => {
      const n = nodes().find((x) => x.id === id)
      if (!n || n.type === 'plane') return
      const deps = dependents(nodes(), id)
      if (deps.length && !window.confirm(`Вместе с «${n.name}» будут удалены зависимые: ${deps.map((d) => d.name).join(', ')}. Удалить?`)) return
      const gone = new Set([id, ...deps.map((d) => d.id)])
      commit(nodes().filter((x) => !gone.has(x.id)), { selection: null })
    },

    toggleHidden: (id) => {
      commit(nodes().map((n) => (n.id === id ? { ...n, hidden: !n.hidden } : n)))
    },

    undo: () => {
      const { past, future, project, mode } = get()
      if (mode.kind !== 'model' || !past.length) return
      set({ project: { ...project, part: { ...project.part, nodes: past[past.length - 1] } }, past: past.slice(0, -1), future: [project.part.nodes, ...future], selection: null })
      get().rebuild()
    },

    redo: () => {
      const { past, future, project, mode } = get()
      if (mode.kind !== 'model' || !future.length) return
      set({ project: { ...project, part: { ...project.part, nodes: future[0] } }, past: [...past, project.part.nodes], future: future.slice(1), selection: null })
      get().rebuild()
    },

    loadProject: (p) => {
      set({ project: migrateProject(p), past: [], future: [], selection: null, mode: { kind: 'model' }, startOpen: false, workspace: 'part', views: null })
      get().rebuild()
      get().requestCamera({ kind: 'fit' })
    },

    rebuild: () => {
      if (!get().kernel.ready) return
      const gen = nextGen('rebuild')
      setKernel({ busy: true })
      kernel.rebuild(nodes(), null, gen).then((r) => {
        if (!isLatest('rebuild', r.gen)) return
        setKernel({ busy: false, body: r.body, bodyUpTo: null, frames: r.frames, statuses: Object.fromEntries(r.statuses.map((s) => [s.id, s])), lastMs: r.ms })
        const failed = r.statuses.find((s) => s.status === 'error')
        if (failed) get().notify('error', `${nodes().find((n) => n.id === failed.id)?.name ?? 'Операция'}: ${failed.error}`)
        if (get().workspace === 'drawing') get().refreshViews()
      }).catch((e) => setKernel({ busy: false, error: String(e) }))
    },

    setWorkspace: (workspace) => {
      if (get().mode.kind !== 'model') return
      if (workspace === 'drawing' && !get().project.drawing) {
        set({ project: { ...get().project, drawing: { id: nanoid(8), format: 'A3', scale: 'auto', views: ['front', 'top', 'left', 'iso'] } } })
      }
      set({ workspace, hint: workspace === 'drawing' ? 'Чертёж обновляется сам после каждого перестроения модели. Esc — к модели' : 'Выберите плоскость или плоскую грань и нажмите «Эскиз» (S)' })
      if (workspace === 'drawing') get().refreshViews()
    },

    refreshViews: () => {
      const d = get().project.drawing
      if (!d || !get().kernel.ready) return
      kernel.project(nodes(), d.views).then((views) => set({ views }))
    },

    setDrawing: (p) => {
      const d = get().project.drawing
      if (!d) return
      set({ project: { ...get().project, drawing: { ...d, ...p }, updatedAt: new Date().toISOString() } })
      if (p.views) get().refreshViews()
    },

    setStartOpen: (startOpen) => {
      set({ startOpen })
      if (startOpen) loadRecent().then((recent) => set({ recent }))
    },

    openRecent: async (id) => {
      try {
        const p = await idbGet(projectKey(id))
        if (isProject(p)) get().loadProject(p)
        else get().notify('error', 'Проект не найден в хранилище браузера')
      } catch { get().notify('error', 'Хранилище браузера недоступно') }
    },
  }

  function setKernel(k: Partial<KernelState>) {
    set({ kernel: { ...get().kernel, ...k } })
  }

  function currentSketch() {
    const m = get().mode
    return m.kind === 'sketch' ? getNode(nodes(), m.nodeId, 'sketch') : undefined
  }

  /** Правка эскиза: меняем узел, решаем ограничения, обновляем подсветку степеней свободы. */
  function mutateSketch(fn: (s: Built) => Built) {
    const s = currentSketch()
    if (!s) return
    const next = fn({ entities: s.entities, constraints: s.constraints, dimensions: s.dimensions })
    const solved = solve(next)
    // Решатель может «выполнить» несовместимые ограничения, схлопнув отрезок в точку. Такую правку не принимаем.
    if (collapses(next.entities, solved.entities)) {
      get().notify('error', 'Так нельзя: отрезок или окружность выродились бы в точку. Ограничения противоречат друг другу')
      return
    }
    const updated: SketchNode = { ...s, ...next, entities: solved.ok || solved.conflicting.length === 0 ? solved.entities : next.entities }
    setNodes(nodes().map((n) => (n.id === s.id ? updated : n)))
    const { entities: _e, ...info } = solved
    void _e
    set({ sketchInfo: info })
  }

  function resolveSketch() {
    const s = currentSketch()
    if (!s) return
    const { entities: _e, ...info } = solve(s)
    void _e
    set({ sketchInfo: info })
  }

  /** При правке операции показываем тело до неё — и выбор рёбер идёт по нему. */
  function showBodyBefore(id: Id) {
    const all = nodes()
    const idx = all.findIndex((n) => n.id === id)
    const before = [...all.slice(0, idx)].reverse().find((n) => n.type === 'extrude' || n.type === 'edgeop')
    if (!before) { setKernel({ body: null, bodyUpTo: null }); return }
    const gen = nextGen('rebuild')
    setKernel({ busy: true })
    kernel.rebuild(all, before.id, gen).then((r) => {
      if (!isLatest('rebuild', r.gen)) return
      setKernel({ busy: false, body: r.body, bodyUpTo: before.id })
    })
  }

  // Фантом: не чаще одного запроса за кадр, в работе только последний.
  function refreshPreview() {
    if (previewQueued) return
    previewQueued = true
    requestAnimationFrame(() => {
      previewQueued = false
      const m = get().mode
      if ((m.kind !== 'extrude' && m.kind !== 'edgeop') || !get().kernel.ready) return
      const draft = m.kind === 'extrude'
        ? ({ id: m.nodeId ?? '__draft__', type: 'extrude', name: '', seq: 0, ...m.params } as ExtrudeNode)
        : ({ id: m.nodeId ?? '__draft__', type: 'edgeop', name: '', seq: 0, ...m.params } as EdgeOpNode)
      const gen = nextGen('preview')
      kernel.preview(nodes(), draft, gen).then((r) => {
        const cur = get().mode
        if (!isLatest('preview', r.gen) || (cur.kind !== 'extrude' && cur.kind !== 'edgeop')) return
        setKernel({ preview: r.mesh, previewEdges: r.edges ?? null, previewError: r.error ?? null })
      })
    })
  }

  function clearPreview() {
    setKernel({ preview: null, previewEdges: null, previewError: null })
  }
})

const CONSTRAINT_HELP: Record<ConstraintKind, string> = {
  horizontal: 'Горизонтальность: выберите отрезок или две точки',
  vertical: 'Вертикальность: выберите отрезок или две точки',
  parallel: 'Параллельность: выберите два отрезка',
  perpendicular: 'Перпендикулярность: выберите два отрезка',
  equal: 'Равенство: выберите два отрезка или две окружности',
  tangent: 'Касание: выберите отрезок и окружность',
  coincident: 'Совпадение: выберите две точки',
  pointOnLine: 'Точка на кривой: выберите точку, затем отрезок или окружность',
  fix: 'Фиксация: выберите одну точку',
  concentric: 'Концентричность пока не поддерживается',
}

function collapses(before: SketchEntity[], after: SketchEntity[]): boolean {
  const size = (list: SketchEntity[]) => {
    const pts = new Map(list.flatMap((e) => (e.kind === 'point' ? [[e.id, e] as const] : [])))
    const P = (id: Id) => (id === 'origin' ? { x: 0, y: 0 } : pts.get(id) ?? { x: 0, y: 0 })
    return new Map(list.flatMap((e) => {
      if (e.kind === 'line') { const a = P(e.a), b = P(e.b); return [[e.id, Math.hypot(b.x - a.x, b.y - a.y)] as const] }
      if (e.kind === 'circle') return [[e.id, e.r] as const]
      return []
    }))
  }
  const was = size(before)
  for (const [id, v] of size(after)) if (v < 1e-6 && (was.get(id) ?? 1) > 1e-6) return true
  return false
}

async function loadRecent(): Promise<RecentItem[]> {
  try { return ((await idbGet(RECENT_KEY)) as RecentItem[] | undefined) ?? [] } catch { return [] }
}

// Загрузка решателя, ядра и последнего проекта при старте.
export async function bootstrap() {
  const st = useDoc.getState()
  const solverReady = initSolver().catch((e) => st.notify('error', 'Решатель ограничений не загрузился: ' + String(e)))
  let restored = false
  try {
    let lastId = (await idbGet(LAST_KEY)) as Id | undefined
    // Миграция автосохранения M1.
    const legacy = await idbGet(LEGACY_AUTOSAVE)
    if (!lastId && isProject(legacy)) {
      await idbSet(projectKey(legacy.id), legacy)
      await idbSet(RECENT_KEY, [{ id: legacy.id, name: legacy.name, updatedAt: legacy.updatedAt }])
      await idbSet(LAST_KEY, legacy.id)
      await idbDel(LEGACY_AUTOSAVE)
      lastId = legacy.id
    }
    const saved = lastId ? await idbGet(projectKey(lastId)) : undefined
    if (isProject(saved)) { useDoc.setState({ project: migrateProject(saved), savedAt: saved.updatedAt }); restored = true }
  } catch { /* IndexedDB недоступна — работаем без автосохранения */ }
  if (!restored) st.setStartOpen(true)
  await solverReady
  try {
    const { ms } = await kernel.init()
    useDoc.setState({ kernel: { ...useDoc.getState().kernel, ready: true } })
    console.info(`[ReCAD] ядро загружено за ${ms} мс`)
    useDoc.getState().rebuild()
    if (useDoc.getState().project.part.nodes.some((n) => n.type === 'extrude')) useDoc.getState().requestCamera({ kind: 'fit' })
  } catch (e) {
    useDoc.setState({ kernel: { ...useDoc.getState().kernel, error: 'Не удалось загрузить ядро геометрии: ' + String(e) } })
  }

  // Автосохранение через 1.5 с после последней правки (fixes #6) + список недавних.
  let timer: number | undefined
  useDoc.subscribe((s, prev) => {
    if (s.project === prev.project || s.mode.kind === 'sketch') return
    window.clearTimeout(timer)
    timer = window.setTimeout(async () => {
      const p = useDoc.getState().project
      try {
        await idbSet(projectKey(p.id), p)
        await idbSet(LAST_KEY, p.id)
        const recent = [{ id: p.id, name: p.name, updatedAt: p.updatedAt }, ...(await loadRecent()).filter((r) => r.id !== p.id)].slice(0, 12)
        await idbSet(RECENT_KEY, recent)
        useDoc.setState({ savedAt: new Date().toISOString() })
      } catch { /* нет места или приватный режим */ }
    }, 1500)
  })
}
