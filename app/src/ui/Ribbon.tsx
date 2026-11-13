import { useEffect, useState, type ReactNode } from 'react'
import {
  ArrowDownToLine, ArrowLeft, ArrowUpFromLine, Box, Check, Circle, FileDown, Focus, Hexagon, LayoutTemplate, PenLine, RefreshCw, Ruler, Scan, Slash, Square, Squircle,
} from 'lucide-react'
import { useDoc, type ViewName } from '../store/doc'
import type { ConstraintKind, ViewKind } from '../model/types'
import { CONSTRAINT_GLYPH, CONSTRAINT_LABEL } from '../model/sketch'
import { cmdExportDrawingDxf, cmdExportDxf, cmdNormalTo, cmdSketch } from './actions'

type TabId = 'model' | 'sketch' | 'drawing' | 'view'
const TABS: { id: TabId; label: string }[] = [
  { id: 'model', label: 'Моделирование' },
  { id: 'sketch', label: 'Эскиз' },
  { id: 'drawing', label: 'Черчение' },
  { id: 'view', label: 'Вид' },
]

/** Лента: вкладки по режимам. В эскизе — только «Эскиз» и «Вид», на чертеже — «Черчение». */
export function Ribbon() {
  const mode = useDoc((s) => s.mode)
  const workspace = useDoc((s) => s.workspace)
  const [tab, setTab] = useState<TabId>('model')
  useEffect(() => { setTab(workspace === 'drawing' ? 'drawing' : mode.kind === 'sketch' ? 'sketch' : 'model') }, [mode.kind, workspace])
  const enabled = (id: TabId) =>
    workspace === 'drawing' ? id === 'drawing' : mode.kind === 'sketch' ? id === 'sketch' || id === 'view' : id !== 'sketch'

  const pick = (id: TabId) => {
    if (id === 'drawing' && workspace !== 'drawing') useDoc.getState().setWorkspace('drawing')
    setTab(id)
  }

  return (
    <div className={`border-b border-line bg-surface ${mode.kind === 'sketch' ? 'shadow-[inset_0_-2px_0_var(--c-accent)]' : ''}`}>
      <div role="tablist" className="flex h-7 items-end gap-1 px-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            disabled={!enabled(t.id) && !(t.id === 'drawing' && mode.kind === 'model')}
            onClick={() => pick(t.id)}
            className={`h-7 px-3 text-sm font-medium disabled:opacity-35 ${tab === t.id ? 'text-fg shadow-[inset_0_-2px_0_var(--c-accent)]' : 'text-fg-muted hover:text-fg'}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="flex h-[76px] items-stretch gap-0 border-t border-line px-1 py-1">
        {tab === 'model' && <ModelTab />}
        {tab === 'sketch' && <SketchTab />}
        {tab === 'drawing' && <DrawingTab />}
        {tab === 'view' && <ViewTab />}
      </div>
    </div>
  )
}

function ModelTab() {
  const s = useDoc()
  const busy = s.mode.kind !== 'model'
  const noKernel = !s.kernel.ready
  const noBody = !s.kernel.body
  return (
    <>
      <Group label="Эскиз">
        <Big icon={<PenLine size={22} />} label="Эскиз" hotkey="S" disabled={busy} onClick={cmdSketch} />
      </Group>
      <Group label="Элементы тела">
        <Big icon={<ArrowUpFromLine size={22} />} label="Выдавли­вание" hotkey="E" disabled={busy || noKernel} onClick={() => s.startExtrude('add')} />
        <Big icon={<ArrowDownToLine size={22} />} label="Вырез" hotkey="X" disabled={busy || noKernel || noBody} onClick={() => s.startExtrude('cut')} />
      </Group>
      <Group label="Обработка рёбер">
        <Big icon={<Squircle size={22} />} label="Скругление" hotkey="F" disabled={busy || noBody} onClick={() => s.startEdgeOp('fillet')} />
        <Big icon={<Hexagon size={22} />} label="Фаска" hotkey="H" disabled={busy || noBody} onClick={() => s.startEdgeOp('chamfer')} />
      </Group>
    </>
  )
}

const CONSTRAINT_BUTTONS: ConstraintKind[] = ['horizontal', 'vertical', 'parallel', 'perpendicular', 'equal', 'tangent', 'coincident', 'pointOnLine', 'fix']

function SketchTab() {
  const mode = useDoc((s) => s.mode)
  const selCount = useDoc((s) => s.sketchSel.length)
  const { setSketchTool, finishSketch, addConstraint, addDimension } = useDoc.getState()
  const tool = mode.kind === 'sketch' ? mode.tool : null
  const toggle = (t: 'line' | 'rect' | 'circle') => setSketchTool(tool === t ? null : t)
  return (
    <>
      <Group label="Геометрия">
        <Big icon={<Slash size={22} />} label="Отрезок" hotkey="L" active={tool === 'line'} onClick={() => toggle('line')} />
        <Big icon={<Square size={22} />} label="Прямо­угольник" hotkey="R" active={tool === 'rect'} onClick={() => toggle('rect')} />
        <Big icon={<Circle size={22} />} label="Окруж­ность" hotkey="C" active={tool === 'circle'} onClick={() => toggle('circle')} />
      </Group>
      <Group label={selCount ? `Ограничения · выбрано ${selCount}` : 'Ограничения · выберите объекты'}>
        <div className="grid grid-cols-3 gap-x-0.5">
          {CONSTRAINT_BUTTONS.map((k) => (
            <button key={k} disabled={!selCount} onClick={() => addConstraint(k)} title={CONSTRAINT_LABEL[k]}
              className="flex h-[18px] items-center gap-1 rounded-sm px-1 text-left text-xs text-fg hover:bg-surface-2 disabled:opacity-35">
              <span className="w-3 text-center text-fg-muted">{CONSTRAINT_GLYPH[k]}</span>{CONSTRAINT_LABEL[k]}
            </button>
          ))}
        </div>
      </Group>
      <Group label="Размеры">
        <Big icon={<Ruler size={22} />} label="Размер" hotkey="D" disabled={!selCount} title="Выберите отрезок, окружность, две точки или точку и отрезок, затем «Размер» (D)" onClick={addDimension} />
      </Group>
      <Group label="Файл">
        <Big icon={<FileDown size={22} />} label="DXF эскиза" onClick={cmdExportDxf} />
      </Group>
      <div className="ml-auto flex items-center pr-2">
        <button onClick={finishSketch} title="Закончить эскиз (Esc)"
          className="flex h-[60px] items-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-on-accent hover:brightness-110">
          <Check size={18} /> Закончить эскиз
        </button>
      </div>
    </>
  )
}

const VIEW_LABEL: Record<ViewKind, string> = { front: 'Главный вид', top: 'Вид сверху', left: 'Вид слева', iso: 'Изометрия' }

function DrawingTab() {
  const workspace = useDoc((s) => s.workspace)
  const doc = useDoc((s) => s.project.drawing)
  const { setWorkspace, setDrawing, refreshViews } = useDoc.getState()
  if (workspace !== 'drawing' || !doc) {
    return (
      <Group label="Чертёж">
        <Big icon={<LayoutTemplate size={22} />} label="Чертёж по модели" onClick={() => setWorkspace('drawing')} />
      </Group>
    )
  }
  const toggleView = (v: ViewKind) => setDrawing({ views: doc.views.includes(v) ? doc.views.filter((x) => x !== v) : [...doc.views, v] })
  return (
    <>
      <Group label="Документ">
        <Big icon={<ArrowLeft size={22} />} label="К модели" onClick={() => setWorkspace('part')} />
        <Big icon={<RefreshCw size={22} />} label="Обновить виды" onClick={refreshViews} />
      </Group>
      <Group label="Стандартные виды">
        <div className="grid grid-cols-2 gap-x-1">
          {(['front', 'top', 'left', 'iso'] as ViewKind[]).map((v) => (
            <label key={v} className="flex h-[18px] items-center gap-1.5 px-1 text-xs">
              <input type="checkbox" checked={doc.views.includes(v)} onChange={() => toggleView(v)} disabled={v === 'front'} className="accent-[var(--c-accent)]" />
              {VIEW_LABEL[v]}
            </label>
          ))}
        </div>
      </Group>
      <Group label="Лист">
        <div className="flex flex-col gap-1 px-1 text-xs">
          <label className="flex items-center gap-2">Формат
            <select value={doc.format} onChange={(e) => setDrawing({ format: e.target.value as 'A3' | 'A4' })} className="h-5 rounded-sm border border-line-input bg-bg px-1 text-fg">
              <option value="A3">A3 (альбомный)</option><option value="A4">A4 (книжный)</option>
            </select>
          </label>
          <label className="flex items-center gap-2">Масштаб
            <select value={String(doc.scale)} onChange={(e) => setDrawing({ scale: e.target.value === 'auto' ? 'auto' : Number(e.target.value) })} className="h-5 rounded-sm border border-line-input bg-bg px-1 text-fg">
              <option value="auto">Подобрать</option>
              {[4, 2, 1, 0.5, 0.25, 0.2, 0.1].map((s) => <option key={s} value={s}>{s >= 1 ? `${s}:1` : `1:${1 / s}`}</option>)}
            </select>
          </label>
        </div>
      </Group>
      <Group label="Файл">
        <Big icon={<FileDown size={22} />} label="DXF чертежа" onClick={cmdExportDrawingDxf} />
      </Group>
    </>
  )
}

function ViewTab() {
  const requestCamera = useDoc((s) => s.requestCamera)
  const view = (v: ViewName) => requestCamera({ kind: 'view', view: v })
  return (
    <>
      <Group label="Ориентация">
        <Big icon={<Box size={22} />} label="Изометрия" hotkey="0" onClick={() => view('iso')} />
        <div className="flex flex-col">
          <Small label="Спереди" hotkey="1" onClick={() => view('front')} />
          <Small label="Сверху" hotkey="7" onClick={() => view('top')} />
          <Small label="Справа" hotkey="3" onClick={() => view('right')} />
        </div>
      </Group>
      <Group label="Камера">
        <Big icon={<Scan size={22} />} label="Нормально к" hotkey="N" onClick={cmdNormalTo} />
        <Big icon={<Focus size={22} />} label="Показать всё" hotkey="Space" onClick={() => requestCamera({ kind: 'fit' })} />
      </Group>
    </>
  )
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col border-r border-line px-1 last:border-r-0">
      <div className="flex flex-1 items-start gap-0.5">{children}</div>
      <div className="whitespace-nowrap text-center text-xs text-fg-faint">{label}</div>
    </div>
  )
}

function Big(props: { icon: ReactNode; label: string; hotkey?: string; onClick?: () => void; disabled?: boolean; active?: boolean; title?: string }) {
  return (
    <button
      onClick={props.onClick}
      disabled={props.disabled}
      aria-pressed={props.active}
      title={props.title ?? (props.hotkey ? `${props.label.replace('­', '')} (${props.hotkey})` : undefined)}
      className={`flex h-[56px] w-[68px] flex-col items-center justify-start gap-1 rounded-sm pt-1 text-xs leading-[13px] disabled:opacity-35 ${props.active ? 'bg-accent-weak text-fg ring-1 ring-accent' : 'text-fg hover:bg-surface-2'}`}
    >
      <span className={props.active ? 'text-accent' : 'text-fg-muted'}>{props.icon}</span>
      <span className="hyphens-manual text-center">{props.label}</span>
    </button>
  )
}

function Small(props: { label: string; hotkey?: string; onClick: () => void }) {
  return (
    <button onClick={props.onClick} title={props.hotkey ? `${props.label} (${props.hotkey})` : undefined} className="h-[18px] rounded-sm px-2 text-left text-xs text-fg hover:bg-surface-2">
      {props.label}
    </button>
  )
}
