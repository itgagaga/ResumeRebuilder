import { useLayoutEffect, useRef } from 'react'
import type { Element } from './types'
import { readEditable, textNodes } from './textEditing'

interface Props { element: Element; onChange: (e: Element) => void; onFinish: () => void; undo: () => void; redo: () => void }

export default function InlineTextEditor({ element, onChange, onFinish, undo, redo }: Props) {
  const root = useRef<HTMLDivElement>(null), composing = useRef(false), lastEmitted = useRef('')
  const signature = JSON.stringify([element.text,element.textRuns || []])
  const initialized = useRef(false)
  useLayoutEffect(() => {
    if (!root.current || composing.current || (initialized.current && signature === lastEmitted.current)) return
    root.current.replaceChildren(textNodes(element))
    lastEmitted.current = signature; initialized.current = true
    root.current.focus()
    const range = document.createRange(); range.selectNodeContents(root.current); range.collapse(false)
    const selection = window.getSelection(); selection?.removeAllRanges(); selection?.addRange(range)
  }, [signature,element])
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
  return <div ref={root} className="inline-editor editable-surface" contentEditable suppressContentEditableWarning role="textbox" aria-label="直接编辑文字" aria-multiline="true" tabIndex={0}
    style={{ font: 'inherit', color: 'inherit', lineHeight: 'inherit', textAlign: 'inherit', width: `${100/element.style.fontScaleX}%`, transform: `scaleX(${element.style.fontScaleX})`, transformOrigin: 'left top' }}
    onPointerDown={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()}
    onInput={emit} onCompositionStart={() => { composing.current = true }} onCompositionEnd={() => { composing.current = false; emit() }}
    onPaste={event => { event.preventDefault(); insertPlainText(event.clipboardData.getData('text/plain')) }}
    onDrop={event => { event.preventDefault(); insertPlainText(event.dataTransfer.getData('text/plain')) }}
    onBlur={onFinish} onKeyDown={event => {
      const key = event.key.toLowerCase(), modifier = event.ctrlKey || event.metaKey
      if (composing.current || event.nativeEvent.isComposing) { event.stopPropagation(); return }
      if (modifier && key === 's') return
      event.stopPropagation()
      if (modifier && (key === 'z' || key === 'y')) { event.preventDefault(); key === 'y' || event.shiftKey ? redo() : undo() }
      else if (modifier && (key === 'i' || key === 'u')) event.preventDefault()
      else if (event.key === 'Escape') { event.preventDefault(); root.current?.blur() }
    }}/>
}
