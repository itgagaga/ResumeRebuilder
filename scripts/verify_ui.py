"""Exercise the built UI and real API with fictional data in an isolated directory."""
import io
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import pdfplumber
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["RESUME_DATA_DIR"] = str(ROOT/"artifacts/ui-workflow/projects")
from backend.browser import launch_browser
from backend.main import app
from fastapi.testclient import TestClient


def main():
    output = ROOT / "artifacts"
    output.mkdir(exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / "runtime" / "browsers")
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        context = browser.new_context(viewport={"width":1440,"height":960}, accept_downloads=True)
        errors, external = [], []
        context.on("page", lambda tab: tab.on("pageerror", lambda exc: errors.append(str(exc))))
        def route_local(route):
            request = route.request
            url = urlparse(request.url)
            if url.scheme not in {"http", "https"}:
                route.continue_(); return
            if url.hostname != "127.0.0.1":
                external.append(request.url); route.abort(); return
            response = client.request(request.method, url.path, content=request.post_data_buffer,
                                      headers=request.headers)
            route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)
        context.route("**/*", route_local)
        page = context.new_page()
        page.goto("http://127.0.0.1:8765",wait_until="networkidle")
        expect(page.get_by_role("heading",level=1)).to_contain_text("写下自己的故事")
        page.screenshot(path=output/"welcome.png",full_page=True)
        page.get_by_role("button",name="体验示例").click()
        expect(page.get_by_label("工程名称")).to_be_visible(timeout=60000)
        expect(page.locator('[data-text-id]').filter(has_text="张三")).to_have_count(1)
        expect(page.locator('[contenteditable="true"], .tool-rail, .inspector')).to_have_count(0)
        expect(page.get_by_role("button",name="高级调整",exact=True)).to_have_count(0)
        page.screenshot(path=output/"preview.png",full_page=True)
        page.locator('[title="下一页"]').click()
        expect(page.get_by_text("第 2 / 2 页",exact=True)).to_be_visible()
        expect(page.locator('[data-text-id]').filter(has_text="项目经历")).to_have_count(1)
        page.locator('[title="上一页"]').click()

        with page.expect_popup() as opened:
            page.get_by_role("button",name="进入 HTML 编辑",exact=True).click()
        html = opened.value
        name = html.locator('[data-resume-text]').filter(has_text="张三")
        name.fill("李四")
        expect(page.locator('[data-text-id]').filter(has_text="张三")).to_have_count(1)
        photo = html.locator('[data-kind="image_placeholder"]').first
        photo.click()
        html.locator('#resume-photo-file').set_input_files(ROOT/"examples/replacement.png")
        expect(photo.locator('img')).to_have_count(1)
        with html.expect_download() as saved:
            html.locator('#resume-save').click()
        html_path = output/"edited-resume.html"
        saved.value.save_as(html_path)
        html.goto(html_path.as_uri())
        expect(html.locator('[data-resume-text]').filter(has_text="李四")).to_have_count(1)
        expect(html.locator('[data-kind="image_placeholder"] img')).to_have_count(1)
        pdf_bytes = html.pdf(print_background=True,prefer_css_page_size=True)
        (output/"edited-resume.pdf").write_bytes(pdf_bytes)
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            assert "李四" in text and "张三" not in text
            assert len(pdf.pages) == 2 and len(pdf.pages[0].images) == 1
        html.close()

        # A project package retains the source model, independent of HTML edits.
        page.get_by_role("button",name="导出",exact=True).click()
        page.get_by_role("button",name="工程包",exact=False).click()
        with page.expect_download() as package:
            page.get_by_role("button",name="确认导出 工程包").click()
        project_path = output/"source-resume.rresume"
        package.value.save_as(project_path)
        page.locator('input[type=file]').set_input_files(project_path)
        expect(page.locator('[data-text-id]').filter(has_text="张三")).to_have_count(1,timeout=30000)
        expect(page.locator('[contenteditable="true"], .tool-rail, .inspector')).to_have_count(0)
        assert not errors, errors
        assert not external, external
        browser.close()
        print("UI workflow passed: import, read-only preview/pages, HTML edit/photo/save/reopen/PDF, project package isolation. No external requests or JS errors.")


if __name__ == "__main__": main()
