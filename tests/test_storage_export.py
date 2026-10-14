import io
import zipfile
from unittest.mock import patch

import pdfplumber
import pytest
from PIL import Image
from pydantic import ValidationError

from backend.config import AppError
from backend.exporter import render_html, render_pdf
from backend.models import Element, Page, Project, Style
from backend.parser import import_source
from backend.storage import load_project, pack_project, save_project, store_asset, unpack_project


def test_original_identity_removed_from_exports_and_package(samples):
    project = import_source((samples / "native-resume.pdf").read_bytes(), "张三的原始模板")
    for p in project.pages:
        for e in p.elements:
            if e.text == "张三":
                e.text = "李四"
    html = render_html(project)
    assert "李四" in html and "张三" not in html
    assert "上传图片" not in html
    assert "reference" not in html and "data:image" not in html
    project.name = "李四的简历"
    payload = pack_project(project, include_reference=False)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == ["project.json"]
        assert "张三" not in archive.read("project.json").decode()


def test_replacement_image_crop_round_trip(samples):
    project = import_source((samples / "native-resume.pdf").read_bytes(), "简历")
    asset = store_asset(project, (samples / "replacement.png").read_bytes())
    photo = next(e for e in project.pages[0].elements if e.type == "image_placeholder")
    photo.assetId = asset.id; photo.shape = "circle"
    photo.crop.scale = 1.8; photo.crop.offsetX = -20; photo.crop.offsetY = 35
    save_project(project)
    restored = unpack_project(pack_project(load_project(project.projectId)))
    other = next(e for e in restored.pages[0].elements if e.type == "image_placeholder")
    assert other.assetId == asset.id and other.crop == photo.crop
    assert other.shape == "circle"
    assert restored.referenceAvailable
    html = render_html(restored)
    assert "data:image/png;base64," in html
    assert "border-radius:50%" in html
    assert "scale(1.8)" in html


def test_offline_pdf_selectable_text_new_image_and_page_sizes(samples):
    project = import_source((samples / "native-resume.pdf").read_bytes(), "简历")
    for e in project.pages[0].elements:
        if e.text == "张三": e.text = "李四"
    photo = next(e for e in project.pages[0].elements if e.type == "image_placeholder")
    photo.assetId = store_asset(project, (samples / "replacement.png").read_bytes()).id
    photo.shape = "circle"
    with patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden")):
        data = render_pdf(project)
    with pdfplumber.open(io.BytesIO(data)) as doc:
        assert len(doc.pages) == 2
        text = "\n".join(p.extract_text() or "" for p in doc.pages)
        assert "李四" in text and "张三" not in text
        assert "上传图片" not in text
        assert len(doc.pages[0].images) == 1
        assert doc.pages[0].width == pytest.approx(595.28, abs=1)
        assert doc.pages[0].height == pytest.approx(841.89, abs=1)


def test_export_escapes_html():
    project = Project(projectId="test", name="安全简历", pages=[Page(id="p",width=595,height=842,elements=[Element(id="t", type="text",x=0,y=0,width=100,height=20,text='<script>alert("x")</script>')])])
    output = render_html(project)
    assert '<script>' not in output
    assert '&lt;script&gt;' in output
    with pytest.raises(ValidationError): Style(fontFamily="Arial; background:url(https://example.com)")
    with pytest.raises(ValidationError): Style(background="url(file:///etc/passwd)")


@pytest.mark.parametrize("name", ["../escape.png", "/escape.png", "assets/../../escape.png", "C:/escape.png", "assets\\escape.png"])
def test_archive_path_traversal_rejected(name):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive: archive.writestr(name,b"bad")
    with pytest.raises(AppError): unpack_project(data.getvalue())


def test_zip_bomb_and_duplicates_rejected():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive: archive.writestr("project.json", b"0"*(26*1024*1024))
    with pytest.raises(AppError): unpack_project(data.getvalue())
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("project.json", "{}"); archive.writestr("project.json", "{}")
    with pytest.raises(AppError): unpack_project(data.getvalue())


def test_api_export_empty_confirmation_and_reference_deletion(client, samples):
    project = import_source((samples / "native-resume.pdf").read_bytes(), "简历")
    save_project(project)
    base = f"/api/projects/{project.projectId}"
    assert client.post(base+"/export", json={"format":"html"}).status_code == 409
    output = client.post(base+"/export",json={"format":"html","confirmEmpty":True})
    assert output.status_code == 200
    assert "上传图片" not in output.text
    assert client.get(base+"/reference/1").status_code == 200
    assert client.delete(base+"/reference").status_code == 200
    assert client.get(base+"/reference/1").status_code == 404


def test_untrusted_origin_and_host_rejected(client):
    assert client.post("/api/projects", headers={"Origin":"https://attacker.example"}).status_code == 403
    assert client.get("/api/projects",headers={"Host":"attacker.example:8765"}).status_code == 403
    assert client.post("/api/projects",headers={"Origin":"null"}).status_code == 403


def test_asset_type_and_reference_validation(client, samples):
    project = client.post("/api/projects").json()
    project["pages"][0]["elements"] = [{"id":"image", "type":"image_placeholder", "x":5,"y":5,"width":80,"height":80,"assetId":"missing"}]
    assert client.put(f'/api/projects/{project["projectId"]}',json=project).status_code == 422
    response = client.post(f'/api/projects/{project["projectId"]}/assets',files={"file":("bad.jpg",b"<svg></svg>","image/jpeg")})
    assert response.status_code == 400


def test_project_archive_api_reopen(client, samples):
    project = import_source((samples / "native-resume.pdf").read_bytes(), "Round trip")
    save_project(project)
    response = client.post("/api/import",files={"file":("resume.rresume",pack_project(project,False),"application/zip")})
    assert response.status_code == 200
    assert not response.json()["referenceAvailable"]
    assert response.json()["projectId"] != project.projectId


def test_uploaded_png_preserves_alpha_and_removes_metadata():
    from backend.storage import decode_image
    source = Image.new("RGBA", (20, 30), (10, 100, 80, 64))
    raw = io.BytesIO(); source.save(raw, format="PNG")
    image = decode_image(raw.getvalue())
    assert image.mode == "RGBA"
    assert image.getpixel((5,5))[3] == 64
    assert not image.info


def test_pdf_mixed_page_units_and_sizes():
    project = Project(projectId="mixed",name="Mixed",pages=[Page(id="p1",width=595,height=842,unit="pt"),Page(id="p2",width=800,height=400,unit="px")])
    output = render_pdf(project)
    with pdfplumber.open(io.BytesIO(output)) as pdf:
        assert len(pdf.pages) == 2
        assert pdf.pages[0].width == pytest.approx(595,abs=1)
        assert pdf.pages[1].width == pytest.approx(600,abs=1)
        assert pdf.pages[1].height == pytest.approx(300,abs=1)
