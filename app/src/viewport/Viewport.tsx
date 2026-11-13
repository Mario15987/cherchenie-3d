import { Canvas } from '@react-three/fiber'
import { GizmoHelper, GizmoViewcube, GizmoViewport, Grid, OrbitControls } from '@react-three/drei'
import { MOUSE } from 'three'
import { useDoc } from '../store/doc'
import { useColors } from '../lib/colors'
import { CameraRig } from './CameraRig'
import { BasePlanes } from './BasePlanes'
import { Body, Preview } from './Body'
import { ExtrudeHandle } from './ExtrudeHandle'
import { SketchEditor, SketchesDisplay } from './Sketch'
import { Axes } from './Axes'

export function Viewport() {
  const c = useColors()
  const mode = useDoc((s) => s.mode)
  const select = useDoc((s) => s.select)

  return (
    <div className="relative h-full w-full" style={{ background: `linear-gradient(${c['viewport-top']}, ${c['viewport-bottom']})` }}>
      <Canvas
        camera={{ fov: 35, near: 0.5, far: 50000, position: [260, 210, 320] }}
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true }}
        raycaster={{ params: { Line: { threshold: 1.2 }, Points: { threshold: 1 }, Mesh: {}, LOD: {}, Sprite: {} } }}
        onPointerMissed={(e) => { if (e.button === 0 && mode.kind === 'model') select(null) }}
        onContextMenu={(e) => e.preventDefault()}
      >
        <ambientLight intensity={0.55} />
        <hemisphereLight args={['#ffffff', '#445566', 0.6]} />
        <directionalLight position={[300, 500, 400]} intensity={1.1} />
        <directionalLight position={[-400, -200, -300]} intensity={0.35} />

        <Grid
          infiniteGrid
          cellSize={10}
          sectionSize={100}
          cellColor={c['grid-minor']}
          sectionColor={c['grid-major']}
          cellThickness={0.6}
          sectionThickness={1}
          fadeDistance={3000}
          fadeStrength={1.5}
          visible={mode.kind !== 'sketch'}
        />
        <Axes />
        <BasePlanes />
        <Body />
        <Preview />
        <SketchesDisplay />
        {mode.kind === 'sketch' && <SketchEditor key={mode.nodeId} />}
        {mode.kind === 'extrude' && <ExtrudeHandle />}

        <OrbitControls
          makeDefault
          enableDamping={false}
          zoomToCursor
          mouseButtons={{ LEFT: undefined as unknown as MOUSE, MIDDLE: MOUSE.PAN, RIGHT: MOUSE.ROTATE }}
        />
        <CameraRig />

        <GizmoHelper alignment="top-right" margin={[72, 72]}>
          <GizmoViewcube
            faces={['Справа', 'Слева', 'Сверху', 'Снизу', 'Спереди', 'Сзади']}
            color={c.body}
            hoverColor={c.accent}
            textColor={c['viewport-bottom']}
            strokeColor={c.edge}
            opacity={0.95}
            font="bold 17px Inter, Segoe UI, sans-serif"
          />
        </GizmoHelper>
        {/* Второй HUD рисуется после первого, иначе он перекрывает видовой куб. */}
        <GizmoHelper alignment="bottom-right" margin={[56, 56]} renderPriority={2}>
          <GizmoViewport axisColors={[c['axis-x'], c['axis-y'], c['axis-z']]} labelColor={c['viewport-bottom']} disabled scale={30} />
        </GizmoHelper>
      </Canvas>
      <ModeBadge />
    </div>
  )
}

function ModeBadge() {
  const mode = useDoc((s) => s.mode)
  const nodes = useDoc((s) => s.project.part.nodes)
  if (mode.kind === 'model') return null
  const name = mode.kind === 'sketch'
    ? nodes.find((n) => n.id === mode.nodeId)?.name
    : mode.kind === 'edgeop' ? (mode.params.op === 'fillet' ? 'Скругление' : 'Фаска')
    : mode.params.op === 'add' ? 'Выдавливание' : 'Вырез'
  return (
    <div className="pointer-events-none absolute left-3 top-3 rounded-md bg-accent-weak px-2 py-1 text-xs font-semibold text-fg">
      {mode.kind === 'sketch' ? `Режим эскиза · ${name}` : `Операция · ${name}`}
    </div>
  )
}
