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
        result = get_engine()(image,return_word_box=True,return_single_char_box=True)
    elements = []
    if result.boxes is None:
        return elements
    from .image_layout import recover_text, infer_font, char_evidence, recover_bullet
    rgb = np.asarray(image)
    samples = []
    for index in range(0,len(result.txts),max(1,len(result.txts)//8)):
        if index < len(result.word_results):
            samples.extend(char_evidence(rgb,str(result.txts[index]),result.word_results[index])[:8])
    choice = infer_font(samples)
    bullets = []
    for index,(box, text, confidence) in enumerate(zip(result.boxes, result.txts, result.scores)):
        words = result.word_results[index] if index < len(result.word_results) else ()
        element = recover_text(rgb,str(text),box,words,confidence,factor,page_number,choice)
        bullet = recover_bullet(rgb,element,box,factor,page_number)
        if bullet: bullets.append(bullet)
        elements.append(element)
    from .font_metrics import calibrate_text_widths
    calibrate_text_widths(elements,page_width)
    return elements+bullets
