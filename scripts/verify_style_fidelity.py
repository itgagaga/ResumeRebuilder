"""Browser-generated fictional truth: measure bold precision/recall and decoration coverage."""
import difflib
import argparse
import html
import io
import json
import sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from PIL import Image
import numpy as np
import cv2
from playwright.sync_api import sync_playwright
from backend.browser import launch_browser
from backend.ocr import recognize
from backend.image_layout import recover_shapes
from backend.models import Project,Page
from backend.exporter import render_html

THEMES=[('sans','Arial, Microsoft YaHei, sans-serif','#f9fafc'),
        ('serif','Times New Roman, SimSun, serif','#fafafa'),
        ('deng','Arial, DengXian, sans-serif','#f1f7f5'),
        ('mixed','Calibri, Microsoft YaHei, sans-serif','#eef5fc')]

def fixture(family,fill,dense=False):
    records=[('研发实践',True,None),('2022-08 — 2025-11',True,None),
             ('负责可靠系统设计与持续质量改进工作',False,(4,8)),
             ('持续验证项目功能，整理文档并改善交付流程。',False,None),
             ('工具与方法',False,None),('Data Analysis and Document Search',False,(5,13)),
             ('参与代码审查与自动化测试，跟踪结果并复盘。',False,None)]
    if dense:
        records=[('研发实践',True,None),('2022-08 — 2025-11',False,None)]
        paragraphs=[
            '围绕用户需求梳理业务流程，设计页面交互和服务接口，整理开发说明与使用手册。通过自动化测试验证数据处理结果，记录异常情况并跟踪修复，在迭代中持续改进功能与体验。',
            '参与模块开发与联调，使用 Data Tools 完成数据分析与质量检查。与团队共同制定交付计划，跟踪问题清单、审核测试结果，保持沟通记录和变更说明，确保文档、配置及运行结果一致。',
            '对比多种实现方案，整理性能指标与验证记录。根据评审意见调整系统结构，补充边界条件和失败恢复策略，通过回归测试确认修改效果，同时持续维护部署说明和日常检查流程。',
            '结合任务目标编写测试案例，核对计算结果与页面展示，分析数据差异并记录处理过程。独立完成常用工具脚本，减少重复操作，支持协作人员快速复现问题并确认解决结果。']
        for i in range(12):
            if i==6:records.append(('工具与方法',True,None))
            prefix=['能力说明：','协作方式：','质量实践：'][i%3] if i%3==0 else ''
            text=prefix+paragraphs[i%4]
            records.append((text,False,(0,len(prefix)) if prefix else None))
    rows=[]
    for i,(text,bold,span) in enumerate(records):
        content=html.escape(text)
        if span:
            a,b=span;content=html.escape(text[:a])+'<b>'+html.escape(text[a:b])+'</b>'+html.escape(text[b:])
        heading=(text in ('研发实践','工具与方法')) if dense else i in (0,4)
        rows.append(f'<div class="row {"heading" if heading else ""}" data-key="{i}" data-bold="{str(bold).lower()}" data-span="{json.dumps(span)}" style="font-weight:{700 if bold else 400}">{content}</div>')
    return f'''<!doctype html><meta charset="utf-8"><style>
    *{{box-sizing:border-box}}body{{margin:0;background:white;font-family:{family};color:#333333}}
    main{{width:1000px;min-height:900px;padding:40px}}
    .row{{font-size:{18 if dense else 26}px;line-height:{1.5 if dense else 1.4};margin-bottom:{12 if dense else 28}px;white-space:{'normal' if dense else 'nowrap'}}}
    .heading{{background:{fill};position:relative;padding:8px 20px;height:54px}}
    .heading:before{{content:'';position:absolute;left:0;top:0;width:14px;height:54px;border-left:5px solid #6397cf;border-radius:14px 0 0 14px}}
    </style><main>{''.join(rows)}</main>'''

def compare(elements,truth,factor):
    tp=fp=fn=correct=aligned=total=0;rows=[]
    for target in truth:
        text=target['text'];expected=[target['bold']]*len(text)
        if target['span']:
            a,b=target['span'];expected[a:b]=[True]*(b-a)
        candidates=sorted([e for e in elements if e.type=='text' and target['y']*factor-3<=e.y+e.height/2<=(target['y']+target['height'])*factor+3],key=lambda e:e.y)
        lines=[]
        for element in candidates:
            if lines and abs(element.y-lines[-1][0].y)<=3*factor:lines[-1].append(element)
            else:lines.append([element])
        candidates=[e for line in lines for e in sorted(line,key=lambda e:e.x)]
        observed=''.join(e.text for e in candidates);weights=[]
        for e in candidates:
            weights.extend(next((r.fontWeight>=600 for r in e.textRuns if r.start<=i<r.end),e.style.fontWeight>=600) for i in range(len(e.text)))
        matcher=difflib.SequenceMatcher(None,text,observed,autojunk=False);row_correct=row_total=0
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                i,j=block.a+offset,block.b+offset
                if text[i].isspace():continue
                want,got=expected[i],weights[j]
                tp+=want and got;fp+=not want and got;fn+=want and not got
                correct+=want==got;aligned+=1;row_correct+=want==got;row_total+=1
        total+=sum(not c.isspace() for c in text)
        rows.append({'text':text,'observed':observed,'styleAccuracy':row_correct/max(1,row_total),'weights':[e.style.fontWeight for e in candidates], 'runs':[[r.model_dump() for r in e.textRuns] for e in candidates]})
    return {'characterCoverage':aligned/max(1,total),'weightAccuracy':correct/max(1,aligned),'falseBoldRate':fp/max(1,aligned-tp-fn),
            'boldPrecision':tp/max(1,tp+fp),'boldRecall':tp/max(1,tp+fn),'rows':rows}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--raw',action='store_true');parser.add_argument('--filter',default='');parser.add_argument('--dense',action='store_true');args=parser.parse_args()
    output=ROOT/('artifacts/typography-20261015/dense' if args.dense else 'artifacts/style-fidelity/corpus');output.mkdir(parents=True,exist_ok=True)
    fixtures=[]
    with sync_playwright() as pw:
        browser=launch_browser(pw);tab=browser.new_page(viewport={'width':1000,'height':900})
        for key,family,fill in (THEMES[:2] if args.dense else THEMES):
            tab.set_content(fixture(family,fill,args.dense));tab.evaluate('async()=>await document.fonts.ready')
            truth=tab.locator('[data-key]').evaluate_all('els=>els.map(e=>{const b=e.getBoundingClientRect();return {text:e.textContent,x:b.x,y:b.y,width:b.width,height:b.height,heading:e.classList.contains("heading"),bold:e.dataset.bold==="true",span:JSON.parse(e.dataset.span)}})')
            raw=tab.screenshot(full_page=True)
            for scale,kind in [(1,'png'),(.72,'jpeg')]:
                image=Image.open(io.BytesIO(raw)).convert('RGB')
                if scale!=1:
                    image=image.resize((round(image.width*scale),round(image.height*scale)),Image.Resampling.LANCZOS)
                    stream=io.BytesIO();image.save(stream,format='JPEG',quality=78);image=Image.open(io.BytesIO(stream.getvalue())).convert('RGB')
                name=f'{key}-{kind}';image.save(output/f'{name}.{kind}')
                if args.filter and args.filter not in name:continue
                fixtures.append((name,image,truth))
        browser.close()
    if not fixtures:parser.error('没有匹配的样例')
    report=[]
    for name,image,truth in fixtures:
        if args.raw:
            from unittest.mock import patch
            with patch('backend.typography.smooth_typography',lambda analyses,*args,**kwargs:analyses),patch('backend.browser_typography.refine_typography',lambda *args:(None,None)):
                elements=recognize(image,595.28,1)
        else:elements=recognize(image,595.28,1)
        shapes,_=recover_shapes(image,595.28,1)
        metrics=compare(elements,truth,595.28/1000)
        bands=[s for s in shapes if s.width>595.28*.8 and s.height>20]
        accents=[s for s in shapes if s.shape=='polygon']
        metrics.update(bands=len(bands),curvedAccents=len(accents))
        band_ious=[];accent_ious=[]
        page_factor=595.28/1000;pixel_factor=image.width/595.28
        rgb=np.asarray(image);pixel_scale=image.width/1000
        for target in [t for t in truth if t['heading']]:
            x,y,width,height=[target[k]*page_factor for k in ('x','y','width','height')]
            if bands:
                band=min(bands,key=lambda e:abs(e.y-y))
                overlap=max(0,min(x+width,band.x+band.width)-max(x,band.x))*max(0,min(y+height,band.y+band.height)-max(y,band.y))
                band_ious.append(overlap/max(1,width*height+band.width*band.height-overlap))
            left,top,right,bottom=round(target['x']*pixel_scale),round(target['y']*pixel_scale),round((target['x']+16)*pixel_scale),round((target['y']+target['height'])*pixel_scale)
            patch=rgb[top:bottom,left:right].astype(float)
            expected=(patch.max(axis=2)-patch.min(axis=2)>35)
            recovered=np.zeros(rgb.shape[:2],dtype=np.uint8)
            if accents:
                accent=min(accents,key=lambda e:abs(e.y-y))
                points=np.array([[(accent.x+px*accent.width)*pixel_factor,(accent.y+py*accent.height)*pixel_factor] for px,py in accent.shapePoints]).round().astype(np.int32)
                cv2.fillPoly(recovered,[points],1)
            observed=recovered[top:bottom,left:right]>0
            accent_ious.append(float((expected&observed).sum()/max(1,(expected|observed).sum())))
        metrics.update(minBandIoU=min(band_ious,default=0),minAccentIoU=min(accent_ious,default=0))
        project=Project(projectId='quality',name='虚构样式验收',pages=[Page(id='page',width=595.28,height=image.height*595.28/image.width,elements=shapes+elements)])
        (output/f'{name}.json').write_text(project.model_dump_json(indent=2),encoding='utf8')
        (output/f'{name}.html').write_text(render_html(project,editable=True),encoding='utf8')
        with sync_playwright() as pw:
            browser=launch_browser(pw);tab=browser.new_page();tab.set_content(render_html(project));tab.evaluate('async()=>await document.fonts.ready')
            metrics['overflow']=tab.locator('.page>div>span').evaluate_all('els=>els.filter(e=>e.scrollHeight>e.clientHeight+2||e.scrollWidth>e.clientWidth+2).length')
            tab.locator('.page').screenshot(path=output/f'{name}-restored.png');browser.close()
        passed=metrics['characterCoverage']>=.9 and metrics['weightAccuracy']>=.9 and metrics['boldPrecision']>=.85 and metrics['boldRecall']>=.85 and len(bands)==2 and len(accents)==2 and metrics['minBandIoU']>=.85 and metrics['minAccentIoU']>=.7 and metrics['overflow']==0
        report.append({'fixture':name,'passes':passed,**metrics})
        report_name='report-raw.json' if args.raw else 'report-filtered.json' if args.filter else 'report.json'
        (output/report_name).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'fixture':name,'passes':passed,**{k:v for k,v in metrics.items() if k!='rows'}}),flush=True)
    archive=output/'runs';archive.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    (archive/f'{stamp}-{report_name}').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    assert all(r['passes'] for r in report), 'Style gates failed; preserve report and fix the missed styles.'
    print(f'{len(report)}/{len(report)} style gates passed.',flush=True)

if __name__=='__main__':main()
