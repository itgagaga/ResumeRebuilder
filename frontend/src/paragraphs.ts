import type { Element, Page } from './types'
import { layoutText } from './textEditing'

// Only join nearby, aligned lines with matching typography. Never infer semantics
// from a heading's wording or retain a second copy of the source text.
const listStart = /^\s*(?:[•●▪◆◇·]|[-–—]\s|\d+[.、)）]|[（(]\d+[)）])/
export function nextParagraphLine(page: Page, first: Element): Element | undefined {
  if (first.type !== 'text' || Math.abs(first.rotation) > .1 || !first.text.trim() || first.textLayout === 'fixed') return
  const candidates = page.elements.filter(e => e.type === 'text' && e.id !== first.id && e.y >= first.y+first.height-.5 && Math.abs(e.x-first.x) <= first.style.fontSize*.65).sort((a,b) => a.y-b.y || a.x-b.x)
  const next = candidates[0]
  if (!next || !next.text.trim() || next.textLayout === 'fixed' || Math.abs(next.rotation) > .1) return
  if (first.text.length+next.text.length+1 > 100000 || (first.textRuns?.length || 0)+(next.textRuns?.length || 0) > 2000) return
  const a = first.style, b = next.style
  if (next.y-first.y-first.height > a.fontSize*1.15 || Math.abs(a.fontSize-b.fontSize) > .3 || a.fontFamily !== b.fontFamily || Math.abs(a.fontScaleX-b.fontScaleX) > .08 || a.fontWeight !== b.fontWeight || a.fontStyle !== b.fontStyle || a.color !== b.color || a.textAlign !== b.textAlign || a.textAlign !== 'left' || a.background !== 'transparent' || b.background !== 'transparent' || a.borderWidth || b.borderWidth || listStart.test(next.text)) return
  // A column of dates / metadata beside either line must remain a separate row.
  const rowMate = page.elements.some(e => e.type === 'text' && e.id !== first.id && e.id !== next.id &&
    [first,next].some(line => Math.abs(e.y-line.y) < a.fontSize*.6 && e.x >= line.x+line.width-1))
  if (rowMate) return
  const nextBullet = page.elements.some(e => e.type === 'rect' && e.shape === 'circle' && e.width <= a.fontSize && e.height <= a.fontSize &&
    e.x < next.x && e.x+e.width >= next.x-a.fontSize*2 && e.y+e.height/2 >= next.y && e.y+e.height/2 <= next.y+next.height)
  if (nextBullet) return
  const right = Math.max(first.x+first.width,next.x+next.width)
  if (page.elements.some(e => e.type !== 'text' && e.y > first.y+first.height-.5 && e.y < next.y && e.x < right && e.x+e.width > first.x)) return
  return next
}

function combined(first: Element, next: Element): Element {
  // Chinese soft wraps join without spaces; Latin words require a boundary.
  const separator = /[\p{L}\p{N}.,;:!?)}\]"'’”]$/u.test(first.text) && /^[\p{L}\p{N}("'‘“]/u.test(next.text) && !/[\p{Script=Han}]$/u.test(first.text) && !/^[\p{Script=Han}]/u.test(next.text) ? ' ' : ''
  const offset = Array.from(first.text+separator).length
  return { ...first, text: first.text+separator+next.text,
    textRuns: [...(first.textRuns || []),...(next.textRuns || []).map(run => ({ ...run, start: run.start+offset, end: run.end+offset }))],
    width: Math.max(first.width,next.x+next.width-first.x), height: next.y+next.height-first.y,
    textLayout: 'paragraph', flowBelow: true }
}

export function mergeParagraphLine(page: Page, firstId: string): Page {
  const first = page.elements.find(e => e.id === firstId)
  const next = first && nextParagraphLine(page,first)
  if (!first || !next) return page
  const merged = combined(first,next)
  // Replace both rows before measurement: their union is the old paragraph box.
  const baseline = { ...page, elements: page.elements.filter(e => e.id !== next.id).map(e => e.id === first.id ? merged : e) }
  return layoutText(baseline,merged)
}

export function paragraphCandidates(page: Page): { firstId: string; nextId: string; preview: string }[] {
  const pairs: { firstId: string; nextId: string; preview: string }[] = []
  for (const first of [...page.elements].sort((a,b) => a.y-b.y || a.x-b.x)) {
    const next = nextParagraphLine(page,first)
    // A short label is unlikely to be the beginning of a wrapped paragraph.
    if (!next || first.textLayout === 'paragraph' || next.textLayout === 'paragraph' || first.text.includes('\n') || first.width < page.width*.25 || Array.from(first.text).length < 18) continue
    const right = Math.max(...page.elements.filter(e => e.type === 'text' && Math.abs(e.x-first.x) < first.style.fontSize && Math.abs(e.style.fontSize-first.style.fontSize) < .3).map(e => e.x+e.width))
    if (first.x+first.width < right-first.style.fontSize*3) continue
    pairs.push({ firstId: first.id, nextId: next.id, preview: `${first.text.slice(-32)} ↵ ${next.text.slice(0,32)}` })
  }
  return pairs
}

export function organizeParagraphs(page: Page): Page {
  // Resolve chains by ID, then measure once per paragraph; deleted line geometry
  // never becomes an obstacle for the next pair in the same chain.
  const pairs = paragraphCandidates(page), consumed = new Set<string>()
  let result = page
  for (const pair of pairs) {
    if (consumed.has(pair.firstId)) continue
    let first = result.elements.find(e => e.id === pair.firstId)!
    let nextId: string | undefined = pair.nextId
    while (nextId) {
      const next = result.elements.find(e => e.id === nextId)
      if (!next || consumed.has(nextId)) break
      if (first.text.length+next.text.length+1 > 100000 || first.textRuns.length+next.textRuns.length > 2000) break
      consumed.add(nextId); first = combined(first,next)
      nextId = pairs.find(p => p.firstId === nextId)?.nextId
    }
    const baseline = { ...result, elements: result.elements.filter(e => !consumed.has(e.id)).map(e => e.id === first.id ? first : e) }
    result = layoutText(baseline,first)
  }
  return result
}
