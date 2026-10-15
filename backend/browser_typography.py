"""Match system-font faces against the rasterizer that also renders the editable HTML."""
import base64
import numpy as np
import cv2

from .image_layout import FONT_CHOICES,font_file
from .typography import LATIN_CHOICES,indexed_words,match_typography,smooth_typography,_samples

FAMILIES={'msyh.ttc':'Microsoft YaHei','msyhbd.ttc':'Microsoft YaHei','simhei.ttf':'SimHei',
          'simsun.ttc':'SimSun','Deng.ttf':'DengXian','Dengb.ttf':'DengXian',
          'arial.ttf':'Arial','arialbd.ttf':'Arial','times.ttf':'Times New Roman','timesbd.ttf':'Times New Roman',
          'georgia.ttf':'Georgia','georgiab.ttf':'Georgia','calibri.ttf':'Calibri','calibrib.ttf':'Calibri'}

def refine_typography(rgb,rows,analyses):
    if not analyses:return analyses,None
    from playwright.sync_api import sync_playwright
    from .browser import launch_browser
    requests={}
    sizes_by_row=[]
    for row,analysis in zip(rows,analyses):
        size=analysis[1]
        if size is None:
            size=max(6,(analysis[3][2][3]-analysis[3][2][1])*1.12)
        if size>96:return None,None
        # Digits and Latin cap heights can bias the initial size independently
        # of Chinese. Widen that search without multiplying every body's work.
        radius=4 if not _samples(row[1],row[3],False) else 2
        sizes=[round(float(s)*2)/2 for s in np.arange(max(5,size-radius),size+radius+.1,.5)]
        sizes_by_row.append(sizes)
        # Font identification needs representative glyphs, not every glyph in
        # every family. Otherwise dense pages exhaust the budget and lose the
        # entire refinement, while short fixtures misleadingly keep it.
        for _,char,_ in _samples(row[1],row[3],False)+_samples(row[1],row[3],True):
            choices=FONT_CHOICES if not char.isascii() else [(name,'msyh.ttc','msyhbd.ttc',regular,bold) for name,regular,bold in LATIN_CHOICES]
            for choice in choices:
                for current_size in sizes:
                    for bold in (False,True):
                        filename=font_file(char,choice,bold)
                        for resolution in (1,1.5,2):
                            key=(filename,char,bold,current_size,resolution)
                            requests[key]=[FAMILIES[filename],char,700 if bold else 400,current_size,resolution]
    # Bound the optional refinement for pathological pages. Missing glyphs use
    # the normal local estimator; it must never prevent text from being imported.
    if not requests or len(requests)>100000:return None,None
    glyphs={}
    def collect(tab,requests):
        keys=list(requests)
        if not keys:return
        values=tab.evaluate(RENDER_GLYPHS,list(requests.values()))
        for key,value in zip(keys,values):
            if not value:continue
            resolution=key[-1]
            glyph=np.frombuffer(base64.b64decode(value[2]),dtype=np.uint8).reshape(value[1],value[0]).astype(np.float32)/255
            if resolution!=1:
                glyph=cv2.resize(glyph,(max(1,round(value[0]/resolution)),max(1,round(value[1]/resolution))),interpolation=cv2.INTER_AREA)
            glyphs.setdefault(key[:-1],[]).append(glyph)
    def provider(char,choice,bold,size,antialias=True):
        glyph=glyphs.get((font_file(char,choice,bold),char,bold,round(float(size)*2)/2))
        # Do not silently mix a PIL rasterizer into browser face comparisons.
        # An unavailable reference is uncertain, not evidence of bold weight.
        return glyph
    with sync_playwright() as pw:
        browser=launch_browser(pw)
        try:
            tab=browser.new_page();tab.route('**/*',lambda route:route.abort())
            collect(tab,requests)
            refined=[match_typography(rgb,row[1],row[0],row[3],glyph_provider=provider,sizes=sizes) for row,sizes in zip(rows,sizes_by_row)]
            refined=smooth_typography(refined,rgb=rgb)
            requests={}
            # Only the selected face is needed for full character style checks.
            for row,analysis in zip(rows,refined):
                choice,size=analysis[:2]
                if size is None:continue
                sizes=[float(s) for s in np.arange(max(5,size-1),size+1.1,.5)]
                for _,char,score,_ in indexed_words(row[1],row[3]):
                    if score<.9 or not char.isalnum():continue
                    for current_size in sizes:
                        for bold in (False,True):
                            filename=font_file(char,choice,bold)
                            if (filename,char,bold,round(current_size*2)/2) in glyphs:continue
                            for resolution in (1,1.5,2):
                                key=(filename,char,bold,current_size,resolution)
                                requests[key]=[FAMILIES[filename],char,700 if bold else 400,current_size,resolution]
            if len(requests)<=100000:collect(tab,requests)
        finally:browser.close()
    return refined,provider


RENDER_GLYPHS='''requests=>{
              const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d',{willReadFrequently:true});
              return requests.map(([family,char,weight,size,resolution])=>{
                size*=resolution;
                const font=weight+' '+size+'px "'+family+'"';ctx.font=font;
                const metrics=ctx.measureText(char);
                const width=Math.max(1,Math.ceil(metrics.actualBoundingBoxLeft)+Math.ceil(metrics.actualBoundingBoxRight)+4);
                const height=Math.max(1,Math.ceil(metrics.actualBoundingBoxAscent)+Math.ceil(metrics.actualBoundingBoxDescent)+4);
                canvas.width=width;canvas.height=height;ctx.font=font;ctx.textBaseline='alphabetic';
                ctx.fillText(char,2+Math.ceil(metrics.actualBoundingBoxLeft),2+Math.ceil(metrics.actualBoundingBoxAscent));
                const data=ctx.getImageData(0,0,width,height).data;
                let left=width,top=height,right=0,bottom=0;
                for(let y=0;y<height;y++)for(let x=0;x<width;x++)if(data[(y*width+x)*4+3]>2){left=Math.min(left,x);top=Math.min(top,y);right=Math.max(right,x+1);bottom=Math.max(bottom,y+1)}
                if(right<=left)return null;
                let bytes='';for(let y=top;y<bottom;y++)for(let x=left;x<right;x++)bytes+=String.fromCharCode(data[(y*width+x)*4+3]);
                return [right-left,bottom-top,btoa(bytes)];
              });
            }'''
