import { useRef, useState } from 'react'
import { Viewport } from './viewport/Viewport'
import { Ribbon } from './ui/Ribbon'
import { TreePanel } from './ui/TreePanel'
import { ParamsPanel } from './ui/ParamsPanel'
import { StatusBar, TitleBar, Toast } from './ui/Chrome'
import { useHotkeys } from './ui/hotkeys'
import { StartScreen } from './ui/StartScreen'
import { DrawingView } from './drawing/DrawingView'
import { useDoc } from './store/doc'

export function App() {
  useHotkeys()
  const workspace = useDoc((s) => s.workspace)
  const [width, setWidth] = useState(300)
  const [split, setSplit] = useState(0.48)
  const left = useRef<HTMLDivElement>(null)

  const drag = (kind: 'width' | 'split') => (e: React.PointerEvent) => {
    e.preventDefault()
    const move = (ev: PointerEvent) => {
      if (kind === 'width') setWidth(Math.min(420, Math.max(240, ev.clientX)))
      else if (left.current) {
        const r = left.current.getBoundingClientRect()
        setSplit(Math.min(0.8, Math.max(0.2, (ev.clientY - r.top) / r.height)))
      }
    }
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return (
    <div className="relative flex h-full flex-col">
      <TitleBar />
      <Ribbon />
      <div className="relative flex min-h-0 flex-1">
        <aside ref={left} className="flex min-h-0 shrink-0 flex-col border-r border-line bg-surface" style={{ width }}>
          <div className="min-h-0" style={{ flex: `${split} 1 0` }}><TreePanel /></div>
          <div role="separator" aria-orientation="horizontal" onPointerDown={drag('split')} className="h-1 shrink-0 cursor-row-resize border-y border-line bg-surface-2 hover:bg-accent/40" />
          <div className="min-h-0 overflow-hidden" style={{ flex: `${1 - split} 1 0` }}><ParamsPanel /></div>
        </aside>
        <div role="separator" aria-orientation="vertical" onPointerDown={drag('width')} className="w-1 shrink-0 cursor-col-resize hover:bg-accent/40" />
        <main className="relative min-w-0 flex-1">
          {workspace === 'drawing' ? <DrawingView /> : <Viewport />}
          <Toast />
        </main>
      </div>
      <StatusBar />
      <StartScreen />
    </div>
  )
}
