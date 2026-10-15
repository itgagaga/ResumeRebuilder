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
    parser.add_argument("--output",type=Path,default=ROOT/"artifacts"/"image-quality")
    args = parser.parse_args()
    output = args.output.resolve()
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
    (output/"restored-editable.html").write_text(render_html(project,editable=True),encoding="utf-8")
    (output/"project.json").write_text(project.model_dump_json(indent=2),encoding="utf-8")
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        tab = browser.new_page(viewport={"width":source.width+20,"height":source.height+20})
        tab.route("**/*",lambda route:route.abort())
        tab.set_content(html)
        scale = source.width/(page.width*96/72)
        tab.add_style_tag(content=f"body{{background:white}}.page{{margin:0;transform:scale({scale});transform-origin:top left}}")
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
            elif path == f"/api/projects/{project.projectId}/export":
                from backend.models import Project
                current = Project.model_validate(saved[-1]) if saved else project
                route.fulfill(body=render_html(current,editable=True),content_type="text/html")
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
        editor_overflow = editor.locator('[data-text-id]').evaluate_all("""els=>els.filter(el=>{
            const cs=getComputedStyle(el),matrix=new DOMMatrixReadOnly(cs.transform),zoom=Number(cs.zoom)||1;
            return Math.max(el.scrollHeight,el.clientHeight)*zoom*Math.abs(matrix.d)>el.parentElement.clientHeight+2 ||
                Math.max(el.scrollWidth,el.clientWidth)*zoom*Math.abs(matrix.a)>el.parentElement.clientWidth+2;
        }).length""")
        editor.screenshot(path=output/"editor.png",full_page=True)
        rich = next((e for e in page.elements if e.textRuns),None)
        # The primary HTML action must open the current saved content and retain
        # geometry in an independent editor, including normalized contours.
        with editor.expect_popup() as opened:
            editor.get_by_role('button',name='进入 HTML 编辑',exact=True).click()
        standalone = opened.value
        expect(standalone.locator('#resume-save')).to_be_visible()
        expect(standalone.locator('[data-resume-text]')).to_have_count(sum(e.type=='text' for e in page.elements))
        if rich:
            expect(standalone.locator(f'[data-resume-element="{rich.id}"] [data-resume-text]')).to_have_text(rich.text)
        curves = [e for e in page.elements if e.shape=='polygon']
        for curve in curves:
            assert standalone.locator(f'[data-resume-element="{curve.id}"]').evaluate('el=>getComputedStyle(el).clipPath').startswith('polygon(')
        assert standalone.evaluate('window.opener === null')
        standalone.screenshot(path=output/'standalone.png',full_page=True)
        if rich:
            standalone.locator(f'[data-resume-element="{rich.id}"] [data-resume-text]').fill('测试替换文字')
            with standalone.expect_download() as downloaded:
                standalone.locator('#resume-save').click()
            downloaded.value.save_as(output/'edited-in-html.html')
            assert '测试替换文字' in (output/'edited-in-html.html').read_text(encoding='utf-8')
            expect(editor.locator(f'[data-text-id="{rich.id}"]')).to_have_text(rich.text)
        standalone.close()
        assert not errors,errors
        assert overflowing == 0 and editor_overflow == 0,(overflowing,editor_overflow)
        browser.close()
    rendered = Image.open(output/"restored.png").convert("RGB")
    side_by_side = Image.new("RGB",(source.width+rendered.width+20,max(source.height,rendered.height)),"#dfe5df")
    side_by_side.paste(source,(0,0));side_by_side.paste(rendered,(source.width+20,0))
    side_by_side.save(output/"comparison.png")
    (output/"restored.pdf").write_bytes(render_pdf(project))
    (output/"quality.json").write_text(json.dumps({'textLines':sum(e.type=='text' for e in page.elements),'shapes':sum(e.type=='rect' for e in page.elements),
        'exportOverflow':overflowing,'editorOverflow':editor_overflow,'sourceAssets':len(project.assets),
        'lowConfidenceLines':sum(e.type=='text' and e.sourceRegion is not None and e.sourceRegion.confidence is not None and e.sourceRegion.confidence<.85 for e in page.elements)},indent=2),encoding='utf-8')
    print(f"Rebuilt {sum(e.type=='text' for e in page.elements)} text lines, {sum(e.type=='rect' for e in page.elements)} shapes. Export/editor overflowing lines: {overflowing}/{editor_overflow}. Exported source image assets: {len(project.assets)}. Read-only preview and independent HTML edit/save passed.")
    print(f"Private QA artifacts: {output}")


if __name__ == "__main__": main()
