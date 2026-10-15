"""Verify the preview-first workflow using fictional data and an isolated API."""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.browser import launch_browser
from backend.exporter import render_html
from backend.models import Project
from scripts.verify_document_editing import fixture
from playwright.sync_api import expect, sync_playwright


def main():
    output = ROOT/'artifacts/preview-workflow'
    output.mkdir(parents=True, exist_ok=True)
    project = fixture()
    project.name = '只读预览流程验收'
    original = project.model_dump()
    saved, errors, external = [original], [], []
    fail_save = [False]
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        context = browser.new_context(viewport={'width':1440, 'height':1000}, accept_downloads=True)
        tab = context.new_page()
        context.on('page', lambda page: page.on('pageerror', lambda error: errors.append(str(error))))
        tab.on('pageerror', lambda error: errors.append(str(error)))

        def route_handler(route):
            url = urlparse(route.request.url)
            if url.scheme not in {'http', 'https'}:
                route.continue_(); return
            if url.hostname != '127.0.0.1':
                external.append(route.request.url); route.abort(); return
            path = url.path
            if path == '/api/health': route.fulfill(json={'ocrReady':True,'pdfReady':True})
            elif path == '/api/projects': route.fulfill(json=[{'projectId':project.projectId,'name':project.name,'pages':2}])
            elif path == f'/api/projects/{project.projectId}':
                if route.request.method == 'PUT':
                    if fail_save[0]: route.fulfill(status=500, json={'detail':'测试保存失败'}); return
                    saved.append(Project.model_validate(route.request.post_data_json).model_dump())
                route.fulfill(json=saved[-1])
            elif path == f'/api/projects/{project.projectId}/export':
                route.fulfill(body=render_html(Project.model_validate(saved[-1]), editable=True), content_type='text/html')
            elif path.startswith('/api/'): route.fulfill(status=404, json={})
            else:
                root = (ROOT/'frontend/dist').resolve()
                target = (root/(path.lstrip('/') or 'index.html')).resolve()
                route.fulfill(path=target) if target.is_relative_to(root) and target.is_file() else route.fulfill(status=404)

        context.route('**/*', route_handler)
        tab.goto('http://127.0.0.1:8765/')
        tab.get_by_role('button', name=project.name).click()
        target = tab.locator('[data-element-id="name"]')

        def preview_only():
            expect(tab.locator('.preview-mode')).to_have_count(1)
            expect(tab.locator('[contenteditable="true"], .selection-box, .handle, .tool-rail, .inspector, .editing-toolbar')).to_have_count(0)
            expect(tab.get_by_role('button', name='高级调整', exact=True)).to_be_visible()
            expect(tab.locator('.editor-column .canvas-heading')).to_contain_text('识别结果预览')
            expect(tab.locator('.html-edit-guide')).to_contain_text('HTML 编辑页的修改不会同步到此预览')

        def positions():
            return tab.locator('[data-element-id]').evaluate_all('els=>els.map(el=>({id:el.dataset.elementId,style:el.getAttribute("style"),text:el.textContent}))')

        def drag(locator, dx=35, dy=15):
            box = locator.bounding_box()
            tab.mouse.move(box['x']+5, box['y']+8); tab.mouse.down()
            tab.mouse.move(box['x']+5+dx, box['y']+8+dy, steps=8); tab.mouse.up()

        preview_only()
        before = positions()
        target.click(); target.dblclick(); drag(target)
        tab.locator('.editor-column [data-text-id="name"]').evaluate('el=>{const r=document.createRange();r.selectNodeContents(el);getSelection().removeAllRanges();getSelection().addRange(r)}')
        assert tab.evaluate('getSelection().toString()') == '虚构用户'
        for key in ['Delete','Backspace','t','i','r','l','ArrowRight','Control+d','Control+v','Control+z','Control+y']:
            tab.keyboard.press(key)
        assert positions() == before
        assert len(saved) == 1
        preview_only()
        # Read-only selection/copy is allowed; shortcuts cannot edit the model.
        tab.keyboard.press('Control+s')
        expect(tab.locator('.save-state')).to_contain_text('已保存')
        assert saved[-1] == original
        tab.locator('[title="放大"]').click(); tab.locator('[title="适应宽度"]').click()
        tab.locator('[title="下一页"]').click(); expect(tab.locator('[data-element-id="page2text"]')).to_be_visible()
        preview_only()
        tab.locator('[title="上一页"]').click()
        tab.get_by_role('button', name='原页对照', exact=True).click()
        expect(tab.locator('.source-column')).to_have_count(0)
        tab.get_by_role('button', name='原页对照', exact=True).click()
        expect(tab.locator('.source-column')).to_have_count(1)

        # Advanced tools retain position changes, content edits and undo history.
        tab.get_by_role('button', name='高级调整', exact=True).click()
        expect(tab.get_by_role('button', name='版式调整', exact=True)).to_have_attribute('aria-pressed','true')
        target.click(); expect(tab.locator('.handle')).to_have_count(8)
        start_left = target.evaluate('el=>el.style.left')
        drag(target)
        assert target.evaluate('el=>el.style.left') != start_left
        tab.get_by_role('button', name='内容编辑', exact=True).click()
        editor = tab.locator('[data-element-id="name"] .inline-editor')
        editor.click(); editor.fill('高级调整后的虚构姓名')
        # Exiting while the editor is focused commits the text and closes tools.
        tab.get_by_role('button', name='返回只读预览', exact=True).click()
        preview_only(); expect(target).to_have_text('高级调整后的虚构姓名')
        adjusted = positions()
        tab.keyboard.press('Control+z'); tab.keyboard.press('Delete')
        assert positions() == adjusted
        tab.get_by_role('button', name='高级调整', exact=True).click()
        tab.locator('[title="撤销 Ctrl+Z"]').click(); expect(target).to_have_text('虚构用户')
        tab.locator('[title="重做 Ctrl+Y"]').click(); expect(target).to_have_text('高级调整后的虚构姓名')
        tab.get_by_role('button', name='框选图片区', exact=True).click()
        tab.get_by_role('button', name='返回只读预览', exact=True).click()
        preview_only()
        tab.keyboard.press('i'); drag(tab.locator('.paper'), dx=60, dy=50)
        assert positions() == adjusted

        # The main action opens the current project model in a standalone page.
        with tab.expect_popup() as opened:
            tab.get_by_role('button', name='进入 HTML 编辑', exact=True).click()
        html = opened.value
        expect(html.locator('#resume-font-brush')).to_be_visible()
        html_text = html.locator('[data-resume-element="name"] [data-resume-text]')
        expect(html_text).to_have_text('高级调整后的虚构姓名')
        assert html.evaluate('window.opener===null')
        html_text.fill('HTML 页独立修改')
        expect(target).to_have_text('高级调整后的虚构姓名')
        expect(tab.locator('.html-edit-guide')).to_contain_text('再次打开会从当前工程生成新文件')
        with html.expect_download() as download: html.locator('#resume-save').click()
        download.value.save_as(output/'edited-in-html.html')
        assert 'HTML 页独立修改' in (output/'edited-in-html.html').read_text(encoding='utf-8')
        html.close()
        tab.get_by_role('button', name='导出', exact=True).click()
        expect(tab.get_by_role('dialog', name='导出简历')).to_contain_text('不包含 HTML 编辑页的独立修改')
        tab.get_by_label('关闭导出窗口').click()
        tab.screenshot(path=output/'preview-desktop.png', full_page=True)

        # Failure paths leave the preview intact and do not strand blank popups.
        tab.evaluate('window.qaOpen=window.open;window.open=()=>null')
        tab.get_by_role('button', name='进入 HTML 编辑', exact=True).click()
        expect(tab.get_by_role('alert')).to_contain_text('浏览器阻止了新窗口')
        tab.evaluate('window.open=(...args)=>{const popup=window.qaOpen(...args);window.qaPopup=popup;return popup}')
        fail_save[0] = True
        with tab.expect_popup() as failed:
            tab.get_by_role('button', name='进入 HTML 编辑', exact=True).click()
        expect(tab.get_by_role('alert')).to_contain_text('测试保存失败')
        tab.wait_for_function('window.qaPopup.closed === true')
        # Headless Edge can retain a chrome-error DevTools target after window.close.
        if not failed.value.is_closed(): failed.value.close()
        tab.evaluate('window.open=window.qaOpen')
        fail_save[0] = False
        preview_only()
        tab.reload(); tab.get_by_role('button', name=project.name).click()
        preview_only(); expect(target).to_have_text('高级调整后的虚构姓名')
        for width in [1050, 600, 390]:
            tab.set_viewport_size({'width':width,'height':900})
            expect(tab.get_by_role('button',name='进入 HTML 编辑',exact=True)).to_be_in_viewport()
            expect(tab.get_by_role('button',name='高级调整',exact=True)).to_be_in_viewport()
            assert tab.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
            tab.screenshot(path=output/f'preview-{width}.png', full_page=True)
        assert not errors, errors
        assert not external, external
        browser.close()
    (output/'report.json').write_text(json.dumps({'readOnly':True,'advancedTools':True,'htmlSaveBoundary':True,'errorPaths':True,'responsiveWidths':[1440,1050,600,390]}, indent=2), encoding='utf-8')
    print('Preview workflow passed: read-only clicks/drag/keys, zoom/pages/compare, advanced tools and preserved edits/history, HTML popup/current model/save isolation, blocked popup/save failure, reload defaults, desktop/mobile; no JS errors or external requests.')


if __name__ == '__main__':
    main()
