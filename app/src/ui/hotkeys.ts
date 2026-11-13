import { useEffect } from 'react'
import { useDoc } from '../store/doc'
import { cmdNormalTo, cmdOpenProject, cmdSaveProject, cmdSketch, selectedId } from './actions'

/** Горячие клавиши из replica/design.md. В полях ввода работают только сами поля. */
export function useHotkeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t?.tagName === 'INPUT' || t?.tagName === 'TEXTAREA') return
      const st = useDoc.getState()
      const m = st.mode
      const ctrl = e.ctrlKey || e.metaKey
      const k = e.key.toLowerCase()
      const code = e.code

      if (ctrl && (code === 'KeyZ' || k === 'z') && !e.shiftKey) { e.preventDefault(); st.undo(); return }
      if (ctrl && ((code === 'KeyY' || k === 'y') || ((code === 'KeyZ' || k === 'z') && e.shiftKey))) { e.preventDefault(); st.redo(); return }
      if (ctrl && (code === 'KeyS' || k === 's')) { e.preventDefault(); cmdSaveProject(); return }
      if (ctrl && (code === 'KeyO' || k === 'o')) { e.preventDefault(); cmdOpenProject(); return }
      if (ctrl || e.altKey) return

      if (e.key === 'Escape') {
        e.preventDefault()
        if (m.kind === 'extrude') st.cancelExtrude()
        else if (m.kind === 'edgeop') st.cancelEdgeOp()
        else if (m.kind === 'sketch') { if (m.tool) st.setSketchTool(null); else if (st.sketchSel.length) st.setSketchSel([]); else st.finishSketch() }
        else if (st.workspace === 'drawing') st.setWorkspace('part')
        else st.select(null)
        return
      }
      if (st.workspace === 'drawing') return
      if (e.key === 'Enter') {
        if (m.kind === 'extrude') { e.preventDefault(); st.commitExtrude() }
        else if (m.kind === 'edgeop') { e.preventDefault(); st.commitEdgeOp() }
        else if (m.kind === 'model' && selectedId()) { e.preventDefault(); st.editNode(selectedId()!) }
        return
      }
      if (e.key === ' ') { e.preventDefault(); st.requestCamera({ kind: 'fit' }); return }

      // Буквы по физическим клавишам, чтобы работали и в русской раскладке.
      const letter = code.startsWith('Key') ? code.slice(3) : ''
      if (letter === 'N') { cmdNormalTo(); return }
      if (code === 'Digit0' || code === 'Numpad0') { st.requestCamera({ kind: 'view', view: 'iso' }); return }
      if (code === 'Digit1' || code === 'Numpad1') { st.requestCamera({ kind: 'view', view: 'front' }); return }
      if (code === 'Digit3' || code === 'Numpad3') { st.requestCamera({ kind: 'view', view: 'right' }); return }
      if (code === 'Digit7' || code === 'Numpad7') { st.requestCamera({ kind: 'view', view: 'top' }); return }

      // preventDefault: иначе буква попадёт в поле, которое команда сразу фокусирует.
      if (m.kind === 'sketch') {
        if (letter === 'L') { e.preventDefault(); st.setSketchTool('line') }
        if (letter === 'R') { e.preventDefault(); st.setSketchTool('rect') }
        if (letter === 'C') { e.preventDefault(); st.setSketchTool('circle') }
        if (letter === 'D') { e.preventDefault(); st.addDimension() }
        if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); st.removeSketchItems(st.sketchSel) }
        return
      }
      if (m.kind === 'edgeop') return
      if (m.kind !== 'model') return
      if (letter === 'S') { e.preventDefault(); cmdSketch() }
      if (letter === 'E') { e.preventDefault(); st.startExtrude('add') }
      if (letter === 'X') { e.preventDefault(); st.startExtrude('cut') }
      if (letter === 'F') { e.preventDefault(); st.startEdgeOp('fillet') }
      if (letter === 'H') { e.preventDefault(); st.startEdgeOp('chamfer') }
      if (e.key === 'Delete' && selectedId()) st.deleteNode(selectedId()!)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
