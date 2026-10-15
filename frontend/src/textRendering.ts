import type { Element, Page } from './types'
import type { CSSProperties } from 'react'

export const textUnitScale = (page: Page) => page.unit === 'pt' ? 96/72 : 1

// A large CSS font with layout zoom preserves the effective glyph size and
// small-size advance rounding without browser minimum-font clamping.
export function textSurfaceStyle(element: Element, unitScale: number): CSSProperties {
  const zoom = Math.min(1,element.style.fontSize*unitScale/100)
  return {
    display: 'block', fontSize: element.style.fontSize*unitScale/zoom, zoom,
    lineHeight: element.style.lineHeight, width: `${100*unitScale/element.style.fontScaleX}%`,
    transform: `scale(${element.style.fontScaleX/unitScale},${1/unitScale})`, transformOrigin: 'left top',
  }
}

export function textOverflows(node: HTMLElement): boolean {
  const container = node.parentElement
  if (!container) return false
  const matrix = new DOMMatrixReadOnly(getComputedStyle(node).transform)
  const zoom = Number(getComputedStyle(node).zoom) || 1
  return Math.max(node.scrollHeight,node.clientHeight)*zoom*Math.abs(matrix.d) > container.clientHeight+2 ||
    Math.max(node.scrollWidth,node.clientWidth)*zoom*Math.abs(matrix.a) > container.clientWidth+2
}
