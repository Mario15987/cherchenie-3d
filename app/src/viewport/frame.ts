import { Matrix4, Vector3 } from 'three'
import type { Frame } from '../model/types'

/** Матрица «локальные координаты плоскости → мир». */
export function frameMatrix(f: Frame): Matrix4 {
  return new Matrix4().makeBasis(new Vector3(...f.xDir), new Vector3(...f.yDir), new Vector3(...f.normal)).setPosition(...f.origin)
}
