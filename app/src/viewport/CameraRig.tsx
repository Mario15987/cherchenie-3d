import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { Box3, PerspectiveCamera, Vector3 } from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import { useDoc, type ViewName } from '../store/doc'

const VIEWS: Record<ViewName, Vector3> = {
  iso: new Vector3(1, 0.82, 1.22).normalize(),
  front: new Vector3(0, 0, 1),
  top: new Vector3(0, 1, 0.0001).normalize(),
  right: new Vector3(1, 0, 0),
}
const DURATION = 350

/** Обрабатывает запросы камеры из стора: стандартные виды, «нормально к», «показать всё». */
export function CameraRig() {
  const camera = useThree((s) => s.camera) as PerspectiveCamera
  const controls = useThree((s) => s.controls) as unknown as OrbitControlsImpl | null
  const request = useDoc((s) => s.camera)
  const anim = useRef<{ t0: number; fromPos: Vector3; toPos: Vector3; fromTarget: Vector3; toTarget: Vector3 } | null>(null)

  useEffect(() => {
    if (!request || !controls) return
    const { body } = useDoc.getState().kernel
    const box = body ? new Box3(new Vector3(...body.bbox.min), new Vector3(...body.bbox.max)) : new Box3(new Vector3(-60, -60, -60), new Vector3(60, 60, 60))
    const center = box.getCenter(new Vector3())
    const radius = Math.max(box.getSize(new Vector3()).length() / 2, 40)
    const fit = (radius / Math.sin((camera.fov * Math.PI) / 360)) * 1.15

    let dir: Vector3
    let target = center
    let dist = fit
    if (request.kind === 'view') dir = VIEWS[request.view].clone()
    else if (request.kind === 'normal') {
      dir = new Vector3(...request.frame.normal)
      if (Math.abs(dir.y) > 0.999) dir.z += 0.0001
      dir.normalize()
      target = new Vector3(...request.frame.origin)
      dist = Math.max(fit, 260)
    } else {
      dir = camera.position.clone().sub(controls.target).normalize()
    }
    anim.current = {
      t0: performance.now(),
      fromPos: camera.position.clone(),
      toPos: target.clone().add(dir.multiplyScalar(dist)),
      fromTarget: controls.target.clone(),
      toTarget: target.clone(),
    }
  }, [request, controls, camera])

  useFrame(() => {
    const a = anim.current
    if (!a || !controls) return
    const k = Math.min(1, (performance.now() - a.t0) / DURATION)
    const e = 1 - Math.pow(1 - k, 3)
    camera.position.lerpVectors(a.fromPos, a.toPos, e)
    controls.target.lerpVectors(a.fromTarget, a.toTarget, e)
    camera.lookAt(controls.target)
    controls.update()
    if (k >= 1) anim.current = null
  })

  return null
}
