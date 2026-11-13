import { useMemo } from 'react'
import { useDoc } from '../store/doc'

// Цвета сцены берутся из тех же CSS-токенов, что и интерфейс (replica/design/tokens*.json).
const KEYS = [
  'viewport-top', 'viewport-bottom', 'grid-major', 'grid-minor', 'axis-x', 'axis-y', 'axis-z', 'plane', 'body', 'edge',
  'hover', 'selection', 'sketch-free', 'sketch-defined', 'sketch-over', 'sketch-construction', 'preview-add', 'preview-cut',
  'surface', 'surface-2', 'text', 'text-muted', 'accent', 'border',
] as const
export type SceneColors = Record<(typeof KEYS)[number], string>

export function readColors(): SceneColors {
  const cs = getComputedStyle(document.documentElement)
  return Object.fromEntries(KEYS.map((k) => [k, cs.getPropertyValue(`--c-${k}`).trim() || '#888'])) as SceneColors
}

export function useColors(): SceneColors {
  const theme = useDoc((s) => s.theme)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => readColors(), [theme])
}

// Тема применяется синхронно при изменении состояния, до рендера React.
const apply = (t: string) => { document.documentElement.dataset.theme = t }
apply(useDoc.getState().theme)
useDoc.subscribe((s, p) => { if (s.theme !== p.theme) apply(s.theme) })
