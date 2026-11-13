// Команды, общие для ленты, меню и горячих клавиш.
import { useDoc } from '../store/doc'
import { kernel } from '../kernel/client'
import { getNode, isProject, newProject, PLANE_FRAMES, sketchFrame } from '../model/project'
import { sketchToDxf } from '../model/sketch'
import { drawingToDxf } from '../drawing/sheet'
import { openTextFile, saveBlob } from '../lib/files'

const st = () => useDoc.getState()

const safeName = () => (st().project.name || 'Деталь').replace(/[\\/:*?"<>|]+/g, '_')

export function selectedId() {
  const s = st().selection
  return s?.kind === 'node' ? s.id : null
}

export function cmdSketch() {
  if (st().selection?.kind === 'face') return st().startSketchOnFace()
  const id = selectedId()
  const nodes = st().project.part.nodes
  const plane = getNode(nodes, id, 'plane')
  if (plane) return st().startSketch(plane.id)
  const sketch = getNode(nodes, id, 'sketch')
  if (sketch) return st().editSketch(sketch.id)
  st().notify('info', 'Выберите плоскость XY, ZX, ZY или плоскую грань тела')
}

export async function cmdSaveProject() {
  const blob = new Blob([JSON.stringify(st().project, null, 2)], { type: 'application/json' })
  if (await saveBlob(`${safeName()}.recad.json`, blob, 'Проект ReCAD', '.json')) st().notify('info', 'Проект сохранён в файл')
}

export async function cmdOpenProject() {
  const text = await openTextFile('.json')
  if (!text) return
  try {
    const p = JSON.parse(text)
    if (!isProject(p)) throw new Error('не проект ReCAD')
    st().loadProject(p)
    st().notify('info', `Открыт проект «${p.name}»`)
  } catch (e) {
    st().notify('error', `Не удалось открыть файл: ${(e as Error).message}`)
  }
}

export function cmdNewProject() {
  if (st().project.part.nodes.length > 3 && !window.confirm('Начать новую деталь? Текущая будет заменена, в том числе в автосохранении. Сохраните её в файл, если она нужна.')) return
  st().loadProject(newProject())
}

export async function cmdExport(kind: 'stl' | 'step') {
  if (!st().kernel.body) { st().notify('error', 'Нет тела для экспорта: сначала создайте выдавливание'); return }
  const blob = await kernel.exportBody(st().project.part.nodes, kind)
  if (!blob) { st().notify('error', 'Ядро не вернуло тело'); return }
  const ok = kind === 'stl'
    ? await saveBlob(`${safeName()}.stl`, new Blob([blob], { type: 'model/stl' }), 'STL', '.stl')
    : await saveBlob(`${safeName()}.step`, new Blob([blob], { type: 'model/step' }), 'STEP', '.step')
  if (ok) st().notify('info', `Экспорт ${kind.toUpperCase()} готов`)
}

export async function cmdExportDxf() {
  const nodes = st().project.part.nodes
  const m = st().mode
  const id = m.kind === 'sketch' ? m.nodeId : selectedId()
  const direct = getNode(nodes, id, 'sketch')
  const viaOp = getNode(nodes, id, 'extrude')
  const sketch = direct ?? (viaOp ? getNode(nodes, viaOp.sketchId, 'sketch') : undefined)
  if (!sketch) { st().notify('error', 'Выберите эскиз (или операцию с эскизом) для экспорта в DXF'); return }
  const blob = new Blob([sketchToDxf(sketch)], { type: 'application/dxf' })
  if (await saveBlob(`${safeName()} - ${sketch.name.replace(':', '-')}.dxf`, blob, 'DXF', '.dxf')) st().notify('info', `${sketch.name} выгружен в DXF`)
}

export function cmdNormalTo() {
  const m = st().mode
  const sel = st().selection
  const nodes = st().project.part.nodes
  if (sel?.kind === 'face') return st().requestCamera({ kind: 'normal', frame: sel.frame })
  const id = m.kind === 'sketch' ? m.nodeId : selectedId()
  const n = nodes.find((x) => x.id === id)
  if (n?.type === 'plane') st().requestCamera({ kind: 'normal', frame: PLANE_FRAMES[n.key] })
  else if (n?.type === 'sketch') st().requestCamera({ kind: 'normal', frame: sketchFrame(nodes, n, st().kernel.frames) })
  else st().notify('info', 'Выберите плоскость, грань или эскиз')
}

export async function cmdExportDrawingDxf() {
  const { views, project } = st()
  if (!views?.length || !project.drawing) { st().notify('error', 'Чертёж пуст: в детали нет тела'); return }
  const blob = new Blob([drawingToDxf(project, views)], { type: 'application/dxf' })
  if (await saveBlob(`${safeName()} - чертёж.dxf`, blob, 'DXF', '.dxf')) st().notify('info', 'Чертёж выгружен в DXF')
}
