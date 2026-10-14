"""Generate independent browser-rendered fixtures, then measure before/after OCR reconstruction."""
import argparse
import difflib
import html
import io
import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))

from PIL import Image
from playwright.sync_api import sync_playwright
from backend import ocr
from backend.browser import launch_browser
from backend.exporter import render_html
from backend.image_layout import recover_shapes
from backend.models import Page,Project


THEMES = [
    ('sans','Arial, Microsoft YaHei, sans-serif',22,False,'#14786d'),
    ('serif','Times New Roman, SimSun, serif',22,False,'#333333'),
    ('mixed','Calibri, Microsoft YaHei, sans-serif',20,False,'#315d86'),
    ('columns','Arial, DengXian, sans-serif',20,True,'#684d7c'),
]


def fixture(family,size,columns,color):
    records = [
        ('name','林知远',30,True),
        ('contact','示例资料 / OFFLINE RESUME',size,False),
        ('heading','项目实践',size+5,True),
        ('intro','负责界面体验与数据处理，协作完成系统开发和质量改进。',size,False),
        ('tech','Engineering: Python, Spring Boot, PostgreSQL, Redis.',size,False),
        ('work','通过测试验证可靠性，持续改善文档、工具与交付流程。',size,False),
        ('english','Document Search uses Hybrid Retrieval and Query Rewrite.',size,False),
        ('metric','Performance: 97.5% accuracy, 120 ms response time.',size,False),
        ('heading2','教育与技能',size+5,True),
        ('school','示例学院 · 软件工程 · 2020 — 2024',size,False),
        ('skills','掌握软件设计、团队沟通、自动化测试与项目管理。',size,False),
        ('final','All content in this fixture is fictional and generated locally.',size,False),
    ]
    rows = []
    for key,text,fontsize,bold in records:
        tag = 'h2' if key.startswith('heading') else 'p'
        rows.append(f'<{tag} data-line="{key}" style="font-size:{fontsize}px;font-weight:{700 if bold else 400}">{html.escape(text)}</{tag}>')
    if columns:
        body = ''.join(rows[:3])+f'<div class="columns"><div>{"".join(rows[3:8])}</div><div>{"".join(rows[8:])}</div></div>'
    else: body = ''.join(rows)
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
    *{{box-sizing:border-box}}body{{margin:0;background:white;font-family:{family};color:#252525}}
    main{{width:1040px;min-height:1180px;padding:44px 54px}}p,h2{{margin:0 0 15px;line-height:1.55}}
    h2{{color:{color};border-bottom:1px solid {color};padding-bottom:4px}}
    .columns{{display:grid;grid-template-columns:1fr 1fr;gap:38px}}
    </style></head><body><main>{body}</main></body></html>'''


def normal(text): return ''.join(c for c in text if not c.isspace())


def measurements(elements,truth,width,height):
    rows,errors,total = [],0,0
    for target in truth:
        source = normal(target['text'])
        matches = [e for e in elements if e.type == 'text' and target['x']-3 <= e.x+e.width/2 <= target['x']+target['width']+3 and target['y']-3 <= e.y+e.height/2 <= target['y']+target['height']+3]
        observed = normal(''.join(e.text for e in sorted(matches,key=lambda e:(e.y,e.x))))
        matcher = difflib.SequenceMatcher(None,source,observed,autojunk=False)
        distance = sum(max(b-a,d-c) for op,a,b,c,d in matcher.get_opcodes() if op != 'equal')
        total += len(source);errors += distance
        size_error = sorted(abs(e.style.fontSize/target['size']-1) for e in matches)
        family = target['family']
        if any('\u4e00' <= c <= '\u9fff' for c in target['text']):
            expected_family = next((f for f in ['Microsoft YaHei','SimSun','DengXian','SimHei'] if f in family),family.split(',')[0].strip('" '))
        else: expected_family = family.split(',')[0].strip('" ')
        rows.append({'key':target['key'],'accuracy':max(0,1-distance/max(1,len(source))),
                     'sizeError':size_error[len(size_error)//2] if size_error else None,
                     'positionError':min(((abs(e.x-target['x'])/width+abs(e.y-target['y'])/height)/2 for e in matches),default=None),
                     'familyMatch':bool(matches) and sum(len(e.text) for e in matches if expected_family in e.style.fontFamily) >= sum(len(e.text) for e in matches)*.5,
                     'families':list(dict.fromkeys(e.style.fontFamily for e in matches)), 'missing':not matches})
    size_errors = sorted(r['sizeError'] for r in rows if r['sizeError'] is not None)
    return {'characterAccuracy':max(0,1-errors/max(1,total)), 'missingBlocks':sum(r['missing'] for r in rows),
            'medianSizeError':size_errors[len(size_errors)//2] if size_errors else None,
            'familyMatchRate':sum(r['familyMatch'] for r in rows)/len(rows),
            'meanPositionError':sum(r['positionError'] or 0 for r in rows)/len(rows),'rows':rows}


def load_baseline():
    # Read committed implementations into isolated modules; never switch the checkout.
    modules = {}
    for name in ['image_layout','ocr']:
        source = subprocess.check_output(['git','show',f'HEAD:backend/{name}.py'],cwd=ROOT).decode('utf-8')
        module = types.ModuleType(f'backend.baseline_{name}');module.__package__ = 'backend'
        exec(compile(source,f'<baseline-{name}>','exec'),module.__dict__)
        modules[name] = module
    modules['ocr']._engine = ocr.get_engine()
    return modules


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline',action='store_true')
    parser.add_argument('--quick',action='store_true',help='Use one scale per layout.')
    parser.add_argument('--holdout',action='store_true',help='Include two additional compact/multicolumn layouts not used for font tuning.')
    parser.add_argument('--filter',default='',help='Run only matching fixture names for failure diagnosis.')
    args = parser.parse_args()
    output = ROOT/'artifacts/generalization/corpus';output.mkdir(parents=True,exist_ok=True)
    report_path = output/('report-filtered.json' if args.filter else 'report.json')
    baseline = load_baseline() if args.baseline else None
    report,fixtures = [],[]
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        page = browser.new_page(viewport={'width':1040,'height':1180})
        themes = THEMES+([('compact-serif','Times New Roman, SimSun, serif',18,True,'#333333'),('compact-sans','Arial, Microsoft YaHei, sans-serif',18,False,'#555555')] if args.holdout else [])
        for name,family,size,columns,color in themes:
            for scale,kind in ([(1,'png')] if args.quick else [(1,'png'),(.72,'jpeg')]):
                key = f'{name}-{scale}-{kind}'
                if args.filter and args.filter not in key: continue
                page.set_content(fixture(family,size,columns,color))
                page.evaluate('async()=>await document.fonts.ready')
                truth = page.locator('[data-line]').evaluate_all('els=>els.map(e=>{const b=e.getBoundingClientRect();return {key:e.dataset.line,text:e.textContent,x:b.x,y:b.y,width:b.width,height:b.height,size:parseFloat(getComputedStyle(e).fontSize),family:getComputedStyle(e).fontFamily}})')
                raw = page.screenshot(type='png',full_page=True)
                image = Image.open(io.BytesIO(raw)).convert('RGB')
                if scale != 1: image = image.resize((round(image.width*scale),round(image.height*scale)),Image.Resampling.LANCZOS)
                if kind == 'jpeg':
                    stream = io.BytesIO();image.save(stream,format='JPEG',quality=74);image=Image.open(io.BytesIO(stream.getvalue())).convert('RGB')
                image.save(output/f'{key}.{kind}')
                factor = 595.28/1040
                expected = [{**r,**{k:r[k]*factor for k in ['x','y','width','height','size']}} for r in truth]
                fixtures.append((key,image,expected))
        browser.close()
    # OCR performs its own font measurement in a browser; do not nest sync Playwright sessions.
    for key,image,expected in fixtures:
        before = None
        if baseline:
            ocr.get_engine().update_params(use_det=True,use_cls=True,use_rec=True)
            with patch.dict(sys.modules,{'backend.image_layout':baseline['image_layout']}):
                old = baseline['ocr'].recognize(image,595.28,1)
            before = measurements(old,expected,595.28,image.height*595.28/image.width)
        elements = ocr.recognize(image,595.28,1)
        after = measurements(elements,expected,595.28,image.height*595.28/image.width)
        shapes,_ = recover_shapes(image,595.28,1)
        project = Project(projectId='quality',name='虚构质量验收',pages=[Page(id='p',width=595.28,height=image.height*595.28/image.width,elements=shapes+elements)])
        with sync_playwright() as pw:
            browser = launch_browser(pw);page = browser.new_page()
            page.set_content(render_html(project));page.evaluate('async()=>await document.fonts.ready')
            after['overflow'] = page.locator('.page>div>span').evaluate_all('els=>els.filter(e=>e.scrollHeight>e.clientHeight+2||e.scrollWidth>e.clientWidth+2).length')
            page.locator('.page').screenshot(path=output/f'{key}-restored.png')
            browser.close()
        (output/f'{key}.json').write_text(project.model_dump_json(indent=2),encoding='utf-8')
        row = {'fixture':key,'before':before,'after':after};report.append(row)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'fixture':key,'beforeAccuracy':before and round(before['characterAccuracy'],3),'afterAccuracy':round(after['characterAccuracy'],3),'sizeError':round(after['medianSizeError'],3),'familyMatch':round(after['familyMatchRate'],3),'missingBlocks':after['missingBlocks'],'overflow':after['overflow']}),flush=True)
    for row in report:
        a=row['after'];row['passes'] = a['characterAccuracy'] >= .90 and a['missingBlocks'] == 0 and a['overflow'] == 0 and a['medianSizeError'] <= .12 and a['familyMatchRate'] >= .65 and a['meanPositionError'] <= .015
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Passed {sum(r["passes"] for r in report)}/{len(report)} complete quality gates. Failed fixtures: '+', '.join(r['fixture'] for r in report if not r['passes']),flush=True)
    assert all(r['passes'] for r in report), 'Quality gate failed; inspect report.json instead of treating a completed render as success.'
    print(f'{len(report)} fixtures passed: text >=90%, candidate-family match >=65%, median size error <=12%, mean normalized position error <=1.5%, no missing blocks/overflow. Full metrics in {output}/report.json')


if __name__ == '__main__':main()
