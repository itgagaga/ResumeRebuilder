import { ScanLine } from 'lucide-react'
import type { Project } from './types'

export default function SourcePreview({ project, pageIndex, zoom }: { project: Project; pageIndex: number; zoom: number }) {
  const page = project.pages[pageIndex], scale = zoom * (page.unit === 'pt' ? 96/72 : 1)
  return <div className="source-paper" style={{ width: page.width*scale, height: page.height*scale }}>
    {project.referenceAvailable ? <img draggable={false} src={`/api/projects/${project.projectId}/reference/${pageIndex+1}`} alt={`原始参考第 ${pageIndex+1} 页`} /> : <div className="no-source"><ScanLine size={32}/><h3>暂无原始参考</h3><p>本工程未保留原始参考图。<br/>可重新导入源文件进行对照。</p></div>}
  </div>
}
