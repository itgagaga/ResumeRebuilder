import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUpRight, Upload, Download, ImagePlus, Minus, Plus, Save, ChevronLeft, ChevronRight, Columns2, PanelLeftClose, ScanLine, ShieldCheck, FileText, FolderOpen, Check, X, AlertTriangle, Trash2, Layers, Loader2, Maximize } from 'lucide-react'
import ResumePreview from './ResumePreview'
import SourcePreview from './SourcePreview'
import { download, exportBlob, request, save, upload } from './api'
import type { Project } from './types'

type Recent = { projectId: string; name: string; pages: number }

export default function App() {
  const [project, setProject] = useState<Project | null>(null)
  const [saved, setSaved] = useState('')
  const [recent, setRecent] = useState<Recent[]>([])
  const [pageIndex, setPageIndex] = useState(0)
  const [htmlOpened, setHtmlOpened] = useState(false)
  const [zoom, setZoom] = useState(0.62)
  const [compare, setCompare] = useState(true)
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null)
  const [overflow, setOverflow] = useState<string[]>([])
  const [exportDialog, setExportDialog] = useState(false)
  const [exportFormat, setExportFormat] = useState('html')
  const [includeReference, setIncludeReference] = useState(true)
  const [showWarnings, setShowWarnings] = useState(false)
  const [health, setHealth] = useState({ ocrReady: false, pdfReady: false })
  const fileInput = useRef<HTMLInputElement>(null), editorColumn = useRef<HTMLDivElement>(null)
  const dirty = project !== null && saved !== JSON.stringify(project)
  const page = project?.pages[pageIndex]
  const emptyCount = project?.pages.flatMap(p => p.elements).filter(e => e.type === 'image_placeholder' && !e.assetId).length || 0
  const outsideCount = page?.elements.filter(e => e.x < 0 || e.y < 0 || e.x+e.width > page.width || e.y+e.height > page.height).length || 0
  const exportOutsideCount = project?.pages.reduce((count,p) => count+p.elements.filter(e => e.x < 0 || e.y < 0 || e.x+e.width > p.width || e.y+e.height > p.height).length,0) || 0

  const notify = useCallback((text: string, error = false) => setNotice({ text, error }), [])
  useEffect(() => { if (notice) { const timer = setTimeout(() => setNotice(null), notice.error ? 10000 : 4000); return () => clearTimeout(timer) } }, [notice])
  const refreshRecent = () => request<Recent[]>('/projects').then(setRecent).catch(() => {})
  useEffect(() => { refreshRecent(); request<typeof health>('/health').then(setHealth).catch(() => notify('本地服务未连接，请运行启动脚本。', true)) }, [notify])
  useEffect(() => { const handler = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = '' } }; window.addEventListener('beforeunload', handler); return () => window.removeEventListener('beforeunload', handler) }, [dirty])
  function accept(p: Project) { setProject(p); setSaved(JSON.stringify(p)); setPageIndex(0); setOverflow([]); setHtmlOpened(false); setShowWarnings(p.warnings.length > 0); refreshRecent() }
  const canReplace = () => !dirty || window.confirm('当前工程有未保存的修改。是否放弃这些修改并打开其他工程？')
  async function task(message: string, action: () => Promise<void>) { setBusy(message); try { await action() } catch (e) { notify(e instanceof Error ? e.message : '操作失败，请重试', true) } finally { setBusy('') } }
  async function importFile(file: File) { if (!canReplace()) return; await task('正在本地解析文件与识别文字…', async () => { accept(await upload(file)); notify('识别结果已就绪。对照预览后，点击“进入 HTML 编辑”修改简历。') }) }
  async function demo() { if (!canReplace()) return; await task('正在打开内置示例…', async () => accept(await request<Project>('/demo', { method: 'POST' }))) }
  async function openRecent(projectId: string) { if (!canReplace()) return; await task('正在打开工程…', async () => accept(await request<Project>(`/projects/${projectId}`))) }
  async function saveProject() { if (!project) return; await task('正在保存工程…', async () => { const result = await save(project); setSaved(JSON.stringify(project)); setProject({ ...project, assets: result.assets }); notify('工程已保存到本机。'); refreshRecent() }) }
  async function exportProject() { if (!project) return; await task(exportFormat === 'pdf' ? '正在生成 PDF，请等待字体与图片加载…' : '正在生成导出文件…', async () => { await save(project); setSaved(JSON.stringify(project)); await download(project.projectId, exportFormat, includeReference); setExportDialog(false); notify('已导出当前内容。') }) }
  async function openHtmlEditor() {
    if (!project) return
    const tab = window.open('about:blank', '_blank')
    if (!tab) { notify('浏览器阻止了新窗口，请允许弹出窗口，或使用导出 HTML。', true); return }
    tab.opener = null
    await task('正在生成可编辑 HTML…', async () => {
      try {
        await save(project); setSaved(JSON.stringify(project))
        const url = URL.createObjectURL(await exportBlob(project.projectId, 'html', false))
        tab.location.href = url
        setHtmlOpened(true)
        setTimeout(() => URL.revokeObjectURL(url), 60000)
        notify('已打开独立 HTML。修改后在新页面保存 HTML；文件修改不会自动同步回工程。')
      } catch (error) { tab.close(); throw error }
    })
  }
  async function deleteReference() { if (!project || !window.confirm('永久删除本工程的原始参考图？简历内容和替换图片会保留。')) return; await task('正在删除原始参考…', async () => { await save(project); accept(await request<Project>(`/projects/${project.projectId}/reference`, { method: 'DELETE' })); notify('原始参考已删除。') }) }
  function fit() { if (!page || !editorColumn.current) return; const width = editorColumn.current.clientWidth-64; setZoom(Math.min(1.4,Math.max(0.2,width/(page.width*(page.unit === 'pt' ? 96/72 : 1))))) }
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!project || busy || exportDialog) return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); void saveProject(); return }
    }
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler)
  })

  return <div className={project ? 'app editor-app' : 'app welcome-app'}>
    <input ref={fileInput} type="file" hidden accept=".pdf,.png,.jpg,.jpeg,.webp,.rresume" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void importFile(file) }}/>
    <header className="topbar"><button className="brand" onClick={() => { if (canReplace()) { setProject(null); setSaved(''); refreshRecent() } }} title="回到工作台"><span className="brand-icon"><Layers size={21}/></span><span>Resume<span className="brand-light"> Rebuilder</span></span><span className="version">LOCAL</span></button>
      {project ? <><div className="project-title"><input aria-label="工程名称" value={project.name} onChange={event => setProject({ ...project, name: event.target.value.slice(0,150) })}/><span className={`save-state ${dirty ? 'dirty' : ''}`}>{dirty ? '未保存' : <><Check size={12}/>已保存</>}</span></div><div className="header-actions"><button className="button quiet" onClick={() => fileInput.current?.click()}><FolderOpen size={16}/>导入 / 打开</button>{dirty && <button className="button quiet" onClick={saveProject}><Save size={16}/>保存</button>}<button className="button primary" onClick={openHtmlEditor}><ArrowUpRight size={16}/>进入 HTML 编辑</button><button className="button quiet" onClick={() => setExportDialog(true)}><Download size={16}/>导出<ChevronRight size={14}/></button></div></> : <span className="local-status"><span className="status-dot"/>本地运行 · 文件留在你的电脑</span>}
    </header>
    {!project ? <main className="welcome" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); const file = event.dataTransfer.files[0]; if (file) void importFile(file) }}>
      <section className="welcome-copy"><div className="eyebrow"><span/>你的简历，重新编辑</div><h1>保留喜欢的版式，<br/>写下自己的故事<span>。</span></h1><p className="lead">从 PDF、图片或截图开始，对照预览识别结果。<br/>进入 HTML 编辑，修改文字、使用格式刷、替换头像并保存简历。</p>
        <div className="welcome-actions"><button className="button primary large" onClick={() => fileInput.current?.click()}><Upload size={18}/>导入简历模板<ArrowUpRight size={18}/></button><button className="button secondary large" onClick={demo}>体验示例<ChevronRight size={16}/></button></div><div className="supported">PDF / PNG / JPG / WebP <span>·</span> 或拖入文件 <span>·</span> 最大 25 MB</div>
        <div className="trust-row"><span><ShieldCheck size={16}/>本地处理</span><span><ScanLine size={16}/>离线 OCR</span><span><FileText size={16}/>可选中文字的 PDF</span></div>
      </section>
      <section className="welcome-art" aria-label="工作流程示意"><div className="art-top"><span className="micro-label">FROM TEMPLATE TO YOUR STORY</span><span className="art-dot"/></div><div className="art-paper"><div className="art-paper-top"><div><div className="art-name">你的名字</div><div className="art-subtitle">DESIGN YOUR NEXT CHAPTER</div></div><div className="art-photo"><ImagePlus size={25}/></div></div><div className="art-contact">hello@example.com　 /　 138 0000 0000</div><div className="art-section"><span>个人简介</span><b>01</b></div><div className="art-line long"/><div className="art-line"/><div className="art-section"><span>工作经历</span><b>02</b></div><div className="art-job"><b>你的经历，从这里开始</b><span>2023 — 至今</span></div><div className="art-line long"/><div className="art-line long"/><div className="art-line short"/><div className="art-section"><span>教育背景</span><b>03</b></div><div className="art-line long"/><div className="art-line"/><div className="art-selection"><span>可编辑文字</span><i/><i/><i/><i/></div></div><div className="floating-note"><span className="note-check"><Check size={16}/></span><div><b>版式保留，内容由你</b><span>源头像 → 可替换图片框</span></div></div><div className="art-caption">解析 <span>→</span> 编辑 <span>→</span> 导出</div></section>
      {recent.length > 0 && <section className="recent"><div className="section-heading"><h2>继续最近的工程</h2><span>保存在本机</span></div><div className="recent-grid">{recent.slice(0,6).map(p => <button key={p.projectId} onClick={() => openRecent(p.projectId)}><div className="recent-icon"><FileText size={22}/></div><div><b>{p.name || '未命名工程'}</b><span>{p.pages} 页 · 本地工程</span></div><ChevronRight size={16}/></button>)}</div></section>}
      <footer className="welcome-footer">RESUME REBUILDER <span>无账号，无在线 AI 依赖。</span><span>先还原，再创造。</span></footer>
    </main> : page && <>
      <div className="workspace-toolbar preview-toolbar"><div className="toolbar-left"><button className={compare ? 'toolbar-active' : ''} onClick={() => setCompare(!compare)}>{compare ? <Columns2 size={16}/> : <PanelLeftClose size={16}/>}原页对照</button></div>
        <div className="zoom-controls"><button title="缩小" onClick={() => setZoom(z => Math.max(0.2,z-0.1))}><Minus size={15}/></button><span>{Math.round(zoom*100)}%</span><button title="放大" onClick={() => setZoom(z => Math.min(2,z+0.1))}><Plus size={15}/></button><button title="适应宽度" onClick={fit}><Maximize size={15}/></button></div>
      </div>
      <div className="html-edit-guide"><div><strong>先对照预览，再进入 HTML 编辑</strong><p>{htmlOpened ? '已打开过 HTML 编辑。请在编辑页保存修改后的 HTML，或从该页打印 PDF；再次打开会从当前工程生成新文件。' : '修改文字、字体、使用格式刷或更换图片，请进入 HTML 编辑。修改后请在编辑页保存 HTML 或打印 PDF。'}</p><span>这里展示工程中的识别结果，HTML 编辑页的修改不会同步到此预览。</span></div><button className="button secondary" onClick={openHtmlEditor}><ArrowUpRight size={16}/>在 HTML 中编辑</button></div>
      <div className="workspace">
        <div className={`canvas-area ${compare ? 'with-source' : ''}`}>
          {compare && <section className="canvas-column source-column"><div className="canvas-heading"><div><span className="panel-dot muted"/>原始参考<span className="micro-label">SOURCE</span></div><button title="删除原始参考" aria-label="删除原始参考" disabled={!project.referenceAvailable} onClick={deleteReference}><Trash2 size={14}/></button></div><div className="canvas-scroll"><SourcePreview project={project} pageIndex={pageIndex} zoom={zoom}/></div><div className="column-foot">原始参考仅用于对照，不参与成品导出</div></section>}
          <section className="canvas-column editor-column" ref={editorColumn}><div className="canvas-heading"><div><span className="panel-dot"/>识别结果预览<span className="micro-label">READ ONLY</span></div><span className="dimension">{Math.round(page.width)} × {Math.round(page.height)} {page.unit}</span></div><div className="canvas-scroll"><ResumePreview key={page.id} projectId={project.projectId} page={page} zoom={zoom} setOverflow={setOverflow}/></div><div className="column-foot">只读预览 · 编辑简历请点击“进入 HTML 编辑”</div></section>
        </div>
      </div>
      <footer className="statusbar"><div className="page-controls"><button disabled={pageIndex === 0} title="上一页" onClick={() => setPageIndex(i => i-1)}><ChevronLeft size={15}/></button><span>第 {pageIndex+1} / {project.pages.length} 页</span><button title="下一页" disabled={pageIndex === project.pages.length-1} onClick={() => setPageIndex(i => i+1)}><ChevronRight size={15}/></button></div><span className="status-meta">{page.sourceType === 'native-pdf' ? 'PDF 对象解析' : page.sourceType === 'blank' ? '空白页面' : '本地 OCR'} · {page.elements.length} 个元素</span><div className="status-right">{emptyCount > 0 && <span><ImagePlus size={13}/>{emptyCount} 个图片待替换</span>}{overflow.length > 0 && <span className="warning-text"><AlertTriangle size={13}/>{overflow.length} 个文字溢出</span>}{outsideCount > 0 && <span className="warning-text">{outsideCount} 个元素超出页面</span>}<button className={project.warnings.length ? 'warning-text' : ''} onClick={() => setShowWarnings(!showWarnings)}><AlertTriangle size={13}/>{project.warnings.length} 条解析提示</button><span className="status-dot"/>本地</div></footer>
      {showWarnings && <div className="warnings-popover"><div className="section-heading"><b>解析与安装提示</b><button onClick={() => setShowWarnings(false)}><X size={16}/></button></div>{project.warnings.length ? project.warnings.map((w,i) => <p key={i}>{w}</p>) : <p>暂无解析提示。复杂布局仍建议对照原页检查。</p>}{(!health.ocrReady || !health.pdfReady) && <p>安装尚未完成：{!health.ocrReady && 'OCR 模型 '}{!health.pdfReady && 'PDF 浏览器运行时'}。请运行 setup.ps1。</p>}</div>}
    </>}
    {exportDialog && project && <div className="modal-backdrop" onClick={() => !busy && setExportDialog(false)}><section className="export-dialog" role="dialog" aria-modal="true" aria-label="导出简历" onClick={event => event.stopPropagation()}><div className="section-heading"><div><span className="eyebrow">READY FOR YOUR NEXT CHAPTER</span><h2>导出你的简历</h2></div><button aria-label="关闭导出窗口" onClick={() => setExportDialog(false)}><X size={20}/></button></div><p>此处导出当前工程中的内容，不包含 HTML 编辑页的独立修改。若已在 HTML 编辑页修改简历，请回到该页保存 HTML 或打印 PDF。导出前会保存当前工程。</p><div className="export-options">{[{ value: 'pdf', label: 'PDF', desc: '投递简历 · 可选中文字', icon: FileText }, { value: 'html', label: 'HTML', desc: '独立打开 · 可编辑保存', icon: Columns2 }, { value: 'project', label: '工程包', desc: '备份工程 · 本机迁移', icon: FolderOpen }].map(f => <button className={exportFormat === f.value ? 'active' : ''} key={f.value} onClick={() => setExportFormat(f.value)}><f.icon size={23}/><b>{f.label}</b><span>{f.desc}</span></button>)}</div>{exportFormat === 'project' ? <label className="check-field"><input type="checkbox" checked={includeReference} onChange={event => setIncludeReference(event.target.checked)}/>在工程包内保留原始参考图（可能含原个人信息）</label> : <>{emptyCount > 0 && <div className="warning-box"><AlertTriangle size={17}/>{emptyCount} 个图片区尚未替换，继续导出将保留空白、背景和边框，不输出“上传图片”提示。</div>}{overflow.length > 0 && <div className="warning-box">当前页有 {overflow.length} 个文字框溢出，请进入 HTML 编辑检查文字排版，并在编辑页保存或打印。</div>}{exportOutsideCount > 0 && <div className="warning-box"><AlertTriangle size={17}/>{exportOutsideCount} 个元素超出纸张边界，{exportFormat === 'html' ? 'HTML 会扩展页面高度，打印时按纸张等比缩小；请检查固定尺寸文字和横向越界。' : 'PDF 会按页面边缘裁切。建议进入 HTML 编辑检查后从编辑页打印 PDF。'}</div>}</>}<div className="export-footer"><span>{project.pages.length} 页 · 保持页面比例</span><button className="button primary" disabled={!!busy} onClick={exportProject}><Download size={16}/>确认导出 {exportFormat === 'project' ? '工程包' : exportFormat.toUpperCase()}</button></div></section></div>}
    {busy && <div className="busy-overlay" role="status"><div><Loader2 size={27} className="spin"/><b>{busy}</b><span>全部处理在本机完成</span></div></div>}
    {notice && <div className={`toast ${notice.error ? 'error' : ''}`} role={notice.error ? 'alert' : 'status'}>{notice.error ? <AlertTriangle size={18}/> : <Check size={18}/>}<span>{notice.text}</span><button aria-label="关闭提示" onClick={() => setNotice(null)}><X size={15}/></button></div>}
  </div>
}
