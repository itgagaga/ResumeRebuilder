import base64
import html
import os

from .config import ROOT, RUNTIME, AppError
from .storage import asset_path
from .browser import launch_browser


def text_html(element):
    parts, cursor = [], 0
    for run in element.textRuns:
        parts.append(html.escape(element.text[cursor:run.start]))
        parts.append(f'<span style="font-weight:{run.fontWeight}">{html.escape(element.text[run.start:run.end])}</span>')
        cursor = run.end
    parts.append(html.escape(element.text[cursor:]))
    return ''.join(parts)


def render_html(project, *, editable=False):
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
            if element.shape == "polygon":
                points = ','.join(f'{x*100:.4f}% {y*100:.4f}%' for x,y in element.shapePoints)
                properties += f"clip-path:polygon({points});"
            attributes = ""
            if editable:
                attributes = (f' data-resume-element="{element.id}" data-kind="{element.type}"'
                              f' data-layout="{element.textLayout}" data-flow="{str(element.flowBelow).lower()}"'
                              f' data-scale="{style.fontScaleX}"')
            if element.type == "text":
                properties += (
                    f"font-family:{style.fontFamily};font-size:{style.fontSize*factor}px;"
                    f"font-weight:{style.fontWeight};font-style:{style.fontStyle};color:{style.color};"
                    f"line-height:{style.lineHeight};text-align:{style.textAlign};white-space:pre-wrap;overflow-wrap:break-word;"
                )
                tag = "div" if editable else "span"
                editor_attributes = ' data-resume-text contenteditable="true" spellcheck="false" role="textbox" aria-label="编辑简历文字" aria-multiline="true"' if editable else ""
                # Layout zoom retains effective small-size glyph metrics while
                # keeping the specified CSS font above browser minimum settings.
                zoom = min(1,style.fontSize*factor/100)
                height = "auto;min-height:100%" if editable else "100%"
                content = (f'<{tag}{editor_attributes} style="display:block;font-size:{style.fontSize*factor/zoom}px;line-height:{style.lineHeight};zoom:{zoom};width:{100/style.fontScaleX}%;height:{height};transform:scaleX({style.fontScaleX});transform-origin:left top;">'
                           + text_html(element) + f'</{tag}>')
            elif element.type == "image_placeholder":
                properties += "overflow:hidden;"
                if element.assetId:
                    encoded = base64.b64encode(asset_path(project, element.assetId).read_bytes()).decode("ascii")
                    crop = element.crop
                    content = (f'<img alt="" src="data:image/png;base64,{encoded}" style="width:100%;height:100%;display:block;'
                               f'object-fit:{element.fit};object-position:{50+crop.offsetX/2}% {50+crop.offsetY/2}%;'
                               f'transform:translate({crop.offsetX/2}%,{crop.offsetY/2}%) scale({crop.scale});"/>')
            objects.append(f'<div{attributes} style="{html.escape(properties, quote=True)}">{content}</div>')
        page_content = "".join(objects)
        page_attributes = ""
        if editable:
            page_attributes = f' data-base-width="{page.width*factor}" data-base-height="{page.height*factor}"'
            page_content = f'<div class="resume-content" style="position:relative;width:100%;height:100%">{page_content}</div>'
            css_pages.append(f'@media print{{.page:nth-of-type({index+1}){{width:{page.width*factor}px!important;height:{page.height*factor}px!important}}}}')
        pages.append(f'<section class="page"{page_attributes} style="page:p{index};width:{page.width*factor}px;height:{page.height*factor}px;background:{page.background}">{page_content}</section>')
    editor_css = editor_ui = editor_script = editor_policy = ""
    if editable:
        editor_policy = ('<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; '
                         'img-src data: blob:; style-src &#39;unsafe-inline&#39;; script-src &#39;unsafe-inline&#39;; '
                         'base-uri &#39;none&#39;; form-action &#39;none&#39;">')
        editor_css = (ROOT / "backend" / "standalone_editor.css").read_text(encoding="utf-8")
        editor_script = '<script>' + (ROOT / "backend" / "standalone_editor.js").read_text(encoding="utf-8") + '</script>'
        editor_ui = ('<nav class="resume-toolbar" aria-label="简历编辑工具" data-editor-ui>'
                     '<button type="button" id="resume-save">保存修改后的 HTML</button>'
                     '<button type="button" id="resume-bold" aria-pressed="false" title="选中文字后点击，也可按 Ctrl+B"><b>B</b> 加粗 / 取消加粗</button>'
                     '<button type="button" id="resume-font-brush" aria-pressed="false" title="先选源文字，单击刷一次，双击连续刷；Esc 取消">格式刷（字体）</button>'
                     '<button type="button" id="resume-photo">更换图片</button>'
                     '<button type="button" id="resume-print">打印 / 导出 PDF</button>'
                     '<label>文字排版 <select id="resume-layout" aria-label="文字排版" disabled>'
                     '<option value="auto">先扩宽，再换行</option><option value="paragraph">固定宽度，自动增减高度</option>'
                     '<option value="wrap">固定宽度，只增高</option><option value="fixed">固定尺寸</option></select></label>'
                     '<input id="resume-photo-file" type="file" accept="image/png,image/jpeg,image/webp" hidden></nav>'
                     '<p class="resume-hint" id="resume-hint" role="status" data-editor-ui>点击文字即可修改；点击图片可更换。保存会下载包含修改的新 HTML 文件，无需启动本地服务。</p>'
                     '<noscript data-editor-ui>请在浏览器中启用 JavaScript，才能保存修改和更换图片。</noscript>')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>' + '简历'
            + '</title><meta name="viewport" content="width=device-width,initial-scale=1">' + editor_policy + '<style>*{box-sizing:border-box}body{margin:0;background:#e7e9ec}.page{position:relative;margin:20px auto;overflow:hidden}'
            + ''.join(css_pages) + '@media print{body{background:white}.page{margin:0;break-after:page}.page:last-of-type{break-after:auto}}'
            + editor_css + '</style></head><body>' + editor_ui + ''.join(pages) + editor_script + '</body></html>')


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
