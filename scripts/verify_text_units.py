"""Check actual line breaks under browser minimum-font settings, using an isolated API.

Optional --project reads a private saved project without changing it. Only synthetic
text is used by default; reports and screenshots stay in ignored artifacts/.
"""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.browser import launch_browser, system_browser
from backend.exporter import render_html
from backend.font_metrics import calibrate_text_widths
from backend.models import Element, Page, Project, Style, TextRun
from playwright.sync_api import expect, sync_playwright


# Check glyph positions, not scrollHeight/clientHeight: contenteditable expands
# to fit unwanted extra lines and can still overlap the next positioned object.
LINE_METRICS = """els=>els.map(el=>{
    const rows=[], walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
    const cs=getComputedStyle(el), zoom=Number(cs.zoom)||1;
    const scaleY=Math.abs(new DOMMatrixReadOnly(cs.transform).d)*zoom;
    const page=el.closest('.paper') || el.closest('.page');
    const pageScale=page.getBoundingClientRect().height/page.offsetHeight;
    const tolerance=parseFloat(getComputedStyle(el).lineHeight)*scaleY*pageScale*.4;
    while(walker.nextNode()) {
        const text=walker.currentNode;
        for(let i=0;i<text.length;i++) {
            if(/\\s/.test(text.data[i])) continue;
            const range=document.createRange();range.setStart(text,i);range.setEnd(text,i+1);
            const rect=range.getBoundingClientRect(), center=(rect.top+rect.bottom)/2;
            if(!rows.some(y=>Math.abs(y-center)<tolerance)) rows.push(center);
        }
    }
    return {text:el.textContent,lines:rows.length,font:cs.fontSize,effectiveFont:parseFloat(cs.fontSize)*zoom,
            width:el.getBoundingClientRect().width,frameWidth:el.parentElement.getBoundingClientRect().width};
})"""


def fixture():
    rows = [
        '1. 系统设计：基于本地任务框架，按传感器接收、数据处理、无线通信、音频播放、定位和电源管理划分模块，各部分通过队列交互，末尾保留完整组件',
        '2. Mixed text: GPIO interrupts, FreeRTOS tasks, UART DMA, GPS / MQTT，中文与英文混合正文，检查最后两个字符组件',
        '3. 普通正文和局部粗体共同保留，并检查标点、日期2026-10和英文SDK的实际字宽，长行不能因为浏览器抬高最小字号而掉到下面组件',
    ]
    elements = [Element(id=f'line{i}', type='text', text=text, x=24, y=40+i*30, width=540, height=12,
                        style=Style(fontFamily='Calibri, SimHei, sans-serif',fontSize=8.818962962963),
                        textRuns=[TextRun(start=3,end=8)] if i == 2 else []) for i,text in enumerate(rows)]
    elements.append(Element(id='tiny',type='text',text='较小字号测试 ABC 2026',x=24,y=140,width=90,height=5.6,
                            style=Style(fontSize=4,fontFamily='Calibri, Microsoft YaHei, sans-serif')))
    assert calibrate_text_widths(elements,595)
    # A genuine multiline paragraph and a fixed overflowing box must keep their
    # respective behavior; don't hide the bug by disabling all line wrapping.
    elements += [Element(id='paragraph',type='text',text='可编辑段落，允许自动换行并随输入增长。'*7,
                         x=24,y=160,width=220,height=100,textLayout='paragraph',style=Style(fontSize=10)),
                 Element(id='fixed',type='text',text='固定尺寸的文字框内容太长，应提示越界，不能静默掩盖。'*5,
                         x=330,y=160,width=200,height=12,textLayout='fixed',style=Style(fontSize=10))]
    return Project(projectId='text_units',name='文字单位验收',pages=[Page(id='page',width=595,height=842,elements=elements)])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path)
    parser.add_argument('--pixels',action='store_true',help='Use an equivalent px-unit synthetic page')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/text-units')
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    project=Project.model_validate_json(args.project.read_text(encoding='utf8')) if args.project else fixture()
    if args.pixels:
        if args.project:parser.error('--pixels is only for the synthetic fixture')
        for page in project.pages:
            page.unit='px';page.width*=96/72;page.height*=96/72
            for element in page.elements:
                for key in ['x','y','width','height']:setattr(element,key,getattr(element,key)*96/72)
                element.style.fontSize*=96/72
    original=project.model_dump();saved=[original];errors=[];reports=[]
    with sync_playwright() as pw:
        for minimum in [0,10,12,16,24]:
            executable=system_browser()
            browser=pw.chromium.launch(headless=True,executable_path=str(executable),args=[f'--blink-settings=minimumFontSize={minimum}']) if executable else launch_browser(pw)
            tab=browser.new_page(viewport={'width':1700,'height':1100})
            tab.on('pageerror',lambda error:errors.append(str(error)))
            def route_handler(route):
                url=urlparse(route.request.url);path=url.path
                if url.hostname!='127.0.0.1':route.abort();return
                if path=='/api/health':route.fulfill(json={'ocrReady':True,'pdfReady':True})
                elif path=='/api/projects':route.fulfill(json=[{'projectId':project.projectId,'name':project.name,'pages':len(project.pages)}])
                elif path==f'/api/projects/{project.projectId}':
                    if route.request.method=='PUT':saved.append(Project.model_validate(route.request.post_data_json).model_dump())
                    route.fulfill(json=saved[-1])
                elif path==f'/api/projects/{project.projectId}/reference/1' and args.project:
                    reference=args.project.parent/'reference/1.png'
                    route.fulfill(path=reference) if reference.is_file() else route.fulfill(status=404)
                elif path.startswith('/api/'):route.fulfill(status=404,json={})
                else:
                    root=(ROOT/'frontend/dist').resolve();target=(root/(path.lstrip('/') or 'index.html')).resolve()
                    route.fulfill(path=target) if target.is_relative_to(root) and target.is_file() else route.fulfill(status=404)
            tab.route('**/*',route_handler)
            def open_editor():
                tab.goto('http://127.0.0.1:8765/')
                tab.locator('.recent-grid button').first.click()
                tab.locator('[data-text-id]').first.wait_for()
                tab.evaluate('async()=>await document.fonts.ready')
            saved[:]=[original];open_editor()
            reference=browser.new_page();reference.route('**/*',lambda route:route.abort())
            reference.set_content(render_html(project));reference.evaluate('async()=>await document.fonts.ready')
            export_metrics=reference.locator('.page>div>span').evaluate_all(LINE_METRICS)
            reference.set_content(render_html(project,editable=True));reference.evaluate('async()=>await document.fonts.ready')
            standalone_metrics=reference.locator('[data-resume-text]').evaluate_all(LINE_METRICS)
            assert len(standalone_metrics)==len(export_metrics)
            for actual,exported in zip(standalone_metrics,export_metrics):
                assert actual['lines']==exported['lines'],('standalone',minimum,actual,exported)
                assert abs(actual['effectiveFont']-exported['effectiveFont'])<.02,('standalone',minimum,actual,exported)
                assert abs(actual['width']-actual['frameWidth'])<1,('standalone width',minimum,actual)
            text_elements=[e for e in sorted(project.pages[0].elements,key=lambda e:e.zIndex) if e.type=='text']
            for mode in ['只读预览']:
                metrics=tab.locator('[data-text-id]').evaluate_all(LINE_METRICS)
                assert len(metrics)==len(export_metrics)
                for source,actual,exported in zip(text_elements,metrics,export_metrics):
                    assert actual['lines']==exported['lines'],(minimum,mode,source.id,actual,exported)
                    factor=96/72 if project.pages[0].unit=='pt' else 1
                    assert abs(actual['effectiveFont']-source.style.fontSize*factor)<.02,(minimum,source.id,actual)
                    if abs(source.rotation)<.1:
                        assert abs(actual['width']-actual['frameWidth'])<1,(minimum,source.id,actual)
                    if source.height < source.style.fontSize*1.5 and source.textLayout!='fixed':
                        assert actual['lines']==1,(minimum,source.id,actual)
                reports.append({'minimumFontSize':minimum,'mode':mode,'blocks':len(metrics),'lineCounts':[m['lines'] for m in metrics],
                                'belowMinimumWrapped':[e.id for e,m in zip(text_elements,metrics) if e.height<e.style.fontSize*1.5 and e.style.fontSize*factor<minimum and m['lines']>1]})
            if not args.project:
                # Demonstrate that the old unit conversion produces the reported
                # symptom with only the minimum font setting changed.
                if minimum==12 and not args.pixels:
                    tab.locator('[data-text-id="line0"]').evaluate("""el=>{
                        el.style.zoom='1';el.style.fontSize=(parseFloat(el.parentElement.style.fontSize)*4/3)+'px';
                        const m=new DOMMatrixReadOnly(el.style.transform), s=m.a/m.d;
                        el.style.width=(100*4/3/s)+'%';el.style.minHeight=(parseFloat(el.parentElement.style.height)*4/3)+'px';
                    }""")
                    before=tab.locator('[data-text-id="line0"]').evaluate_all(LINE_METRICS)[0]
                    assert before['lines']==2,before
                    tab.screenshot(path=output/'before-minimum-12.png',full_page=True)
                    saved[:]=[original];open_editor()
                # Fixed-frame overflow is still diagnosed in the read-only status.
                expect(tab.locator('.status-right')).to_contain_text('文字溢出')
                assert next(m['lines'] for m in metrics if m['text'].startswith('可编辑段落')) > 1
            tab.screenshot(path=output/f'after-minimum-{minimum}.png',full_page=True)
            browser.close()
    assert not errors,errors
    (output/'report.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    details='Private project read-only.' if args.project else ('Pixel-page multiline rendering and fixed overflow verified.' if args.pixels else 'Old behavior reproduced; multiline rendering and fixed overflow verified.')
    print(f'Passed {len(reports)} rendering cases: minimum fonts 0/10/12/16/24px, read-only preview; actual effective font sizes and glyph line counts match export. '+details)


if __name__=='__main__':main()
