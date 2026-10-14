export type Tool = 'select' | 'text' | 'image_placeholder' | 'rect' | 'line'
export interface Style {
  fontFamily: string; fontSize: number; fontScaleX: number; fontWeight: number; fontStyle: 'normal' | 'italic';
  color: string; background: string; borderColor: string; borderWidth: number; borderRadius: number;
  lineHeight: number; textAlign: 'left' | 'center' | 'right' | 'justify'
}
export interface Element {
  id: string; type: Exclude<Tool, 'select'>; x: number; y: number; width: number; height: number;
  rotation: number; zIndex: number; text: string; textRuns: { start: number; end: number; fontWeight: number }[]; style: Style; shape: 'rect' | 'circle' | 'rounded' | 'polygon';
  shapePoints?: [number, number][];
  textLayout?: 'auto' | 'wrap' | 'fixed' | 'paragraph'; flowBelow?: boolean;
  assetId: string | null; fit: 'cover' | 'contain'; crop: { scale: number; offsetX: number; offsetY: number };
  sourceRegion: { detectedFrom: string; page: number; confidence: number | null; sourceFont?: string | null } | null;
}
export interface Asset { id: string; filename: string; width: number; height: number; mime: 'image/png' }
export interface Page { id: string; width: number; height: number; unit: 'pt' | 'px'; background: string; elements: Element[]; sourceType: 'blank' | 'image' | 'native-pdf' | 'scan-pdf' }
export interface Project {
  schemaVersion: '1.0.0'; projectId: string; name: string; pages: Page[]; assets: Record<string, Asset>;
  warnings: string[]; referenceAvailable: boolean
}
export const id = () => `el_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`
export const defaultStyle: Style = { fontFamily: 'Arial, Microsoft YaHei, sans-serif', fontSize: 12, fontScaleX: 1, fontWeight: 400, fontStyle: 'normal', color: '#222222', background: 'transparent', borderColor: '#b8c2cc', borderWidth: 0, borderRadius: 0, lineHeight: 1.15, textAlign: 'left' }
export function createElement(type: Element['type'], x = 50, y = 50, width = 180, height = 28): Element {
  return { id: id(), type, x, y, width, height, rotation: 0, zIndex: 2, text: type === 'text' ? '点击编辑文字' : '', textRuns: [], textLayout: 'auto', flowBelow: true, style: { ...defaultStyle, ...(type === 'image_placeholder' ? { background: '#f0f3f5' } : type === 'rect' ? { background: '#e5ece8' } : type === 'line' ? { background: '#36594a' } : {}) }, shape: 'rect', assetId: null, fit: 'cover', crop: { scale: 1, offsetX: 0, offsetY: 0 }, sourceRegion: null }
}
