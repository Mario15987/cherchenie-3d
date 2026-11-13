import * as Comlink from 'comlink'
import type { KernelApi } from './protocol'

const worker = new Worker(new URL('./kernel.worker.ts', import.meta.url), { type: 'module' })
export const kernel = Comlink.wrap<KernelApi>(worker)

// Номера поколений по каналам: устаревшие ответы воркера отбрасываются.
// Превью и перестроение не вытесняют друг друга.
type Channel = 'rebuild' | 'preview'
const gens: Record<Channel, number> = { rebuild: 0, preview: 0 }
export const nextGen = (c: Channel) => ++gens[c]
export const isLatest = (c: Channel, g: number) => g === gens[c]
