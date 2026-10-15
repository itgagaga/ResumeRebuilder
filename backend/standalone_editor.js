/* Self-contained editor: no server, imported modules, stored source text, or network access. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const hint = $('#resume-hint'), picker = $('#resume-photo-file');
  const bold = $('#resume-bold'), layout = $('#resume-layout');
  const fontBrush = $('#resume-font-brush');
  const pages = [...document.querySelectorAll('.page')];
  const initialHint = '点击文字即可修改；点击图片可更换。保存会下载包含修改的新 HTML 文件，无需启动本地服务。';
  let dirty = false, activeText = null, activeImage = null, pendingImage = null;
  let brushFont = null, brushLocked = false;
  const fontProperties = ['fontFamily','fontSize','fontWeight','fontStyle','color'];
  const composing = new WeakSet();
  const editableAt = node => (node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement)?.closest('[data-resume-text]');
  const elements = page => [...page.querySelectorAll('[data-resume-element]')];
  const number = value => Number.parseFloat(value) || 0;
  const bounds = element => ({ x: number(element.style.left), y: number(element.style.top), width: number(element.style.width), height: number(element.style.height) });
  function changed() { dirty = true; hint.textContent = '有未保存的修改。点击“保存修改后的 HTML”下载新文件，再打开新文件可继续编辑。'; }
  function margin(page) {
    return Math.max(8,Math.min(32,...elements(page).filter(e => e.dataset.kind === 'text' && number(e.style.left) >= 0).map(e => number(e.style.left))));
  }
  function refreshPages() {
    for (const page of pages) {
      const bottom = Math.max(0,...elements(page).map(e => number(e.style.top)+number(e.style.height)));
      const height = Math.max(Number(page.dataset.baseHeight),bottom+margin(page));
      page.style.height = height+'px';
      page.querySelector('.resume-content').style.height = height+'px';
      page.style.setProperty('--resume-print-scale',String(Math.min(1,Number(page.dataset.baseHeight)/height)));
    }
  }
  function measure(editor, width, nowrap = false) {
    const clone = editor.cloneNode(true), cs = getComputedStyle(editor);
    const zoom = number(cs.zoom) || 1;
    clone.removeAttribute('data-resume-text'); clone.removeAttribute('contenteditable');
    Object.assign(clone.style,{ position:'fixed', left:'-20000px', top:'0', visibility:'hidden', transform:'none',
      font:cs.font, lineHeight:cs.lineHeight, textAlign:cs.textAlign, width:nowrap ? 'max-content' : (width/zoom)+'px',
      height:'auto', minHeight:'0', whiteSpace:nowrap ? 'pre' : 'pre-wrap', overflowWrap:'break-word' });
    if (!clone.textContent || clone.textContent.endsWith('\n')) clone.append(document.createTextNode('\u200b'));
    document.body.append(clone);
    const box = clone.getBoundingClientRect(); clone.remove(); return box;
  }
  function reflow(editor) {
    const element = editor.closest('[data-resume-element]'), page = element.closest('.page');
    const cs = getComputedStyle(element), mode = element.dataset.layout;
    const old = bounds(element), all = elements(page).map(node => ({ node, ...bounds(node) }));
    if (mode === 'fixed' || Math.abs(number(element.style.transform.match(/rotate\(([^)]+)\)/)?.[1])) > .1) { refreshPages(); return; }
    const scale = Number(element.dataset.scale) || 1, border = number(cs.borderLeftWidth)+number(cs.borderRightWidth);
    if (mode === 'auto') {
      let right = Number(page.dataset.baseWidth)-margin(page);
      const lineHeight = number(element.style.fontSize)*(number(element.style.lineHeight) || 1.15);
      for (const other of all) {
        if (other.node !== element && other.node.dataset.kind !== 'line' && other.x > old.x+2 && other.y < old.y+lineHeight && other.y+other.height > old.y+2) right = Math.min(right,other.x-4);
      }
      const available = Math.max(4,right-old.x), desired = measure(editor,0,true).width*scale+border+2;
      element.style.width = Math.max(Math.min(old.width,available),Math.min(desired,available))+'px';
    }
    const width = Math.max(1,(number(element.style.width)-border)/scale);
    const measured = measure(editor,width).height+border+2;
    const minimum = number(element.style.fontSize)*(number(element.style.lineHeight) || 1.15)+border+2;
    const height = mode === 'paragraph' ? Math.max(minimum,measured) : Math.max(old.height,measured);
    element.style.height = height+'px';
    const delta = number(element.style.height)-old.height;
    if (Math.abs(delta) > .1 && element.dataset.flow !== 'false') {
      const moving = new Set(), queue = [{ node:element, ...old, width:Math.max(old.width,number(element.style.width)) }];
      for (let i = 0; i < queue.length; i++) {
        const anchor = queue[i], inset = number(getComputedStyle(anchor.node).fontSize)*2;
        for (const other of all) {
          if (other.node !== element && !moving.has(other.node) && other.y >= anchor.y+anchor.height-.5 && other.x < anchor.x+anchor.width && other.x+other.width > Math.max(0,anchor.x-inset)) {
            moving.add(other.node); queue.push(other);
          }
        }
      }
      for (const other of all) if (moving.has(other.node)) other.node.style.top = (other.y+delta)+'px';
    }
    refreshPages();
  }
  // Normalize browser-created markup, retaining only current text and font styles.
  // The saved file contains no second copy of a previous resume or application model.
  function currentContent(root) {
    const base = getComputedStyle(root), segments = [];
    let text = '';
    const append = (value, style = base) => {
      value = value.replaceAll('\u00a0',' '); text += value;
      if (value) segments.push({ value, font:Object.fromEntries(fontProperties.map(key => [key,style[key]])) });
    };
    const walk = node => {
      if (node.nodeType === Node.TEXT_NODE) append(node.textContent,getComputedStyle(node.parentElement));
      else if (node instanceof HTMLElement) {
        if (node.tagName === 'BR') {
          if (!(node.parentElement !== root && node.parentElement?.childNodes.length === 1)) append('\n');
          return;
        }
        const block = /^(DIV|P)$/.test(node.tagName);
        if (block && text && !text.endsWith('\n')) append('\n');
        node.childNodes.forEach(walk);
        if (block && node.nextSibling && (!text.endsWith('\n') || (node.childNodes.length === 1 && node.firstChild instanceof HTMLBRElement))) append('\n');
      }
    };
    root.childNodes.forEach(walk);
    const fragment = document.createDocumentFragment();
    for (const part of segments) {
      const differences = fontProperties.filter(key => part.font[key] !== base[key]);
      if (!differences.length) fragment.append(document.createTextNode(part.value));
      else {
        const span = document.createElement('span');
        for (const key of differences) span.style[key] = part.font[key];
        span.textContent = part.value; fragment.append(span);
      }
    }
    return fragment;
  }
  document.addEventListener('focusin', event => {
    const editor = editableAt(event.target);
    if (!editor) return;
    activeText = editor; layout.disabled = false; layout.value = editor.parentElement.dataset.layout;
  });
  document.addEventListener('compositionstart', event => { const editor = editableAt(event.target); if (editor) composing.add(editor); });
  document.addEventListener('compositionend', event => {
    const editor = editableAt(event.target); if (!editor) return;
    composing.delete(editor); reflow(editor); changed();
  });
  document.addEventListener('input', event => {
    const editor = editableAt(event.target); if (!editor || composing.has(editor) || event.isComposing) return;
    reflow(editor); changed();
  });
  document.addEventListener('focusout', event => {
    const editor = editableAt(event.target);
    if (editor && composing.has(editor)) { composing.delete(editor); reflow(editor); changed(); }
  });
  function insertPlain(editor, text) {
    if (!text) return;
    const selection = window.getSelection();
    if (!selection?.rangeCount || !editor.contains(selection.anchorNode) || !editor.contains(selection.focusNode)) return;
    if (!document.execCommand('insertText',false,text)) {
      const range = selection.getRangeAt(0), node = document.createTextNode(text);
      range.deleteContents(); range.insertNode(node); range.setStartAfter(node); range.collapse(true);
      selection.removeAllRanges(); selection.addRange(range);
    }
    reflow(editor); changed();
  }
  document.addEventListener('paste', event => {
    const editor = editableAt(event.target); if (!editor) return;
    event.preventDefault(); insertPlain(editor,event.clipboardData.getData('text/plain'));
  });
  document.addEventListener('dragover', event => { if (event.dataTransfer?.types.includes('Files')) event.preventDefault(); });
  document.addEventListener('drop', event => {
    event.preventDefault();
    const editor = editableAt(event.target); if (editor) insertPlain(editor,event.dataTransfer.getData('text/plain'));
  });
  function toggleBold() {
    const selection = window.getSelection(), start = editableAt(selection?.anchorNode), end = editableAt(selection?.focusNode);
    if (!selection || selection.isCollapsed || !start || start !== end) { hint.textContent = '请先选中同一段文字，再点击加粗按钮。'; return; }
    document.execCommand('bold'); reflow(start); changed();
    bold.setAttribute('aria-pressed',String(document.queryCommandState('bold')));
  }
  bold.addEventListener('mousedown', event => event.preventDefault());
  bold.addEventListener('click',toggleBold);
  function stopBrush(message) {
    brushFont = null; brushLocked = false;
    fontBrush.setAttribute('aria-pressed','false');
    document.body.classList.remove('resume-font-brushing');
    if (message) hint.textContent = message;
  }
  function brushHint() {
    hint.textContent = brushLocked ? '连续格式刷已开启：拖选目标文字应用字体；按 Esc 或再次点击格式刷退出。' : '字体已复制：拖选目标文字应用一次；双击格式刷可连续使用，Esc 取消。';
  }
  fontBrush.addEventListener('mousedown', event => event.preventDefault());
  fontBrush.addEventListener('click', event => {
    if (brushFont) {
      if (event.detail > 1) { brushLocked = true; brushHint(); }
      else stopBrush('已取消格式刷。');
      return;
    }
    const selection = window.getSelection(), editor = editableAt(selection?.anchorNode);
    if (!selection?.rangeCount || !editor || editableAt(selection.focusNode) !== editor || composing.has(editor)) {
      hint.textContent = '请先选中源文字（或将光标放入源文字），再点击格式刷。'; return;
    }
    const range = selection.getRangeAt(0), walker = document.createTreeWalker(editor,NodeFilter.SHOW_TEXT);
    let sample = range.startContainer.nodeType === Node.TEXT_NODE ? range.startContainer : null;
    if (!selection.isCollapsed) {
      sample = null;
      while (walker.nextNode()) {
        const node = walker.currentNode;
        if (node.length && range.intersectsNode(node) && !(node === range.startContainer && range.startOffset === node.length) && !(node === range.endContainer && range.endOffset === 0)) { sample = node; break; }
      }
    }
    const style = getComputedStyle(sample?.parentElement || editor);
    brushFont = Object.fromEntries(fontProperties.map(key => [key,style[key]]));
    // Editor font sizes are enlarged internally to avoid browser minimum fonts.
    // Capture the visible size and convert it to the target editor's zoom below.
    brushFont.fontSize = number(style.fontSize)*(number(getComputedStyle(editor).zoom) || 1);
    brushLocked = event.detail > 1;
    fontBrush.setAttribute('aria-pressed','true'); document.body.classList.add('resume-font-brushing'); brushHint();
  });
  function paintFont() {
    if (!brushFont) return;
    const selection = window.getSelection(), editor = editableAt(selection?.anchorNode);
    if (!selection?.rangeCount || selection.isCollapsed || !editor || editableAt(selection.focusNode) !== editor || composing.has(editor)) return;
    const range = selection.getRangeAt(0), wrapper = document.createElement('span');
    Object.assign(wrapper.style,brushFont,{ fontSize:(brushFont.fontSize/(number(getComputedStyle(editor).zoom) || 1))+'px' });
    wrapper.append(range.cloneContents());
    // Existing bold/italic tags and nested spans must not override the brush.
    for (const node of wrapper.querySelectorAll('*')) {
      for (const key of fontProperties) node.style[key] = 'inherit';
      if (node.tagName === 'FONT') for (const attribute of ['face','size','color']) node.removeAttribute(attribute);
    }
    // A native editing command keeps the entire brush action undoable.
    if (!document.execCommand('insertHTML',false,wrapper.outerHTML)) { hint.textContent = '未能应用字体，请重新选择目标文字后再试。'; return; }
    reflow(editor); changed();
    if (brushLocked) brushHint(); else stopBrush('已应用字体格式。可按 Ctrl+Z 撤销；请保存修改后的 HTML。');
  }
  document.addEventListener('pointerup', event => { if (editableAt(event.target)) paintFont(); });
  document.addEventListener('keyup', event => { if (event.shiftKey && ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)) paintFont(); });
  document.addEventListener('selectionchange', () => {
    const selection = window.getSelection();
    bold.setAttribute('aria-pressed',String(!!editableAt(selection?.anchorNode) && document.queryCommandState('bold')));
  });
  layout.addEventListener('change', () => {
    if (!activeText) return;
    activeText.parentElement.dataset.layout = layout.value; reflow(activeText); changed();
  });
  function chooseImage(element) {
    if (pendingImage) { hint.textContent = '图片正在处理，请稍候。'; return; }
    if (!element) { hint.textContent = '请先点击简历中需要更换的图片区域。当前没有图片区域时，请在工作台添加后重新导出。'; return; }
    activeImage?.removeAttribute('data-active-image'); activeImage = element;
    activeImage.setAttribute('data-active-image',''); picker.click();
  }
  document.addEventListener('click', event => {
    const image = event.target.closest('[data-kind="image_placeholder"]'); if (image) chooseImage(image);
  });
  $('#resume-photo').addEventListener('click', () => {
    const photos = document.querySelectorAll('[data-kind="image_placeholder"]');
    chooseImage(activeImage || (photos.length === 1 ? photos[0] : null));
  });
  async function replaceImage(file, target) {
    if (!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size > 25*1024*1024) throw new Error('请选择不超过 25MB 的 PNG、JPG 或 WebP 图片。');
    const url = URL.createObjectURL(file);
    try {
      const image = new Image(); image.src = url; await image.decode();
      if (image.naturalWidth*image.naturalHeight > 30000000) throw new Error('图片超过 3000 万像素，请先缩小图片。');
      const canvas = document.createElement('canvas'); canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
      canvas.getContext('2d').drawImage(image,0,0);
      const replacement = document.createElement('img'); replacement.alt = '';
      replacement.src = canvas.toDataURL('image/png');
      Object.assign(replacement.style,{ width:'100%', height:'100%', display:'block', objectFit:'cover' });
      target.replaceChildren(replacement); changed();
    } finally { URL.revokeObjectURL(url); }
  }
  picker.addEventListener('change', () => {
    const file = picker.files[0]; if (!file || !activeImage) return;
    pendingImage = replaceImage(file,activeImage).catch(error => { hint.textContent = error.message || '图片无法读取，请换一张图片。'; }).finally(() => { picker.value = ''; pendingImage = null; });
  });
  async function saveFile() {
    if (pendingImage) await pendingImage;
    for (const editor of document.querySelectorAll('[data-resume-text]')) if (composing.has(editor)) { hint.textContent = '请先完成正在输入的文字，再保存文件。'; return; }
    refreshPages();
    const clone = document.documentElement.cloneNode(true);
    const live = [...document.querySelectorAll('[data-resume-text]')];
    clone.querySelectorAll('[data-resume-text]').forEach((editor,index) => editor.replaceChildren(currentContent(live[index])));
    clone.querySelectorAll('[data-active-image]').forEach(e => e.removeAttribute('data-active-image'));
    clone.querySelector('#resume-photo-file').value = '';
    clone.querySelector('#resume-layout').disabled = true;
    clone.querySelector('#resume-bold').setAttribute('aria-pressed','false');
    clone.querySelector('#resume-font-brush').setAttribute('aria-pressed','false');
    clone.querySelector('body').classList.remove('resume-font-brushing');
    clone.querySelector('#resume-hint').textContent = initialHint;
    const html = '<!doctype html>\n'+clone.outerHTML;
    const url = URL.createObjectURL(new Blob([html],{ type:'text/html;charset=utf-8' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'resume-editable.html';
    anchor.click(); setTimeout(() => URL.revokeObjectURL(url),10000);
    dirty = false; hint.textContent = '已生成包含修改的新 HTML 文件。请保留下载的新文件；原文件不会被自动覆盖。';
  }
  $('#resume-save').addEventListener('click',saveFile);
  document.addEventListener('keydown', event => {
    if (event.isComposing) return;
    const modifier = event.ctrlKey || event.metaKey, key = event.key.toLowerCase();
    if (modifier && key === 's') { event.preventDefault(); void saveFile(); }
    else if (modifier && key === 'b' && editableAt(event.target)) { event.preventDefault(); document.execCommand('bold'); }
    else if (modifier && ['i','u'].includes(key) && editableAt(event.target)) event.preventDefault();
    else if (event.key === 'Escape') {
      if (brushFont) { event.preventDefault(); stopBrush('已取消格式刷。'); }
      else if (editableAt(event.target)) event.target.blur();
    }
  });
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('beforeprint',refreshPages);
  $('#resume-print').addEventListener('click',async () => {
    if (pendingImage) await pendingImage;
    await document.fonts.ready;
    await Promise.all([...document.images].map(image => image.decode().catch(() => {})));
    refreshPages(); window.print();
  });
  refreshPages();
})();
