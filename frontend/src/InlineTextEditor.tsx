import { useLayoutEffect, useRef } from 'react'
import type { Element } from './types'
import { readEditable, textNodes } from './textEditing'

interface Props {
  element: Element; onChange: (e: Element) => void; onFinish: () => void; undo: () => void; redo: () => void;
  active?: boolean; autoFocus?: boolean; enabled?: boolean; onActivate?: () => void; onNavigate?: (backward: boolean) => boolean
}

export default function InlineTextEditor({ element, onChange, onFinish, undo, redo, active = true, autoFocus = true, enabled = true, onActivate, onNavigate }: Props) {
  const root = useRef<HTMLDivElement>(null), composing = useRef(false), lastEmitted = useRef('')
  const signature = JSON.stringify([element.text,element.textRuns || []])
  const initialized = useRef(false)
  useLayoutEffect(() => {
    if (!root.current || composing.current || (initialized.current && signature === lastEmitted.current)) return
    const selection = window.getSelection(), focused = document.activeElement === root.current
    let offsets: [number,number] | undefined
    if (focused && selection?.rangeCount && root.current.contains(selection.anchorNode) && root.current.contains(selection.focusNode)) {
      const current = selection.getRangeAt(0), prefix = current.cloneRange()
      prefix.selectNodeContents(root.current); prefix.setEnd(current.startContainer,current.startOffset)
      const start = prefix.toString().length
      offsets = [start,start+current.toString().length]
    }
    root.current.replaceChildren(textNodes(element))
    lastEmitted.current = signature; initialized.current = true
    if (offsets) {
      const walker = document.createTreeWalker(root.current,NodeFilter.SHOW_TEXT), nodes: Text[] = []
      while (walker.nextNode()) nodes.push(walker.currentNode as Text)
      const locate = (offset: number): [Node,number] => {
        for (const node of nodes) { if (offset <= node.length) return [node,offset]; offset -= node.length }
        return nodes.length ? [nodes[nodes.length-1],nodes[nodes.length-1].length] : [root.current!,0]
      }
      const range = document.createRange(); range.setStart(...locate(offsets[0])); range.setEnd(...locate(offsets[1]))
      selection?.removeAllRanges(); selection?.addRange(range)
    }
  }, [signature,element])
  useLayoutEffect(() => {
    if (!autoFocus || !root.current) return
    root.current.focus()
    const range = document.createRange(); range.selectNodeContents(root.current); range.collapse(false)
    const selection = window.getSelection(); selection?.removeAllRanges(); selection?.addRange(range)
  }, [autoFocus])
  function emit() {
    if (!root.current || composing.current) return
    const content = readEditable(root.current,element.style.fontWeight)
    const nextSignature = JSON.stringify([content.text,content.textRuns])
    if (nextSignature === lastEmitted.current) return
    lastEmitted.current = nextSignature
    onChange({ ...element, ...content })
  }
  function insertPlainText(text: string) {
    const selection = window.getSelection()
    if (!selection?.rangeCount || !root.current?.contains(selection.anchorNode)) return
    const range = selection.getRangeAt(0)
    range.deleteContents(); const node = document.createTextNode(text); range.insertNode(node)
    range.setStartAfter(node); range.collapse(true); selection.removeAllRanges(); selection.addRange(range)
    emit()
  }
  return <div ref={root} className={`inline-editor text-content ${enabled ? 'editable-surface' : ''} ${active ? 'is-editing' : ''}`} data-text-id={element.id} contentEditable={enabled} suppressContentEditableWarning role="textbox" aria-label={active ? '直接编辑文字' : `点击编辑：${element.text.slice(0,24) || '空段落'}`} aria-multiline="true" tabIndex={enabled ? 0 : -1}
    style={{ font: 'inherit', color: 'inherit', lineHeight: 'inherit', textAlign: 'inherit', width: `${100/element.style.fontScaleX}%`, transform: `scaleX(${element.style.fontScaleX})`, transformOrigin: 'left top' }}
    onFocus={onActivate} onPointerDown={event => { if (enabled) event.stopPropagation() }} onDoubleClick={event => { if (enabled) event.stopPropagation() }}
    onInput={emit} onCompositionStart={() => { composing.current = true }} onCompositionEnd={() => { composing.current = false; emit() }}
    onPaste={event => { event.preventDefault(); insertPlainText(event.clipboardData.getData('text/plain')) }}
    onDrop={event => { event.preventDefault(); insertPlainText(event.dataTransfer.getData('text/plain')) }}
    onBlur={() => { composing.current = false; emit(); onFinish() }} onKeyDown={event => {
      const key = event.key.toLowerCase(), modifier = event.ctrlKey || event.metaKey
      if (composing.current || event.nativeEvent.isComposing) { event.stopPropagation(); return }
      if (modifier && key === 's') return
      event.stopPropagation()
      if (modifier && (key === 'z' || key === 'y')) { event.preventDefault(); key === 'y' || event.shiftKey ? redo() : undo() }
      else if (modifier && (key === 'i' || key === 'u')) event.preventDefault()
      else if (event.key === 'Tab' && onNavigate?.(event.shiftKey)) event.preventDefault()
      else if (event.key === 'Escape') { event.preventDefault(); root.current?.blur() }
    }}/>
}
