import base64
import html
import os

from .config import ROOT, RUNTIME, AppError
from .coordinates import pt_to_css
from .storage import asset_path
from .browser import launch_browser


def render_html(project):
    pages = []
    css_pages = []
    for index, page in enumerate(project.pages):
        factor = 96/72 if page.unit == "pt" else 1
        physical_factor = 1 if page.unit == "pt" else 72/96
        css_pages.append(f"@page p{index} {{size:{page.width*physical_factor}pt {page.height*physical_factor}pt;margin:0;}}")
        objects = []
        for element in sorted(page.elements, key=lambda e: e.zIndex):
            style = element.style
            radius = "50%" if element.shape == "circle" else f"{(style.borderRadius or 10)*factor}px" if element.shape == "rounded" else f"{style.borderRadius*factor}px"
            properties = (
                f"position:absolute;left:{element.x*factor}px;top:{element.y*factor}px;"
                f"width:{element.width*factor}px;height:{element.height*factor}px;"
                f"transform:rotate({element.rotation}deg);transform-origin:{'left top' if element.type == 'line' else 'center'};"
                f"z-index:{element.zIndex};box-sizing:border-box;"
                f"background:{style.background};border:{style.borderWidth*factor}px solid {style.borderColor};"
                f"border-radius:{radius};"
            )
            content = ""
            if element.type == "text":
                properties += (
                    f"font-family:{style.fontFamily};font-size:{style.fontSize*factor}px;"
                    f"font-weight:{style.fontWeight};font-style:{style.fontStyle};color:{style.color};"
                    f"line-height:{style.lineHeight};text-align:{style.textAlign};white-space:pre-wrap;overflow-wrap:break-word;"
                )
                content = (f'<span style="display:block;width:{100/style.fontScaleX}%;height:100%;transform:scaleX({style.fontScaleX});transform-origin:left top;">'
                           + html.escape(element.text) + '</span>')
            elif element.type == "image_placeholder":
                properties += "overflow:hidden;"
                if element.assetId:
                    encoded = base64.b64encode(asset_path(project, element.assetId).read_bytes()).decode("ascii")
                    crop = element.crop
                    content = (f'<img alt="" src="data:image/png;base64,{encoded}" style="width:100%;height:100%;display:block;'
                               f'object-fit:{element.fit};object-position:{50+crop.offsetX/2}% {50+crop.offsetY/2}%;'
                               f'transform:translate({crop.offsetX/2}%,{crop.offsetY/2}%) scale({crop.scale});"/>')
            objects.append(f'<div style="{html.escape(properties, quote=True)}">{content}</div>')
        pages.append(f'<section class="page" style="page:p{index};width:{page.width*factor}px;height:{page.height*factor}px;background:{page.background}">{"".join(objects)}</section>')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>' + '简历'
            + '</title><style>*{box-sizing:border-box}body{margin:0;background:#e7e9ec}.page{position:relative;margin:20px auto;overflow:hidden}'
            + ''.join(css_pages) + '@media print{body{background:white}.page{margin:0;break-after:page}.page:last-child{break-after:auto}}</style></head><body>'
            + ''.join(pages) + '</body></html>')


def render_pdf(project):
    from playwright.sync_api import sync_playwright
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(RUNTIME / "browsers"))
    try:
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            page = browser.new_page()
            # Render an isolated document. Block all network requests; only embedded user assets may load.
            page.route("**/*", lambda route: route.abort())
            page.set_content(render_html(project), wait_until="load")
            page.evaluate("async () => { await document.fonts.ready; await Promise.all(Array.from(document.images).map(i => i.decode())); }")
            result = page.pdf(print_background=True, prefer_css_page_size=True, display_header_footer=False)
            browser.close()
            return result
    except Exception as exc:
        raise AppError("PDF 导出失败，请运行安装脚本安装 Chromium 浏览器运行时，并确认字体可用", 503) from exc
