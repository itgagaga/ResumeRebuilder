"""Match system-font faces against the rasterizer that also renders the editable HTML."""
import base64
import numpy as np
import cv2

from .image_layout import FONT_CHOICES,font_file,render_glyph
from .typography import LATIN_CHOICES,indexed_words,match_typography,smooth_typography

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
        sizes=[round(float(s)*2)/2 for s in np.arange(max(5,size-2),size+2.1,.5)]
        sizes_by_row.append(sizes)
        for _,char,score,_ in indexed_words(row[1],row[3]):
            if score<.9 or not char.isalnum():continue
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
    keys=list(requests)
    with sync_playwright() as pw:
        browser=launch_browser(pw)
        try:
            tab=browser.new_page();tab.route('**/*',lambda route:route.abort())
            values=tab.evaluate('''requests=>{
              const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d',{willReadFrequently:true});
              return requests.map(([family,char,weight,size,resolution])=>{
                size*=resolution;
                const side=Math.ceil(size*4);canvas.width=side;canvas.height=side;
                ctx.font=weight+' '+size+'px "'+family+'"';ctx.textBaseline='alphabetic';
                ctx.fillText(char,Math.ceil(size),Math.ceil(size*2));
                const data=ctx.getImageData(0,0,side,side).data;
                let left=side,top=side,right=0,bottom=0;
                for(let y=0;y<side;y++)for(let x=0;x<side;x++)if(data[(y*side+x)*4+3]>2){left=Math.min(left,x);top=Math.min(top,y);right=Math.max(right,x+1);bottom=Math.max(bottom,y+1)}
                if(right<=left)return null;
                let bytes='';for(let y=top;y<bottom;y++)for(let x=left;x<right;x++)bytes+=String.fromCharCode(data[(y*side+x)*4+3]);
                return [right-left,bottom-top,btoa(bytes)];
              });
            }''',list(requests.values()))
        finally:browser.close()
    glyphs={}
    for key,value in zip(keys,values):
        if not value:continue
        resolution=key[-1]
        glyph=np.frombuffer(base64.b64decode(value[2]),dtype=np.uint8).reshape(value[1],value[0]).astype(np.float32)/255
        if resolution!=1:
            glyph=cv2.resize(glyph,(max(1,round(value[0]/resolution)),max(1,round(value[1]/resolution))),interpolation=cv2.INTER_AREA)
        glyphs.setdefault(key[:-1],[]).append(glyph)
    def provider(char,choice,bold,size,antialias=True):
        glyph=glyphs.get((font_file(char,choice,bold),char,bold,round(float(size)*2)/2))
        return glyph if glyph is not None else render_glyph(char,choice,bold,round(size),antialias=antialias)
    refined=[match_typography(rgb,row[1],row[0],row[3],glyph_provider=provider,sizes=sizes) for row,sizes in zip(rows,sizes_by_row)]
    return smooth_typography(refined,rgb=rgb),provider
