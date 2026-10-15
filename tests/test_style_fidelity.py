"""Style regressions across colors/scales; no private resume content or title keywords."""
import io

import numpy as np
import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from backend.image_layout import recover_shapes, load_font, FONT_CHOICES, recover_text
from backend.models import Element, Page, Project, Style
from backend.exporter import render_html
from types import SimpleNamespace


@pytest.mark.parametrize('fill',['#f9fafc','#fafafa','#eff8f8','#edf0f8'])
@pytest.mark.parametrize('scale',[.65,1,1.6])
def test_pale_bands_and_curved_accents_survive_jpeg(fill,scale):
    image = Image.new('RGB',(1000,1400),'white'); draw = ImageDraw.Draw(image)
    for y in [180,600]:
        draw.rectangle((40,y,950,y+49),fill=fill)
        draw.arc((40,y,62,y+49),90,270,fill='#6397cf',width=5)
        # Text holes and compression must not fragment the background.
        draw.rectangle((90,y+15,105,y+31),fill='#333333')
    # Photo-like content contains a narrow colored stripe; it is not a section accent.
    draw.rectangle((850,30,950,120),fill='#abbccc')
    draw.rectangle((860,35,866,110),fill='#6397cf')
    image = image.resize((round(1000*scale),round(1400*scale)),Image.Resampling.LANCZOS)
    encoded = io.BytesIO();image.save(encoded,format='JPEG',quality=78)
    shapes,_ = recover_shapes(Image.open(io.BytesIO(encoded.getvalue())),1000,1)
    bands = [e for e in shapes if e.width>800 and e.height>30]
    curves = [e for e in shapes if e.shape=='polygon']
    assert len(bands)==2 and len(curves)==2
    for y in [180,600]:
        band = min(bands,key=lambda e:abs(e.y-y))
        assert abs(band.y-y)<4 and abs(band.height-50)<6
        accent = min(curves,key=lambda e:abs(e.y-y))
        assert abs(accent.x-40)<4 and abs(accent.height-50)<7
    assert all(e.assetId is None for e in shapes)


@pytest.mark.parametrize('choice_index',[0,2,3])
@pytest.mark.parametrize('weight',[400,700])
def test_numeric_metadata_recovers_weight_and_size(choice_index,weight):
    choice = FONT_CHOICES[choice_index];size=28
    font=load_font(choice[4 if weight==700 else 3],size)
    if font is None:pytest.skip('System fonts unavailable')
    image=Image.new('RGB',(600,120),'white');draw=ImageDraw.Draw(image)
    text='2022-08 — 2025-11';x=25;words=[]
    for char in text:
        b=draw.textbbox((x,40),char,font=font,anchor='lt')
        draw.text((x,40),char,font=font,anchor='lt',fill='#333333')
        if not char.isspace():words.append((char,.99,[[b[0],b[1]],[b[2],b[1]],[b[2],b[3]],[b[0],b[3]]]))
        x+=font.getlength(char)
    box=np.array([[22,36],[x+4,36],[x+4,75],[22,75]])
    element=recover_text(np.asarray(image),text,box,words,.99,1,1)
    assert element.style.fontWeight==weight
    assert abs(element.style.fontSize-size)/size<.12


def test_polygon_is_validated_and_survives_html_and_project_roundtrip():
    shape=Element(id='curve',type='rect',x=20,y=50,width=10,height=40,shape='polygon',
                  shapePoints=[(0,0),(.8,0),(.3,.5),(.8,1),(0,1)],style=Style(background='#6397cf'))
    project=Project(projectId='contours',name='fictional',pages=[Page(id='page',width=595,height=842,elements=[shape])])
    restored=Project.model_validate_json(project.model_dump_json())
    assert restored.pages[0].elements[0].shapePoints==shape.shapePoints
    assert 'clip-path:polygon(' in render_html(restored,editable=True)
    assert 'clip-path:polygon(' in render_html(restored)
    with pytest.raises(ValidationError):
        Element.model_validate({**shape.model_dump(),'shapePoints':[(0,0),(2,0),(0,1)]})


@pytest.mark.parametrize('choice_index',[0,2,3])
@pytest.mark.parametrize('size',[22,32])
def test_chinese_bold_inside_sentence_is_recovered_without_prefix_rules(choice_index,size):
    choice=FONT_CHOICES[choice_index]
    regular,bold=load_font(choice[1],size),load_font(choice[2],size)
    if regular is None or bold is None:pytest.skip('System fonts unavailable')
    image=Image.new('RGB',(1100,130),'white');draw=ImageDraw.Draw(image)
    text='负责可靠系统设计与持续质量改进工作';x=30;words=[]
    for index,char in enumerate(text):
        font=bold if 4<=index<8 else regular
        stroke=1 if 4<=index<8 and choice[1]==choice[2] else 0
        b=draw.textbbox((x,40),char,font=font,anchor='lt',stroke_width=stroke)
        draw.text((x,40),char,font=font,anchor='lt',fill='#333333',stroke_width=stroke)
        words.append((char,.99,[[b[0],b[1]],[b[2],b[1]],[b[2],b[3]],[b[0],b[3]]]))
        x+=font.getlength(char)
    element=recover_text(np.asarray(image),text,np.array([[25,35],[x+4,35],[x+4,40+size+5],[25,40+size+5]]),words,.99,1,1)
    weights=[next((r.fontWeight for r in element.textRuns if r.start<=i<r.end),element.style.fontWeight) for i in range(len(text))]
    assert sum(weights[i]==700 for i in range(4,8))>=3
    assert sum(weights[i]==400 for i in list(range(4))+list(range(8,len(text))))>=len(text)-5


def test_browser_face_refinement_failure_retains_ocr_and_editable_text(monkeypatch):
    from backend import ocr
    def engine(image,**options):
        return SimpleNamespace(boxes=np.array([[[10,10],[180,10],[180,35],[10,35]]]),txts=['Retain editable text'],scores=[.99],word_results=[[]])
    def unavailable(*args):raise RuntimeError('Browser unavailable')
    monkeypatch.setattr(ocr,'get_engine',lambda:engine)
    monkeypatch.setattr('backend.browser_typography.refine_typography',unavailable)
    monkeypatch.setattr('backend.font_metrics.calibrate_text_widths',lambda *args:False)
    elements=ocr.recognize(Image.new('RGB',(220,70),'white'),595,1)
    assert len(elements)==1 and elements[0].text=='Retain editable text'
    assert elements[0].sourceRegion.confidence==.99


def test_uncertain_font_does_not_invent_bold_when_browser_refinement_is_unavailable(monkeypatch):
    from backend.image_layout import infer_runs
    text='普通正文需要保持正常字重'
    words=[(ch,.99,[[i*20,0],[i*20+18,0],[i*20+18,22],[i*20,22]]) for i,ch in enumerate(text)]
    info={'chinese':{'scores':[.84,.83,.8,.81]},'latin':{'scores':[]}}
    def should_not_match(*args,**kwargs):raise AssertionError('Uncertain font must not infer bold ranges')
    monkeypatch.setattr('backend.typography._match',should_not_match)
    assert infer_runs(np.full((40,400,3),255,dtype=np.uint8),text,words,FONT_CHOICES[0],20,np.array([255]*3),None,info)==[]


def test_dense_page_keeps_browser_refinement_with_bounded_references(monkeypatch):
    import base64
    from contextlib import nullcontext
    from backend.browser_typography import refine_typography
    rows=[];analyses=[];calls=[]
    for row_index in range(12):
        text=''.join(chr(0x4e00+row_index*100+i) for i in range(100))
        words=[(ch,.99,[[i*20,0],[i*20+18,0],[i*20+18,22],[i*20,22]]) for i,ch in enumerate(text)]
        rows.append((np.array([[0,0],[2000,0],[2000,22],[0,22]]),text,.99,words))
        analyses.append((FONT_CHOICES[0],20,400,(np.zeros((22,2000),bool),np.array([255]*3),(0,0,2000,22)),{}))
    class Tab:
        def route(self,*args):pass
        def evaluate(self,script,requests):
            calls.append(len(requests));return [[3,3,base64.b64encode(bytes([255]*9)).decode()]]*len(requests)
    class Browser:
        def new_page(self):return Tab()
        def close(self):pass
    monkeypatch.setattr('playwright.sync_api.sync_playwright',lambda:nullcontext(None))
    monkeypatch.setattr('backend.browser.launch_browser',lambda _:Browser())
    monkeypatch.setattr('backend.browser_typography.match_typography',lambda *args,**kwargs:analyses[0])
    monkeypatch.setattr('backend.browser_typography.smooth_typography',lambda values,**kwargs:values)
    refined,provider=refine_typography(np.full((40,2100,3),255,np.uint8),rows,analyses)
    assert refined is not None and len(refined)==12 and provider is not None
    assert len(calls)==2 and max(calls)<100000
    assert provider(rows[-1][1][-1],FONT_CHOICES[0],False,20) is not None
    assert provider('Z',FONT_CHOICES[0],False,90) is None


@pytest.mark.parametrize('has_space',[False,True])
def test_pixel_word_spacing_when_ocr_character_boxes_touch(has_space):
    from backend.typography import restore_spaces
    font=load_font('arial.ttf',28)
    if font is None:pytest.skip('System fonts unavailable')
    image=Image.new('RGB',(500,100),'white');draw=ImageDraw.Draw(image)
    text='WebSearch';words=[];positions=[];x=30
    for i,ch in enumerate(text):
        if i==3 and has_space:x+=font.getlength(' ')
        positions.append(x);draw.text((x,30),ch,font=font,fill='#222222',anchor='lt');x+=font.getlength(ch)
    positions.append(x)
    for i,ch in enumerate(text):
        left,right=positions[i],positions[i+1]
        words.append((ch,.99,[[left,25],[right,25],[right,64],[left,64]]))
    assert restore_spaces(text,words,np.asarray(image),FONT_CHOICES[0],28)==('Web Search' if has_space else 'WebSearch')


def test_numeric_labels_do_not_invent_mixed_weight(monkeypatch):
    from backend.image_layout import infer_runs
    def should_not_match(*args,**kwargs):raise AssertionError('Use the token face for numeric labels')
    monkeypatch.setattr('backend.typography._match',should_not_match)
    assert infer_runs(np.full((40,300,3),255,np.uint8),'2022/08 - 2025/11',[],FONT_CHOICES[0],22,np.array([255]*3))==[]
