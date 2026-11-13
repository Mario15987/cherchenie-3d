import { useEffect, useMemo, useRef, useState } from 'react'
import { Grid, Html, Line } from '@react-three/drei'
import { useThree, type ThreeEvent } from '@react-three/fiber'
import { DoubleSide, Vector3 } from 'three'
import { useDoc } from '../store/doc'
import { useColors, type SceneColors } from '../lib/colors'
import { consumedSketches, getNode, sketchFrame, toLocal } from '../model/project'
import { CONSTRAINT_GLYPH, CONSTRAINT_LABEL, fmt, makeCircle, makeRect, points, pt, sid, type Built, type Point } from '../model/sketch'
import { ORIGIN_ID, type Id, type SketchDimension, type SketchEntity, type SketchNode, type Vec2 } from '../model/types'
import { frameMatrix } from './frame'

const SNAP_PX = 9
const PICK_PX = 7
const AUTO_DEG = 4
const round = (v: number, step = 0.5) => Math.round(v / step) * step
const v3 = (p: Vec2): [number, number, number] => [p[0], p[1], 0]

function circlePoints(c: Vec2, r: number): [number, number, number][] {
  return Array.from({ length: 97 }, (_, i) => {
    const a = (i / 96) * Math.PI * 2
    return [c[0] + Math.cos(a) * r, c[1] + Math.sin(a) * r, 0]
  })
}

/** Привязки: существующие точки (с переиспользованием), середины отрезков, центры окружностей. */
function snapTargets(s: SketchNode): { p: Vec2; kind: string; pointId?: Id }[] {
  const pm = points(s)
  const out: { p: Vec2; kind: string; pointId?: Id }[] = []
  for (const p of pm.values()) out.push({ p: [p.x, p.y], kind: p.id === ORIGIN_ID ? 'начало координат' : 'точка', pointId: p.id })
  for (const e of s.entities) {
    if (e.kind === 'line') {
      const a = pt(pm, e.a), b = pt(pm, e.b)
      out.push({ p: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], kind: 'середина' })
    }
    if (e.kind === 'circle') {
      const c = pt(pm, e.c)
      for (const deg of [0, 90, 180, 270]) out.push({ p: [c[0] + e.r * Math.cos((deg * Math.PI) / 180), c[1] + e.r * Math.sin((deg * Math.PI) / 180)], kind: 'квадрант' })
    }
  }
  return out
}

function distToSeg(p: Vec2, a: Vec2, b: Vec2) {
  const dx = b[0] - a[0], dy = b[1] - a[1]
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)))
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
}

/** Ближайший объект эскиза под курсором: точки важнее кривых. */
function pick(s: SketchNode, p: Vec2, tol: number): Id | null {
  const pm = points(s)
  let best: Id | null = null, bd = tol
  for (const q of pm.values()) {
    const d = Math.hypot(q.x - p[0], q.y - p[1])
    if (d < bd) { bd = d; best = q.id }
  }
  if (best) return best
  bd = tol
  for (const e of s.entities) {
    let d = Infinity
    if (e.kind === 'line') d = distToSeg(p, pt(pm, e.a), pt(pm, e.b))
    if (e.kind === 'circle') { const c = pt(pm, e.c); d = Math.abs(Math.hypot(p[0] - c[0], p[1] - c[1]) - e.r) }
    if (d < bd) { bd = d; best = e.id }
  }
  return best
}

/** Цвет объекта по состоянию: выбран, конфликт, свободен, определён. */
function useEntityColor() {
  const c = useColors()
  const info = useDoc((s) => s.sketchInfo)
  const sel = useDoc((s) => s.sketchSel)
  const mode = useDoc((s) => s.mode)
  const nodes = useDoc((s) => s.project.part.nodes)
  const sketch = mode.kind === 'sketch' ? getNode(nodes, mode.nodeId, 'sketch') : undefined
  const bad = useMemo(() => {
    const out = new Set<Id>()
    if (!sketch || !info) return out
    const problems = new Set([...info.conflicting, ...info.redundant])
    for (const x of [...sketch.constraints, ...sketch.dimensions]) if (problems.has(x.id)) x.refs.forEach((r) => out.add(r))
    return out
  }, [sketch, info])
  return (id: Id) => (sel.includes(id) ? c.selection : bad.has(id) ? c['sketch-over'] : info?.free.has(id) ? c['sketch-free'] : c['sketch-defined'])
}

function SketchGeometry({ sketch, color, width = 1.6 }: { sketch: SketchNode; color: (id: Id) => string; width?: number }) {
  const pm = points(sketch)
  return (
    <>
      {sketch.entities.map((e) => {
        if (e.kind === 'line') return <Line key={e.id} points={[v3(pt(pm, e.a)), v3(pt(pm, e.b))]} color={color(e.id)} lineWidth={width} dashed={e.construction} dashSize={3} gapSize={2} depthTest={false} transparent renderOrder={10} />
        if (e.kind === 'circle') return <Line key={e.id} points={circlePoints(pt(pm, e.c), e.r)} color={color(e.id)} lineWidth={width} dashed={e.construction} dashSize={3} gapSize={2} depthTest={false} transparent renderOrder={10} />
        return null
      })}
    </>
  )
}

/** Эскизы вне режима редактирования: свободные видны, использованные — только при выделении. */
export function SketchesDisplay() {
  const c = useColors()
  const nodes = useDoc((s) => s.project.part.nodes)
  const frames = useDoc((s) => s.kernel.frames)
  const mode = useDoc((s) => s.mode)
  const selection = useDoc((s) => s.selection)
  const used = useMemo(() => consumedSketches(nodes), [nodes])
  const sketches = nodes.filter((n): n is SketchNode => n.type === 'sketch')
  return (
    <>
      {sketches.map((s) => {
        if (mode.kind === 'sketch' && mode.nodeId === s.id) return null
        const active = (mode.kind === 'extrude' && mode.params.sketchId === s.id) || (selection?.kind === 'node' && selection.id === s.id)
        if (s.hidden || (used.has(s.id) && !active)) return null
        const color = active ? c.selection : c['sketch-defined']
        return (
          <group key={s.id} matrix={frameMatrix(sketchFrame(nodes, s, frames))} matrixAutoUpdate={false}>
            <SketchGeometry sketch={s} color={() => color} width={active ? 2.2 : 1.4} />
          </group>
        )
      })}
    </>
  )
}

type Draft = { tool: 'line' | 'rect' | 'circle'; p0: Vec2; p0Id?: Id }
type Snap = { p: Vec2; kind: string | null; pointId?: Id; auto?: 'horizontal' | 'vertical' }

/** Редактор эскиза: отрезок (цепочкой), прямоугольник, окружность; выбор объектов; курсорный ввод размеров. */
export function SketchEditor() {
  const c = useColors()
  const mode = useDoc((s) => s.mode)
  const nodes = useDoc((s) => s.project.part.nodes)
  const frames = useDoc((s) => s.kernel.frames)
  const sel = useDoc((s) => s.sketchSel)
  const { camera, size, controls } = useThree()
  const sketch = mode.kind === 'sketch' ? getNode(nodes, mode.nodeId, 'sketch') : undefined
  const tool = mode.kind === 'sketch' ? mode.tool : null
  const frame = useMemo(() => (sketch ? sketchFrame(nodes, sketch, frames) : null), [nodes, sketch, frames])
  const matrix = useMemo(() => (frame ? frameMatrix(frame) : null), [frame])
  const color = useEntityColor()

  const [draft, setDraft] = useState<Draft | null>(null)
  const [cur, setCur] = useState<Snap | null>(null)
  const [hoverId, setHoverId] = useState<Id | null>(null)
  const [typed, setTyped] = useState<{ a: string; b: string }>({ a: '', b: '' })
  const inputA = useRef<HTMLInputElement>(null)
  const { addBuilt, setHint, setCursor, setSketchSel } = useDoc.getState()

  useEffect(() => {
    const hints: Record<string, string> = {
      none: 'Щёлкните объект, чтобы выбрать (Shift — несколько). Инструменты: Отрезок (L), Прямоугольник (R), Окружность (C). Esc — закончить эскиз',
      line0: 'Укажите начало отрезка',
      line1: 'Укажите конец или введите длину. Горизонталь и вертикаль ставятся сами (Shift — без них). Щелчок в начальную точку замыкает контур',
      rect0: 'Укажите первый угол прямоугольника',
      rect1: 'Укажите второй угол или введите ширину и высоту (Tab), Enter — готово',
      circle0: 'Укажите центр окружности',
      circle1: 'Укажите точку на окружности или введите диаметр, Enter — готово',
    }
    setHint(hints[tool ? `${tool}${draft ? 1 : 0}` : 'none'])
  }, [tool, draft, setHint])

  useEffect(() => { setDraft(null); setTyped({ a: '', b: '' }) }, [tool])
  useEffect(() => () => setCursor(null), [setCursor])

  // После первой точки фокус в поле размера: цифры пишутся туда, Tab — к следующему.
  const hasDraft = !!draft
  useEffect(() => { if (hasDraft) requestAnimationFrame(() => inputA.current?.focus()) }, [hasDraft])

  // Esc сначала отменяет начатую фигуру, а не весь эскиз.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && draft) {
        e.stopPropagation(); e.preventDefault()
        setDraft(null); setTyped({ a: '', b: '' })
        ;(document.activeElement as HTMLElement)?.blur?.()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [draft])

  if (!sketch || !frame || !matrix) return null
  const pm = points(sketch)

  const worldPerPixel = () => {
    const target = (controls as unknown as { target?: Vector3 })?.target ?? new Vector3()
    const fov = (camera as unknown as { fov?: number }).fov ?? 35
    return (2 * camera.position.distanceTo(target) * Math.tan((fov * Math.PI) / 360)) / size.height
  }

  const snap = (p: Vec2, shift: boolean): Snap => {
    const tol = worldPerPixel() * SNAP_PX
    let best: Snap | null = null
    let bd = tol
    for (const s of snapTargets(sketch)) {
      const d = Math.hypot(s.p[0] - p[0], s.p[1] - p[1])
      if (d < bd) { bd = d; best = { p: s.p, kind: s.kind, pointId: s.pointId } }
    }
    let out: Snap = best ?? { p: [round(p[0]), round(p[1])], kind: null }
    // Автоограничения для отрезка видны до щелчка (fixes #3).
    if (draft?.tool === 'line' && !shift && !out.pointId) {
      const dx = out.p[0] - draft.p0[0], dy = out.p[1] - draft.p0[1]
      const ang = Math.abs((Math.atan2(dy, dx) * 180) / Math.PI)
      if (Math.hypot(dx, dy) > 0 && (ang < AUTO_DEG || ang > 180 - AUTO_DEG)) out = { ...out, p: [out.p[0], draft.p0[1]], auto: 'horizontal' }
      else if (Math.hypot(dx, dy) > 0 && Math.abs(ang - 90) < AUTO_DEG) out = { ...out, p: [draft.p0[0], out.p[1]], auto: 'vertical' }
    }
    return out
  }

  const local = (e: ThreeEvent<PointerEvent | MouseEvent>) => toLocal(frame, [e.point.x, e.point.y, e.point.z])
  const num = (s: string) => { const v = parseFloat(s.replace(',', '.')); return Number.isFinite(v) && v > 0 ? v : undefined }

  /** Конец отрезка с учётом введённой длины. */
  const lineEnd = (d: Draft, s: Snap): Snap => {
    const L = num(typed.a)
    if (!L) return s
    const dx = s.p[0] - d.p0[0], dy = s.p[1] - d.p0[1]
    const k = Math.hypot(dx, dy) || 1
    return { ...s, pointId: undefined, p: [d.p0[0] + (dx / k) * L, d.p0[1] + (dy / k) * L] }
  }

  const commit = (d: Draft, s: Snap) => {
    if (d.tool === 'line') {
      const end = lineEnd(d, s)
      if (Math.hypot(end.p[0] - d.p0[0], end.p[1] - d.p0[1]) < 1e-6) return
      const b: Built = { entities: [], constraints: [], dimensions: [] }
      const aId = d.p0Id ?? sid()
      if (!d.p0Id) b.entities.push({ id: aId, kind: 'point', x: d.p0[0], y: d.p0[1] })
      const bId = end.pointId ?? sid()
      if (!end.pointId) b.entities.push({ id: bId, kind: 'point', x: end.p[0], y: end.p[1] })
      const lid = sid()
      b.entities.push({ id: lid, kind: 'line', a: aId, b: bId })
      if (end.auto) b.constraints.push({ id: sid(), kind: end.auto, refs: [lid] })
      const L = num(typed.a)
      if (L) b.dimensions.push({ id: sid(), kind: 'distance', refs: [lid], value: L })
      addBuilt(b)
      // Цепочка продолжается, пока не замкнули на существующую точку.
      setDraft(end.pointId ? null : { tool: 'line', p0: end.p, p0Id: bId })
    } else if (d.tool === 'rect') {
      const w = num(typed.a), h = num(typed.b)
      const sx = s.p[0] >= d.p0[0] ? 1 : -1, sy = s.p[1] >= d.p0[1] ? 1 : -1
      const p1: Vec2 = [w ? d.p0[0] + sx * w : s.p[0], h ? d.p0[1] + sy * h : s.p[1]]
      if (Math.abs(p1[0] - d.p0[0]) < 1e-6 || Math.abs(p1[1] - d.p0[1]) < 1e-6) return
      addBuilt(makeRect(d.p0, p1, { a: d.p0Id }))
      setDraft(null)
    } else {
      const D = num(typed.a)
      const r = D ? D / 2 : Math.hypot(s.p[0] - d.p0[0], s.p[1] - d.p0[1])
      if (!(r > 0)) return
      addBuilt(makeCircle(d.p0, r, { c: d.p0Id }))
      setDraft(null)
    }
    setTyped({ a: '', b: '' })
    ;(document.activeElement as HTMLElement)?.blur?.()
  }

  // Над HTML-подписями координаты события считаются от подписи, а не от холста: такие события пропускаем.
  const fromCanvas = (e: ThreeEvent<PointerEvent | MouseEvent>) => (e.nativeEvent.target as Element | null)?.tagName === 'CANVAS'

  const onMove = (e: ThreeEvent<PointerEvent>) => {
    if (!fromCanvas(e)) return
    const p = local(e)
    const s = snap(p, e.shiftKey)
    setCur(s)
    setCursor(s.p)
    setHoverId(tool ? null : pick(sketch, p, worldPerPixel() * PICK_PX))
  }

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    if (e.button !== 0 || e.delta > 4 || !fromCanvas(e)) return
    e.stopPropagation()
    const p = local(e)
    if (!tool) {
      const id = pick(sketch, p, worldPerPixel() * PICK_PX)
      const multi = e.shiftKey || e.ctrlKey || e.metaKey
      if (!id) { if (!multi) setSketchSel([]); return }
      setSketchSel(multi ? (sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]) : [id])
      return
    }
    const s = snap(p, e.shiftKey)
    if (!draft) setDraft({ tool, p0: s.p, p0Id: s.pointId })
    else commit(draft, s)
  }

  const onFieldKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && draft && cur) { e.preventDefault(); e.stopPropagation(); commit(draft, cur) }
  }

  // Резиновая нить и живые значения у курсора.
  let rubber: [number, number, number][] | null = null
  let liveA = '', liveB = ''
  if (draft && cur) {
    if (draft.tool === 'line') {
      const end = lineEnd(draft, cur)
      rubber = [v3(draft.p0), v3(end.p)]
      liveA = fmt(Math.hypot(end.p[0] - draft.p0[0], end.p[1] - draft.p0[1]))
    } else if (draft.tool === 'rect') {
      const w = num(typed.a) ?? Math.abs(cur.p[0] - draft.p0[0]), h = num(typed.b) ?? Math.abs(cur.p[1] - draft.p0[1])
      const sx = cur.p[0] >= draft.p0[0] ? 1 : -1, sy = cur.p[1] >= draft.p0[1] ? 1 : -1
      const [x0, y0] = draft.p0, x1 = x0 + sx * w, y1 = y0 + sy * h
      rubber = [[x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0], [x0, y0, 0]]
      liveA = fmt(w); liveB = fmt(h)
    } else {
      const d = num(typed.a) ?? 2 * Math.hypot(cur.p[0] - draft.p0[0], cur.p[1] - draft.p0[1])
      rubber = circlePoints(draft.p0, d / 2)
      liveA = fmt(d)
    }
  }
  const wpp = worldPerPixel()
  const hoverColor = (id: Id) => (id === hoverId && !sel.includes(id) ? c.hover : color(id))

  return (
    <group matrix={matrix} matrixAutoUpdate={false}>
      <group rotation={[Math.PI / 2, 0, 0]}>
        <Grid infiniteGrid cellSize={5} sectionSize={50} cellColor={c['grid-minor']} sectionColor={c['grid-major']} fadeDistance={2500} side={DoubleSide} />
      </group>
      <Line points={[[-1000, 0, 0], [1000, 0, 0]]} color={c['axis-x']} lineWidth={1} transparent opacity={0.5} depthTest={false} />
      <Line points={[[0, -1000, 0], [0, 1000, 0]]} color={c['axis-y']} lineWidth={1} transparent opacity={0.5} depthTest={false} />

      <mesh onPointerMove={onMove} onClick={onClick} onPointerOut={() => { setCur(null); setCursor(null); setHoverId(null) }}>
        <planeGeometry args={[1e5, 1e5]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} side={DoubleSide} />
      </mesh>

      <SketchGeometry sketch={sketch} color={hoverColor} width={2} />
      <PointMarks pts={[...pm.values()]} color={hoverColor} c={c} />
      <ConstraintBadges sketch={sketch} wpp={wpp} />
      {sketch.dimensions.map((d) => <DimensionLabel key={d.id} dim={d} sketch={sketch} wpp={wpp} />)}

      {rubber && <Line points={rubber} color={c.hover} lineWidth={1.6} dashed dashSize={3} gapSize={2} depthTest={false} transparent renderOrder={11} />}
      {cur && (cur.kind || cur.auto) && (
        <Html position={v3(cur.p)} style={{ pointerEvents: 'none' }} zIndexRange={[30, 0]}>
          <div className="-mt-6 ml-3 whitespace-nowrap text-xs text-fg-muted">
            {cur.auto ? <span className="rounded-sm bg-surface px-1 text-accent">{CONSTRAINT_GLYPH[cur.auto]} {CONSTRAINT_LABEL[cur.auto].toLowerCase()}</span> : cur.kind}
          </div>
        </Html>
      )}
      {draft && cur && (
        <Html position={v3(cur.p)} zIndexRange={[40, 0]} style={{ pointerEvents: 'none' }}>
          <div className="pointer-events-auto ml-4 mt-4 flex gap-1 rounded-md border border-line bg-surface p-1 shadow-[var(--shadow-pop)]" onPointerDown={(e) => e.stopPropagation()}>
            <CursorField refEl={inputA} label={draft.tool === 'rect' ? 'Ш' : draft.tool === 'circle' ? 'Ø' : 'Длина'} value={typed.a} placeholder={liveA} onChange={(v) => setTyped({ ...typed, a: v })} onKeyDown={onFieldKey} />
            {draft.tool === 'rect' && <CursorField label="В" value={typed.b} placeholder={liveB} onChange={(v) => setTyped({ ...typed, b: v })} onKeyDown={onFieldKey} />}
          </div>
        </Html>
      )}
    </group>
  )
}

/** Точки эскиза постоянного экранного размера. */
function PointMarks({ pts, color, c }: { pts: Point[]; color: (id: Id) => string; c: SceneColors }) {
  // По одной группе точек на цвет: так не нужен отдельный шейдер с цветом на вершину.
  const byColor = new Map<string, Point[]>()
  for (const p of pts) {
    const col = p.id === ORIGIN_ID ? c.text : color(p.id)
    byColor.set(col, [...(byColor.get(col) ?? []), p])
  }
  return (
    <>
      {[...byColor.entries()].map(([col, list]) => (
        <points key={col + list.map((p) => p.id).join()} renderOrder={12}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[new Float32Array(list.flatMap((p) => [p.x, p.y, 0])), 3]} />
          </bufferGeometry>
          <pointsMaterial color={col} size={6} sizeAttenuation={false} depthTest={false} transparent />
        </points>
      ))}
    </>
  )
}

function anchorOf(s: SketchNode, id: Id): Vec2 | null {
  const pm = points(s)
  if (pm.has(id)) return pt(pm, id)
  const e = s.entities.find((x) => x.id === id)
  if (e?.kind === 'line') { const a = pt(pm, e.a), b = pt(pm, e.b); return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] }
  if (e?.kind === 'circle') { const cc = pt(pm, e.c); return [cc[0], cc[1] + e.r] }
  return null
}

/** Значки ограничений у объектов. Щелчок — выбрать (Delete удалит), красный — конфликт. */
function ConstraintBadges({ sketch, wpp }: { sketch: SketchNode; wpp: number }) {
  const info = useDoc((s) => s.sketchInfo)
  const sel = useDoc((s) => s.sketchSel)
  const setSel = useDoc((s) => s.setSketchSel)
  // Несколько значков у одного объекта раскладываем в ряд.
  const slots = new Map<string, number>()
  return (
    <>
      {sketch.constraints.map((k) => {
        const anchor = anchorOf(sketch, k.refs[0])
        if (!anchor) return null
        const key = k.refs[0]
        const slot = slots.get(key) ?? 0
        slots.set(key, slot + 1)
        const bad = info?.conflicting.includes(k.id) ? 'conflict' : info?.redundant.includes(k.id) ? 'redundant' : null
        const selected = sel.includes(k.id)
        return (
          <Html key={k.id} position={[anchor[0] + wpp * (8 + slot * 16), anchor[1] + wpp * 10, 0]} center zIndexRange={[25, 0]} style={{ pointerEvents: 'none' }}>
            <button
              title={`${CONSTRAINT_LABEL[k.kind]}${bad === 'conflict' ? ' — противоречит другим' : bad === 'redundant' ? ' — лишнее' : ''}. Щелчок — выбрать, Delete — удалить`}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); setSel(e.shiftKey ? [...sel, k.id] : [k.id]) }}
              className={`pointer-events-auto flex h-4 min-w-4 items-center justify-center rounded-sm border px-0.5 text-[10px] leading-none ${selected ? 'border-[var(--c-selection)] bg-[var(--c-selection)] text-bg' : bad === 'conflict' ? 'border-danger bg-danger text-bg' : bad === 'redundant' ? 'border-warning bg-surface text-warning' : 'border-line bg-surface text-fg-muted hover:text-fg'}`}
            >
              {CONSTRAINT_GLYPH[k.kind]}
            </button>
          </Html>
        )
      })}
    </>
  )
}

function dimGeometry(d: SketchDimension, s: SketchNode): { at: Vec2; offset: string; prefix: string } | null {
  const pm = points(s)
  const line = (id: Id) => s.entities.find((e) => e.id === id && e.kind === 'line') as Extract<SketchEntity, { kind: 'line' }> | undefined
  const ends = (): [Vec2, Vec2] | null => {
    if (d.refs.length === 1) { const l = line(d.refs[0]); return l ? [pt(pm, l.a), pt(pm, l.b)] : null }
    return [pt(pm, d.refs[0]), pt(pm, d.refs[1])]
  }
  if (d.kind === 'diameter') {
    const e = s.entities.find((x) => x.id === d.refs[0])
    if (e?.kind !== 'circle') return null
    const cc = pt(pm, e.c)
    return { at: [cc[0] + e.r * Math.SQRT1_2, cc[1] + e.r * Math.SQRT1_2], offset: 'translate(4px, calc(-100% - 4px))', prefix: 'Ø' }
  }
  if (d.kind === 'pointLine') {
    const p = pt(pm, d.refs[0]); const l = line(d.refs[1])
    if (!l) return null
    const a = pt(pm, l.a)
    return { at: [(p[0] + a[0]) / 2, (p[1] + a[1]) / 2], offset: 'translate(-50%, -50%)', prefix: '' }
  }
  const e = ends()
  if (!e) return null
  const [a, b] = e
  if (d.kind === 'hdistance') return { at: [(a[0] + b[0]) / 2, Math.min(a[1], b[1])], offset: 'translate(-50%, 6px)', prefix: '' }
  if (d.kind === 'vdistance') return { at: [Math.max(a[0], b[0]), (a[1] + b[1]) / 2], offset: 'translate(6px, -50%)', prefix: '' }
  return { at: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], offset: 'translate(6px, -100%)', prefix: '' }
}

/** Управляющий размер. Двойной клик — правка значения на месте; красный — противоречит ограничениям. */
function DimensionLabel({ dim, sketch, wpp }: { dim: SketchDimension; sketch: SketchNode; wpp: number }) {
  const setDimension = useDoc((s) => s.setDimension)
  const info = useDoc((s) => s.sketchInfo)
  const sel = useDoc((s) => s.sketchSel)
  const setSel = useDoc((s) => s.setSketchSel)
  const [edit, setEdit] = useState<string | null>(null)
  const g = dimGeometry(dim, sketch)
  if (!g) return null
  void wpp
  const bad = info?.conflicting.includes(dim.id) || info?.redundant.includes(dim.id)
  const apply = () => {
    const v = edit !== null ? parseFloat(edit.replace(',', '.')) : NaN
    if (v > 0) setDimension(dim.id, v)
    setEdit(null)
  }
  return (
    <Html position={v3(g.at)} zIndexRange={[35, 0]} style={{ pointerEvents: 'none' }}>
      <div className="pointer-events-auto" style={{ transform: g.offset }} onPointerDown={(e) => e.stopPropagation()}>
        {edit === null ? (
          <button
            className={`num whitespace-nowrap rounded-sm px-1 text-xs ${sel.includes(dim.id) ? 'bg-[var(--c-selection)] text-bg' : bad ? 'text-danger' : 'text-fg hover:bg-surface-2'}`}
            title="Двойной клик — изменить размер, щелчок — выбрать"
            onClick={(e) => setSel(e.shiftKey ? [...sel, dim.id] : [dim.id])}
            onDoubleClick={() => setEdit(fmt(dim.value))}
          >
            {g.prefix}{fmt(dim.value)}
          </button>
        ) : (
          <input
            autoFocus
            className="num h-5 w-16 rounded-sm border border-accent bg-bg px-1 text-xs text-fg outline-none"
            value={edit}
            onChange={(e) => setEdit(e.target.value)}
            onBlur={apply}
            onFocus={(e) => e.target.select()}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.stopPropagation(); apply() }
              if (e.key === 'Escape') { e.stopPropagation(); e.nativeEvent.stopImmediatePropagation(); setEdit(null) }
            }}
          />
        )}
      </div>
    </Html>
  )
}

function CursorField(props: { refEl?: React.RefObject<HTMLInputElement | null>; label: string; value: string; placeholder: string; onChange: (v: string) => void; onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void }) {
  return (
    <label className="flex items-center gap-1 text-xs text-fg-muted">
      {props.label}
      <input
        ref={props.refEl}
        className="num h-6 w-16 rounded-sm border border-line-input bg-bg px-1 text-base text-fg outline-none focus:border-accent"
        inputMode="decimal"
        value={props.value}
        placeholder={props.placeholder}
        onChange={(e) => props.onChange(e.target.value)}
        onKeyDown={props.onKeyDown}
      />
    </label>
  )
}
