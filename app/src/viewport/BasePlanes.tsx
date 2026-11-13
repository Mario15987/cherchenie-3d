import { useMemo } from 'react'
import { Html, Line } from '@react-three/drei'
import { DoubleSide } from 'three'
import { useDoc } from '../store/doc'
import { useColors } from '../lib/colors'
import { PLANE_FRAMES } from '../model/project'
import type { PlaneNode } from '../model/types'
import { frameMatrix } from './frame'

const S = 50 // половина стороны квадрата плоскости, мм

/** Базовые плоскости XY, ZX, ZY: выбор кликом, двойной клик — сразу эскиз. */
export function BasePlanes() {
  const nodes = useDoc((s) => s.project.part.nodes)
  const mode = useDoc((s) => s.mode)
  const planes = nodes.filter((n): n is PlaneNode => n.type === 'plane' && !n.hidden)
  if (mode.kind !== 'model' && mode.kind !== 'extrude') return null
  return (
    <>
      {planes.map((p) => <PlaneQuad key={p.id} plane={p} />)}
    </>
  )
}

function PlaneQuad({ plane }: { plane: PlaneNode }) {
  const c = useColors()
  const selected = useDoc((s) => s.selection?.kind === 'node' && s.selection.id === plane.id)
  const hovered = useDoc((s) => s.hover === plane.id)
  const { select, setHover, startSketch } = useDoc.getState()
  const matrix = useMemo(() => frameMatrix(PLANE_FRAMES[plane.key]), [plane.key])
  const color = selected ? c.selection : hovered ? c.hover : c.plane
  const outline: [number, number, number][] = [[-S, -S, 0], [S, -S, 0], [S, S, 0], [-S, S, 0], [-S, -S, 0]]

  return (
    <group matrix={matrix} matrixAutoUpdate={false}>
      <mesh
        onPointerOver={(e) => { e.stopPropagation(); setHover(plane.id) }}
        onPointerOut={() => setHover(null)}
        onClick={(e) => { if (e.delta > 4 || e.button !== 0) return; e.stopPropagation(); select({ kind: 'node', id: plane.id }) }}
        onDoubleClick={(e) => { e.stopPropagation(); startSketch(plane.id) }}
      >
        <planeGeometry args={[S * 2, S * 2]} />
        <meshBasicMaterial color={color} transparent opacity={selected ? 0.18 : hovered ? 0.14 : 0.06} side={DoubleSide} depthWrite={false} />
      </mesh>
      <Line points={outline} color={color} lineWidth={selected || hovered ? 1.6 : 1} transparent opacity={selected || hovered ? 0.95 : 0.45} />
      <Html position={[-S, S, 0]} style={{ pointerEvents: 'none' }} zIndexRange={[10, 0]}>
        <span className="num whitespace-nowrap pl-1 text-xs" style={{ color }}>{plane.key}</span>
      </Html>
    </group>
  )
}
