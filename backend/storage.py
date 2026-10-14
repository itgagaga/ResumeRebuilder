import io
import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError

from .config import DATA, MAX_PIXELS, AppError
from .models import Asset, Project


def new_id(prefix="project"):
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def project_dir(project_id):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", project_id):
        raise AppError("非法工程 ID")
    return DATA / project_id


def load_project(project_id):
    path = project_dir(project_id) / "project.json"
    if not path.exists():
        raise AppError("工程不存在", 404)
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


def save_project(project):
    folder = project_dir(project.projectId)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{uuid.uuid4().hex}.tmp"
    tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(folder / "project.json")


def decode_image(data):
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in {"PNG", "JPEG", "WEBP"}:
            raise AppError("仅支持真实的 JPG、PNG、WebP 图片")
        if image.width * image.height > MAX_PIXELS:
            raise AppError("图片超过 3000 万像素，请先缩小图片")
        image.load()
        image = ImageOps.exif_transpose(image)
        normalized = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
        normalized.info.clear()
        return normalized
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise AppError("图片损坏或格式不支持") from exc


def store_asset(project, data):
    image = decode_image(data)
    asset_id = new_id("asset")
    asset = Asset(id=asset_id, filename=f"{asset_id}.png", width=image.width, height=image.height)
    folder = project_dir(project.projectId) / "assets"
    folder.mkdir(exist_ok=True, parents=True)
    image.save(folder / asset.filename)
    project.assets[asset_id] = asset
    save_project(project)
    return asset


def asset_path(project, asset_id):
    asset = project.assets.get(asset_id)
    if not asset:
        raise AppError("图片资源不存在", 404)
    path = project_dir(project.projectId) / "assets" / asset.filename
    if not path.exists():
        raise AppError("图片资源文件丢失", 404)
    return path


def pack_project(project, include_reference=True):
    output = io.BytesIO()
    used = {e.assetId for p in project.pages for e in p.elements if e.assetId}
    clean = project.model_copy(deep=True)
    clean.assets = {key: value for key, value in clean.assets.items() if key in used}
    clean.referenceAvailable = bool(include_reference and project.referenceAvailable)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.json", clean.model_dump_json(indent=2))
        for key, asset in clean.assets.items():
            archive.write(asset_path(project, key), f"assets/{asset.filename}")
        if clean.referenceAvailable:
            for i in range(len(project.pages)):
                path = project_dir(project.projectId) / "reference" / f"{i + 1}.png"
                if path.exists():
                    archive.write(path, f"reference/{i + 1}.png")
    return output.getvalue()


def unpack_project(data):
    folder = None
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        items = archive.infolist()
        if len(items) > 150 or sum(x.file_size for x in items) > 100 * 1024 * 1024:
            raise AppError("工程包解压体积或文件数超过限制")
        names = [x.filename for x in items]
        if len(names) != len(set(names)):
            raise AppError("工程包包含重复路径")
        for item in items:
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename or ":" in item.filename:
                raise AppError("工程包含非法路径")
            if not re.fullmatch(r"project\.json|assets/[a-zA-Z0-9_-]{1,80}\.png|reference/[0-9]{1,2}\.png", item.filename):
                raise AppError("工程包包含不支持的文件")
            if item.file_size > 25 * 1024 * 1024 or item.flag_bits & 1:
                raise AppError("工程文件过大或已加密")
        if "project.json" not in names:
            raise AppError("工程包缺少 project.json")
        project = Project.model_validate_json(archive.read("project.json"))
        project.projectId = new_id()
        folder = project_dir(project.projectId)
        for key, asset in list(project.assets.items()):
            name = f"assets/{asset.filename}"
            if name not in names:
                raise AppError("工程包缺少图片资源")
            normalized = decode_image(archive.read(name))
            (folder / "assets").mkdir(parents=True, exist_ok=True)
            normalized.save(folder / "assets" / asset.filename)
            asset.width, asset.height = normalized.size
        reference_names = [f"reference/{i+1}.png" for i in range(len(project.pages))]
        project.referenceAvailable = all(name in names for name in reference_names)
        if project.referenceAvailable:
            (folder / "reference").mkdir(parents=True, exist_ok=True)
            for name in reference_names:
                decode_image(archive.read(name)).save(folder / name)
        save_project(project)
        return project
    except AppError:
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    except (zipfile.BadZipFile, KeyError, ValidationError, RuntimeError, ValueError) as exc:
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
        raise AppError("工程包损坏或文档结构不合法") from exc
