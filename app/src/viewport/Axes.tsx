import { Line } from '@react-three/drei'
import { useColors } from '../lib/colors'

/** Оси начала координат: X красная, Y зелёная, Z синяя. */
export function Axes() {
  const c = useColors()
  const L = 70
  return (
    <group>
      <Line points={[[0, 0, 0], [L, 0, 0]]} color={c['axis-x']} lineWidth={2} />
      <Line points={[[0, 0, 0], [0, L, 0]]} color={c['axis-y']} lineWidth={2} />
      <Line points={[[0, 0, 0], [0, 0, L]]} color={c['axis-z']} lineWidth={2} />
      <mesh>
        <sphereGeometry args={[1, 16, 12]} />
        <meshBasicMaterial color={c.text} />
      </mesh>
    </group>
  )
}
