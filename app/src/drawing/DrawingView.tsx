import { useRef, useState } from 'react'
import { useDoc } from '../store/doc'
import { layout, scaleLabel, titleBlock, toSheet } from './sheet'

/** Лист чертежа (S08): ассоциативные виды модели, рамка, основная надпись. Колесо — масштаб, СКМ/ПКМ — сдвиг. */
export function DrawingView() {
  const project = useDoc((s) => s.project)
  const views = useDoc((s) => s.views)
  const busy = useDoc((s) => s.kernel.busy)
  const [zoom, setZoom] = useState({ k: 1, x: 0, y: 0 })
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null)
  const doc = project.drawing
  if (!doc) return null
  const l = layout(doc, views ?? [])
  const H = l.sheet.h
  const Y = (y: number) => H - y
  const path = (pts: [number, number][]) => 'M' + pts.map((p) => `${p[0].toFixed(3)} ${Y(p[1]).toFixed(3)}`).join('L')

  return (
    <div
      className="relative h-full w-full overflow-hidden bg-surface-3"
      onWheel={(e) => setZoom((z) => ({ ...z, k: Math.min(8, Math.max(0.3, z.k * (e.deltaY < 0 ? 1.1 : 1 / 1.1))) }))}
      onPointerDown={(e) => { if (e.button !== 0) { drag.current = { x: e.clientX, y: e.clientY, ox: zoom.x, oy: zoom.y }; (e.target as Element).setPointerCapture(e.pointerId) } }}
      onPointerMove={(e) => { const d = drag.current; if (d) setZoom((z) => ({ ...z, x: d.ox + e.clientX - d.x, y: d.oy + e.clientY - d.y })) }}
      onPointerUp={() => { drag.current = null }}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="absolute inset-0 flex items-center justify-center p-6" style={{ transform: `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.k})` }}>
        <svg viewBox={`0 0 ${l.sheet.w} ${l.sheet.h}`} className="h-full max-w-full bg-white shadow-[var(--shadow-pop)]" style={{ aspectRatio: `${l.sheet.w} / ${l.sheet.h}` }} role="img" aria-label="Лист чертежа">
          <g fill="none" stroke="#111" strokeLinecap="round" strokeLinejoin="round">
            <rect x={l.frame.x} y={Y(l.frame.y + l.frame.h)} width={l.frame.w} height={l.frame.h} strokeWidth={0.7} />
            {l.views.map((p) => (
              <g key={p.view.kind}>
                {p.view.hidden.map((poly, i) => (
                  <path key={'h' + i} d={path(pairs(poly).map(([x, y]) => toSheet(p, l.scale, x, y)))} strokeWidth={0.3} strokeDasharray="3 1.5" stroke="#444" />
                ))}
                {p.view.visible.map((poly, i) => (
                  <path key={'v' + i} d={path(pairs(poly).map(([x, y]) => toSheet(p, l.scale, x, y)))} strokeWidth={0.6} />
                ))}
              </g>
            ))}
            {titleBlock(l, project).map((c, i) => (
              <g key={i}>
                <rect x={c.x} y={Y(c.y + c.h)} width={c.w} height={c.h} strokeWidth={c.big ? 0.6 : 0.3} />
                {c.label && <text x={c.x + 1} y={Y(c.y + c.h) + 2.6} fontSize={2} fill="#555" stroke="none" fontFamily="Inter, Segoe UI, sans-serif">{c.label}</text>}
                {c.value && (
                  <text x={c.x + c.w / 2} y={Y(c.y + c.h / 2) + (c.big ? 2 : 1.1)} fontSize={c.big ? 5 : 2.6} textAnchor="middle" fill="#111" stroke="none" fontFamily="Inter, Segoe UI, sans-serif">
                    {c.value}
                  </text>
                )}
              </g>
            ))}
          </g>
        </svg>
      </div>
      <div className="pointer-events-none absolute left-3 top-3 flex gap-2 text-xs">
        <span className="rounded-md bg-accent-weak px-2 py-1 font-semibold text-fg">Чертёж · {doc.format} · М {scaleLabel(l.scale)}</span>
        {busy && <span className="rounded-md bg-surface px-2 py-1 text-fg-muted">Обновление видов…</span>}
        {!l.fits && <span className="rounded-md bg-surface px-2 py-1 text-warning">Виды не помещаются в формат — выберите масштаб меньше или A3</span>}
        {views && views.length === 0 && <span className="rounded-md bg-surface px-2 py-1 text-fg-muted">В детали нет тела — виды появятся после первого выдавливания</span>}
      </div>
    </div>
  )
}

function pairs(poly: number[]): [number, number][] {
  const out: [number, number][] = []
  for (let i = 0; i + 1 < poly.length; i += 2) out.push([poly[i], poly[i + 1]])
  return out
}
