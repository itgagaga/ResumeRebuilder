import io
import math
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageFont

from .config import AppError, MAX_PAGES
from .models import Element, Page, Project, SourceRegion, Style
from .ocr import recognize
from .storage import decode_image, new_id, project_dir


def color(value, default="#222222"):
    if value is None:
        return default
    if isinstance(value, (float, int)):
        value = (value, value, value)
    if len(value) == 4:
        c, m, y, k = value
        value = (1-min(1, c+k), 1-min(1, m+k), 1-min(1, y+k))
    if len(value) == 1:
        value = value * 3
    try:
        return "#" + "".join(f"{max(0, min(255, round(float(v)*255))):02x}" for v in value[:3])
    except (TypeError, ValueError):
        return default


def text_lines(chars, origin, page_number):
    # Group characters by baseline, style and distance; preserve the extracted original text.
    groups = []
    rotated = [c for c in chars if not c.get("upright", True)]
    for char in sorted([c for c in chars if c.get("upright", True)], key=lambda c: (round(c["top"] / 2) * 2, c["x0"])):
        if not char.get("text") or char.get("size", 0) <= 0:
            continue
        last = groups[-1] if groups else None
        size = char["size"]
        previous = last[-1] if last else None
        same = previous and abs(char["top"]-previous["top"]) < max(2, size*0.25)
        same = same and char.get("fontname") == previous.get("fontname") and abs(size-previous["size"]) < 0.5
        same = same and char["x0"] - previous["x1"] < size * 2.2 and char["x0"] >= previous["x0"]
        same = same and char.get("non_stroking_color") == previous.get("non_stroking_color")
        if same:
            last.append(char)
        else:
            groups.append([char])
    elements = []
    for group in groups:
        first = group[0]
        text = ""
        prev = None
        for ch in group:
            if prev and ch["x0"]-prev["x1"] > first["size"]*0.23 and not text.endswith(" ") and ch["text"] != " ":
                text += " "
            text += ch["text"]
            prev = ch
        if not text.strip():
            continue
        x0 = min(c["x0"] for c in group)
        y0 = min(c["top"] for c in group)
        font = first.get("fontname", "").lower()
        family = "SimSun, Georgia, serif" if any(f in font for f in ("song", "simsun")) else "Georgia, SimSun, serif" if "times" in font else "Arial, Microsoft YaHei, sans-serif"
        width = max(1, max(c["x1"] for c in group)-x0+2)
        elements.append(Element(
            id=new_id("text"), type="text", x=x0-origin[0], y=y0-origin[1],
            width=width,
            height=max(1, max(c["bottom"] for c in group)-y0, first["size"]*1.3),
            zIndex=2, text=text,
            style=Style(fontFamily=family, fontSize=min(500, first["size"]), fontScaleX=estimate_font_scale(text, family, first["size"], width),
                        fontWeight=700 if any(f in font for f in ("bold", "black", "heavy")) else 400,
                        fontStyle="italic" if "italic" in font or "oblique" in font else "normal",
                        color=color(first.get("non_stroking_color"))),
            sourceRegion=SourceRegion(detectedFrom="pdf-text", page=page_number, sourceFont=first.get("fontname", "")[:200]),
        ))
    elements.extend(rotated_text_lines(rotated, origin, page_number))
    return elements


def estimate_font_scale(text, family, size, width):
    # Preserve native line width even when PDF fonts are unavailable locally. Store only a numeric
    # metric correction, never a backup copy of the original text. Editing still wraps and warns.
    if family.startswith("SimSun"):
        candidates = ["C:/Windows/Fonts/simsun.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
    elif family.startswith("Georgia"):
        candidates = ["C:/Windows/Fonts/georgia.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf"]
    else:
        # CJK glyphs in the Arial stack resolve to Microsoft YaHei.
        candidates = ["C:/Windows/Fonts/msyh.ttc"] if any(ord(c)>127 for c in text) else ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    path = next((p for p in candidates if Path(p).exists()), None)
    if not path:
        return 1
    try:
        metric_font = ImageFont.truetype(path, max(1, round(size*4)))
        measured = metric_font.getlength(text)/4
        return max(0.4, min(2, (width-1)/max(1,measured)))
    except OSError:
        return 1


def rotated_text_lines(chars, origin, page_number):
    """Group rotated glyphs along their actual baseline instead of emitting one box per character."""
    projected = []
    for ch in chars:
        if not ch.get("text") or ch.get("size", 0) <= 0:
            continue
        a, b, *_ = ch.get("matrix", (0, -1, 1, 0, 0, 0))
        angle = round(-math.degrees(math.atan2(b, a)), 1)
        rad = math.radians(angle)
        u = (math.cos(rad), math.sin(rad))
        v = (-math.sin(rad), math.cos(rad))
        corners = [(x, y) for x in (ch["x0"], ch["x1"]) for y in (ch["top"], ch["bottom"])]
        us, vs = [x*u[0]+y*u[1] for x,y in corners], [x*v[0]+y*v[1] for x,y in corners]
        projected.append((angle, (min(vs)+max(vs))/2, min(us), max(us), ch))
    groups = []
    for item in sorted(projected, key=lambda c: (c[0], round(c[1]/3)*3, c[2])):
        previous = groups[-1][-1] if groups else None
        if previous and item[0] == previous[0] and abs(item[1]-previous[1]) < 4 and item[2]-previous[3] < max(4, item[4]["size"]*2) and item[4].get("fontname") == previous[4].get("fontname"):
            groups[-1].append(item)
        else:
            groups.append([item])
    result = []
    for group in groups:
        text = "".join(item[4]["text"] for item in group)
        if not text.strip():
            continue
        x0, x1 = min(i[4]["x0"] for i in group), max(i[4]["x1"] for i in group)
        y0, y1 = min(i[4]["top"] for i in group), max(i[4]["bottom"] for i in group)
        size = max(i[3]-i[2] for i in group if i[4]["text"].strip())
        # PDF rotated char.size may be the glyph width; transverse extent is a better font-height estimate.
        height = max(1, abs((x1-x0)*math.sin(math.radians(group[0][0]))) + abs((y1-y0)*math.cos(math.radians(group[0][0]))))
        width = max(i[3] for i in group)-min(i[2] for i in group)+2
        size = min(500, height)
        result.append(Element(id=new_id("text"),type="text", text=text,
                              x=(x0+x1)/2-width/2-origin[0], y=(y0+y1)/2-height*1.3/2-origin[1],
                              width=max(1,width),height=height*1.3,rotation=group[0][0],zIndex=2,
                              style=Style(fontSize=size,color=color(group[0][4].get("non_stroking_color"))),
                              sourceRegion=SourceRegion(detectedFrom="pdf-text",page=page_number)))
    return result


def pdf_elements(page, page_number):
    origin = page.bbox[:2]
    elements = text_lines(page.chars, origin, page_number)
    for rect in page.rects:
        if rect["width"] < 0.1 or rect["height"] < 0.1:
            continue
        elements.append(Element(
            id=new_id("rect"), type="rect", x=rect["x0"]-origin[0], y=rect["top"]-origin[1],
            width=min(10000, rect["width"]), height=min(10000, rect["height"]), zIndex=0,
            style=Style(background=color(rect.get("non_stroking_color"), "transparent") if rect.get("fill") else "transparent",
                        borderColor=color(rect.get("stroking_color")),
                        borderWidth=min(100, rect.get("linewidth", 1) or 1) if rect.get("stroke") else 0),
        ))
    for line in page.lines:
        x0, y0, x1, y1 = line["x0"], line["top"], line["x1"], line["bottom"]
        # pdfplumber's endpoints preserve direction for diagonal lines.
        pts = line.get("pts")
        if pts and len(pts) >= 2:
            (x0, y0), (x1, y1) = pts[0], pts[-1]
        length = math.hypot(x1-x0, y1-y0)
        if length < 0.1:
            continue
        elements.append(Element(
            id=new_id("line"), type="line", x=x0-origin[0], y=y0-origin[1], width=min(10000, length),
            height=max(0.5, min(100, line.get("linewidth", 1) or 1)), rotation=math.degrees(math.atan2(y1-y0, x1-x0)),
            zIndex=1, style=Style(background=color(line.get("stroking_color"))),
        ))
    # Metadata only: never call image streams, decode an embedded image, or copy source pixels into assets.
    for image in page.images:
        if image["width"] * image["height"] >= page.width * page.height * 0.8:
            continue
        elements.append(Element(
            id=new_id("photo"), type="image_placeholder", x=image["x0"]-origin[0], y=image["top"]-origin[1],
            width=max(1, min(10000, image["width"])), height=max(1, min(10000, image["height"])), zIndex=3,
            style=Style(background="#f0f3f5"),
            sourceRegion=SourceRegion(detectedFrom="pdf-image-bbox", page=page_number),
        ))
    return elements


def import_source(data, name, project_id=None):
    project = Project(projectId=project_id or new_id(), name=name[:150] or "未命名工程", pages=[Page(id=new_id("page"), width=595, height=842)])
    references = project_dir(project.projectId) / "reference"
    references.mkdir(parents=True)
    project.pages = []
    if data[:5] == b"%PDF-":
        try:
            with pdfplumber.open(io.BytesIO(data)) as document, pdfium.PdfDocument(data) as renderer:
                if not 1 <= len(document.pages) <= MAX_PAGES:
                    raise AppError(f"PDF 页数须在 1～{MAX_PAGES} 页之间")
                for number, native_page in enumerate(document.pages, 1):
                    cropped = native_page
                    if native_page.cropbox and native_page.cropbox != native_page.bbox:
                        cropped = native_page.crop(native_page.cropbox)
                    width, height = cropped.width, cropped.height
                    if width > 3000 or height > 5000 or width <= 0 or height <= 0:
                        raise AppError("PDF 页面尺寸超限")
                    rendered_page = renderer[number-1]
                    scale = min(2, 2400 / max(width, height))
                    bitmap = rendered_page.render(scale=scale)
                    image = bitmap.to_pil().convert("RGB")
                    image.save(references / f"{number}.png")
                    bitmap.close()
                    rendered_page.close()
                    large_scan = any(i["width"]*i["height"] >= width*height*0.8 for i in cropped.images)
                    native_text = "".join(ch.get("text", "") for ch in cropped.chars).strip()
                    scanned = large_scan and len(native_text) < 10 or not native_text
                    if scanned:
                        elements = safe_ocr(image, width, number, project)
                        source_type = "scan-pdf"
                    else:
                        elements = pdf_elements(cropped, number)
                        source_type = "native-pdf"
                        if cropped.curves:
                            project.warnings.append(f"第 {number} 页包含复杂曲线/遮罩，请对照原页手动校正形状和图片边界。")
                        if any(not ch.get("upright", True) for ch in cropped.chars):
                            project.warnings.append(f"第 {number} 页包含旋转文字，请检查方向与位置。")
                    project.pages.append(Page(id=new_id("page"), width=width, height=height, sourceType=source_type, elements=elements))
        except AppError:
            raise
        except Exception as exc:
            raise AppError("PDF 损坏、已加密或无法解析，请尝试未加密的 PDF") from exc
    else:
        image = decode_image(data)
        image.save(references / "1.png")
        width, height = 595.28, 595.28 * image.height / image.width
        if height > 5000:
            raise AppError("图片长宽比过大，请按页面切分")
        project.pages.append(Page(id=new_id("page"), width=width, height=height, sourceType="image",
                                  elements=safe_ocr(image, width, 1, project)))
    project.referenceAvailable = True
    return project


def safe_ocr(image, width, number, project):
    try:
        elements = recognize(image, width, number)
        project.warnings.append(f"第 {number} 页使用本地 OCR，字体、颜色与识别文字需要人工校对；可在原页框选图片区。")
        if not elements:
            project.warnings.append(f"第 {number} 页未识别到文字，可手动新增文字框。")
        return elements
    except Exception:
        project.warnings.append(f"第 {number} 页 OCR 不可用或识别失败，请检查本地安装；仍可手动新增文字和图片区。")
        return []
