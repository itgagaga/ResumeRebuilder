"""Open exported file:// HTML, edit and save it twice without any running server."""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pdfplumber
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright
from backend import storage
from backend.browser import launch_browser
from backend.main import app
from backend.models import Element, Page, Project, Style
from backend.exporter import render_html


def main():
    output = ROOT / "artifacts/standalone-html"
    output.mkdir(parents=True, exist_ok=True)
    storage.DATA = output / "projects"
    body = Style(fontSize=12,lineHeight=1.5)
    teal = Style(fontSize=16,fontWeight=700,color="#00a6a7",background="#eff8f8",lineHeight=1.5)
    project = Project(projectId="standalone",name="旧姓名不应进入导出元数据",pages=[Page(id="p1",width=595,height=842,elements=[
        Element(id="name",type="text",text="待修改姓名",x=40,y=35,width=220,height=36,style=Style(fontSize=24,lineHeight=1.4)),
        Element(id="contact",type="text",text="虚构示例 · 本地文件可直接编辑",x=40,y=80,width=360,height=20,style=body),
        Element(id="photo",type="image_placeholder",x=465,y=30,width=80,height=80),
        Element(id="heading",type="text",text="个人简介",x=40,y=130,width=510,height=28,style=teal),
        Element(id="body",type="text",text="点击这里修改正文，并保存为新的可编辑 HTML 文件。",x=40,y=175,width=500,height=38,style=body,textLayout="paragraph"),
        Element(id="following",type="text",text="工作经历",x=40,y=240,width=510,height=28,style=teal),
        Element(id="experience",type="text",text="示例公司 · 产品研发\n负责离线编辑功能和本地文件保存。",x=40,y=285,width=500,height=40,style=body,textLayout="paragraph"),
        Element(id="empty",type="image_placeholder",x=40,y=390,width=80,height=80),
        Element(id="optional",type="text",text="",x=40,y=500,width=400,height=20,style=body,textLayout="paragraph"),
    ]),Page(id="p2",width=595,height=842,elements=[
        Element(id="second",type="text",text="第二页 · 独立可编辑内容",x=40,y=40,width=500,height=30,style=teal),
    ])])
    storage.save_project(project)
    client = TestClient(app,base_url="http://127.0.0.1:8765")
    response = client.post('/api/projects/standalone/export',json={"format":"html","confirmEmpty":True})
    assert response.status_code == 200
    assert 'resume-editable.html' in response.headers['content-disposition']
    initial_file = output / "resume-editable.html"
    initial_file.write_bytes(response.content)
    assert '旧姓名不应' not in response.text
    errors, external = [], []
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        tab = browser.new_page(viewport={"width":1200,"height":1100})
        tab.on('pageerror',lambda error: errors.append(str(error)))
        tab.on('request',lambda req: external.append(req.url) if req.url.startswith(('http:','https:')) else None)
        tab.route('http://**/*',lambda route: route.abort())
        tab.route('https://**/*',lambda route: route.abort())
        tab.goto(initial_file.as_uri())
        expect(tab.locator('[contenteditable="true"]')).to_have_count(8)
        text = lambda name: tab.locator(f'[data-resume-element="{name}"] [data-resume-text]')
        name, body_text = text('name'), text('body')
        name.click(position={"x":2,"y":10}); name.fill('李四')
        body_text.click(); body_text.fill('新增内容，需要随正文长度调整后续栏目。'*90+'TAILTOKEN')
        expect(tab.locator('#resume-layout')).to_have_value('paragraph')
        assert float(tab.locator('.page').first.evaluate('el=>el.style.height.slice(0,-2)')) > 842*96/72
        # The browser prints every source page once, scaling expanded content to fit.
        pdf = tab.pdf(print_background=True,prefer_css_page_size=True)
        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            assert len(doc.pages) == 2
            assert 'TAILTOKEN' in ''.join(p.extract_text() or '' for p in doc.pages)
        (output/'long-content.pdf').write_bytes(pdf)
        body_text.fill('普通加粗正文')
        assert abs(float(tab.locator('.page').first.evaluate('el=>el.style.height.slice(0,-2)'))-842*96/72) < .01
        body_text.evaluate("el=>{const r=document.createRange();r.setStart(el.firstChild,2);r.setEnd(el.firstChild,4);const s=window.getSelection();s.removeAllRanges();s.addRange(r);}")
        tab.locator('#resume-bold').click()
        expect(tab.locator('#resume-bold')).to_have_attribute('aria-pressed','true')
        assert body_text.evaluate("el=>[...el.querySelectorAll('b,strong,span')].some(n=>n.textContent==='加粗'&&getComputedStyle(n).fontWeight==='700')")
        # Ctrl+Z and Ctrl+Y use native text history and trigger matching reflow.
        body_text.click(); body_text.press('End'); body_text.press_sequentially('新')
        body_text.press('Control+z'); expect(body_text).not_to_contain_text('新')
        body_text.press('Control+y'); expect(body_text).to_contain_text('新')
        body_text.press('End')
        body_text.evaluate("el=>{const dt=new DataTransfer();dt.setData('text/plain','<script>纯文本</script>');dt.setData('text/html','<img src=https://example.com/x onerror=alert(1)>');el.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:dt}));}")
        assert body_text.locator('script,img').count() == 0
        expect(body_text).to_contain_text('<script>纯文本</script>')
        # Composition updates remain in place; no framework or server is involved.
        contact = text('contact'); contact.click(); contact.fill('输入法')
        contact.dispatch_event('compositionstart',{'data':''})
        contact.evaluate("el=>{el.textContent='中文输入法正常';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}));}")
        contact.dispatch_event('compositionend',{'data':'中文'})
        expect(contact).to_have_text('中文输入法正常')
        experience = text('experience'); experience.click(); experience.fill('第一行')
        experience.press('End'); experience.press('Enter'); experience.press('Enter'); experience.press_sequentially('第三行')
        optional = text('optional');optional.click();optional.fill('删除后保留可输入的空行');optional.fill('')
        assert optional.bounding_box()['height'] >= 18*96/72
        # Replace a photo, preserve a blank slot, and normalize the new image inline.
        with tab.expect_file_chooser() as chooser:
            tab.locator('[data-resume-element="photo"]').click()
        chooser.value.set_files(ROOT/'examples/replacement.png')
        image = tab.locator('[data-resume-element="photo"] img')
        expect(image).to_have_attribute('src',__import__('re').compile('^data:image/png;base64,'))
        image_data = image.get_attribute('src')
        with tab.expect_download() as download:
            tab.locator('#resume-save').click()
        saved_file = output/'saved-once.html';download.value.save_as(saved_file)
        saved = saved_file.read_text(encoding='utf-8')
        assert '待修改姓名' not in saved and '旧姓名不应' not in saved
        assert '<script>纯文本</script>' not in saved and '&lt;script&gt;' in saved
        assert initial_file.read_bytes() == response.content
        tab.goto(saved_file.as_uri())
        expect(text('name')).to_have_text('李四')
        expect(text('contact')).to_have_text('中文输入法正常')
        expect(text('experience')).to_have_text('第一行\n\n第三行')
        expect(text('optional')).to_have_text('')
        assert image.get_attribute('src') == image_data
        assert text('body').evaluate("el=>[...el.querySelectorAll('span')].some(n=>n.textContent==='加粗'&&getComputedStyle(n).fontWeight==='700')")
        # Print button uses browser printing; editor controls/placeholders stay out of PDF.
        tab.evaluate('window.print=()=>{window.qaPrintCalled=true}')
        tab.locator('#resume-print').click()
        tab.wait_for_function('window.qaPrintCalled===true')
        tab.emulate_media(media='print')
        expect(tab.locator('.resume-toolbar')).not_to_be_visible()
        assert tab.locator('[data-resume-element="empty"]').evaluate("el=>getComputedStyle(el,'::after').display") == 'none'
        pdf = tab.pdf(print_background=True,prefer_css_page_size=True)
        (output/'edited.pdf').write_bytes(pdf)
        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            text_in_pdf = '\n'.join(page.extract_text() or '' for page in doc.pages)
            assert len(doc.pages) == 2 and '李四' in text_in_pdf and '第二页' in text_in_pdf
            assert '保存修改后的 HTML' not in text_in_pdf and '点击更换图片' not in text_in_pdf
            assert len(doc.pages[0].images) == 1
        tab.emulate_media(media='screen')
        name = text('name'); name.click(); name.fill('王五')
        with tab.expect_download() as download:
            name.press('Control+s')
        second_file = output/'saved-twice.html';download.value.save_as(second_file)
        assert '李四' not in second_file.read_text(encoding='utf-8')
        tab.goto(second_file.as_uri())
        expect(text('name')).to_have_text('王五')
        assert image.get_attribute('src') == image_data
        tab.screenshot(path=output/'standalone-editor.png',full_page=True)
        assert not errors, errors
        assert not external, external
        # Deliver a clean, fictional one-page example separately from QA payloads.
        example = project.model_copy(deep=True)
        example.pages = example.pages[:1]
        example.pages[0].elements = [e for e in example.pages[0].elements if e.id not in {'empty','optional'}]
        for element in example.pages[0].elements:
            if element.id == 'name': element.text = '你的姓名'
            elif element.id == 'contact': element.text = '联系电话 · 邮箱 · 求职意向'
            elif element.id == 'body': element.text = '点击文字直接修改。你可以选中文字加粗，替换照片，并把修改保存为新的 HTML 文件。'
        example_file = output/'可编辑简历示例.html'
        example_file.write_text(render_html(example,editable=True),encoding='utf-8')
        tab.goto(example_file.as_uri())
        expect(text('name')).to_have_text('你的姓名')
        tab.screenshot(path=output/'editable-example.png',full_page=True)
        browser.close()
    print('Standalone HTML passed: API download, file:// editing without a server, growth/shrink, long-content printing, bold, native undo/redo, safe paste, IME, photo replacement, two save/reopen cycles, Ctrl+S, clean two-page PDF. No JS errors or network requests.')


if __name__ == '__main__': main()
