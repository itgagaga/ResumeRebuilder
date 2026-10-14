"""Create entirely synthetic fixtures; no real person's resume or photo is used."""
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent


def make_samples(output=ROOT / "examples"):
    output.mkdir(parents=True, exist_ok=True)
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    photo = Image.new("RGB", (160, 200), "#b8cbbb")
    draw = ImageDraw.Draw(photo)
    draw.ellipse((50, 30, 110, 90), fill="#6c8c77")
    draw.ellipse((20, 95, 140, 245), fill="#6c8c77")
    photo.save(output / "replacement.png")
    pdf = canvas.Canvas(str(output / "native-resume.pdf"), pagesize=(595.28, 841.89))
    pdf.setFillColorRGB(.18, .34, .28)
    pdf.setFont("STSong-Light", 30)
    pdf.drawString(48, 765, "张三")
    pdf.setFont("STSong-Light", 12)
    pdf.drawString(48, 737, "产品设计师 / PRODUCT DESIGNER")
    pdf.setFillColorRGB(.4, .46, .42)
    pdf.setFont("STSong-Light", 10)
    pdf.drawString(48, 707, "138 0000 0000  ·  hello@example.com  ·  上海")
    pdf.drawImage(ImageReader(photo), 460, 719, width=80, height=100)
    for title, top, rows in [
        ("个人简介", 655, ["关注体验设计与产品落地，擅长将复杂问题转化为清晰的解决方案。", "这是一份合成测试简历，所有内容均可直接修改。"]),
        ("工作经历", 550, ["示例科技有限公司  /  产品设计师", "2023.06 — 至今", "负责核心产品的交互与视觉设计，协作完成从需求到交付的全过程。", "通过用户研究与可用性测试，持续改进产品体验。"]),
        ("教育背景", 390, ["示例大学  /  设计学学士", "2019.09 — 2023.06", "主修课程：设计基础、交互设计、信息可视化。"]),
        ("专业技能", 245, ["界面设计  ·  用户研究  ·  原型制作  ·  团队协作", "语言：中文 / English"]),
    ]:
        pdf.setFillColorRGB(.18, .34, .28)
        pdf.setFont("STSong-Light", 14)
        pdf.drawString(48, top, title)
        pdf.setStrokeColorRGB(.7, .78, .71)
        pdf.setLineWidth(.7)
        pdf.line(48, top-12, 547, top-12)
        for j, row in enumerate(rows):
            pdf.setFillColorRGB(.3, .35, .31)
            pdf.setFont("STSong-Light", 11)
            pdf.drawString(48, top-40-j*24, row)
    pdf.showPage()
    pdf.setFont("STSong-Light", 20)
    pdf.drawString(48, 770, "项目经历")
    pdf.setFont("STSong-Light", 12)
    pdf.drawString(48, 730, "本地简历编辑工具 · 设计与开发")
    pdf.drawString(48, 702, "探索可编辑的页面重建，保护本地数据与导出隐私。")
    pdf.save()
    font_paths = [Path("C:/Windows/Fonts/msyh.ttc"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")]
    font_path = next((p for p in font_paths if p.exists()), None)
    if not font_path:
        raise RuntimeError("生成中文截图示例需要系统中文字体")
    image = Image.new("RGB", (1190, 1684), "white")
    d = ImageDraw.Draw(image)
    font = lambda size: ImageFont.truetype(str(font_path), size)
    d.text((96, 110), "张三", font=font(60), fill="#304f40")
    d.text((96, 220), "产品设计师", font=font(28), fill="#607366")
    d.text((96, 285), "138 0000 0000  hello@example.com", font=font(24), fill="#607366")
    d.ellipse((915, 105, 1090, 280), fill="#b8cbbb")
    d.ellipse((970, 135, 1035, 200), fill="#6c8c77")
    d.ellipse((940, 210, 1060, 330), fill="#6c8c77")
    for title, y, text in [("个人简介", 410, "关注体验设计与产品落地，擅长清晰表达与团队协作。"), ("工作经历", 680, "示例科技有限公司 产品设计师 2023年至今"), ("教育背景", 980, "示例大学 设计学学士 2019年至2023年")]:
        d.text((96, y), title, font=font(32), fill="#304f40")
        d.line((96,y+60,1094,y+60), fill="#bdcdbc", width=2)
        d.text((96,y+100), text, font=font(25), fill="#607366")
    image.save(output / "chinese-resume.png")
    scan = canvas.Canvas(str(output / "scanned-resume.pdf"), pagesize=(595,842))
    scan.drawImage(ImageReader(image),0,0,595,842)
    scan.save()
    # Repeated use of one PDF image resource must produce one box at each displayed position.
    repeated = canvas.Canvas(str(output / "repeated-photo.pdf"), pagesize=(595,842))
    repeated.setFont("Helvetica",16); repeated.drawString(50,790,"Repeated photo")
    repeated.drawImage(ImageReader(photo),50,600,80,100)
    repeated.drawImage(ImageReader(photo),400,600,80,100)
    repeated.save()


if __name__ == "__main__":
    make_samples()
    print("Synthetic examples created in examples/")
