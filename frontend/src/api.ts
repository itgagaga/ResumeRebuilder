import type { Project, Asset } from './types'
export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(typeof error.detail === 'string' ? error.detail : '文档字段不合法，请检查输入值')
  }
  return response.json()
}
export const save = (project: Project) => request<Project>(`/projects/${project.projectId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(project) })
export const upload = (file: File) => { const form = new FormData(); form.append('file', file); return request<Project>('/import', { method: 'POST', body: form }) }
export const uploadAsset = (projectId: string, file: File) => { const form = new FormData(); form.append('file', file); return request<Asset>(`/projects/${projectId}/assets`, { method: 'POST', body: form }) }
export const assetUrl = (projectId: string, assetId: string) => `/api/projects/${projectId}/assets/${assetId}`
export async function exportBlob(projectId: string, format: string, includeReference: boolean) {
  const response = await fetch(`/api/projects/${projectId}/export`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ format, includeReference, confirmEmpty: true }) })
  if (!response.ok) { const error = await response.json(); throw new Error(error.detail) }
  return response.blob()
}
export async function download(projectId: string, format: string, includeReference: boolean) {
  const url = URL.createObjectURL(await exportBlob(projectId, format, includeReference))
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = format === 'html' ? 'resume-editable.html' : `resume.${format === 'project' ? 'rresume' : format}`; anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 10000)
}
