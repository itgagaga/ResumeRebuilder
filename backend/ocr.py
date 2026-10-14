import threading
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

from .config import AppError

_engine = None
_lock = threading.Lock()
MODEL_ARTIFACTS = {
    "det": ("PP-OCRv6_det_small.onnx", "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"),
    "cls": ("ch_ppocr_mobile_v2.0_cls_mobile.onnx", "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"),
    "rec": ("PP-OCRv6_rec_small.onnx", "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"),
}


def model_paths():
    import rapidocr
    root = Path(rapidocr.__file__).parent / "models"
    paths = {}
    for kind, (filename, _) in MODEL_ARTIFACTS.items():
        path = root / filename
        if not path.is_file():
            raise AppError("本地 OCR 模型缺失，请先运行安装脚本；运行期间不会下载模型")
        paths[kind] = path
    return paths


def get_engine():
    global _engine
    if _engine is None:
        from rapidocr import RapidOCR
        paths = model_paths()
        for kind, path in paths.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_ARTIFACTS[kind][1]:
                raise AppError("本地 OCR 模型校验失败，请使用锁定依赖重新安装")
        _engine = RapidOCR(params={
            "Det.model_path": str(paths["det"]),
            "Cls.model_path": str(paths["cls"]),
            "Rec.model_path": str(paths["rec"]),
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 2,
        })
    return _engine


def recognize(image: Image.Image, page_width: float, page_number: int):
    image = image.convert("RGB")
    if max(image.size) > 2400:
        image = image.copy()
        image.thumbnail((2400, 2400))
    factor = page_width / image.width
    with _lock:
        # RapidOCR expects BGR for numpy arrays but handles PIL's RGB explicitly.
        engine = get_engine()
        result = engine(image,use_det=True,use_cls=True,use_rec=True,return_word_box=True,return_single_char_box=True)
        rows = []
        if result.boxes is not None:
            attempts = 0
            for index,(box,text,score) in enumerate(zip(result.boxes,result.txts,result.scores)):
                words = result.word_results[index] if index < len(result.word_results) else ()
                row = (np.asarray(box),str(text),float(score),words)
                if score < .85 and attempts < 12:
                    attempts += 1
                    try:
                        row = retry_line(engine,image,row)
                    except Exception:
                        # A failed retry must not discard all successfully recognized rows.
                        pass
                rows.append(row)
    elements = []
    if result.boxes is None:
        return elements
    from .image_layout import recover_text, recover_bullet, char_evidence, infer_font, FONT_CHOICES
    from .typography import match_typography,smooth_typography
    rgb = np.asarray(image)
    analyses = []
    valid = []
    for index,(box,text,_,words) in enumerate(rows):
        try:
            analyses.append(match_typography(rgb,text,box,words));valid.append(index)
        except Exception:
            # Typography is best effort; a single unusual box cannot erase recognized text.
            pass
    pooled = []
    for box,text,_,words in rows[::max(1,len(rows)//8)]:
        pooled.extend(char_evidence(rgb,text,words)[:8])
    pooled_choice = infer_font(pooled)
    # infer_font also returns the default when evidence is inconclusive. Do not
    # promote that default into a hard prior that overwrites a better local match.
    if pooled_choice == FONT_CHOICES[0]: pooled_choice = None
    typography = dict(zip(valid,smooth_typography(analyses,pooled_choice)))
    bullets = []
    for index,(box,text,confidence,words) in enumerate(rows):
        try:
            element = recover_text(rgb,text,box,words,confidence,factor,page_number,typography=typography.get(index))
        except Exception:
            from .models import Element,SourceRegion,Style
            from .storage import new_id
            left,top = box.min(axis=0);right,bottom = box.max(axis=0)
            element = Element(id=new_id('text'),type='text',text=text,x=float(left*factor),y=float(top*factor),width=float(max(1,right-left)*factor),height=float(max(1,bottom-top)*factor),
                              style=Style(fontSize=float(max(5,min(500,(bottom-top)*.85*factor)))),
                              sourceRegion=SourceRegion(detectedFrom='ocr-style-fallback',page=page_number,confidence=confidence,sourceFont='样式估计未完成，请校对'))
        bullet = recover_bullet(rgb,element,box,factor,page_number)
        if bullet: bullets.append(bullet)
        elements.append(element)
    from .font_metrics import calibrate_text_widths
    calibrate_text_widths(elements,page_width)
    return elements+bullets


def retry_line(engine,image,row):
    """Re-detect a weak line without orientation classification; preserve source coordinates."""
    box,text,score,words = row
    left,top = np.floor(box.min(axis=0)).astype(int)
    right,bottom = np.ceil(box.max(axis=0)).astype(int)
    left,top,right,bottom = max(0,left-3),max(0,top-3),min(image.width,right+3),min(image.height,bottom+3)
    if right <= left or bottom <= top: return row
    retry = engine(image.crop((left,top,right,bottom)),use_det=True,use_cls=False,use_rec=True,return_word_box=True,return_single_char_box=True)
    if retry.boxes is None: return row
    candidates = []
    for i,(candidate_box,candidate_text,candidate_score) in enumerate(zip(retry.boxes,retry.txts,retry.scores)):
        mapped = np.asarray(candidate_box)+[left,top]
        if abs(mapped[:,1].mean()-box[:,1].mean()) > (bottom-top)*.4: continue
        if np.ptp(mapped[:,0]) < np.ptp(box[:,0])*.65: continue
        candidate_words = retry.word_results[i] if i < len(retry.word_results) else ()
        shifted = [(char,confidence,(np.asarray(quad)+[left,top]).tolist()) for char,confidence,quad in candidate_words if quad is not None]
        candidates.append((mapped,str(candidate_text),float(candidate_score),shifted))
    if not candidates: return row
    best = max(candidates,key=lambda candidate:len(candidate[1].strip())*candidate[2])
    if best[2] >= .85 and best[2] > score+.05 and len(best[1].strip()) >= len(text.strip()): return best
    return row
