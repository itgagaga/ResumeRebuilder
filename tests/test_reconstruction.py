import io
import math
import socket
from unittest.mock import patch

import pdfplumber
import pytest
from PIL import Image
from reportlab.pdfgen import canvas

from backend.coordinates import css_to_pt, pt_to_css
from backend.parser import import_source
from backend.ocr import recognize


def test_pdf_original_text_and_placeholder(samples):
    project = import_source((samples / "native-resume.pdf").read_bytes(), "测试简历")
    assert len(project.pages) == 2
    assert project.pages[0].width == pytest.approx(595.28)
    assert any(e.text == "张三" for e in project.pages[0].elements)
    photos = [e for e in project.pages[0].elements if e.type == "image_placeholder"]
    assert len(photos) == 1
    assert photos[0].assetId is None
    assert photos[0].x == 460 and photos[0].width == 80
    assert not project.assets
    assert any(e.type == "line" for e in project.pages[0].elements)


def test_repeated_pdf_resource_has_each_position(samples):
    project = import_source((samples / "repeated-photo.pdf").read_bytes(), "重复图片")
    photos = [e for e in project.pages[0].elements if e.type == "image_placeholder"]
    assert len(photos) == 2
    assert sorted(e.x for e in photos) == [50, 400]


def test_real_chinese_ocr_runs_without_network(samples):
    image = Image.open(samples / "chinese-resume.png")
    # Fails if OCR attempts to fetch a model from the network.
    with patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden")), patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
        elements = recognize(image, 595, 1)
    assert any("张三" in e.text for e in elements)
    assert any("教育背景" in e.text for e in elements)
    assert all(e.sourceRegion.confidence is not None for e in elements)
    assert all(0 <= e.x <= 595 for e in elements)


def test_scan_pdf_is_ocr_not_full_page_photo(samples):
    project = import_source((samples / "scanned-resume.pdf").read_bytes(), "扫描简历")
    assert project.pages[0].sourceType == "scan-pdf"
    assert not any(e.type == "image_placeholder" for e in project.pages[0].elements)
    assert any("张三" in e.text for e in project.pages[0].elements)


def test_missing_ocr_keeps_manual_editing(samples):
    with patch("backend.parser.recognize", side_effect=RuntimeError("missing model")):
        project = import_source((samples / "chinese-resume.png").read_bytes(), "OCR 缺失")
    assert len(project.pages) == 1
    assert project.pages[0].elements == []
    assert any("OCR 不可用" in w for w in project.warnings)


def test_coordinate_round_trip():
    assert pt_to_css(72) == 96
    assert css_to_pt(pt_to_css(595.28)) == pytest.approx(595.28)


def test_rotated_pdf_dimensions_match_reference():
    data = io.BytesIO()
    doc = canvas.Canvas(data, pagesize=(600, 800)); doc.setPageRotation(90)
    doc.setFont("Helvetica", 20); doc.drawString(50, 500, "Rotated page"); doc.save()
    project = import_source(data.getvalue(), "旋转页面")
    assert len(project.pages) == 1
    assert project.pages[0].width > 0
    assert any("Rotated" in e.text for e in project.pages[0].elements)


def test_invalid_input_returns_clear_error(client):
    response = client.post("/api/import", files={"file": ("fake.png", b"not an image", "image/png")})
    assert response.status_code == 400
    assert "detail" in response.json()
    assert client.get("/api/projects").json() == []


def test_cropbox_normalizes_element_and_reference():
    from backend.storage import project_dir
    from reportlab.pdfbase.pdfdoc import PDFArray
    data = io.BytesIO()
    doc = canvas.Canvas(data, pagesize=(600,800))
    doc.setFont("Helvetica",20); doc.drawString(70,650,"Cropped page")
    doc.showPage(); doc._doc.Pages.pages[0].CropBox = PDFArray([50,100,550,700])
    doc.save()
    project = import_source(data.getvalue(),"Crop")
    page = project.pages[0]
    assert (page.width,page.height) == (500,600)
    text = next(e for e in page.elements if "Cropped" in e.text)
    assert text.x == 20
    preview = Image.open(project_dir(project.projectId)/"reference"/"1.png")
    assert preview.width/preview.height == pytest.approx(500/600)
