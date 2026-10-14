import type { Element } from './types'

export default function TextContent({ element }: { element: Element }) {
  const chars = Array.from(element.text), content = []
  let cursor = 0
  for (const run of element.textRuns || []) {
    if (run.start > cursor) content.push(chars.slice(cursor,run.start).join(''))
    content.push(<span key={run.start} style={{ fontWeight: run.fontWeight }}>{chars.slice(run.start,run.end).join('')}</span>)
    cursor = run.end
  }
  content.push(chars.slice(cursor).join(''))
  return <>{content}</>
}
