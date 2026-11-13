import { useMemo, useRef, useState } from 'react'
import { Html } from '@react-three/drei'
import type { ThreeEvent } from '@react-three/fiber'
import { Quaternion, Vector3 } from 'three'
import { useDoc } from '../store/doc'
import { useColors } from '../lib/colors'
import { getNode, sketchFrame, toWorld } from '../model/project'
import { centroid } from '../model/sketch'

/** Ручка-стрелка выдавливания: перетаскивание вдоль нормали меняет расстояние. */
export function ExtrudeHandle() {
  const c = useColors()
  const mode = useDoc((s) => s.mode)
  const nodes = useDoc((s) => s.project.part.nodes)
  const frames = useDoc((s) => s.kernel.frames)
  const [hot, setHot] = useState(false)
  const drag = useRef<{ base: number; t0: number } | null>(null)

  const params = mode.kind === 'extrude' ? mode.params : null
  const sketch = params ? getNode(nodes, params.sketchId, 'sketch') : undefined
  const geom = useMemo(() => {
    if (!sketch) return null
    const f = sketchFrame(nodes, sketch, frames)
    const origin = new Vector3(...toWorld(f, centroid(sketch)))
    return { origin, normal: new Vector3(...f.normal) }
  }, [nodes, sketch, frames])

  if (!params || !geom || params.extent === 'throughAll') return null
  const sign = params.direction === 'reverse' ? -1 : 1
  const reach = params.direction === 'symmetric' ? params.distance / 2 : params.distance
  const dir = geom.normal.clone().multiplyScalar(sign)
  const tip = geom.origin.clone().addScaledVector(dir, reach)
  const quat = new Quaternion().setFromUnitVectors(new Vector3(0, 1, 0), dir)
  const color = hot || drag.current ? c.selection : c.accent

  /** Параметр ближайшей точки оси выдавливания к лучу курсора. */
  const axisParam = (e: ThreeEvent<PointerEvent>) => {
    const r = e.ray.direction, w0 = geom.origin.clone().sub(e.ray.origin)
    const b = dir.dot(r), d = dir.dot(w0), ee = r.dot(w0)
    const den = 1 - b * b
    return den < 1e-6 ? 0 : (b * ee - d) / den
  }

  const onDown = (e: ThreeEvent<PointerEvent>) => {
    if (e.button !== 0) return
    e.stopPropagation()
    ;(e.target as Element).setPointerCapture(e.pointerId)
    drag.current = { base: params.distance, t0: axisParam(e) }
  }
  const onMove = (e: ThreeEvent<PointerEvent>) => {
    if (!drag.current) return
    e.stopPropagation()
    const dt = axisParam(e) - drag.current.t0
    const k = params.direction === 'symmetric' ? 2 : 1
    const step = e.shiftKey ? 0.1 : 1
    const next = Math.max(step, Math.round((drag.current.base + dt * k) / step) * step)
    useDoc.getState().setExtrudeParams({ distance: Number(next.toFixed(3)) })
  }
  const onUp = (e: ThreeEvent<PointerEvent>) => {
    if (!drag.current) return
    ;(e.target as Element).releasePointerCapture(e.pointerId)
    drag.current = null
  }

  const L = 14
  return (
    <group position={tip} quaternion={quat}>
      <group
        onPointerOver={() => setHot(true)}
        onPointerOut={() => setHot(false)}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
      >
        <mesh position={[0, L / 2, 0]}>
          <cylinderGeometry args={[0.9, 0.9, L, 12]} />
          <meshBasicMaterial color={color} depthTest={false} />
        </mesh>
        <mesh position={[0, L + 3, 0]}>
          <coneGeometry args={[3, 7, 20]} />
          <meshBasicMaterial color={color} depthTest={false} />
        </mesh>
        <mesh position={[0, L / 2 + 2, 0]} visible={false}>
          <cylinderGeometry args={[5, 5, L + 8, 8]} />
        </mesh>
      </group>
      <Html position={[0, L + 10, 0]} center style={{ pointerEvents: 'none' }} zIndexRange={[20, 0]}>
        <div className="num whitespace-nowrap rounded-sm bg-surface px-1.5 py-0.5 text-xs text-fg shadow-[var(--shadow-pop)]">
          {params.distance} мм
        </div>
      </Html>
    </group>
  )
}
