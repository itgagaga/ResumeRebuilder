"""Exercise the actual browser workflow against the running local server."""
import io
import os
import sys
from pathlib import Path

import pdfplumber
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.browser import launch_browser


def main():
    output = ROOT / "artifacts"
    output.mkdir(exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / "runtime" / "browsers")
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        page = browser.new_page(viewport={"width":1440,"height":960}, device_scale_factor=1)
        errors, external = [], []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("request", lambda req: external.append(req.url) if not req.url.startswith(("http://127.0.0.1:8765", "data:", "blob:")) else None)
        page.goto("http://127.0.0.1:8765",wait_until="networkidle")
        expect(page.get_by_role("heading",level=1)).to_contain_text("写下自己的故事")
        page.screenshot(path=output/"welcome.png",full_page=True)
        page.get_by_role("button",name="体验示例").click()
        expect(page.get_by_label("工程名称")).to_be_visible(timeout=60000)
        expect(page.locator('[data-text-id]').filter(has_text="张三")).to_have_count(1)
        expect(page.locator(".photo-empty")).to_have_count(1)
        name = page.locator('[data-text-id]').filter(has_text="张三")
        name.dblclick()
        expect(page.get_by_label("直接编辑文字")).to_be_visible()
        page.get_by_label("直接编辑文字").fill("李四")
        page.get_by_label("直接编辑文字").press("Escape")
        expect(page.get_by_label("文字内容")).to_have_value("李四")
        # Undo/redo must update the actual document text.
        page.locator('[title="撤销 Ctrl+Z"]').click()
        expect(page.locator('[data-text-id]').filter(has_text="张三")).to_have_count(1)
        page.locator('[title="重做 Ctrl+Y"]').click()
        expect(page.locator('[data-text-id]').filter(has_text="李四")).to_have_count(1)
        # Dragging is expressed in page units, independent of display zoom.
        name = page.locator('[data-text-id]').filter(has_text="李四")
        rect = name.bounding_box()
        page.mouse.move(rect['x']+rect['width']/2,rect['y']+rect['height']/2)
        page.mouse.down(); page.mouse.move(rect['x']+rect['width']/2+20,rect['y']+rect['height']/2+10,steps=5); page.mouse.up()
        expect(page.get_by_label("文字内容")).to_have_value("李四")
        page.locator('[data-element-id]').filter(has=page.locator('.photo-empty')).click()
        page.locator('input[type=file]').nth(1).set_input_files(ROOT/"examples"/"replacement.png")
        expect(page.locator('img[alt="用户上传的图片"]')).to_have_count(1,timeout=10000)
        page.get_by_role("combobox",name="外形").select_option("circle")
        page.locator('.range-field input').nth(0).fill('1.5')
        page.locator('.range-field input').nth(1).fill('20')
        # Save and export current content; inspect the actual PDF rather than only the response type.
        page.get_by_role("button",name="保存",exact=True).click()
        expect(page.locator('.save-state')).to_contain_text("已保存",timeout=10000)
        page.screenshot(path=output/"editor.png",full_page=True)
        page.get_by_role("button",name="导出",exact=True).click()
        with page.expect_download(timeout=60000) as download:
            page.get_by_role("button",name="确认导出 PDF").click()
        pdf_path = output/"edited-resume.pdf"
        download.value.save_as(pdf_path)
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            assert "李四" in text and "张三" not in text
            assert len(pdf.pages) == 2
            assert len(pdf.pages[0].images) == 1
        # Download and re-import the project package through the visible UI.
        page.get_by_role("button",name="导出",exact=True).click()
        page.get_by_role("button",name="工程包",exact=False).click()
        with page.expect_download() as package:
            page.get_by_role("button",name="确认导出 工程包").click()
        project_path = output/"edited-resume.rresume"
        package.value.save_as(project_path)
        page.locator('input[type=file]').nth(0).set_input_files(project_path)
        expect(page.locator('[data-text-id]').filter(has_text="李四")).to_have_count(1,timeout=30000)
        expect(page.locator('img[alt="用户上传的图片"]')).to_have_count(1)
        # Create a manual photo region on the original page; existing text must remain.
        before = page.locator('[data-text-id]').count()
        page.get_by_role("button",name="框选图片区",exact=True).click()
        source = page.locator('.source-paper').bounding_box()
        page.mouse.move(source['x']+50, source['y']+100); page.mouse.down(); page.mouse.move(source['x']+100, source['y']+150,steps=5); page.mouse.up()
        expect(page.locator('.photo-empty')).to_have_count(1)
        assert page.locator('[data-text-id]').count() == before
        # Long input is visibly diagnosed rather than silently lost.
        page.locator('[data-text-id]').filter(has_text="李四").click()
        page.get_by_role("combobox",name="内容增长").select_option("fixed")
        page.get_by_label("文字内容").fill("这是一段用于测试文字溢出的长内容"*8)
        expect(page.get_by_text("文字超出边界，请扩大文本框或缩小字号。")).to_be_visible(timeout=10000)
        # Exercise pagination.
        page.locator('[title="下一页"]').click()
        expect(page.get_by_text("第 2 / 2 页",exact=True)).to_be_visible()
        expect(page.locator('[data-text-id]').filter(has_text="项目经历")).to_have_count(1)
        assert not errors, errors
        assert not external, external
        browser.close()
        print("UI workflow passed: edit, undo/redo, drag, photo crop, save, PDF export, project reopen, manual region, overflow, pagination. No external requests or JS errors.")


if __name__ == "__main__": main()
