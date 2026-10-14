import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import DATA, MAX_UPLOAD, ROOT, AppError
from .exporter import render_html, render_pdf
from .models import Page, Project
from .browser import browser_ready
from .storage import asset_path, load_project, new_id, pack_project, project_dir, save_project, store_asset, unpack_project

app = FastAPI(title="Resume Rebuilder", version="0.1.0", docs_url="/api/docs", redoc_url=None)


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = request.url.hostname
    origin = request.headers.get("origin")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return JSONResponse({"detail": "服务仅接受本机访问"}, status_code=403)
    if origin:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.port not in {8765, 5173}:
            return JSONResponse({"detail": "不允许跨站访问本地文件服务"}, status_code=403)
    try:
        response = await call_next(request)
    except OSError:
        return JSONResponse({"detail": "本地文件读写失败，请检查磁盘空间和文件权限"}, status_code=500)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(AppError)
async def app_error(request, exc):
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


async def read_upload(file: UploadFile):
    data = await file.read(MAX_UPLOAD+1)
    await file.close()
    if not data:
        raise AppError("上传文件为空")
    if len(data) > MAX_UPLOAD:
        raise AppError("上传文件超过 25MB 限制", 413)
    return data


@app.get("/api/health")
def health():
    from .ocr import model_paths
    try:
        model_paths()
        ocr = True
    except Exception:
        ocr = False
    return {"ok": True, "localOnly": True, "ocrReady": ocr, "pdfReady": browser_ready()}


@app.get("/api/projects")
def list_projects():
    DATA.mkdir(parents=True, exist_ok=True)
    entries = []
    for path in sorted(DATA.glob("*/project.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        try:
            p = load_project(path.parent.name)
            entries.append({"projectId": p.projectId, "name": p.name, "pages": len(p.pages)})
        except Exception:
            continue
    return entries


@app.post("/api/projects")
def new_project():
    project = Project(projectId=new_id(), name="我的简历", pages=[Page(id=new_id("page"), width=595.28, height=841.89)])
    save_project(project)
    return project


def parse_in_worker(data, name):
    # Bound malformed PDFs / expensive OCR to a disposable process.
    task_project_id = new_id()
    with tempfile.TemporaryDirectory(prefix="resume-import-") as tmp:
        source, result_file = Path(tmp) / "source", Path(tmp) / "result.json"
        source.write_bytes(data)
        try:
            result = subprocess.run([sys.executable, "-m", "backend.worker", str(source), name, str(result_file), task_project_id],
                                    cwd=ROOT, capture_output=True, timeout=180,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            shutil.rmtree(project_dir(task_project_id), ignore_errors=True)
            raise AppError("文件处理超过 3 分钟，请减少页数或缩小图片", 408) from exc
        if result.returncode or not result_file.exists():
            shutil.rmtree(project_dir(task_project_id), ignore_errors=True)
            raise AppError("文件解析进程失败，请检查文件或本地依赖")
        result = json.loads(result_file.read_text(encoding="utf-8"))
        if "error" in result:
            shutil.rmtree(project_dir(task_project_id), ignore_errors=True)
            raise AppError(result["error"])
        return Project.model_validate(result["project"])


@app.post("/api/demo")
def demo_project():
    example = ROOT / "examples" / "native-resume.pdf"
    if not example.exists():
        raise AppError("内置示例缺失，请运行 scripts/create_samples.py")
    project = parse_in_worker(example.read_bytes(), "示例简历 · 可直接编辑")
    save_project(project)
    return project


@app.post("/api/import")
def import_file(file: UploadFile = File(...)):
    # Synchronous endpoint runs in FastAPI's worker pool, keeping editor/API responsive.
    data = file.file.read(MAX_UPLOAD+1)
    file.file.close()
    if not data:
        raise AppError("上传文件为空")
    if len(data) > MAX_UPLOAD:
        raise AppError("上传文件超过 25MB 限制", 413)
    if data[:2] == b"PK":
        project = unpack_project(data)
    else:
        project = parse_in_worker(data, Path(file.filename or "简历").stem[:150])
        save_project(project)
    return project


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    return load_project(project_id)


@app.put("/api/projects/{project_id}")
def update_project(project_id: str, project: Project):
    current = load_project(project_id)
    if project.projectId != project_id:
        raise AppError("工程 ID 不匹配")
    for key, asset in project.assets.items():
        if current.assets.get(key) != asset:
            raise AppError("资源只能通过上传接口创建")
    project.assets = current.assets
    project.referenceAvailable = current.referenceAvailable
    save_project(project)
    return project


@app.post("/api/projects/{project_id}/assets")
async def upload_asset(project_id: str, file: UploadFile = File(...)):
    project = load_project(project_id)
    return store_asset(project, await read_upload(file))


@app.get("/api/projects/{project_id}/assets/{asset_id}")
def get_asset(project_id: str, asset_id: str):
    return FileResponse(asset_path(load_project(project_id), asset_id), media_type="image/png")


@app.delete("/api/projects/{project_id}/assets/{asset_id}")
def delete_asset(project_id: str, asset_id: str):
    project = load_project(project_id)
    if any(e.assetId == asset_id for p in project.pages for e in p.elements):
        raise AppError("此图片仍在使用，请先清除占位框中的图片")
    path = asset_path(project, asset_id)
    del project.assets[asset_id]
    save_project(project)
    path.unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/projects/{project_id}/reference/{number}")
def reference(project_id: str, number: int):
    project = load_project(project_id)
    if not project.referenceAvailable or not 1 <= number <= len(project.pages):
        raise AppError("原始参考页不存在", 404)
    path = project_dir(project_id) / "reference" / f"{number}.png"
    if not path.exists():
        raise AppError("原始参考页不存在", 404)
    return FileResponse(path, media_type="image/png")


@app.delete("/api/projects/{project_id}/reference")
def delete_reference(project_id: str):
    project = load_project(project_id)
    folder = project_dir(project_id) / "reference"
    # Safe server-owned path: validated ID, constant subdirectory, no arbitrary client path.
    if folder.exists():
        shutil.rmtree(folder)
    project.referenceAvailable = False
    save_project(project)
    return project


class ExportRequest(BaseModel):
    format: str = Field(pattern=r"^(html|pdf|project)$")
    includeReference: bool = True
    confirmEmpty: bool = False


@app.post("/api/projects/{project_id}/export")
def export_project(project_id: str, options: ExportRequest):
    project = load_project(project_id)
    empty = sum(e.type == "image_placeholder" and not e.assetId for p in project.pages for e in p.elements)
    if options.format != "project" and empty and not options.confirmEmpty:
        raise AppError(f"还有 {empty} 个图片区未替换，确认后将导出空白区域", 409)
    if options.format == "html":
        data, media, extension = render_html(project).encode("utf-8"), "text/html", "html"
    elif options.format == "pdf":
        data, media, extension = render_pdf(project), "application/pdf", "pdf"
    else:
        data, media, extension = pack_project(project, options.includeReference), "application/zip", "rresume"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="resume.{extension}"'})


dist = ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="editor")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8765)
