"""Measure imported text with the same local browser used by HTML/PDF output."""
import os

from .browser import browser_ready,launch_browser
from .config import RUNTIME
from .models import Page,Project


def calibrate_text_widths(elements,page_width):
    if not elements or not browser_ready():
        return False
    from playwright.sync_api import sync_playwright
    from .exporter import render_html
    project = Project(projectId="font_metrics",name="字体度量",pages=[Page(id="page",width=page_width,height=5000,elements=elements)])
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",str(RUNTIME/"browsers"))
    try:
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            try:
                tab = browser.new_page()
                tab.route("**/*",lambda route:route.abort())
                tab.set_content(render_html(project))
                tab.evaluate("async()=>await document.fonts.ready")
                widths = tab.locator(".page>div>span").evaluate_all("""els=>els.map(el=>{
                    el.style.transform='none';el.style.width='max-content';el.style.whiteSpace='pre';
                    return el.getBoundingClientRect().width;
                })""")
                editor_widths = tab.locator(".page>div>span").evaluate_all("""els=>els.map(el=>{
                    el.parentElement.style.fontSize=(parseFloat(getComputedStyle(el).fontSize)*.75)+'px';
                    return el.getBoundingClientRect().width*4/3;
                })""")
                if len(widths) != len(elements):
                    return False
                for element,width,editor_width in zip(elements,widths,editor_widths):
                    width = max(width,editor_width)
                    if element.sourceRegion and element.sourceRegion.confidence is not None and element.sourceRegion.confidence < .85:
                        element.style.fontScaleX = 1
                    elif width>0:
                        element.style.fontScaleX = max(.4,min(2,(element.width-.3)*96/72/width))
                return True
            finally:
                browser.close()
    except Exception:
        # OCR and manual editing remain available if the optional browser runtime isn't installed.
        return False
