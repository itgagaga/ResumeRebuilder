import type { Element, Page } from './types'
import type { CSSProperties } from 'react'

export const textUnitScale = (page: Page) => page.unit === 'pt' ? 96/72 : 1
export const textRenderZoom = (element: Element, unitScale: number) => Math.min(1,element.style.fontSize*unitScale/100)

// A large CSS font with layout zoom preserves the intended effective glyph
// size without triggering browser minimum-font clamping. Unlike transform-only
// scaling, layout zoom also preserves small-size glyph advance rounding.
export function textSurfaceStyle(element: Element, unitScale: number): CSSProperties {
  const zoom = textRenderZoom(element,unitScale)
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
  // contenteditable grows its own height, so comparing its scrollHeight with
  // its clientHeight alone misses a wrapped line overlapping the next object.
  return Math.max(node.scrollHeight,node.clientHeight)*zoom*Math.abs(matrix.d) > container.clientHeight+2 ||
    Math.max(node.scrollWidth,node.clientWidth)*zoom*Math.abs(matrix.a) > container.clientWidth+2
}

export function textNodes(element: Element): DocumentFragment {
  const fragment = document.createDocumentFragment(), chars = Array.from(element.text)
  let cursor = 0
  for (const run of element.textRuns || []) {
    if (run.start > cursor) fragment.append(document.createTextNode(chars.slice(cursor,run.start).join('')))
    const span = document.createElement('span'); span.style.fontWeight = String(run.fontWeight)
    span.textContent = chars.slice(run.start,run.end).join(''); fragment.append(span); cursor = run.end
  }
  fragment.append(document.createTextNode(chars.slice(cursor).join('')))
  return fragment
}

export function readEditable(root: HTMLElement, baseWeight: number) {
  let text = '', length = 0
  const textRuns: Element['textRuns'] = []
  const append = (value: string, weight: number) => {
    value = value.replaceAll('\u00a0',' ')
    const start = length; text += value; length += Array.from(value).length
    if (weight !== baseWeight && value) {
      const previous = textRuns[textRuns.length-1]
      if (previous && previous.end === start && previous.fontWeight === weight) previous.end = length
      else textRuns.push({ start, end: length, fontWeight: weight })
    }
  }
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      append(node.textContent || '', Number(getComputedStyle(node.parentElement!).fontWeight) || baseWeight)
    } else if (node instanceof HTMLElement) {
      if (node.tagName === 'BR') {
        if (!(node.parentElement !== root && node.parentElement?.childNodes.length === 1)) append('\n',baseWeight)
        return
      }
      const block = /^(DIV|P)$/.test(node.tagName)
      if (block && text && !text.endsWith('\n')) append('\n',baseWeight)
      node.childNodes.forEach(walk)
      if (block && node.nextSibling && !text.endsWith('\n')) append('\n',baseWeight)
      else if (block && node.nextSibling && node.childNodes.length === 1 && node.firstChild instanceof HTMLBRElement) append('\n',baseWeight)
    }
  }
  root.childNodes.forEach(walk)
  return { text, textRuns }
}

export function rebaseTextRuns(previous: Element, text: string): Element['textRuns'] {
  const before = Array.from(previous.text), after = Array.from(text)
  let start = 0, suffix = 0
  while (start < Math.min(before.length,after.length) && before[start] === after[start]) start++
  while (suffix < Math.min(before.length-start,after.length-start) && before[before.length-1-suffix] === after[after.length-1-suffix]) suffix++
  const oldEnd = before.length-suffix, newEnd = after.length-suffix, delta = after.length-before.length
  const runs: Element['textRuns'] = []
  for (const run of previous.textRuns || []) {
    if (run.end <= start) runs.push({ ...run })
    else if (run.start >= oldEnd) runs.push({ ...run, start: run.start+delta, end: run.end+delta })
    else {
      if (run.start < start) runs.push({ ...run, end: start })
      if (run.start < start && run.end > oldEnd && newEnd > start) runs.push({ ...run, start, end: newEnd })
      if (run.end > oldEnd) runs.push({ ...run, start: newEnd, end: run.end+delta })
    }
  }
  const merged: Element['textRuns'] = []
  for (const run of runs.filter(r => r.start >= 0 && r.end > r.start && r.end <= after.length)) {
    const last = merged[merged.length-1]
    if (last && last.end === run.start && last.fontWeight === run.fontWeight) last.end = run.end
    else merged.push(run)
  }
  return merged
}

export function availableTextWidth(element: Element, page: Page) {
  const margin = Math.max(8,Math.min(32,...page.elements.filter(e => e.type === 'text' && e.x >= 0).map(e => e.x)))
  let right = page.width-margin
  const rowBottom = element.y+element.style.fontSize*element.style.lineHeight
  for (const other of page.elements) {
    if (other.id !== element.id && other.type !== 'line' && other.x > element.x+2 && other.y < rowBottom && other.y+other.height > element.y+2) right = Math.min(right,other.x-4)
  }
  return Math.max(4,right-element.x)
}

export function layoutText(page: Page, updated: Element): Page {
  const previous = page.elements.find(e => e.id === updated.id)
  let element = { ...updated }, delta = 0
  if (element.type === 'text' && element.textLayout !== 'fixed' && (element.text || element.textLayout === 'paragraph') && Math.abs(element.rotation) < .1) {
    const measure = document.createElement('div'), unitScale = textUnitScale(page), zoom = textRenderZoom(element,textUnitScale(page))
    Object.assign(measure.style,{ position: 'fixed', left: '-20000px', top: '0', visibility: 'hidden',
      fontFamily: element.style.fontFamily, fontSize: `${element.style.fontSize*unitScale/zoom}px`, zoom: String(zoom), fontWeight: String(element.style.fontWeight),
      fontSynthesis: 'weight style small-caps',
      fontStyle: element.style.fontStyle, lineHeight: String(element.style.lineHeight), whiteSpace: 'pre',
      overflowWrap: 'break-word', width: 'max-content', padding: '0', margin: '0', border: '0' })
    measure.append(textNodes(element))
    // An empty paragraph and a trailing newline still need a visible caret line.
    if (!element.text || element.text.endsWith('\n')) measure.append(document.createTextNode('\u200b'))
    document.body.append(measure)
    const horizontalBorder = element.style.borderWidth*2
    if (element.textLayout !== 'wrap' && element.textLayout !== 'paragraph') {
      const desired = measure.getBoundingClientRect().width/unitScale*element.style.fontScaleX+horizontalBorder+2
      // A rotated or already over-page object remains a manual correction, rather than silently clipped.
      element.width = Math.min(10000,Math.max(Math.min(element.width,availableTextWidth(element,page)),Math.min(desired,availableTextWidth(element,page))))
    }
    measure.style.whiteSpace = 'pre-wrap'
    measure.style.width = `${Math.max(1,(element.width-horizontalBorder)/element.style.fontScaleX*unitScale/zoom)}px`
    const measured = measure.getBoundingClientRect().height/unitScale+horizontalBorder+2
    element.height = Math.min(10000,element.textLayout === 'paragraph' ? Math.max(element.style.fontSize*element.style.lineHeight+horizontalBorder+2,measured) : Math.max(element.height,measured))
    measure.remove()
    delta = element.height-(previous?.height || element.height)
  }
  // Propagate through full-width headings so their following rows move with them.
  // Use the old geometry for both growing and shrinking to preserve existing gaps.
  const moving = new Set<string>()
  if (previous && Math.abs(delta) > .1 && element.flowBelow !== false) {
    const queue = [previous]
    for (let i = 0; i < queue.length; i++) {
      const anchor = queue[i], left = Math.max(0,anchor.x-anchor.style.fontSize*2), right = anchor.x+Math.max(anchor.width,i === 0 ? element.width : 0)
      for (const other of page.elements) {
        if (other.id !== element.id && !moving.has(other.id) && other.y >= anchor.y+anchor.height-.5 && other.x < right && other.x+other.width > left) {
          moving.add(other.id); queue.push(other)
        }
      }
    }
  }
  return { ...page, elements: page.elements.map(other => {
    if (other.id === element.id) return element
    if (moving.has(other.id)) return { ...other, y: Math.max(-10000,Math.min(10000,other.y+delta)) }
    return other
  }) }
}
