"""Verify content editing and paragraph reconstruction against an isolated API."""
import io
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.models import Element, Page, Project, Style
from backend.browser import launch_browser
from backend.exporter import render_html, render_pdf
from playwright.sync_api import expect, sync_playwright
import pdfplumber


def fixture():
    body = Style(fontSize=12, lineHeight=1.5)
    return Project(projectId="document_editing", name="段落编辑验收", pages=[Page(id="page", width=595, height=842, elements=[
        Element(id="name", type="text", text="虚构用户", x=40, y=25, width=160, height=30, style=Style(fontSize=22),sourceRegion={"detectedFrom":"ocr","page":1,"confidence":.6}),
        Element(id="line1", type="text", text="负责简历编辑产品的页面开发与维护，持续改善文字输入和排版体验，", x=40, y=80, width=440, height=20, style=body, textRuns=[{"start":2,"end":6,"fontWeight":700}]),
        Element(id="line2", type="text", text="支持将识别得到的连续正文整理为段落，方便统一修改和保存，", x=40, y=103, width=440, height=20, style=body, textRuns=[{"start":0,"end":2,"fontWeight":700}]),
        Element(id="line3", type="text", text="在本机完成全部编辑流程。", x=40, y=126, width=220, height=20, style=body),
        Element(id="side", type="text", text="独立栏", x=510, y=151, width=60, height=20, style=body),
        Element(id="heading-bg", type="rect", x=30, y=182, width=535, height=28),
        Element(id="heading", type="text", text="专业技能", x=40, y=185, width=500, height=22, style=Style(fontSize=16,fontWeight=700)),
        Element(id="following", type="text", text="后续内容", x=40, y=225, width=440, height=20, style=body),
        Element(id="following-side", type="text", text="2026", x=510, y=225, width=55, height=20, style=body),
        Element(id="list1", type="text", text="1. 第一项保持为独立列表项目，不能随意连接到下一项。", x=40, y=270, width=440, height=20, style=body),
        Element(id="list2", type="text", text="2. 第二项也保留列表边界。", x=40, y=293, width=440, height=20, style=body),
        Element(id="bullet1", type="rect", shape="circle", x=28, y=342, width=4, height=4),
        Element(id="bullet-text1", type="text", text="这是使用独立图形圆点的第一项，也应保留独立段落边界。", x=40, y=335, width=440, height=20, style=body),
        Element(id="bullet2", type="rect", shape="circle", x=28, y=365, width=4, height=4),
        Element(id="bullet-text2", type="text", text="这是下一条独立的列表内容。", x=40, y=358, width=440, height=20, style=body),
    ]), Page(id="page2", width=595, height=842, elements=[Element(id="page2text",type="text",text="第二页独立内容",x=40,y=40,width=300,height=25)])])


def main():
    output = ROOT / "artifacts/document-editing"
    output.mkdir(parents=True, exist_ok=True)
    os.environ["RESUME_DATA_DIR"] = str(output / "projects")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / "runtime/browsers")
    original = fixture().model_dump()
    saved = [original]
    errors, external = [], []
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        tab = browser.new_page(viewport={"width":1700,"height":1100})
        tab.on("pageerror", lambda exc: errors.append(str(exc)))

        def handler(route):
            url = urlparse(route.request.url)
            if url.hostname != "127.0.0.1":
                external.append(route.request.url); route.abort(); return
            path = url.path
            if path == "/api/health": route.fulfill(json={"ocrReady":True,"pdfReady":True})
            elif path == "/api/projects": route.fulfill(json=[{"projectId":original["projectId"],"name":original["name"],"pages":2}])
            elif path == f'/api/projects/{original["projectId"]}':
                if route.request.method == "PUT":
                    value = Project.model_validate(route.request.post_data_json)
                    saved.append(value.model_dump())
                route.fulfill(json=saved[-1])
            elif path.startswith("/api/"): route.fulfill(status=404,json={"detail":"QA only"})
            else:
                root = (ROOT/"frontend/dist").resolve()
                target = (root/(path.lstrip("/") or "index.html")).resolve()
                route.fulfill(path=target) if target.is_relative_to(root) and target.is_file() else route.fulfill(status=404)

        tab.route("**/*", handler)
        tab.goto("http://127.0.0.1:8765/")
        tab.get_by_role("button",name=original["name"]).click()
        tab.get_by_role("button",name="高级调整",exact=True).click()
        tab.get_by_role("button",name="内容编辑",exact=True).click()
        content = tab.get_by_role("button",name="内容编辑",exact=True)
        expect(content).to_have_attribute("aria-pressed","true")
        expect(tab.locator('[data-element-id="name"]')).to_have_class(__import__('re').compile('is-uncertain'))
        name = tab.locator('[data-element-id="name"] .inline-editor')
        name.click(position={"x":2,"y":10})
        # A click positions the caret where clicked; React never remounts the node.
        name.evaluate("el=>window.qaEditor=el")
        name.press_sequentially("新")
        expect(tab.get_by_label("文字内容")).to_have_value("新虚构用户")
        assert name.evaluate("el=>el===window.qaEditor")
        expect(tab.locator(".selection-box")).to_have_count(0)
        name.press("Control+z"); expect(name).to_be_focused()
        expect(tab.get_by_label("文字内容")).to_have_value("虚构用户")
        name.press("Control+y")
        expect(tab.get_by_label("文字内容")).to_have_value("新虚构用户")
        name.press("Tab")
        expect(tab.locator('[data-element-id="line1"] .inline-editor')).to_be_focused()
        tab.locator('[data-element-id="line1"] .inline-editor').press("Shift+Tab")
        expect(name).to_be_focused()
        # Native drag selection selects text instead of moving the underlying object.
        selection_rect = name.evaluate("el=>{const r=document.createRange();r.setStart(el.firstChild,0);r.setEnd(el.firstChild,2);const b=r.getBoundingClientRect();return {x:b.left,y:b.top+b.height/2,end:b.right};}")
        tab.mouse.move(selection_rect["x"]+.2,selection_rect["y"]); tab.mouse.down()
        tab.mouse.move(selection_rect["end"]-.2,selection_rect["y"],steps=5); tab.mouse.up()
        assert tab.evaluate("window.getSelection().toString()") == "新虚"
        name.press_sequentially("李")
        expect(tab.get_by_label("文字内容")).to_have_value("李构用户")
        name.press("Escape")

        # Preview is read-only and excludes numbered list boundaries.
        tab.get_by_role("button",name="整理正文为段落",exact=True).click()
        preview = tab.get_by_role("dialog",name="整理正文为段落")
        expect(preview.locator("li")).to_have_count(2)
        preview.get_by_role("button",name="取消").click()
        expect(tab.locator('[data-element-id="line2"]')).to_have_count(1)
        tab.get_by_role("button",name="整理正文为段落",exact=True).click()
        tab.get_by_role("button",name="应用段落整理").click()
        expect(tab.locator('[data-element-id="line2"]')).to_have_count(0)
        expect(tab.locator('[data-element-id="line3"]')).to_have_count(0)
        expect(tab.locator('[data-element-id="list2"]')).to_have_count(1)
        expect(tab.locator('[data-element-id="bullet-text2"]')).to_have_count(1)
        tab.get_by_role("button",name="整理正文为段落",exact=True).click()
        expect(tab.get_by_role("button",name="应用段落整理")).to_be_disabled()
        tab.get_by_role("button",name="取消",exact=True).click()
        paragraph = tab.locator('[data-element-id="line1"] .inline-editor')
        paragraph.click()
        expect(tab.get_by_label("内容增长")).to_have_value("paragraph")
        expect(paragraph.locator('span')).to_have_count(2)
        tab.locator('[title="撤销 Ctrl+Z"]').click()
        expect(tab.locator('[data-element-id="line2"]')).to_have_count(1)
        tab.locator('[title="重做 Ctrl+Y"]').click()
        expect(tab.locator('[data-element-id="line2"]')).to_have_count(0)

        def save():
            tab.get_by_role("button",name="保存",exact=True).click()
            expect(tab.locator(".save-state")).to_contain_text("已保存")
            return {e["id"]:e for e in saved[-1]["pages"][0]["elements"]}

        initial = save()
        assert initial["line1"]["text"] == "".join(e["text"] for e in original["pages"][0]["elements"] if e["id"] in {"line1","line2","line3"})
        assert initial["line1"]["textRuns"][1]["start"] == len(original["pages"][0]["elements"][1]["text"])
        paragraph.click(); paragraph.fill("增加段落内容并检查下方的标题和后续栏目是否一起移动。"*8)
        expanded = save()
        growth = expanded["line1"]["height"]-initial["line1"]["height"]
        assert growth > 0
        for key in ("heading","heading-bg","following","following-side"):
            assert abs(expanded[key]["y"]-initial[key]["y"]-growth) < .01, key
        assert expanded["side"]["y"] == initial["side"]["y"]
        paragraph.click(); paragraph.fill("精简后的新正文")
        compact = save()
        shrink = compact["line1"]["height"]-expanded["line1"]["height"]
        assert shrink < 0
        assert abs(compact["following"]["y"]-expanded["following"]["y"]-shrink) < .01
        paragraph.click(); paragraph.press("Control+z")
        expect(paragraph).to_contain_text("增加段落内容")
        paragraph.press("Control+y")
        expect(paragraph).to_have_text("精简后的新正文")
        paragraph.press("End"); paragraph.press("Enter"); paragraph.press("Enter")
        expect(tab.get_by_label("文字内容")).to_have_value("精简后的新正文\n\n")
        trailing = save()
        assert trailing["line1"]["height"] > compact["line1"]["height"]+30
        paragraph.click(); paragraph.fill("")
        empty = save()
        assert 18 <= empty["line1"]["height"] <= 22
        # Composition remains in the DOM until committed and is then saved once.
        paragraph.click(); paragraph.fill("输入法")
        paragraph.dispatch_event("compositionstart", {"data":""})
        paragraph.evaluate("el=>{el.textContent='输入法中文';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}));}")
        expect(tab.get_by_label("文字内容")).to_have_value("输入法")
        paragraph.dispatch_event("compositionend", {"data":"中文"})
        expect(tab.get_by_label("文字内容")).to_have_value("输入法中文")
        # Rich paste is reduced to text and cannot execute or load media.
        paragraph.press("End")
        paragraph.evaluate("el=>{const dt=new DataTransfer();dt.setData('text/plain','<script>文本</script>');dt.setData('text/html','<img src=https://example.com/x onerror=alert(1)>');el.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:dt}));}")
        assert paragraph.locator("img,script").count() == 0
        paragraph.press("Escape")
        # Explicit layout mode still supports dragging and size handles.
        tab.get_by_role("button",name="版式调整",exact=True).click()
        target = tab.locator('[data-element-id="name"]')
        target.click()
        expect(tab.locator(".handle")).to_have_count(8)
        rect = target.bounding_box()
        tab.mouse.move(rect["x"]+10,rect["y"]+10); tab.mouse.down()
        tab.mouse.move(rect["x"]+30,rect["y"]+20,steps=5); tab.mouse.up()
        moved = save()
        assert moved["name"]["x"] > 40
        content.click()
        paragraph.click(); paragraph.fill("最终段落，支持单击编辑和自动排版。")
        save()
        # A current-page switch never leaves an editor or stale focus on the prior page.
        tab.locator('[title="下一页"]').click()
        expect(tab.locator('[data-element-id="page2text"] .inline-editor')).to_be_visible()
        tab.locator('[title="上一页"]').click()
        tab.screenshot(path=output/"document-editor.png",full_page=True)
        tab.reload();tab.get_by_role("button",name=original["name"]).click()
        expect(tab.locator('[data-element-id="line1"]')).to_contain_text("最终段落")
        tab.get_by_role("button",name="高级调整",exact=True).click()
        # Responsive toolbar remains operable without overflowing the viewport.
        tab.set_viewport_size({"width":1050,"height":850})
        assert tab.locator('.editing-toolbar').evaluate("el=>el.scrollWidth<=el.clientWidth")
        assert not errors, errors
        assert not external, external
        browser.close()

    exported = Project.model_validate(saved[-1])
    (output/"edited-project.json").write_text(exported.model_dump_json(indent=2),encoding="utf-8")
    html = render_html(exported)
    assert "最终段落" in html and "负责简历编辑产品" not in html
    assert "contenteditable" not in html and "inline-editor" not in html
    (output/"edited.html").write_text(html,encoding="utf-8")
    pdf = render_pdf(exported)
    (output/"edited.pdf").write_bytes(pdf)
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        text = "\n".join(page.extract_text() or "" for page in document.pages)
        assert "最终段落" in text and "负责简历编辑产品" not in text
        assert len(document.pages) == 2
    print("Document editing passed: single-click caret, stable DOM, selection replacement, Tab, preview/cancel, paragraph chains/bold, list boundaries, growth/shrink/transitive flow, undo/redo, empty/trailing lines, IME, safe paste, layout dragging, pagination, save/reopen, HTML/PDF. No JS errors or external requests.")


if __name__ == "__main__":
    main()
