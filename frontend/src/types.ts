export interface Style {
  fontFamily: string; fontSize: number; fontScaleX: number; fontWeight: number; fontStyle: 'normal' | 'italic';
  color: string; background: string; borderColor: string; borderWidth: number; borderRadius: number;
  lineHeight: number; textAlign: 'left' | 'center' | 'right' | 'justify'
}
export interface Element {
  id: string; type: 'text' | 'image_placeholder' | 'rect' | 'line'; x: number; y: number; width: number; height: number;
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
