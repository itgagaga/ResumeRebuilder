import { useEffect, useRef } from 'react'
import { assetUrl } from './api'
import type { Element, Page } from './types'
import TextContent from './TextContent'
import { textSurfaceStyle, textUnitScale, textOverflows } from './textRendering'

function elementStyle(e: Element): React.CSSProperties {
  return { position: 'absolute', left: e.x, top: e.y, width: e.width, height: e.height, zIndex: e.zIndex,
    transform: `rotate(${e.rotation}deg)`, transformOrigin: e.type === 'line' ? 'left top' : 'center',
    fontFamily: e.style.fontFamily, fontSize: e.style.fontSize, fontWeight: e.style.fontWeight, fontStyle: e.style.fontStyle, fontSynthesis: 'weight style small-caps',
    color: e.style.color, background: e.style.background, lineHeight: e.style.lineHeight, textAlign: e.style.textAlign,
    border: `${e.style.borderWidth}px solid ${e.style.borderColor}`,
    borderRadius: e.shape === 'circle' ? '50%' : e.shape === 'rounded' ? e.style.borderRadius || 10 : e.style.borderRadius,
    clipPath: e.shape === 'polygon' ? `polygon(${e.shapePoints?.map(([x,y]) => `${x*100}% ${y*100}%`).join(',')})` : undefined,
    overflow: e.type === 'image_placeholder' ? 'hidden' : 'visible', whiteSpace: 'pre-wrap', overflowWrap: 'break-word', boxSizing: 'border-box' }
}

export default function ResumePreview({ projectId, page, zoom, setOverflow }: { projectId: string; page: Page; zoom: number; setOverflow: (ids: string[]) => void }) {
  const root = useRef<HTMLDivElement>(null)
  const unitScale = textUnitScale(page), scale = zoom * unitScale
  useEffect(() => {
    let disposed = false
    const check = () => {
      if (disposed) return
      const ids = Array.from(root.current?.querySelectorAll<HTMLElement>('[data-text-id]') || [])
        .filter(textOverflows).map(el => el.dataset.textId!)
      setOverflow(ids)
    }
    const timer = setTimeout(check, 80)
    document.fonts.ready.then(check)
    return () => { disposed = true; clearTimeout(timer) }
  }, [page, setOverflow])

  return <div className="paper-wrap" style={{ width: page.width*scale, height: page.height*scale }}>
    <div ref={root} className="paper preview-mode" style={{ width: page.width, height: page.height, background: page.background, transform: `scale(${scale})` }}>
      {page.elements.map(e => <div key={e.id} data-element-id={e.id} style={elementStyle(e)} className="element"
        title={e.type === 'text' && e.sourceRegion?.confidence != null && e.sourceRegion.confidence < .85 ? '识别置信度低，请对照原页核对' : undefined}>
        {e.type === 'text' && <span className="text-content" data-text-id={e.id} style={{ ...textSurfaceStyle(e,unitScale), height: `${100*unitScale}%` }}><TextContent element={e}/></span>}
        {e.type === 'image_placeholder' && e.assetId && <img draggable={false} alt="用户上传的图片" src={assetUrl(projectId, e.assetId)} style={{ width: '100%', height: '100%', display: 'block', objectFit: e.fit, objectPosition: `${50+e.crop.offsetX/2}% ${50+e.crop.offsetY/2}%`, transform: `translate(${e.crop.offsetX/2}%,${e.crop.offsetY/2}%) scale(${e.crop.scale})` }}/>}
      </div>)}
    </div>
  </div>
}
