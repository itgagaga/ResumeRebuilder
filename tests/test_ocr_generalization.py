from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image,ImageDraw

from backend import ocr
from backend.image_layout import FONT_CHOICES,load_font,recover_text,recover_bullet


@pytest.mark.parametrize('choice_index',[0,2,3])
@pytest.mark.parametrize('size',[22,34])
def test_typography_uses_pixels_across_font_families_and_sizes(choice_index,size):
    choice = FONT_CHOICES[choice_index]
    chinese,latin = load_font(choice[1],size),load_font(choice[3],size)
    if chinese is None or latin is None: pytest.skip('System fonts unavailable')
    image = Image.new('RGB',(1000,130),'white');draw = ImageDraw.Draw(image)
    text = '数据分析与工具 Vector Search';words=[];x=30
    for char in text:
        font = latin if char.isascii() else chinese
        box = draw.textbbox((x,40),char,font=font,anchor='lt')
        draw.text((x,40),char,font=font,fill='#222222',anchor='lt')
        if not char.isspace(): words.append((char,.99,[[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]]))
        x += font.getlength(char)
    box = np.array([[26,36],[x+3,36],[x+3,40+size+4],[26,40+size+4]])
    recovered = recover_text(np.asarray(image),text,box,words,.99,1,1)
    assert abs(recovered.style.fontSize-size)/size < .15
    assert choice[0].split(', ')[1] in recovered.style.fontFamily
    assert choice[0].split(', ')[0] in recovered.style.fontFamily
    assert recovered.text == text


def test_weak_line_retry_preserves_original_coordinate_system():
    image = Image.new('RGB',(400,200),'white')
    old = (np.array([[100,50],[300,50],[300,85],[100,85]]),'X',.52,[])
    calls=[]
    def engine(crop,**options):
        calls.append((crop.size,options))
        return SimpleNamespace(boxes=np.array([[[3,3],[203,3],[203,38],[3,38]]]),txts=['Recovered text'],scores=[.97],
                               word_results=[[('R',.99,[[3,3],[15,3],[15,38],[3,38]])]])
    recovered = ocr.retry_line(engine,image,old)
    assert calls[0][1]['use_cls'] is False
    assert recovered[1] == 'Recovered text' and recovered[2] == .97
    assert np.array_equal(recovered[0],old[0])
    assert recovered[3][0][2][0] == [100,50]


def test_word_gap_recovery_does_not_split_normally_spaced_letters():
    from backend.typography import restore_spaces
    def words(text,gap_after=None):
        result=[];x=0
        for index,char in enumerate(text):
            result.append((char,.99,[[x,0],[x+10,0],[x+10,20],[x,20]]))
            x += 20 if index == gap_after else 12
        return result
    assert restore_spaces('RESUME',words('RESUME')) == 'RESUME'
    assert restore_spaces('WebSearch',words('WebSearch',2)) == 'Web Search'


def test_failed_retry_keeps_other_rows_and_marks_low_confidence(monkeypatch):
    calls=[]
    def engine(image,**options):
        calls.append(options)
        if len(calls)>1: raise RuntimeError('Retry unavailable')
        return SimpleNamespace(boxes=np.array([[[10,10],[100,10],[100,35],[10,35]]]),txts=['weak'],scores=[.55],word_results=[[]])
    monkeypatch.setattr(ocr,'get_engine',lambda:engine)
    monkeypatch.setattr('backend.font_metrics.calibrate_text_widths',lambda *args:False)
    elements = ocr.recognize(Image.new('RGB',(150,60),'white'),595,1)
    assert len(elements) == 1 and elements[0].text == 'weak'
    assert elements[0].sourceRegion.confidence == .55
    assert elements[0].style.fontScaleX == 1


def test_style_estimation_failure_does_not_erase_recognized_text(monkeypatch):
    def engine(image,**options):
        return SimpleNamespace(boxes=np.array([[[10,10],[100,10],[100,35],[10,35]]]),txts=['Keep this text'],scores=[.99],word_results=[[]])
    def fail(*args,**kwargs): raise ValueError('Unusual typography')
    monkeypatch.setattr(ocr,'get_engine',lambda:engine)
    monkeypatch.setattr('backend.image_layout.recover_text',fail)
    monkeypatch.setattr('backend.font_metrics.calibrate_text_widths',lambda *args:False)
    result = ocr.recognize(Image.new('RGB',(150,60),'white'),595,1)
    assert len(result) == 1 and result[0].text == 'Keep this text'
    assert result[0].sourceRegion.detectedFrom == 'ocr-style-fallback'


@pytest.mark.parametrize('scale',[.6,1,2])
def test_bullet_geometry_is_scale_relative(scale):
    image = Image.new('RGB',(round(600*scale),round(100*scale)),'white');draw=ImageDraw.Draw(image)
    draw.ellipse(tuple(round(n*scale) for n in (40,32,46,38)),fill='#333333')
    for x in (65,84): draw.rectangle(tuple(round(n*scale) for n in (x,25,x+11,45)),fill='#333333')
    box = np.array([[35,20],[110,20],[110,50],[35,50]])*scale
    from backend.models import Element
    element = Element(id='t',type='text',text='item',x=35*scale,y=20*scale,width=75*scale,height=30*scale)
    bullet = recover_bullet(np.asarray(image),element,box,1,1)
    assert bullet is not None
    assert abs(element.x-65*scale) <= 1
