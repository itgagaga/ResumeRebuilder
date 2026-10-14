import { useEffect, useRef, useState } from 'react'
import { ImagePlus } from 'lucide-react'
import { assetUrl } from './api'
import { createElement, type Element, type Page, type Project, type Tool } from './types'
import TextContent from './TextContent'
import InlineTextEditor from './InlineTextEditor'
import { layoutText } from './textEditing'

type Point = { x: number; y: number }
type Drag = { start: Point; kind: 'move' | 'resize' | 'draw'; element?: Element; handle?: string; original: Project }
interface Props {
  project: Project; page: Page; pageIndex: number; zoom: number; tool: Tool; selected: string | null;
  setSelected: (id: string | null) => void; change: (p: Project, record?: boolean, original?: Project) => void;
  setTool: (t: Tool) => void; setOverflow: (ids: string[]) => void
  editRequest?: { id: string; nonce: number } | null; undo: () => void; redo: () => void
}

export function ElementView({ element: e, projectId, editing = false }: { element: Element; projectId: string; editing?: boolean }) {
  if (e.type === 'image_placeholder') {
    return e.assetId ? <img draggable={false} alt="用户上传的图片" src={assetUrl(projectId, e.assetId)} style={{ width: '100%', height: '100%', display: 'block', objectFit: e.fit, objectPosition: `${50+e.crop.offsetX/2}% ${50+e.crop.offsetY/2}%`, transform: `translate(${e.crop.offsetX/2}%,${e.crop.offsetY/2}%) scale(${e.crop.scale})` }} /> : editing ? <div className="photo-empty"><ImagePlus size={Math.min(24, e.height/3)} /><span>上传图片</span></div> : null
  }
  return e.type === 'text' ? <span className="text-content" data-text-id={e.id} style={{ display: 'block', width: `${100/e.style.fontScaleX}%`, height: '100%', transform: `scaleX(${e.style.fontScaleX})`, transformOrigin: 'left top' }}><TextContent element={e}/></span> : null
}

export function elementStyle(e: Element): React.CSSProperties {
  return { position: 'absolute', left: e.x, top: e.y, width: e.width, height: e.height, zIndex: e.zIndex,
    transform: `rotate(${e.rotation}deg)`, transformOrigin: e.type === 'line' ? 'left top' : 'center',
    fontFamily: e.style.fontFamily, fontSize: e.style.fontSize, fontWeight: e.style.fontWeight, fontStyle: e.style.fontStyle,
    color: e.style.color, background: e.style.background, lineHeight: e.style.lineHeight, textAlign: e.style.textAlign,
    border: `${e.style.borderWidth}px solid ${e.style.borderColor}`,
    borderRadius: e.shape === 'circle' ? '50%' : e.shape === 'rounded' ? e.style.borderRadius || 10 : e.style.borderRadius,
    overflow: e.type === 'image_placeholder' ? 'hidden' : 'visible', whiteSpace: 'pre-wrap', overflowWrap: 'break-word', boxSizing: 'border-box' }
}

export default function Canvas({ project, page, pageIndex, zoom, tool, selected, setSelected, change, setTool, setOverflow, editRequest, undo, redo }: Props) {
  const root = useRef<HTMLDivElement>(null)
  const drag = useRef<Drag | null>(null)
  const [drawing, setDrawing] = useState<{ x: number; y: number; width: number; height: number } | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [overflowIds, setOverflowIds] = useState<string[]>([])
  const scale = zoom * (page.unit === 'pt' ? 96/72 : 1)
  const point = (event: React.PointerEvent): Point => { const rect = root.current!.getBoundingClientRect(); return { x: (event.clientX-rect.left)/scale, y: (event.clientY-rect.top)/scale } }
  const updateElement = (updated: Element, record = true, original?: Project) => {
    const previous = page.elements.find(e => e.id === updated.id)
    const result = structuredClone(project)
    if (updated.type === 'text' && (previous?.text !== updated.text || JSON.stringify(previous?.textRuns) !== JSON.stringify(updated.textRuns))) result.pages[pageIndex] = layoutText(result.pages[pageIndex],updated)
    else result.pages[pageIndex].elements = result.pages[pageIndex].elements.map(e => e.id === updated.id ? updated : e)
    change(result, record, original)
  }
  useEffect(() => {
    const check = () => {
      const ids = Array.from(root.current?.querySelectorAll<HTMLElement>('[data-text-id]') || [])
        .filter(el => el.scrollHeight > el.clientHeight+2 || el.scrollWidth > el.clientWidth+2).map(el => el.dataset.textId!)
      setOverflowIds(ids); setOverflow(ids)
    }
    const timer = setTimeout(check, 80)
    document.fonts.ready.then(check)
    return () => clearTimeout(timer)
  }, [page, setOverflow])
  useEffect(() => { setEditing(null) }, [page.id, selected])
  useEffect(() => { if (editRequest && page.elements.some(e => e.id === editRequest.id && e.type === 'text')) setEditing(editRequest.id) }, [editRequest?.nonce])

  function start(event: React.PointerEvent, element?: Element, handle?: string) {
    if (event.button !== 0 || editing) return
    event.stopPropagation()
    if (tool !== 'select' && !handle) {
      drag.current = { start: point(event), kind: 'draw', original: structuredClone(project) }
      setSelected(null)
    } else if (element) {
      setSelected(element.id)
      drag.current = { start: point(event), kind: handle ? 'resize' : 'move', element: structuredClone(element), handle, original: structuredClone(project) }
    } else { setSelected(null); return }
    root.current!.setPointerCapture(event.pointerId)
  }
  function move(event: React.PointerEvent) {
    const d = drag.current
    if (!d) return
    const p = point(event), dx = p.x-d.start.x, dy = p.y-d.start.y
    if (d.kind === 'draw') { setDrawing({ x: Math.min(d.start.x, p.x), y: Math.min(d.start.y, p.y), width: Math.abs(dx), height: Math.abs(dy) }); return }
    const e = { ...d.element! }
    if (d.kind === 'move') { e.x = Math.round((e.x+dx)*10)/10; e.y = Math.round((e.y+dy)*10)/10 }
    else {
      if (e.type === 'text') e.textLayout = 'wrap'
      if (d.handle!.includes('e')) e.width = Math.max(4, e.width+dx)
      if (d.handle!.includes('s')) e.height = Math.max(1, e.height+dy)
      if (d.handle!.includes('w')) { e.width = Math.max(4, e.width-dx); e.x += d.element!.width-e.width }
      if (d.handle!.includes('n')) { e.height = Math.max(1, e.height-dy); e.y += d.element!.height-e.height }
    }
    updateElement(e, false)
  }
  function end(event: React.PointerEvent) {
    const d = drag.current
    if (!d) return
    if (d.kind === 'draw' && tool !== 'select') {
      const p = point(event), width = Math.abs(p.x-d.start.x), height = Math.abs(p.y-d.start.y)
      const e = createElement(tool, Math.min(p.x, d.start.x), Math.min(p.y, d.start.y), width > 4 ? width : tool === 'image_placeholder' ? 80 : 180, tool === 'line' ? 1.5 : height > 4 ? height : tool === 'image_placeholder' ? 80 : 28)
      const next = structuredClone(project); e.zIndex = Math.max(1, ...page.elements.map(e => e.zIndex))+1
      next.pages[pageIndex].elements.push(e); change(next, true, d.original); setSelected(e.id); setTool('select')
    } else if (JSON.stringify(project) !== JSON.stringify(d.original)) change(project, true, d.original)
    drag.current = null; setDrawing(null)
    if (root.current?.hasPointerCapture(event.pointerId)) root.current.releasePointerCapture(event.pointerId)
  }
  const active = page.elements.find(e => e.id === selected)
  return <div className="paper-wrap" style={{ width: page.width*scale, height: page.height*scale }}>
    <div ref={root} className={`paper tool-${tool}`} style={{ width: page.width, height: page.height, background: page.background, transform: `scale(${scale})` }} onDoubleClick={() => { if (active?.type === 'text' && tool === 'select') setEditing(active.id) }} onPointerDown={e => start(e)} onPointerMove={move} onPointerUp={end} onPointerCancel={e => { if (drag.current) change(drag.current.original, false); drag.current = null; setDrawing(null); if (root.current?.hasPointerCapture(e.pointerId)) root.current.releasePointerCapture(e.pointerId) }}>
      {page.elements.map(e => <div key={e.id} data-element-id={e.id} className={`element ${selected === e.id ? 'is-selected' : ''} ${overflowIds.includes(e.id) ? 'is-overflow' : ''}`}
        style={elementStyle(e)} onPointerDown={event => start(event, e)} onDoubleClick={event => { if (e.type === 'text') { event.stopPropagation(); setSelected(e.id); setEditing(e.id) } }}>
        {editing === e.id ? <InlineTextEditor element={e} onChange={updateElement} onFinish={() => setEditing(null)} undo={undo} redo={redo}/> : <ElementView element={e} projectId={project.projectId} editing />}
      </div>)}
      {active && !editing && <div className="selection-box" style={{ position: 'absolute', left: active.x, top: active.y, width: active.width, height: active.height, transform: `rotate(${active.rotation}deg)`, transformOrigin: active.type === 'line' ? 'left top' : 'center', zIndex: 10001 }}>
        <span className="size-label">{Math.round(active.width)} × {Math.round(active.height)}</span>
        {['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'].map(handle => <button key={handle} className={`handle ${handle}`} aria-label={`调整尺寸 ${handle}`} onPointerDown={event => start(event, active, handle)} />)}
      </div>}
      {drawing && <div className="draw-region" style={{ ...drawing, position: 'absolute', zIndex: 10002 }} />}
      {active && editing === active.id && <div className="editing-caption" style={{ left: active.x, top: Math.max(0,active.y-19) }}>直接输入 · 点击空白处完成</div>}
    </div>
  </div>
}
