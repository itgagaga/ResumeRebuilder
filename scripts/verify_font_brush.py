"""Exercise the standalone font brush with real selection, undo, save and print."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.browser import launch_browser, system_browser
from backend.exporter import render_html
from backend.models import Element, Page, Project, Style, TextRun
from playwright.sync_api import expect, sync_playwright


SELECT = """(el, offsets) => {
    el.focus();
    const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT), nodes=[];
    while(walker.nextNode()) nodes.push(walker.currentNode);
    const locate=offset=>{for(const node of nodes){if(offset<=node.length)return [node,offset];offset-=node.length;}return [el,0];};
    const range=document.createRange();range.setStart(...locate(offsets[0]));range.setEnd(...locate(offsets[1]));
    const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
}"""
FONTS = """el => {
    const result=[], walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT), zoom=parseFloat(getComputedStyle(el).zoom)||1;
    while(walker.nextNode()) {const node=walker.currentNode, cs=getComputedStyle(node.parentElement);
        for(const char of node.data) result.push({char,family:cs.fontFamily,size:parseFloat(cs.fontSize)*zoom,weight:cs.fontWeight,italic:cs.fontStyle,color:cs.color});}
    return result;
}"""


def main():
    output = ROOT / 'artifacts/font-brush'
    output.mkdir(parents=True, exist_ok=True)
    source = Style(fontFamily='Georgia, serif', fontSize=18, fontWeight=700, fontStyle='italic', color='#2468ac')
    normal = Style(fontFamily='Arial, sans-serif', fontSize=10, fontWeight=400, color='#111111')
    project = Project(projectId='font_brush', name='字体格式刷验收', pages=[Page(id='p1', width=595, height=842, elements=[
        Element(id='source', type='text', text='源字体样例', x=40, y=30, width=420, height=36, style=source),
        Element(id='normal', type='text', text='普通字体样例', x=40, y=90, width=420, height=25, style=normal),
        Element(id='target', type='text', text='前缀目标文字后缀', x=40, y=150, width=420, height=30, style=normal,
                textRuns=[TextRun(start=2, end=4, fontWeight=700)], textLayout='paragraph'),
        Element(id='multiline', type='text', text='首行文字\n\n末行文字', x=40, y=220, width=220, height=65, style=normal, textLayout='paragraph'),
        Element(id='below', type='text', text='下方栏目', x=40, y=320, width=420, height=30, style=normal),
    ]), Page(id='p2', unit='px', width=794, height=1123, elements=[
        Element(id='second', type='text', text='跨页目标文字', x=40, y=40, width=450, height=50, style=normal),
    ])])
    initial = output / 'font-brush-demo.html'
    initial.write_text(render_html(project, editable=True), encoding='utf-8')
    reports, errors, external = [], [], []
    with sync_playwright() as pw:
        for minimum in [0, 24]:
            executable = system_browser()
            browser = pw.chromium.launch(headless=True, executable_path=str(executable), args=[f'--blink-settings=minimumFontSize={minimum}']) if executable else launch_browser(pw)
            tab = browser.new_page(viewport={'width':1250, 'height':1000}, accept_downloads=True)
            tab.on('pageerror', lambda error: errors.append(str(error)))
            tab.on('request', lambda req: external.append(req.url) if req.url.startswith(('http:', 'https:')) else None)
            tab.goto(initial.as_uri())
            tab.evaluate('async()=>await document.fonts.ready')
            text = lambda name: tab.locator(f'[data-resume-element="{name}"] [data-resume-text]')
            brush = tab.locator('#resume-font-brush')

            def arm(name='source', locked=False, offsets=(0, 2)):
                text(name).evaluate(SELECT, offsets)
                brush.dblclick() if locked else brush.click()
                expect(brush).to_have_attribute('aria-pressed', 'true')

            def paint(name, offsets):
                text(name).evaluate(SELECT, offsets)
                text(name).dispatch_event('pointerup')

            def matching(actual, expected):
                for key in ['family', 'weight', 'italic', 'color']:
                    assert actual[key] == expected[key], (key, actual, expected)
                assert abs(actual['size']-expected['size']) < .02, (actual, expected)

            # Missing source is actionable and does not arm the brush.
            brush.click(); expect(brush).to_have_attribute('aria-pressed', 'false')
            expect(tab.locator('#resume-hint')).to_contain_text('请先选中源文字')
            src = text('source').evaluate(FONTS)[0]
            before = text('target').evaluate(FONTS)
            frame_before = text('target').evaluate('el=>({left:el.parentElement.style.left,width:el.parentElement.style.width,align:getComputedStyle(el).textAlign,layout:el.parentElement.dataset.layout})')
            arm()
            # Real pointer drag over a subset, including existing nested bold.
            points = text('target').evaluate("""el=>{
                const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT), chars=[];
                while(walker.nextNode()){const node=walker.currentNode;for(let i=0;i<node.length;i++){
                    const r=document.createRange();r.setStart(node,i);r.setEnd(node,i+1);const b=r.getBoundingClientRect();chars.push({x:b.x,y:b.y,w:b.width,h:b.height});}}
                return {start:{x:chars[2].x+.2,y:chars[2].y+chars[2].h/2},end:{x:chars[5].x+chars[5].w-.2,y:chars[5].y+chars[5].h/2}};
            }""")
            tab.mouse.move(**points['start']); tab.mouse.down(); tab.mouse.move(**points['end'], steps=16); tab.mouse.up()
            expect(brush).to_have_attribute('aria-pressed', 'false')
            after = text('target').evaluate(FONTS)
            assert ''.join(c['char'] for c in after) == '前缀目标文字后缀'
            assert after[:2] == before[:2] and after[6:] == before[6:]
            for char in after[2:6]: matching(char, src)
            assert text('target').evaluate('el=>({left:el.parentElement.style.left,width:el.parentElement.style.width,align:getComputedStyle(el).textAlign,layout:el.parentElement.dataset.layout})') == frame_before
            text('target').press('Control+z'); assert text('target').evaluate(FONTS) == before
            text('target').press('Control+y'); assert text('target').evaluate(FONTS) == after

            # Continuous mode, cross-page px/pt conversion, repeated use and Esc.
            arm(locked=True)
            paint('second', (0, 2)); expect(brush).to_have_attribute('aria-pressed', 'true')
            for char in text('second').evaluate(FONTS)[:2]: matching(char, src)
            paint('multiline', (0, 10)); expect(brush).to_have_attribute('aria-pressed', 'true')
            text('multiline').press('Escape'); expect(brush).to_have_attribute('aria-pressed', 'false')
            expect(text('multiline')).to_have_text('首行文字\n\n末行文字')
            # A regular source removes both bold and italic from a painted range.
            arm('normal'); paint('target', (3, 5))
            regular = text('normal').evaluate(FONTS)[0]
            for char in text('target').evaluate(FONTS)[3:5]: matching(char, regular)
            # Copy from a painted local span, using the first selected character.
            arm('target', offsets=(2, 4)); paint('second', (2, 4))
            for char in text('second').evaluate(FONTS)[:4]: matching(char, src)
            # Keyboard selection works with the brush and can be cancelled at toolbar focus.
            arm(); text('normal').evaluate(SELECT, (0, 0)); text('normal').press('Shift+ArrowRight')
            expect(brush).to_have_attribute('aria-pressed', 'false')
            matching(text('normal').evaluate(FONTS)[0], src)
            arm(); brush.focus(); brush.press('Escape'); expect(brush).to_have_attribute('aria-pressed', 'false')
            expected = {name:text(name).evaluate(FONTS) for name in ['source','normal','target','multiline','second']}
            # Saving while armed resets transient UI, retains all font attributes,
            # blank lines, text escaping, and continues to support a second save.
            arm(locked=True)
            for iteration in [1, 2]:
                with tab.expect_download() as download: tab.locator('#resume-save').click()
                saved = output / f'min-{minimum}-saved-{iteration}.html'
                download.value.save_as(saved)
                tab.goto(saved.as_uri()); tab.evaluate('async()=>await document.fonts.ready')
                expect(brush).to_have_attribute('aria-pressed', 'false')
                assert tab.locator('body').get_attribute('class') in [None, '']
                for name, fonts in expected.items(): assert text(name).evaluate(FONTS) == fonts, name
                expect(text('multiline')).to_have_text('首行文字\n\n末行文字')
            tab.screenshot(path=output/f'font-brush-{minimum}.png', full_page=True)
            tab.emulate_media(media='print'); expect(brush).not_to_be_visible()
            (output/f'font-brush-{minimum}.pdf').write_bytes(tab.pdf(print_background=True, prefer_css_page_size=True))
            reports.append({'minimumFontSize':minimum, 'partialSelection':True, 'undoRedo':True, 'continuous':True, 'crossPageUnits':True, 'saveReopenTwice':True})
            browser.close()
    assert not errors, errors
    assert not external, external
    (output/'report.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Font brush passed: real drag, font properties, partial selection, undo/redo, continuous mode, Esc, keyboard selection, pt/px pages, multiline, two saves and print; minimum fonts 0/24px; no page errors or external requests.')


if __name__ == '__main__':
    main()
