"""Verify the preview-first workflow using fictional data and an isolated API."""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.browser import launch_browser
from backend.exporter import render_html
from backend.models import Element, Page, Project, Style
from playwright.sync_api import expect, sync_playwright


def fixture():
    body = Style(fontSize=12, lineHeight=1.5)
    return Project(projectId="preview_workflow", name="只读预览流程验收", pages=[Page(id="page", width=595, height=842, elements=[
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
    output = ROOT/'artifacts/preview-workflow'
    output.mkdir(parents=True, exist_ok=True)
    project = fixture()
    project.referenceAvailable = True
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
            elif path == f'/api/projects/{project.projectId}/reference':
                assert route.request.method == 'DELETE'
                saved.append({**saved[-1], 'referenceAvailable':False})
                route.fulfill(json=saved[-1])
            elif path.startswith(f'/api/projects/{project.projectId}/reference/'):
                route.fulfill(path=ROOT/'examples/replacement.png')
            elif path == f'/api/projects/{project.projectId}/export':
                route.fulfill(body=render_html(Project.model_validate(saved[-1]), editable=True), content_type='text/html')
            elif path.startswith('/api/'): route.fulfill(status=404, json={})
            else:
                root = (ROOT/'frontend/dist').resolve()
                target = (root/(path.lstrip('/') or 'index.html')).resolve()
                route.fulfill(path=target) if target.is_relative_to(root) and target.is_file() else route.fulfill(status=404)

        context.route('**/*', route_handler)
        tab.goto('http://127.0.0.1:8765/')
        expect(tab.get_by_role('button', name='从空白 A4 页面开始', exact=True)).to_have_count(0)
        tab.get_by_role('button', name=project.name).click()
        target = tab.locator('[data-element-id="name"]')

        def preview_only():
            expect(tab.locator('.preview-mode')).to_have_count(1)
            expect(tab.locator('[contenteditable="true"], .selection-box, .handle, .tool-rail, .inspector, .editing-toolbar')).to_have_count(0)
            expect(tab.get_by_role('button', name='高级调整', exact=True)).to_have_count(0)
            expect(tab.get_by_role('button', name='内容编辑', exact=True)).to_have_count(0)
            expect(tab.get_by_role('button', name='框选图片区', exact=True)).to_have_count(0)
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

        # Project metadata can still be saved; resume content stays read-only.
        tab.get_by_label('工程名称').fill('重命名预览工程')
        expect(tab.locator('.save-state')).to_contain_text('未保存')
        tab.get_by_role('button', name='保存', exact=True).click()
        expect(tab.locator('.save-state')).to_contain_text('已保存')
        assert saved[-1]['name'] == '重命名预览工程'
        assert saved[-1]['pages'] == original['pages']
        tab.get_by_label('工程名称').fill(project.name)
        tab.keyboard.press('Control+s')
        expect(tab.locator('.save-state')).to_contain_text('已保存')
        tab.locator('.canvas-heading').last.click()
        drag(tab.locator('.source-paper'), dx=60, dy=50)
        assert saved[-1] == original

        # The main action opens the current project model in a standalone page.
        with tab.expect_popup() as opened:
            tab.get_by_role('button', name='进入 HTML 编辑', exact=True).click()
        html = opened.value
        expect(html.locator('#resume-font-brush')).to_be_visible()
        html_text = html.locator('[data-resume-element="name"] [data-resume-text]')
        expect(html_text).to_have_text('虚构用户')
        assert html.evaluate('window.opener===null')
        html_text.fill('HTML 页独立修改')
        expect(target).to_have_text('虚构用户')
        expect(tab.locator('.html-edit-guide')).to_contain_text('再次打开会从当前工程生成新文件')
        with html.expect_download() as download: html.locator('#resume-save').click()
        download.value.save_as(output/'edited-in-html.html')
        assert 'HTML 页独立修改' in (output/'edited-in-html.html').read_text(encoding='utf-8')
        html.close()
        tab.get_by_role('button', name='导出', exact=True).click()
        expect(tab.get_by_role('dialog', name='导出简历')).to_contain_text('不包含 HTML 编辑页的独立修改')
        with tab.expect_download() as exported:
            tab.get_by_role('button', name='确认导出 HTML', exact=True).click()
        exported.value.save_as(output/'exported-from-project.html')
        assert 'HTML 页独立修改' not in (output/'exported-from-project.html').read_text(encoding='utf-8')
        assert saved[-1] == original
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
        preview_only(); expect(target).to_have_text('虚构用户')
        for width in [1050, 600, 390]:
            tab.set_viewport_size({'width':width,'height':900})
            expect(tab.get_by_role('button',name='进入 HTML 编辑',exact=True)).to_be_in_viewport()
            preview_only()
            assert tab.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
            tab.screenshot(path=output/f'preview-{width}.png', full_page=True)
        # Reference cleanup remains reachable without the removed edit mode.
        tab.set_viewport_size({'width':1440,'height':1000})
        tab.once('dialog', lambda dialog: dialog.dismiss())
        tab.get_by_role('button', name='删除原始参考', exact=True).click()
        assert saved[-1]['referenceAvailable']
        tab.once('dialog', lambda dialog: dialog.accept())
        tab.get_by_role('button', name='删除原始参考', exact=True).click()
        expect(tab.locator('.no-source')).to_be_visible()
        expect(tab.get_by_role('button', name='删除原始参考', exact=True)).to_be_disabled()
        assert not saved[-1]['referenceAvailable']
        assert saved[-1]['pages'] == original['pages']
        preview_only()
        assert not errors, errors
        assert not external, external
        browser.close()
    (output/'report.json').write_text(json.dumps({'readOnly':True,'advancedRemoved':True,'projectRename':True,'referenceCleanup':True,'htmlSaveBoundary':True,'errorPaths':True,'responsiveWidths':[1440,1050,600,390]}, indent=2), encoding='utf-8')
    print('Preview workflow passed: read-only clicks/drag/keys, zoom/pages/compare, removed advanced tools, project rename/reference cleanup, HTML popup/current model/save isolation, blocked popup/save failure, reload defaults, desktop/mobile; no JS errors or external requests.')


if __name__ == '__main__':
    main()
