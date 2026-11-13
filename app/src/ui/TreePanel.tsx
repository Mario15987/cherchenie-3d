import { useMemo, useState, type ReactNode } from 'react'
import { ArrowDownToLine, ArrowUpFromLine, Box, ChevronDown, ChevronRight, CircleAlert, Eye, EyeOff, Hexagon, PenLine, Square, Squircle, Trash } from 'lucide-react'
import { useDoc } from '../store/doc'
import type { FeatureNode, PlaneNode, SketchNode } from '../model/types'
import { consumedSketches } from '../model/project'

const PLANE_COLOR: Record<PlaneNode['key'], string> = { XY: 'text-axis-z', ZX: 'text-axis-y', ZY: 'text-axis-x' }

/** Дерево построения: начало координат с плоскостями, затем история операций. Эскиз вложен в свою операцию. */
export function TreePanel() {
  const nodes = useDoc((s) => s.project.part.nodes)
  const name = useDoc((s) => s.project.name)
  const [originOpen, setOriginOpen] = useState(true)
  const used = useMemo(() => consumedSketches(nodes), [nodes])
  const planes = nodes.filter((n): n is PlaneNode => n.type === 'plane')
  const history = nodes.filter((n) => n.type !== 'plane' && !(n.type === 'sketch' && used.has(n.id)))

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PanelHeader>Дерево построения</PanelHeader>
      <div role="tree" aria-label="Дерево построения" className="min-h-0 flex-1 overflow-auto py-1">
        <Row depth={0} icon={<Box size={14} className="text-fg-muted" />} label={name} bold />
        <Row depth={1} icon={<Square size={12} className="text-fg-faint" />} label="Начало координат" expanded={originOpen} onToggle={() => setOriginOpen(!originOpen)} />
        {originOpen && planes.map((p) => <NodeRow key={p.id} node={p} depth={2} icon={<Square size={14} className={PLANE_COLOR[p.key]} />} />)}
        {history.map((n) => <HistoryRow key={n.id} node={n} nodes={nodes} />)}
        {history.length === 0 && (
          <p className="px-3 py-3 text-xs text-fg-faint">История пуста. Выберите плоскость и создайте эскиз — операции появятся здесь по порядку.</p>
        )}
      </div>
    </div>
  )
}

function HistoryRow({ node, nodes }: { node: FeatureNode; nodes: FeatureNode[] }) {
  const [open, setOpen] = useState(false)
  if (node.type === 'extrude') {
    const sketch = nodes.find((n): n is SketchNode => n.id === node.sketchId && n.type === 'sketch')
    const icon = node.op === 'add' ? <ArrowUpFromLine size={14} className="text-success" /> : <ArrowDownToLine size={14} className="text-danger" />
    return (
      <>
        <NodeRow node={node} depth={1} icon={icon} expanded={sketch ? open : undefined} onToggle={() => setOpen(!open)} />
        {open && sketch && <NodeRow node={sketch} depth={2} icon={<PenLine size={14} className="text-accent" />} />}
      </>
    )
  }
  if (node.type === 'edgeop') {
    const icon = node.op === 'fillet' ? <Squircle size={14} className="text-accent" /> : <Hexagon size={14} className="text-accent" />
    return <NodeRow node={node} depth={1} icon={icon} />
  }
  return <NodeRow node={node} depth={1} icon={<PenLine size={14} className="text-accent" />} />
}

function NodeRow({ node, depth, icon, expanded, onToggle }: { node: FeatureNode; depth: number; icon: ReactNode; expanded?: boolean; onToggle?: () => void }) {
  const selected = useDoc((s) => s.selection?.kind === 'node' && s.selection.id === node.id)
  const hovered = useDoc((s) => s.hover === node.id)
  const status = useDoc((s) => s.kernel.statuses[node.id])
  const editing = useDoc((s) => (s.mode.kind === 'sketch' && s.mode.nodeId === node.id) || (s.mode.kind === 'extrude' && s.mode.nodeId === node.id))
  const { select, setHover, editNode, deleteNode, toggleHidden } = useDoc.getState()
  const error = status?.status === 'error'
  return (
    <Row
      depth={depth}
      icon={icon}
      label={node.name}
      selected={selected}
      hovered={hovered}
      editing={editing}
      error={error ? status?.error : undefined}
      hidden={node.hidden}
      expanded={expanded}
      onToggle={onToggle}
      onSelect={() => select({ kind: 'node', id: node.id })}
      onEdit={() => editNode(node.id)}
      onHover={(h) => setHover(h ? node.id : null)}
      actions={node.type === 'plane' ? undefined : (
        <>
          <IconBtn title={node.hidden ? 'Показать' : 'Скрыть'} onClick={() => toggleHidden(node.id)}>{node.hidden ? <EyeOff size={13} /> : <Eye size={13} />}</IconBtn>
          <IconBtn title="Удалить (Delete)" onClick={() => deleteNode(node.id)}><Trash size={13} /></IconBtn>
        </>
      )}
    />
  )
}

function Row(p: {
  depth: number; icon: ReactNode; label: string; bold?: boolean; selected?: boolean; hovered?: boolean; editing?: boolean; error?: string; hidden?: boolean
  expanded?: boolean; onToggle?: () => void; onSelect?: () => void; onEdit?: () => void; onHover?: (h: boolean) => void; actions?: ReactNode
}) {
  return (
    <div
      role="treeitem"
      aria-selected={p.selected}
      aria-expanded={p.expanded}
      tabIndex={p.onSelect ? 0 : -1}
      title={p.error}
      onClick={p.onSelect}
      onDoubleClick={p.onEdit}
      onKeyDown={(e) => { if (e.key === 'Enter') p.onEdit?.() }}
      onMouseEnter={() => p.onHover?.(true)}
      onMouseLeave={() => p.onHover?.(false)}
      className={`group relative flex h-[22px] cursor-default items-center gap-1.5 pr-1 text-sm ${p.selected ? 'bg-accent-weak text-fg' : p.hovered ? 'bg-surface-2' : 'hover:bg-surface-2'} ${p.hidden ? 'text-fg-faint' : ''} ${p.error ? 'text-danger' : ''}`}
      style={{ paddingLeft: 6 + p.depth * 12 }}
    >
      {p.editing && <span className="absolute inset-y-0 left-0 w-0.5 bg-accent" />}
      <span className="flex w-3 justify-center" onClick={(e) => { e.stopPropagation(); p.onToggle?.() }}>
        {p.expanded === undefined ? null : p.expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </span>
      {p.icon}
      <span className={`truncate ${p.bold ? 'font-semibold' : ''}`}>{p.label}</span>
      {p.error && <CircleAlert size={13} className="shrink-0 text-danger" />}
      <span className="ml-auto hidden gap-0.5 group-hover:flex">{p.actions}</span>
    </div>
  )
}

function IconBtn({ title, onClick, children }: { title: string; onClick: () => void; children: ReactNode }) {
  return (
    <button title={title} aria-label={title} onClick={(e) => { e.stopPropagation(); onClick() }} className="flex h-[18px] w-[18px] items-center justify-center rounded-sm text-fg-muted hover:bg-surface-3 hover:text-fg">
      {children}
    </button>
  )
}

export function PanelHeader({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex h-7 shrink-0 items-center justify-between border-b border-line px-3 text-xs font-semibold uppercase tracking-wide text-fg-faint">
      <span>{children}</span>
      {right}
    </div>
  )
}

