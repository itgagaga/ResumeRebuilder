import numpy as np
import pytest
from PIL import Image,ImageDraw
from pydantic import ValidationError

from backend.image_layout import recover_shapes,recover_text,recover_bullet,FONT_CHOICES,load_font
from backend.models import Element,Page,Project,Style,TextRun
from backend.exporter import render_html
from backend.font_metrics import calibrate_text_widths


def test_ocr_input_preserves_rgb_color_contract(monkeypatch):
    from types import SimpleNamespace
    from backend import ocr
    seen = []
    def engine(image,**options):
        seen.append((type(image),image.getpixel((0,0))))
        return SimpleNamespace(boxes=None)
    monkeypatch.setattr(ocr,"get_engine",lambda:engine)
    assert ocr.recognize(Image.new("RGB",(40,40),(240,20,30)),595,1) == []
    assert seen == [(Image.Image,(240,20,30))]


def test_flat_heading_bands_are_editable_shapes_not_pixels():
    image = Image.new("RGB",(1000,1400),"white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40,100,950,149),fill="#eff8f8")
    draw.rectangle((40,100,44,149),fill="#00a6a7")
    draw.rectangle((40,400,950,449),fill="#ededed")
    # A uniform photo-sized region is not mistaken for a heading band or exported image asset.
    draw.rectangle((850,10,950,90),fill="#348ee2")
    shapes,background = recover_shapes(image,1000,1)
    assert background == "#ffffff"
    assert len(shapes) == 3
    assert all(e.type == "rect" and e.assetId is None for e in shapes)
    banner = next(e for e in shapes if e.style.background == "#eff8f8")
    accent = next(e for e in shapes if e.style.background == "#00a6a7")
    assert banner.x == 40 and banner.width == 911
    assert accent.zIndex > banner.zIndex


def test_heading_recovers_color_bold_and_font_size():
    font = load_font("msyhbd.ttc",28)
    if font is None: pytest.skip("中文测试需要系统微软雅黑字体")
    image = Image.new("RGB",(800,200),"white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30,30,750,90),fill="#eff8f8")
    draw.text((50,45),"专业技能",font=font,fill="#00a6a7",anchor="lt")
    element = recover_text(np.asarray(image),"专业技能",np.array([[45,40],[170,40],[170,80],[45,80]]),[],.99,1,1,FONT_CHOICES[0])
    assert element.style.color == "#00a6a7"
    assert element.style.fontWeight == 700
    assert 23 <= element.style.fontSize <= 32
    assert element.style.fontScaleX > .8


def test_browser_font_calibration_prevents_imported_line_wrapping():
    element = Element(id="t",type="text",text="专业技能 Java SpringBoot 文本宽度校准",x=0,y=0,width=180,height=30,
                      textRuns=[TextRun(start=0,end=4)],style=Style(fontSize=12))
    assert calibrate_text_widths([element],595)
    assert .4 <= element.style.fontScaleX <= 2
    assert element.textRuns[0].end == 4


def test_bullet_is_editable_geometry_with_correct_text_indent():
    image = Image.new("RGB",(600,100),"white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((40,32,46,38),fill="#333333")
    # A synthetic glyph block following a clear bullet gap.
    draw.rectangle((65,25,76,45),fill="#333333")
    draw.rectangle((84,25,95,45),fill="#333333")
    box = np.array([[35,20],[110,20],[110,50],[35,50]])
    element = Element(id="text",type="text",text="条目",x=35,y=20,width=75,height=30)
    bullet = recover_bullet(np.asarray(image),element,box,1,1)
    assert bullet is not None and bullet.shape == "circle"
    assert element.x == 65
    assert element.text == "条目"


def test_local_style_ranges_reference_current_text_and_escape_html():
    element = Element(id="text",type="text",text="技能：<script>alert(1)</script>",x=0,y=0,width=200,height=30,
                      textRuns=[TextRun(start=0,end=3)])
    project = Project(projectId="p",name="test",pages=[Page(id="page",width=595,height=842,elements=[element])])
    output = render_html(project)
    assert '<span style="font-weight:700">技能：</span>' in output
    assert "<script>" not in output and "&lt;script&gt;" in output
    element.text = "新的技能"; element.textRuns = []
    assert "alert(1)" not in render_html(project)
    with pytest.raises(ValidationError):
        Element(id="invalid",type="text",text="短",x=0,y=0,width=10,height=10,textRuns=[TextRun(start=0,end=5)])
