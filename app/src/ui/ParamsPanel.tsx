import { useEffect, useState, type ReactNode } from 'react'
import { Check, CircleAlert, CircleCheck, Trash, X } from 'lucide-react'
import { useDoc } from '../store/doc'
import { getNode, PLANE_LABEL } from '../model/project'
import { CONSTRAINT_GLYPH, CONSTRAINT_LABEL, contourCount, describeEntity, fmt, points } from '../model/sketch'
import type { ExtrudeDirection, ExtrudeExtent, Id, SketchDimension, SketchNode } from '../model/types'
import { PanelHeader } from './TreePanel'

/** Панель параметров: инспектор активной операции или выбранного узла. */
export function ParamsPanel() {
  const mode = useDoc((s) => s.mode)
  const workspace = useDoc((s) => s.workspace)
  if (workspace === 'drawing') return <DrawingInfo />
  if (mode.kind === 'extrude') return <ExtrudeParams />
  if (mode.kind === 'edgeop') return <EdgeOpParams />
  if (mode.kind === 'sketch') return <SketchParams />
  return <SelectionInfo />
}

function OpHeader({ title, onCancel }: { title: string; onCancel: () => void }) {
  return (
    <PanelHeader right={
      <span className="flex gap-1 normal-case">
        <button type="submit" title="Создать (Enter)" aria-label="Создать" className="flex h-6 w-6 items-center justify-center rounded-sm bg-accent text-on-accent hover:brightness-110"><Check size={15} /></button>
        <button type="button" title="Отмена (Esc)" aria-label="Отмена" onClick={onCancel} className="flex h-6 w-6 items-center justify-center rounded-sm text-fg-muted hover:bg-surface-2 hover:text-fg"><X size={15} /></button>
      </span>
    }>{title}</PanelHeader>
  )
}

function ErrorBox({ text }: { text: string | null | undefined }) {
  if (!text) return null
  return (
    <div role="alert" className="flex gap-2 rounded-sm border border-danger/50 bg-danger/10 p-2 text-sm text-danger">
      <CircleAlert size={15} className="mt-0.5 shrink-0" /> {text}
    </div>
  )
}

function ExtrudeParams() {
  const mode = useDoc((s) => s.mode)
  const nodes = useDoc((s) => s.project.part.nodes)
  const previewError = useDoc((s) => s.kernel.previewError)
  const { setExtrudeParams, commitExtrude, cancelExtrude } = useDoc.getState()
  if (mode.kind !== 'extrude') return null
  const p = mode.params
  const sketch = getNode(nodes, p.sketchId, 'sketch')
  const title = mode.nodeId ? nodes.find((n) => n.id === mode.nodeId)?.name ?? '' : p.op === 'add' ? 'Выдавливание' : 'Вырез'
  return (
    <form className="flex min-h-0 flex-col" onSubmit={(e) => { e.preventDefault(); commitExtrude() }}>
      <OpHeader title={title} onCancel={cancelExtrude} />
      <div className="space-y-3 overflow-auto p-3">
        <Field label="Эскиз"><span className="rounded-sm bg-surface-2 px-2 py-0.5 text-sm">{sketch?.name ?? '—'}</span></Field>
        <Field label="Способ">
          <Segmented<ExtrudeExtent> value={p.extent} onChange={(extent) => setExtrudeParams({ extent })} options={[['blind', 'На расстояние'], ['throughAll', 'Через всё']]} />
        </Field>
        {p.extent === 'blind' && (
          <>
            <Field label="Направление">
              <Segmented<ExtrudeDirection> value={p.direction} onChange={(direction) => setExtrudeParams({ direction })} options={[['forward', 'Прямое'], ['reverse', 'Обратное'], ['symmetric', 'Симметрично']]} />
            </Field>
            <Field label="Расстояние, мм">
              <NumberField value={p.distance} onChange={(distance) => setExtrudeParams({ distance })} autoFocus />
            </Field>
          </>
        )}
        <ErrorBox text={previewError} />
        <p className="text-xs text-fg-faint">Тяните стрелку в сцене или вводите число. Колесо мыши над полем: ±1, с Shift: ±10.</p>
      </div>
    </form>
  )
}

function EdgeOpParams() {
  const mode = useDoc((s) => s.mode)
  const nodes = useDoc((s) => s.project.part.nodes)
  const previewError = useDoc((s) => s.kernel.previewError)
  const { setEdgeOpParams, commitEdgeOp, cancelEdgeOp } = useDoc.getState()
  if (mode.kind !== 'edgeop') return null
  const p = mode.params
  const fillet = p.op === 'fillet'
  const title = mode.nodeId ? nodes.find((n) => n.id === mode.nodeId)?.name ?? '' : fillet ? 'Скругление' : 'Фаска'
  return (
    <form className="flex min-h-0 flex-col" onSubmit={(e) => { e.preventDefault(); commitEdgeOp() }}>
      <OpHeader title={title} onCancel={cancelEdgeOp} />
      <div className="space-y-3 overflow-auto p-3">
        <Field label="Рёбра">
          {p.edges.length ? (
            <div className="flex flex-wrap gap-1">
              {p.edges.map((e, i) => (
                <span key={i} className="flex items-center gap-1 rounded-sm bg-surface-2 py-0.5 pl-2 pr-1 text-sm">
                  Ребро {i + 1}
                  <button type="button" aria-label="Убрать ребро" className="text-fg-muted hover:text-danger" onClick={() => setEdgeOpParams({ edges: p.edges.filter((x) => x !== e) })}><X size={12} /></button>
                </span>
              ))}
            </div>
          ) : <p className="text-sm text-fg-muted">Щёлкните рёбра тела в сцене</p>}
        </Field>
        <Field label={fillet ? 'Радиус, мм' : 'Катет, мм'}>
          <NumberField value={p.size} onChange={(size) => setEdgeOpParams({ size })} autoFocus />
        </Field>
        <ErrorBox text={previewError} />
        <p className="text-xs text-fg-faint">Ссылки на рёбра хранятся по происхождению граней, поэтому переживают правку размеров эскиза.</p>
      </div>
    </form>
  )
}

/** Эскиз: степени свободы, конфликты, ограничения и размеры (fixes #1, #2). */
function SketchParams() {
  const mode = useDoc((s) => s.mode)
  const nodes = useDoc((s) => s.project.part.nodes)
  const info = useDoc((s) => s.sketchInfo)
  const sel = useDoc((s) => s.sketchSel)
  const { finishSketch, removeSketchItems, setSketchSel, setDimension } = useDoc.getState()
  if (mode.kind !== 'sketch') return null
  const sketch = getNode(nodes, mode.nodeId, 'sketch')
  if (!sketch) return null
  const cc = contourCount(sketch)
  const support = sketch.support.kind === 'plane' ? PLANE_LABEL[getNode(nodes, sketch.support.planeId, 'plane')?.key ?? 'XY'] : 'Грань тела'
  const label = (id: Id) => {
    const c = sketch.constraints.find((x) => x.id === id)
    if (c) return `${CONSTRAINT_GLYPH[c.kind]} ${CONSTRAINT_LABEL[c.kind]}`
    const d = sketch.dimensions.find((x) => x.id === id)
    return d ? `Размер ${fmt(d.value)}` : id
  }
  const free = info ? [...info.free].filter((id) => sketch.entities.some((e) => e.id === id && e.kind !== 'point')) : []

  return (
    <div className="flex min-h-0 flex-col">
      <PanelHeader right={
        <button title="Закончить эскиз (Esc)" aria-label="Закончить эскиз" onClick={finishSketch} className="flex h-6 w-6 items-center justify-center rounded-sm bg-accent text-on-accent normal-case hover:brightness-110"><Check size={15} /></button>
      }>{sketch.name}</PanelHeader>
      <div className="space-y-3 overflow-auto p-3">
        <Field label="Опора"><span className="text-sm">{support}</span></Field>

        {info && info.conflicting.length > 0 && (
          <div role="alert" className="space-y-1.5 rounded-sm border border-danger/50 bg-danger/10 p-2 text-sm">
            <div className="flex gap-2 text-danger"><CircleAlert size={15} className="mt-0.5 shrink-0" />Эти ограничения противоречат друг другу. Удалите одно:</div>
            {info.conflicting.map((id) => <ItemRow key={id} text={label(id)} onRemove={() => removeSketchItems([id])} danger />)}
          </div>
        )}
        {info && info.redundant.length > 0 && info.conflicting.length === 0 && (
          <div className="space-y-1.5 rounded-sm border border-warning/50 bg-warning/10 p-2 text-sm">
            <div className="text-warning">Лишние ограничения: повторяют уже заданное. Можно удалить:</div>
            {info.redundant.map((id) => <ItemRow key={id} text={label(id)} onRemove={() => removeSketchItems([id])} />)}
          </div>
        )}
        {info && info.dof === 0 && info.conflicting.length === 0 && sketch.entities.length > 0 && (
          <div className="flex items-center gap-2 rounded-sm bg-success/10 px-2 py-1 text-sm text-success"><CircleCheck size={14} />Эскиз полностью определён</div>
        )}
        {info && info.dof > 0 && (
          <div className="space-y-1 rounded-sm bg-accent-weak px-2 py-1.5 text-sm">
            <div>Степеней свободы: <b className="num">{info.dof}</b>. Синим показаны элементы, которым не хватает размеров или ограничений.</div>
            {free.length > 0 && <button className="text-xs text-accent underline-offset-2 hover:underline" onClick={() => setSketchSel(free)}>Выделить свободные ({free.length})</button>}
          </div>
        )}
        <div className={`rounded-sm px-2 py-1 text-sm ${cc.closed && !cc.open ? 'bg-success/10 text-success' : cc.open ? 'bg-warning/10 text-warning' : 'bg-surface-2 text-fg-muted'}`}>
          {cc.closed ? `Замкнутых контуров: ${cc.closed}` : 'Нет замкнутого контура'}
          {cc.open ? ` · незамкнутых цепочек: ${cc.open}` : ''}
        </div>

        {sel.length > 0 && <Selected sketch={sketch} ids={sel} onDelete={() => removeSketchItems(sel)} />}

        <Section title={`Размеры (${sketch.dimensions.length})`}>
          {sketch.dimensions.map((d) => <DimRow key={d.id} d={d} bad={!!info?.conflicting.includes(d.id)} onChange={(v) => setDimension(d.id, v)} onRemove={() => removeSketchItems([d.id])} />)}
        </Section>
        <Section title={`Ограничения (${sketch.constraints.length})`}>
          {sketch.constraints.map((c) => (
            <ItemRow key={c.id} text={`${CONSTRAINT_GLYPH[c.kind]} ${CONSTRAINT_LABEL[c.kind]}`} onRemove={() => removeSketchItems([c.id])} danger={info?.conflicting.includes(c.id)} onClick={() => setSketchSel([c.id, ...c.refs])} />
          ))}
        </Section>
      </div>
    </div>
  )
}

function Selected({ sketch, ids, onDelete }: { sketch: SketchNode; ids: Id[]; onDelete: () => void }) {
  const pm = points(sketch)
  const names = ids.map((id) => {
    const e = sketch.entities.find((x) => x.id === id) ?? pm.get(id)
    if (e) return describeEntity(e, pm)
    const c = sketch.constraints.find((x) => x.id === id)
    if (c) return CONSTRAINT_LABEL[c.kind]
    const d = sketch.dimensions.find((x) => x.id === id)
    return d ? `Размер ${fmt(d.value)}` : '—'
  })
  return (
    <div className="space-y-1 rounded-sm border border-line p-2 text-sm">
      <div className="flex items-center justify-between text-xs text-fg-faint">Выбрано: {ids.length}
        <button onClick={onDelete} className="flex items-center gap-1 text-fg-muted hover:text-danger" title="Удалить (Delete)"><Trash size={12} />Удалить</button>
      </div>
      {names.map((n, i) => <div key={i} className="truncate">{n}</div>)}
      <p className="text-xs text-fg-faint">Ограничения и «Размер» на ленте применяются к выбранному.</p>
    </div>
  )
}

const DIM_LABEL: Record<SketchDimension['kind'], string> = { distance: 'Длина', hdistance: 'По горизонтали', vdistance: 'По вертикали', diameter: 'Диаметр', pointLine: 'До отрезка' }

function DimRow({ d, bad, onChange, onRemove }: { d: SketchDimension; bad: boolean; onChange: (v: number) => void; onRemove: () => void }) {
  return (
    <div className={`flex items-center gap-2 text-sm ${bad ? 'text-danger' : ''}`}>
      <span className="w-28 shrink-0 truncate text-fg-muted">{DIM_LABEL[d.kind]}</span>
      <NumberField value={Number(d.value.toFixed(4))} onChange={onChange} />
      <button aria-label="Удалить размер" onClick={onRemove} className="text-fg-muted hover:text-danger"><Trash size={12} /></button>
    </div>
  )
}

function ItemRow({ text, onRemove, danger, onClick }: { text: string; onRemove: () => void; danger?: boolean; onClick?: () => void }) {
  return (
    <div className={`flex items-center justify-between gap-2 rounded-sm px-1 text-sm hover:bg-surface-2 ${danger ? 'text-danger' : ''}`}>
      <button className="truncate text-left" onClick={onClick}>{text}</button>
      <button aria-label="Удалить" onClick={onRemove} className="text-fg-muted hover:text-danger"><X size={13} /></button>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details open className="group">
      <summary className="cursor-default text-xs font-semibold uppercase tracking-wide text-fg-faint">{title}</summary>
      <div className="mt-1 space-y-1">{children}</div>
    </details>
  )
}

function SelectionInfo() {
  const selection = useDoc((s) => s.selection)
  const nodes = useDoc((s) => s.project.part.nodes)
  const status = useDoc((s) => (s.selection?.kind === 'node' ? s.kernel.statuses[s.selection.id] : undefined))
  const { editNode, startSketchOnFace } = useDoc.getState()
  const n = selection?.kind === 'node' ? nodes.find((x) => x.id === selection.id) : undefined
  let title = n ? n.name : 'Параметры'
  let body: ReactNode = <p className="text-sm text-fg-muted">Выберите узел в дереве, плоскость или грань в сцене. Двойной клик по узлу — редактировать.</p>
  if (selection?.kind === 'face') {
    title = 'Грань'
    body = (
      <div className="space-y-2 text-sm">
        <p>Плоская грань. На ней можно создать эскиз — он будет следовать за гранью при изменении модели.</p>
        <Action onClick={startSketchOnFace}>Эскиз на грани (S)</Action>
      </div>
    )
  }
  if (n?.type === 'plane') body = <p className="text-sm">{PLANE_LABEL[n.key]}. Нажмите «Эскиз» (S) или дважды щёлкните по плоскости.</p>
  if (n?.type === 'sketch') {
    const cc = contourCount(n)
    body = (
      <div className="space-y-2 text-sm">
        <p>Объектов: {n.entities.filter((e) => e.kind !== 'point').length}. Замкнутых контуров: {cc.closed}{cc.open ? `, незамкнутых: ${cc.open}` : ''}.</p>
        <p>Ограничений: {n.constraints.length}, размеров: {n.dimensions.length}.</p>
        {status?.status === 'error' && <ErrorBox text={status.error} />}
        <Action onClick={() => editNode(n.id)}>Редактировать эскиз</Action>
      </div>
    )
  }
  if (n?.type === 'extrude') {
    const sk = getNode(nodes, n.sketchId, 'sketch')
    body = (
      <div className="space-y-2 text-sm">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-fg-muted">Эскиз</dt><dd>{sk?.name}</dd>
          <dt className="text-fg-muted">Способ</dt><dd>{n.extent === 'blind' ? 'На расстояние' : 'Через всё'}</dd>
          {n.extent === 'blind' && <><dt className="text-fg-muted">Направление</dt><dd>{{ forward: 'Прямое', reverse: 'Обратное', symmetric: 'Симметрично' }[n.direction]}</dd></>}
          {n.extent === 'blind' && <><dt className="text-fg-muted">Расстояние</dt><dd className="num">{n.distance} мм</dd></>}
        </dl>
        {status?.status === 'error' && <ErrorBox text={status.error} />}
        <Action onClick={() => editNode(n.id)}>Редактировать операцию</Action>
      </div>
    )
  }
  if (n?.type === 'edgeop') {
    body = (
      <div className="space-y-2 text-sm">
        <p>Рёбер: {n.edges.length}. {n.op === 'fillet' ? 'Радиус' : 'Катет'}: <span className="num">{n.size} мм</span>.</p>
        {status?.status === 'error' && <ErrorBox text={status.error} />}
        <Action onClick={() => editNode(n.id)}>Редактировать операцию</Action>
      </div>
    )
  }
  return (
    <div className="flex min-h-0 flex-col">
      <PanelHeader>{title}</PanelHeader>
      <div className="overflow-auto p-3">{body}</div>
    </div>
  )
}

function DrawingInfo() {
  const doc = useDoc((s) => s.project.drawing)
  const views = useDoc((s) => s.views)
  return (
    <div className="flex min-h-0 flex-col">
      <PanelHeader>Чертёж</PanelHeader>
      <div className="space-y-2 overflow-auto p-3 text-sm">
        <p>Виды строятся из модели и обновляются сами после каждого перестроения — правьте деталь, чертёж догонит.</p>
        <p className="text-fg-muted">Формат {doc?.format}, видов: {views?.length ?? 0}. Невидимые линии — штриховые.</p>
        <p className="text-xs text-fg-faint">Размеры и разрезы на чертеже — следующий этап.</p>
      </div>
    </div>
  )
}

function Action({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return <button onClick={onClick} className="rounded-sm border border-line px-2 py-1 text-sm hover:bg-surface-2">{children}</button>
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="text-xs text-fg-faint">{label}</div>
      {children}
    </div>
  )
}

function Segmented<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: [T, string][] }) {
  return (
    <div role="radiogroup" className="flex rounded-sm border border-line p-0.5">
      {options.map(([v, label]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(v)}
          className={`flex-1 rounded-sm px-1.5 py-0.5 text-sm ${value === v ? 'bg-surface-3 text-fg' : 'text-fg-muted hover:text-fg'}`}>
          {label}
        </button>
      ))}
    </div>
  )
}

export function NumberField({ value, onChange, autoFocus, allowNegative }: { value: number; onChange: (v: number) => void; autoFocus?: boolean; allowNegative?: boolean }) {
  const [text, setText] = useState(String(value))
  const [focused, setFocused] = useState(false)
  useEffect(() => { if (!focused) setText(String(value)) }, [value, focused])
  const parsed = parseFloat(text.replace(',', '.'))
  const invalid = focused && (!Number.isFinite(parsed) || (!allowNegative && parsed <= 0))
  return (
    <input
      inputMode="decimal"
      autoFocus={autoFocus}
      aria-invalid={invalid}
      value={focused ? text : String(value)}
      onFocus={(e) => { setFocused(true); setText(String(value)); requestAnimationFrame(() => e.target.select()) }}
      onBlur={() => setFocused(false)}
      onChange={(e) => {
        setText(e.target.value)
        const v = parseFloat(e.target.value.replace(',', '.'))
        if (Number.isFinite(v) && (allowNegative || v > 0)) onChange(v)
      }}
      onWheel={(e) => {
        if (document.activeElement !== e.currentTarget) return
        const step = e.shiftKey ? 10 : 1
        const v = Number((value + (e.deltaY < 0 ? step : -step)).toFixed(3))
        if (allowNegative || v > 0) { onChange(v); setText(String(v)) }
      }}
      className={`num h-6 w-full rounded-sm border bg-bg px-1.5 text-base text-fg outline-none focus:border-accent ${invalid ? 'border-danger' : 'border-line-input'}`}
    />
  )
}
