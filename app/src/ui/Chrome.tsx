import { useEffect, useRef, useState } from 'react'
import { ChevronDown, CircleAlert, CircleCheck, FilePlus, FolderOpen, Home, LoaderCircle, Moon, Redo2, Save, Sun, Undo2 } from 'lucide-react'
import { useDoc } from '../store/doc'
import { cmdExport, cmdExportDrawingDxf, cmdExportDxf, cmdNewProject, cmdOpenProject, cmdSaveProject } from './actions'

/** Заголовок: имя проекта, статус сохранения, отмена/повтор, файл, тема. */
export function TitleBar() {
  const name = useDoc((s) => s.project.name)
  const savedAt = useDoc((s) => s.savedAt)
  const canUndo = useDoc((s) => s.past.length > 0 && s.mode.kind === 'model')
  const canRedo = useDoc((s) => s.future.length > 0 && s.mode.kind === 'model')
  const theme = useDoc((s) => s.theme)
  const { undo, redo, setTheme } = useDoc.getState()

  return (
    <header className="flex h-8 shrink-0 items-center gap-2 border-b border-line bg-bg px-2">
      <span className="flex items-center gap-1.5 pr-2 text-sm font-semibold tracking-tight">
        <span className="inline-block h-3.5 w-3.5 rotate-45 rounded-[2px] border-2 border-accent" aria-hidden />
        ReCAD
      </span>
      <FileMenu />
      <div className="mx-1 h-4 w-px bg-line" />
      <IconBtn title="Отменить (Ctrl+Z)" disabled={!canUndo} onClick={undo}><Undo2 size={15} /></IconBtn>
      <IconBtn title="Повторить (Ctrl+Y)" disabled={!canRedo} onClick={redo}><Redo2 size={15} /></IconBtn>
      <div className="flex-1 truncate text-center text-sm text-fg-muted">
        <ProjectName name={name} />
      </div>
      <span className="text-xs text-fg-faint" title="Проект автоматически сохраняется в этом браузере">
        {savedAt ? `Сохранено локально в ${new Date(savedAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}` : 'Не сохранено'}
      </span>
      <IconBtn title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
        {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
      </IconBtn>
    </header>
  )
}

function ProjectName({ name }: { name: string }) {
  const [edit, setEdit] = useState<string | null>(null)
  if (edit === null) return <button className="rounded-sm px-1 hover:bg-surface-2" title="Переименовать" onClick={() => setEdit(name)}>{name}</button>
  const apply = () => {
    const v = edit.trim()
    if (v) useDoc.setState((s) => ({ project: { ...s.project, name: v, updatedAt: new Date().toISOString() } }))
    setEdit(null)
  }
  return (
    <input autoFocus value={edit} onChange={(e) => setEdit(e.target.value)} onBlur={apply}
      onKeyDown={(e) => { if (e.key === 'Enter') apply(); if (e.key === 'Escape') setEdit(null) }}
      className="h-6 w-56 rounded-sm border border-accent bg-bg px-1 text-center text-sm text-fg outline-none" />
  )
}

function FileMenu() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const hasBody = useDoc((s) => !!s.kernel.body)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open])
  const item = (label: string, run: () => void, opts: { hotkey?: string; disabled?: boolean; icon?: React.ReactNode } = {}) => (
    <button role="menuitem" disabled={opts.disabled} onClick={() => { setOpen(false); run() }}
      className="flex w-full items-center gap-2 px-3 py-1 text-left text-sm hover:bg-surface-2 disabled:opacity-40">
      <span className="w-4 text-fg-muted">{opts.icon}</span>
      <span className="flex-1">{label}</span>
      {opts.hotkey && <span className="text-xs text-fg-faint">{opts.hotkey}</span>}
    </button>
  )
  return (
    <div ref={ref} className="relative">
      <button aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} className="flex h-6 items-center gap-1 rounded-sm px-2 text-sm hover:bg-surface-2">
        Файл <ChevronDown size={13} />
      </button>
      {open && (
        <div role="menu" className="absolute left-0 top-7 z-50 w-64 rounded-md border border-line bg-surface py-1 shadow-[var(--shadow-pop)]">
          {item('Стартовый экран', () => useDoc.getState().setStartOpen(true), { icon: <Home size={14} /> })}
          {item('Новая деталь', cmdNewProject, { icon: <FilePlus size={14} /> })}
          {item('Открыть проект…', cmdOpenProject, { icon: <FolderOpen size={14} />, hotkey: 'Ctrl+O' })}
          {item('Сохранить проект…', cmdSaveProject, { icon: <Save size={14} />, hotkey: 'Ctrl+S' })}
          <div className="my-1 h-px bg-line" />
          {item('Экспорт STL', () => cmdExport('stl'), { disabled: !hasBody })}
          {item('Экспорт STEP', () => cmdExport('step'), { disabled: !hasBody })}
          {item('Экспорт эскиза в DXF', cmdExportDxf)}
          {item('Экспорт чертежа в DXF', cmdExportDrawingDxf)}
        </div>
      )}
    </div>
  )
}

function IconBtn({ title, onClick, disabled, children }: { title: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button title={title} aria-label={title} onClick={onClick} disabled={disabled}
      className="flex h-6 w-6 items-center justify-center rounded-sm text-fg-muted hover:bg-surface-2 hover:text-fg disabled:opacity-35">
      {children}
    </button>
  )
}

/** Строка состояния: подсказка команды, координаты курсора в эскизе, статус ядра. */
export function StatusBar() {
  const hint = useDoc((s) => s.hint)
  const cursor = useDoc((s) => s.cursor)
  const k = useDoc((s) => s.kernel)
  const fmt = (v: number) => v.toFixed(2)
  return (
    <footer className="flex h-6 shrink-0 items-center gap-4 border-t border-line bg-surface px-3 text-xs">
      <span className="flex-1 truncate text-fg-muted">{hint}</span>
      <span className="num w-44 text-fg-muted">{cursor ? `X ${fmt(cursor[0])}   Y ${fmt(cursor[1])}` : 'X —   Y —'}</span>
      <span className="flex items-center gap-1.5 text-fg-muted" role="status">
        {k.error ? <><CircleAlert size={13} className="text-danger" /> <span className="text-danger">{k.error}</span></>
          : !k.ready ? <><LoaderCircle size={13} className="animate-spin text-warning" /> Ядро геометрии загружается…</>
          : k.busy ? <><LoaderCircle size={13} className="animate-spin text-accent" /> Перестроение…</>
          : <><CircleCheck size={13} className="text-success" /> Ядро готово{k.lastMs !== null ? ` · ${k.lastMs} мс` : ''}</>}
      </span>
    </footer>
  )
}

export function Toast() {
  const toast = useDoc((s) => s.toast)
  const [visible, setVisible] = useState<typeof toast>(null)
  useEffect(() => {
    if (!toast) return
    setVisible(toast)
    const t = window.setTimeout(() => setVisible(null), toast.kind === 'error' ? 6000 : 3500)
    return () => window.clearTimeout(t)
  }, [toast])
  if (!visible) return null
  return (
    <div role={visible.kind === 'error' ? 'alert' : 'status'}
      className={`pointer-events-auto absolute bottom-3 left-1/2 z-50 flex max-w-lg -translate-x-1/2 items-center gap-2 rounded-md border bg-surface px-3 py-2 text-sm shadow-[var(--shadow-pop)] ${visible.kind === 'error' ? 'border-danger/60 text-danger' : 'border-line text-fg'}`}>
      {visible.kind === 'error' ? <CircleAlert size={15} /> : <CircleCheck size={15} className="text-success" />}
      {visible.text}
      <button className="ml-2 text-fg-faint hover:text-fg" aria-label="Закрыть" onClick={() => setVisible(null)}>×</button>
    </div>
  )
}
