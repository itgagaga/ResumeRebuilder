"""Local, private visual QA for a user-supplied image. Outputs stay under ignored artifacts/."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image",type=Path)
    args = parser.parse_args()
    output = ROOT/"artifacts"/"image-quality"
    output.mkdir(parents=True,exist_ok=True)
    os.environ["RESUME_DATA_DIR"] = str(output/"projects")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT/"runtime"/"browsers")
    from PIL import Image
    import numpy as np
    from backend.parser import import_source
    from backend.exporter import render_html,render_pdf
    from backend.browser import launch_browser
    from playwright.sync_api import sync_playwright
    from backend.storage import save_project
    import json
    from urllib.parse import urlparse
    source = Image.open(args.image).convert("RGB")
    project = import_source(args.image.read_bytes(),"图片样式验收")
    save_project(project)
    page = project.pages[0]
    html = render_html(project)
    (output/"restored.html").write_text(html,encoding="utf-8")
    (output/"project.json").write_text(project.model_dump_json(indent=2),encoding="utf-8")
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        tab = browser.new_page(viewport={"width":source.width+20,"height":source.height+20})
        tab.route("**/*",lambda route:route.abort())
        tab.set_content(html)
        scale = source.width/(page.width*96/72)
        tab.add_style_tag(content=f"body{{zoom:{scale};background:white}}.page{{margin:0}}")
        tab.evaluate("async()=>await document.fonts.ready")
        tab.locator(".page").screenshot(path=output/"restored.png")
        overflowing = tab.locator(".page>div>span").evaluate_all("els=>els.filter(e=>e.scrollHeight>e.clientHeight+2||e.scrollWidth>e.clientWidth+2).length")
        # Load the actual built React editor with mocked local API responses, so QA never
        # changes a running user project or restarts the user's backend.
        editor = browser.new_page(viewport={"width":1700,"height":1100})
        errors,saved = [],[]
        editor.on("pageerror",lambda exc:errors.append(str(exc)))
        def route_editor(route):
            path = urlparse(route.request.url).path
            if path == "/api/health":
                route.fulfill(json={"ocrReady":True,"pdfReady":True})
            elif path == "/api/projects":
                route.fulfill(json=[{"projectId":project.projectId,"name":project.name,"pages":1}])
            elif path == f"/api/projects/{project.projectId}":
                if route.request.method == "PUT":
                    saved.append(route.request.post_data_json)
                    route.fulfill(json=route.request.post_data_json)
                else:
                    route.fulfill(json=project.model_dump())
            elif path == f"/api/projects/{project.projectId}/reference/1":
                route.fulfill(body=args.image.read_bytes(),content_type="image/png")
            elif path.startswith("/api/"):
                route.fulfill(status=404,json={"detail":"QA 未实现此接口"})
            else:
                root = (ROOT/"frontend/dist").resolve()
                target = (root/(path.lstrip("/") or "index.html")).resolve()
                if target.is_relative_to(root) and target.is_file():
                    route.fulfill(path=target)
                else:
                    route.fulfill(status=404,body="not found")
        editor.route("**/*",route_editor)
        editor.goto("http://127.0.0.1:8765/")
        editor.get_by_role("button",name=project.name).click()
        from playwright.sync_api import expect
        expect(editor.get_by_label("工程名称")).to_be_visible()
        editor.evaluate("async()=>await document.fonts.ready")
        editor.wait_for_timeout(200)
        editor_overflow = editor.locator(".is-overflow").count()
        editor.screenshot(path=output/"editor.png",full_page=True)
        rich = next((e for e in page.elements if e.textRuns),None)
        if rich:
            editor.locator(f'[data-element-id="{rich.id}"]').click()
            editor.get_by_label("文字内容").fill("测试替换文字")
            editor.get_by_role("button",name="保存",exact=True).click()
            expect(editor.locator(".save-state")).to_contain_text("已保存")
            updated = next(e for e in saved[-1]["pages"][0]["elements"] if e["id"] == rich.id)
            assert updated["text"] == "测试替换文字" and all(0 <= r["start"] < r["end"] <= len(updated["text"]) for r in updated["textRuns"])
        assert not errors,errors
        assert overflowing == 0 and editor_overflow == 0,(overflowing,editor_overflow)
        browser.close()
    rendered = Image.open(output/"restored.png").convert("RGB")
    side_by_side = Image.new("RGB",(source.width+rendered.width+20,max(source.height,rendered.height)),"#dfe5df")
    side_by_side.paste(source,(0,0));side_by_side.paste(rendered,(source.width+20,0))
    side_by_side.save(output/"comparison.png")
    (output/"restored.pdf").write_bytes(render_pdf(project))
    print(f"Rebuilt {sum(e.type=='text' for e in page.elements)} text lines, {sum(e.type=='rect' for e in page.elements)} shapes. Export/editor overflowing lines: {overflowing}/{editor_overflow}. Exported source image assets: {len(project.assets)}. React edit/save of local style ranges passed.")
    print(f"Private QA artifacts: {output}")


if __name__ == "__main__": main()
