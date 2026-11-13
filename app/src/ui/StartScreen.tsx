import { useEffect, useRef } from 'react'
import { Box, FolderOpen, LayoutTemplate, X } from 'lucide-react'
import { useDoc } from '../store/doc'
import { newProject } from '../model/project'
import { cmdOpenProject } from './actions'

/** Стартовый экран (S01): новая деталь, чертёж, открыть файл, недавние проекты этого браузера. */
export function StartScreen() {
  const open = useDoc((s) => s.startOpen)
  const recent = useDoc((s) => s.recent)
  const current = useDoc((s) => s.project.id)
  const { setStartOpen, loadProject, openRecent, setWorkspace } = useDoc.getState()
  const first = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (open) first.current?.focus() }, [open])
  if (!open) return null

  const tile = 'flex flex-1 flex-col items-center gap-2 rounded-lg border border-line bg-surface-2 px-4 py-5 text-sm hover:border-accent hover:bg-accent-weak focus-visible:border-accent'
  return (
    <div role="dialog" aria-modal="true" aria-label="Начало работы" className="absolute inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm"
      onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); setStartOpen(false) } }}>
      <div className="w-[560px] max-w-[calc(100%-32px)] rounded-lg border border-line bg-surface p-5 shadow-[var(--shadow-pop)]">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-lg font-semibold">Начать работу</h1>
          <button aria-label="Закрыть" onClick={() => setStartOpen(false)} className="text-fg-muted hover:text-fg"><X size={16} /></button>
        </div>
        <div className="flex gap-3">
          <button ref={first} className={tile} onClick={() => loadProject(newProject())}><Box size={26} className="text-accent" />Новая деталь</button>
          <button className={tile} onClick={() => { loadProject(newProject()); setWorkspace('drawing') }}><LayoutTemplate size={26} className="text-accent" />Новый чертёж</button>
          <button className={tile} onClick={cmdOpenProject}><FolderOpen size={26} className="text-accent" />Открыть файл…</button>
        </div>
        <h2 className="mb-1 mt-5 text-xs font-semibold uppercase tracking-wide text-fg-faint">Недавние</h2>
        {recent.length === 0 ? (
          <p className="py-3 text-sm text-fg-muted">Здесь появятся ваши проекты. Они сохраняются в этом браузере автоматически.</p>
        ) : (
          <ul className="max-h-60 overflow-auto">
            {recent.map((r) => (
              <li key={r.id}>
                <button onClick={() => (r.id === current ? setStartOpen(false) : openRecent(r.id))} className="flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-left text-sm hover:bg-surface-2">
                  <span className="truncate">{r.name}{r.id === current ? <span className="ml-2 text-xs text-fg-faint">открыт</span> : null}</span>
                  <span className="shrink-0 text-xs text-fg-faint">{new Date(r.updatedAt).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
