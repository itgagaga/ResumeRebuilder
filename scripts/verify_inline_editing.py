"""Exercise in-page editing with an isolated API; never change a running user project."""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project",type=Path,default=ROOT/"artifacts/image-quality/project.json")
    args = parser.parse_args()
    from backend.models import Project,Page,Element,Style
    from backend.browser import launch_browser
    from backend.exporter import render_html,render_pdf
    import pdfplumber
    from playwright.sync_api import sync_playwright,expect
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT/"runtime/browsers")
    if args.project.exists():
        project = Project.model_validate_json(args.project.read_text(encoding="utf-8"))
    else:
        project = Project(projectId="inline_test",name="页面内编辑验收",pages=[Page(id="page",width=595,height=842,elements=[
            Element(id="target",type="text",text="求职意向：后端开发",x=30,y=60,width=140,height=18,style=Style(fontSize=12)),
            Element(id="heading",type="text",text="专业技能",x=30,y=105,width=200,height=25,style=Style(fontSize=16,color="#00a6a7",fontWeight=700)),
        ])])
    project.name = "页面内编辑验收";project.referenceAvailable = False
    original = project.model_dump()
    saved = [json.loads(json.dumps(original))]
    selected = next(e for e in project.pages[0].elements if e.type == "text" and "求职意向" in e.text)
    heading = next(e for e in project.pages[0].elements if e.type == "text" and "专业技能" in e.text)
    output = ROOT/"artifacts/inline-editing";output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        tab = browser.new_page(viewport={"width":1700,"height":1100})
        errors = [];tab.on("pageerror",lambda exc:errors.append(str(exc)))
        def handler(route):
            path = urlparse(route.request.url).path
            if path == "/api/health":route.fulfill(json={"ocrReady":True,"pdfReady":True})
            elif path == "/api/projects":route.fulfill(json=[{"projectId":project.projectId,"name":project.name,"pages":len(project.pages)}])
            elif path == f"/api/projects/{project.projectId}":
                if route.request.method == "PUT":saved.append(route.request.post_data_json)
                route.fulfill(json=saved[-1])
            elif path.startswith("/api/"):route.fulfill(status=404,json={"detail":"QA only"})
            else:
                root = (ROOT/"frontend/dist").resolve();target = (root/(path.lstrip('/') or 'index.html')).resolve()
                route.fulfill(path=target) if target.is_relative_to(root) and target.is_file() else route.fulfill(status=404,body="not found")
        tab.route("**/*",handler)
        tab.goto("http://127.0.0.1:8765/")
        tab.get_by_role("button",name=project.name).click()
        expect(tab.get_by_label("工程名称")).to_be_visible()
        target = tab.locator(f'[data-element-id="{selected.id}"]')
        target.dblclick()
        editor = tab.get_by_role("textbox",name="直接编辑文字")
        expect(editor).to_have_attribute("contenteditable","true")
        editor.press("End");editor.press_sequentially("你好1")
        expect(tab.get_by_label("文字内容")).to_have_value(selected.text+"你好1")
        # Caret remains at the end across React updates, and undo/redo retains editing focus.
        editor.press("Control+z")
        expect(editor).to_be_focused()
        expect(tab.get_by_label("文字内容")).to_have_value(selected.text+"你好")
        editor.press("Control+y")
        expect(tab.get_by_label("文字内容")).to_have_value(selected.text+"你好1")
        editor.press("Escape")
        tab.get_by_role("button",name="保存",exact=True).click()
        expect(tab.locator(".save-state")).to_contain_text("已保存")
        appended = next(e for e in saved[-1]["pages"][0]["elements"] if e["id"] == selected.id)
        assert appended["width"] > selected.width
        assert appended["height"] <= selected.height+1
        assert not target.locator('.is-overflow').count()
        tab.screenshot(path=output/"append-one-line.png",full_page=True)
        # A larger paragraph wraps and pushes the next heading down as a single undoable update.
        target.dblclick();editor = tab.get_by_role("textbox",name="直接编辑文字")
        long_text = selected.text+"，新增的经历与技能需要直接在简历页面编辑。"*7
        editor.fill(long_text);editor.press("Escape")
        tab.get_by_role("button",name="保存",exact=True).click()
        expect(tab.locator(".save-state")).to_contain_text("已保存")
        expanded = next(e for e in saved[-1]["pages"][0]["elements"] if e["id"] == selected.id)
        shifted = next(e for e in saved[-1]["pages"][0]["elements"] if e["id"] == heading.id)
        assert expanded["height"] > appended["height"]
        assert shifted["y"] > heading.y
        assert shifted["y"] >= expanded["y"]+expanded["height"]
        tab.screenshot(path=output/"wrap-and-flow.png",full_page=True)
        tab.locator('[title="撤销 Ctrl+Z"]').click()
        expect(tab.get_by_label("文字内容")).to_have_value(selected.text+"你好1")
        # Inspector is a secondary route, and uses the same automatic layout.
        tab.get_by_label("文字内容").fill(selected.text+"侧栏追加")
        tab.get_by_role("button",name="保存",exact=True).click()
        expect(tab.locator(".save-state")).to_contain_text("已保存")
        value = next(e for e in saved[-1]["pages"][0]["elements"] if e["id"] == selected.id)
        assert value["width"] > selected.width
        # Fixed-size mode remains available for deliberate absolute layout.
        tab.get_by_role("combobox",name="内容增长").select_option("fixed")
        tab.get_by_label("文字内容").fill("固定尺寸测试"*100)
        expect(target).to_have_class(__import__('re').compile("is-overflow"))
        tab.locator('[title="撤销 Ctrl+Z"]').click()
        expect(tab.get_by_label("文字内容")).to_have_value(selected.text+"侧栏追加")
        tab.get_by_role("combobox",name="内容增长").select_option("auto")
        # Enter is represented as a true newline, rather than leaking contenteditable block tags.
        target.dblclick();editor = tab.get_by_role("textbox",name="直接编辑文字")
        editor.fill("第一行");editor.press("End");editor.press("Enter");editor.press_sequentially("第二行")
        expect(tab.get_by_label("文字内容")).to_have_value("第一行\n第二行")
        editor.fill("第一行");editor.press("End");editor.press("Enter");editor.press("Enter");editor.press_sequentially("第三行")
        expect(tab.get_by_label("文字内容")).to_have_value("第一行\n\n第三行")
        editor.fill("普通加粗")
        editor.evaluate("el=>{const r=document.createRange();r.setStart(el.firstChild,2);r.setEnd(el.firstChild,4);const s=window.getSelection();s.removeAllRanges();s.addRange(r);}")
        editor.press("Control+b")
        editor.press("Escape")
        expect(target.locator('.text-content>span')).to_have_css("font-weight","700")
        # IME composition is not interrupted by rerendering the editor.
        target.dblclick();editor = tab.get_by_role("textbox",name="直接编辑文字")
        editor.fill("输入法")
        editor.dispatch_event("compositionstart",{"data":""})
        editor.evaluate("el=>{el.textContent='输入法中文';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}));}")
        expect(tab.get_by_label("文字内容")).to_have_value("输入法")
        editor.dispatch_event("compositionend",{"data":"中文"})
        expect(tab.get_by_label("文字内容")).to_have_value("输入法中文")
        editor.press("Escape")
        # Editing a rich line preserves its unaffected bold prefix.
        rich = next((e for e in project.pages[0].elements if e.textRuns),None)
        if rich:
            rich_target = tab.locator(f'[data-element-id="{rich.id}"]');rich_target.dblclick()
            editor = tab.get_by_role("textbox",name="直接编辑文字")
            editor.press("End");editor.press_sequentially("追加内容");editor.press("Escape")
            expect(rich_target.locator('.text-content>span').first).to_have_css("font-weight",str(rich.textRuns[0].fontWeight))
            tab.get_by_label("文字内容").fill(rich.text+"侧栏保留")
            expect(rich_target.locator('.text-content>span').first).to_have_css("font-weight",str(rich.textRuns[0].fontWeight))
        target.click();tab.get_by_role("button",name="在页面中编辑",exact=True).click()
        editor = tab.get_by_role("textbox",name="直接编辑文字")
        editor.fill("李四的求职意向与新内容")
        # Rich clipboard data is not inserted as HTML, and plain text survives save/export.
        editor.evaluate("el=>{const dt=new DataTransfer();dt.setData('text/plain',' <script>纯文本</script>');dt.setData('text/html','<img src=x onerror=alert(1)>');el.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:dt}));}")
        assert editor.locator('img,script').count() == 0
        editor.press("Escape")
        tab.get_by_role("button",name="保存",exact=True).click()
        expect(tab.locator(".save-state")).to_contain_text("已保存")
        exported = Project.model_validate(saved[-1])
        (output/"edited-project.json").write_text(exported.model_dump_json(indent=2),encoding="utf-8")
        assert '&lt;script&gt;' in render_html(exported)
        assert not errors,errors
        # Reload from the saved document model; new content and geometry persist.
        tab.reload();tab.get_by_role("button",name=project.name).click()
        expect(tab.locator(f'[data-element-id="{selected.id}"]')).to_contain_text("李四的求职意向与新内容")
        browser.close()
    pdf = render_pdf(exported)
    (output/"edited.pdf").write_bytes(pdf)
    import io
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        text = '\n'.join(p.extract_text() or '' for p in document.pages)
        assert "李四" in text
    print("Inline editing passed: append without wrapping, caret, undo/redo, wrapping/flow, inspector sizing, fixed mode, Enter, IME, bold preservation, safe paste, saved reopen and PDF export. No JavaScript errors.")


if __name__ == "__main__":main()
