import { useRef, useState } from 'react'
import { ScanLine } from 'lucide-react'
import { createElement, type Project } from './types'

export default function SourcePreview({ project, pageIndex, zoom, drawingMode, circle, add }: { project: Project; pageIndex: number; zoom: number; drawingMode: boolean; circle: boolean; add: (p: Project, selected: string) => void }) {
  const page = project.pages[pageIndex], scale = zoom * (page.unit === 'pt' ? 96/72 : 1)
  const root = useRef<HTMLDivElement>(null)
  const start = useRef<{ x: number; y: number } | null>(null)
  const [region, setRegion] = useState<{ x: number; y: number; width: number; height: number } | null>(null)
  const point = (e: React.PointerEvent) => { const box = root.current!.getBoundingClientRect(); return { x: Math.max(0, Math.min(page.width, (e.clientX-box.left)/scale)), y: Math.max(0, Math.min(page.height, (e.clientY-box.top)/scale)) } }
  return <div className={`source-paper ${drawingMode ? 'is-drawing' : ''}`} ref={root} style={{ width: page.width*scale, height: page.height*scale }} onPointerDown={event => { if (!drawingMode || !project.referenceAvailable) return; start.current = point(event); root.current!.setPointerCapture(event.pointerId) }} onPointerMove={event => { if (!start.current) return; const p = point(event); setRegion({ x: Math.min(start.current.x,p.x), y: Math.min(start.current.y,p.y), width: Math.abs(p.x-start.current.x), height: Math.abs(p.y-start.current.y) }) }} onPointerUp={event => {
    if (!start.current) return
    const p = point(event), origin = start.current, w = Math.abs(p.x-origin.x), h = Math.abs(p.y-origin.y)
    if (w > 4 && h > 4) { const next = structuredClone(project), e = createElement('image_placeholder', Math.min(p.x,origin.x), Math.min(p.y,origin.y), w, h); e.shape = circle ? 'circle' : 'rect'; e.sourceRegion = { detectedFrom: 'manual-region', page: pageIndex+1, confidence: null }; e.zIndex = Math.max(1, ...page.elements.map(e => e.zIndex))+1; next.pages[pageIndex].elements.push(e); add(next, e.id) }
    start.current = null; setRegion(null); if (root.current!.hasPointerCapture(event.pointerId)) root.current!.releasePointerCapture(event.pointerId)
  }} onPointerCancel={() => { start.current = null; setRegion(null) }}>
    {project.referenceAvailable ? <img draggable={false} src={`/api/projects/${project.projectId}/reference/${pageIndex+1}`} alt={`原始参考第 ${pageIndex+1} 页`} /> : <div className="no-source"><ScanLine size={32}/><h3>暂无原始参考</h3><p>导入 PDF 或图片即可开始对照重建。<br/>也可以直接在右侧创建简历。</p></div>}
    {region && <div className="source-region" style={{ left: region.x*scale, top: region.y*scale, width: region.width*scale, height: region.height*scale, borderRadius: circle ? '50%' : 0 }}><span>新图片占位区域</span></div>}
  </div>
}
