"""Private diagnostics and reusable OCR cache; never updates the source project."""
import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import numpy as np
from PIL import Image
from backend import ocr
from backend import browser_typography
from backend.typography import match_typography,smooth_typography
from backend.exporter import render_html
from backend.image_layout import recover_shapes
from backend.models import Page,Project

def main():
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    image=Image.open(args.source).convert('RGB');image.thumbnail((2400,2400))
    cache=args.output/'ocr.json'
    if cache.exists():records=json.loads(cache.read_text(encoding='utf8'))
    else:
        result=ocr.get_engine()(image,return_word_box=True,return_single_char_box=True)
        records=[dict(box=b.tolist(),text=t,score=float(s),words=[(c,float(v),np.asarray(q).tolist()) for c,v,q in words if q is not None]) for b,t,s,words in zip(result.boxes,result.txts,result.scores,result.word_results)]
        cache.write_text(json.dumps(records,ensure_ascii=False),encoding='utf8')
    rows=[(np.asarray(r['box']),r['text'],r['score'],r['words']) for r in records]
    rgb=np.asarray(image)
    analyses=[match_typography(rgb,t,b,w) for b,t,_,w in rows]
    reports=[]
    original=browser_typography.refine_typography
    def refine(*args):
        started=time.monotonic();refined,provider=original(*args)
        reports.append(dict(browserRefinement=refined is not None,seconds=time.monotonic()-started))
        selected=refined or smooth_typography(analyses,rgb=rgb)
        for record,analysis in zip(records,selected):
            info=analysis[4]
            reports.append(dict(text=record['text'],family=analysis[0][0],size=analysis[1],weight=analysis[2],
                                candidates={kind:dict(scores=stats['scores'],samples=stats['samples']) for kind,stats in info.items()}))
        return refined,provider
    result=SimpleNamespace(boxes=np.array([r['box'] for r in records]),txts=[r['text'] for r in records],scores=[r['score'] for r in records],word_results=[r['words'] for r in records])
    with patch('backend.ocr.get_engine',lambda:lambda *args,**kwargs:result),patch('backend.ocr.retry_line',lambda engine,image,row:row),patch('backend.browser_typography.refine_typography',refine):
        elements=ocr.recognize(image,595.28,1)
    shapes,_=recover_shapes(image,595.28,1)
    project=Project(projectId='diagnostic',name='样式诊断',pages=[Page(id='page',width=595.28,height=595.28*image.height/image.width,elements=shapes+elements)])
    (args.output/'project.json').write_text(project.model_dump_json(indent=2),encoding='utf8')
    (args.output/'analysis.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    (args.output/'restored.html').write_text(render_html(project,editable=True),encoding='utf8')
    print(json.dumps(reports[0]),flush=True)
    print('text rows:',len(records),'bold characters:',sum(len(e.text) if e.style.fontWeight==700 else sum(r.end-r.start for r in e.textRuns) for e in elements),'total characters:',sum(len(e.text) for e in elements),flush=True)

if __name__=='__main__':main()
