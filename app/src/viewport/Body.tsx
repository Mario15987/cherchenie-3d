import { useEffect, useMemo, useState } from 'react'
import type { ThreeEvent } from '@react-three/fiber'
import { BufferAttribute, BufferGeometry } from 'three'
import { useDoc } from '../store/doc'
import { useColors } from '../lib/colors'
import type { MeshData } from '../kernel/protocol'

function useGeometries(mesh: MeshData | null) {
  const geo = useMemo(() => {
    if (!mesh) return null
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(mesh.position, 3))
    g.setAttribute('normal', new BufferAttribute(mesh.normal, 3))
    g.setIndex(new BufferAttribute(mesh.index, 1))
    const e = new BufferGeometry()
    e.setAttribute('position', new BufferAttribute(mesh.edges, 3))
    return { g, e }
  }, [mesh])
  useEffect(() => () => { geo?.g.dispose(); geo?.e.dispose() }, [geo])
  return geo
}

/** Номер грани по номеру треугольника и номер ребра по номеру вершины отрезка. */
function groupAt(groups: Uint32Array, at: number): number | null {
  for (let i = 0; i < groups.length; i += 3) if (at >= groups[i] && at < groups[i] + groups[i + 1]) return groups[i + 2]
  return null
}
function groupRange(groups: Uint32Array, id: number): [number, number] | null {
  for (let i = 0; i < groups.length; i += 3) if (groups[i + 2] === id) return [groups[i], groups[i + 1]]
  return null
}

/** Подсветка одной грани: те же вершины, часть индексов. */
function FaceOverlay({ mesh, faceId, color, opacity }: { mesh: MeshData; faceId: number; color: string; opacity: number }) {
  const geo = useMemo(() => {
    const r = groupRange(mesh.faceGroups, faceId)
    if (!r) return null
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(mesh.position, 3))
    g.setIndex(new BufferAttribute(mesh.index.slice(r[0], r[0] + r[1]), 1))
    return g
  }, [mesh, faceId])
  useEffect(() => () => geo?.dispose(), [geo])
  if (!geo) return null
  return (
    <mesh geometry={geo} renderOrder={2}>
      <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} polygonOffset polygonOffsetFactor={-2} polygonOffsetUnits={-2} />
    </mesh>
  )
}

function EdgeOverlay({ positions, color, width = 3 }: { positions: Float32Array; color: string; width?: number }) {
  const geo = useMemo(() => {
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(positions, 3))
    return g
  }, [positions])
  useEffect(() => () => geo.dispose(), [geo])
  return (
    <lineSegments geometry={geo} renderOrder={5}>
      <lineBasicMaterial color={color} linewidth={width} depthTest={false} />
    </lineSegments>
  )
}

/** Результирующее тело детали. В модели — выбор граней, в скруглении/фаске — выбор рёбер. */
export function Body() {
  const c = useColors()
  const body = useDoc((s) => s.kernel.body)
  const mode = useDoc((s) => s.mode)
  const selection = useDoc((s) => s.selection)
  const geo = useGeometries(body)
  const [hoverFace, setHoverFace] = useState<number | null>(null)
  const [hoverEdge, setHoverEdge] = useState<number | null>(null)
  const dim = mode.kind === 'sketch'
  const picking = mode.kind === 'model' ? 'face' : mode.kind === 'edgeop' ? 'edge' : null
  useEffect(() => { setHoverFace(null); setHoverEdge(null) }, [body, picking])

  const hoverEdgePositions = useMemo(() => {
    if (!body || hoverEdge === null) return null
    const r = groupRange(body.edgeGroups, hoverEdge)
    return r ? body.edges.slice(r[0] * 3, (r[0] + r[1]) * 3) : null
  }, [body, hoverEdge])

  if (!geo || !body) return null

  const faceOf = (e: ThreeEvent<PointerEvent | MouseEvent>) => (e.faceIndex === undefined || e.faceIndex === null ? null : groupAt(body.faceGroups, e.faceIndex * 3))
  const edgeOf = (e: ThreeEvent<PointerEvent | MouseEvent>) => (e.index === undefined ? null : groupAt(body.edgeGroups, e.index))

  return (
    <group>
      <mesh
        geometry={geo.g}
        onPointerMove={picking === 'face' ? (e) => { e.stopPropagation(); setHoverFace(faceOf(e)) } : undefined}
        onPointerOut={() => setHoverFace(null)}
        onClick={picking === 'face' ? (e) => {
          if (e.button !== 0 || e.delta > 4) return
          e.stopPropagation()
          const f = faceOf(e)
          if (f !== null) useDoc.getState().pickFace(f)
        } : undefined}
      >
        <meshStandardMaterial color={c.body} metalness={0.15} roughness={0.55} polygonOffset polygonOffsetFactor={1} polygonOffsetUnits={1} transparent={dim} opacity={dim ? 0.2 : 1} depthWrite={!dim} />
      </mesh>
      <lineSegments
        geometry={geo.e}
        onPointerMove={picking === 'edge' ? (e) => { e.stopPropagation(); setHoverEdge(edgeOf(e)) } : undefined}
        onPointerOut={() => setHoverEdge(null)}
        onClick={picking === 'edge' ? (e) => {
          if (e.button !== 0 || e.delta > 4) return
          e.stopPropagation()
          const id = edgeOf(e)
          if (id !== null) useDoc.getState().toggleEdge(id)
        } : undefined}
      >
        <lineBasicMaterial color={c.edge} transparent={dim} opacity={dim ? 0.5 : 1} />
      </lineSegments>
      {picking === 'face' && hoverFace !== null && <FaceOverlay mesh={body} faceId={hoverFace} color={c.hover} opacity={0.25} />}
      {selection?.kind === 'face' && <FaceOverlay mesh={body} faceId={selection.faceId} color={c.selection} opacity={0.4} />}
      {hoverEdgePositions && <EdgeOverlay positions={hoverEdgePositions} color={c.hover} />}
    </group>
  )
}

/** Фантом операции: зелёный — добавление объёма, красный — вычитание, синий — скругление/фаска. */
export function Preview() {
  const c = useColors()
  const preview = useDoc((s) => s.kernel.preview)
  const edges = useDoc((s) => s.kernel.previewEdges)
  const mode = useDoc((s) => s.mode)
  const kind = mode.kind === 'extrude' ? mode.params.op : mode.kind === 'edgeop' ? 'edge' : null
  const geo = useGeometries(kind ? preview : null)
  if (!kind) return null
  const color = kind === 'add' ? c['preview-add'] : kind === 'cut' ? c['preview-cut'] : c.accent
  return (
    <group renderOrder={3}>
      {geo && (
        <>
          <mesh geometry={geo.g}>
            <meshStandardMaterial color={color} transparent opacity={kind === 'edge' ? 0.55 : 0.38} depthWrite={false} />
          </mesh>
          <lineSegments geometry={geo.e}>
            <lineBasicMaterial color={color} transparent opacity={0.9} />
          </lineSegments>
        </>
      )}
      {edges && edges.length > 0 && <EdgeOverlay positions={edges} color={c.selection} />}
    </group>
  )
}
