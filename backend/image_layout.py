"""Recover editable geometry and typography from pixels, without exporting source image crops."""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .models import Element, SourceRegion, Style, TextRun
from .storage import new_id


FONT_CHOICES = [
    ("Arial, Microsoft YaHei, sans-serif", "msyh.ttc", "msyhbd.ttc", "arial.ttf", "arialbd.ttf"),
    ("Arial, SimHei, sans-serif", "simhei.ttf", "simhei.ttf", "arial.ttf", "arialbd.ttf"),
    ("Times New Roman, SimSun, serif", "simsun.ttc", "simsun.ttc", "times.ttf", "timesbd.ttf"),
    ("Arial, DengXian, sans-serif", "Deng.ttf", "Dengb.ttf", "arial.ttf", "arialbd.ttf"),
]


def hex_color(rgb):
    return "#" + "".join(f"{int(c):02x}" for c in rgb)


def dominant_color(pixels):
    flat = np.asarray(pixels).reshape(-1, 3)
    if not len(flat):
        return np.array([255, 255, 255])
    quantized = (flat.astype(np.int32)//8)
    keys = quantized[:,0]*1024+quantized[:,1]*32+quantized[:,2]
    key = np.bincount(keys, minlength=32768).argmax()
    return np.median(flat[keys == key], axis=0).astype(np.uint8)


def ink_mask(pixels, background=None):
    if background is None:
        background = dominant_color(pixels)
    difference = np.linalg.norm(pixels.astype(np.float32)-background, axis=2)
    # Strong foreground excludes antialiasing and JPEG noise; geometry includes softer edge pixels.
    threshold = max(45,float(np.percentile(difference,99))*.55)
    mask = difference > threshold
    if not mask.any():
        return mask, background
    return mask, background


def tight_mask(mask):
    ys, xs = np.where(mask)
    if not len(xs):
        return None
    return mask[ys.min():ys.max()+1, xs.min():xs.max()+1], (int(xs.min()), int(ys.min()), int(xs.max()+1), int(ys.max()+1))


def recover_soft_decorations(rgb, background, factor, page_number):
    """Join antialiased/JPEG colors before measuring pale bands and colored contours."""
    h,w = rgb.shape[:2]
    pixels = rgb.astype(np.float32)
    distance = np.linalg.norm(pixels-background,axis=2)
    # Bright, subtly tinted backgrounds need a separate mask from dark text.
    pale = ((distance > 4) & (distance < 65) & (pixels.min(axis=2) > 210)).astype(np.uint8)
    pale = cv2.morphologyEx(pale,cv2.MORPH_CLOSE,np.ones((3,7),np.uint8))
    pale = cv2.morphologyEx(pale,cv2.MORPH_OPEN,np.ones((1,max(21,round(w*.18)//2*2+1)),np.uint8))
    chroma = pixels.max(axis=2)-pixels.min(axis=2)
    accent = ((chroma > 30) & (distance > 45)).astype(np.uint8)
    result = []
    for mask,is_accent in ((pale,False),(accent,True)):
        count,labels,stats,_ = cv2.connectedComponentsWithStats(mask,8)
        for label in range(1,count):
            x,y,width,height,area = stats[label]
            band = width >= w*.2 and max(3,h*.004) <= height <= h*.12 and width/height >= 4
            rule = width <= w*.025 and height >= h*.012 and height/width >= 2.5
            if not (rule if is_accent else band): continue
            if is_accent and not any(e.width >= w*.2*factor and abs(e.y-y*factor)<height*factor*.35 and abs(e.height-height*factor)<height*factor*.45 and abs(e.x-x*factor)<w*.04*factor for e in result):
                continue
            density = area/(width*height)
            if density < (.25 if is_accent else .6): continue
            patch = rgb[y:y+height,x:x+width]
            component = (labels[y:y+height,x:x+width] == label).astype(np.uint8)
            samples = patch[component>0]
            if is_accent:
                saturation = samples.max(axis=1).astype(float)-samples.min(axis=1)
                samples = samples[saturation >= np.percentile(saturation,70)]
            fill = np.median(samples,axis=0)
            # Photos and gradients do not have a stable flat fill.
            if np.percentile(np.linalg.norm(samples.astype(float)-fill,axis=1),80) > (32 if is_accent else 12): continue
            contours,_ = cv2.findContours(component,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            contour = max(contours,key=cv2.contourArea)
            points = cv2.approxPolyDP(contour,max(.6,min(width,height)*.025),True)[:,0]
            if len(points)<3 or len(points)>128: continue
            polygon = is_accent and density < .88
            result.append(Element(id=new_id('decoration'),type='rect',x=float(x*factor),y=float(y*factor),
                                  width=float(width*factor),height=float(height*factor),zIndex=1 if is_accent else 0,
                                  shape='polygon' if polygon else 'rect',
                                  shapePoints=[(float(a/max(1,width-1)),float(b/max(1,height-1))) for a,b in points] if polygon else [],
                                  style=Style(background=hex_color(fill)),
                                  sourceRegion=SourceRegion(detectedFrom='pixel-color-contour' if is_accent else 'pixel-pale-band',page=page_number)))
    return result


def recover_shapes(image, page_width, page_number):
    if max(image.size)>2400:
        image = image.copy()
        image.thumbnail((2400,2400))
    rgb = np.asarray(image.convert("RGB"))
    h, w = rgb.shape[:2]
    factor = page_width/w
    background = dominant_color(np.concatenate([rgb[:max(1,h//100)].reshape(-1,3), rgb[-max(1,h//100):].reshape(-1,3)]))
    quantized = rgb.astype(np.int32)//8
    keys = quantized[:,:,0]*1024+quantized[:,:,1]*32+quantized[:,:,2]
    counts = np.bincount(keys.ravel(), minlength=32768)
    result = []
    for key in np.argsort(counts)[-32:]:
        if counts[key] < 70:
            continue
        color = np.array([key//1024*8, key//32%32*8, key%32*8])
        if np.linalg.norm(color-background) < 12:
            continue
        mask = (keys == key).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for label in range(1, count):
            x, y, width, height, area = stats[label]
            # Only flat horizontal bands and narrow vertical rules. A photo is not a shape.
            band = width >= w*.2 and 2 <= height <= h*.15 and width/height >= 4
            rule = 1 <= width <= w*.02 and height >= h*.015 and height/width >= 4
            if not (band or rule) or area/(width*height) < .7:
                continue
            if color.max()-color.min()<8 and color.mean()<160 and not(band and height<=5):
                continue
            sample = rgb[y:y+height,x:x+width][labels[y:y+height,x:x+width] == label]
            fill = hex_color(np.median(sample,axis=0))
            result.append(Element(id=new_id("shape"), type="rect", x=float(x*factor),y=float(y*factor),
                                  width=float(width*factor),height=float(height*factor),zIndex=1 if color.max()-color.min()>70 else 0,
                                  style=Style(background=fill),
                                  sourceRegion=SourceRegion(detectedFrom="pixel-flat-region",page=page_number)))
    soft = recover_soft_decorations(rgb,background,factor,page_number)
    # Prefer one coherent contour to many disconnected quantization buckets.
    for decoration in soft:
        def inside(shape):
            overlap = max(0,min(shape.x+shape.width,decoration.x+decoration.width)-max(shape.x,decoration.x))*max(0,min(shape.y+shape.height,decoration.y+decoration.height)-max(shape.y,decoration.y))
            return shape.zIndex == decoration.zIndex and overlap >= shape.width*shape.height*.85
        result = [shape for shape in result if not inside(shape)]
        result.append(decoration)
    merged = []
    for shape in sorted(result,key=lambda e:(e.style.background,e.y,e.x)):
        previous = merged[-1] if merged else None
        if (previous and previous.shape == shape.shape == 'rect' and previous.style.background == shape.style.background and abs(previous.y-shape.y)<factor
                and abs(previous.height-shape.height)<factor and 0<=shape.x-previous.x-previous.width<=page_width*.02):
            previous.width = shape.x+shape.width-previous.x
        else:
            merged.append(shape)
    # Recover thin grayscale rules across antialiased/JPEG color buckets as geometry.
    contrast = np.linalg.norm(rgb.astype(np.float32)-background,axis=2) > 25
    horizontal = cv2.morphologyEx(contrast.astype(np.uint8),cv2.MORPH_OPEN,np.ones((1,max(20,round(w*.18))),np.uint8))
    count,_,stats,_ = cv2.connectedComponentsWithStats(horizontal,8)
    for x,y,width,height,area in stats[1:]:
        if width < w*.2 or height > max(5,h*.006) or area/(width*height) < .65: continue
        if any(abs(e.y-y*factor) < max(2,height)*factor and min(e.x+e.width,(x+width)*factor)-max(e.x,x*factor) > width*factor*.8 for e in merged): continue
        patch = rgb[y:y+height,x:x+width]
        pixels = patch[horizontal[y:y+height,x:x+width] > 0]
        merged.append(Element(id=new_id('rule'),type='rect',x=float(x*factor),y=float(y*factor),width=float(width*factor),height=float(height*factor),zIndex=0,
                              style=Style(background=hex_color(np.median(pixels,axis=0))),sourceRegion=SourceRegion(detectedFrom='pixel-horizontal-rule',page=page_number)))
    # An accent often obscures the first few pixels of a flat banner. Extend the banner
    # underneath that rule so the editable shapes retain a coherent section background.
    for band in merged:
        if band.width < page_width*.2 or band.zIndex != 0: continue
        for rule in merged:
            if (rule.zIndex>band.zIndex and rule.width<=page_width*.02 and abs(rule.y-band.y)<factor
                    and abs(rule.height-band.height)<factor and abs(rule.x+rule.width-band.x)<factor):
                band.width += band.x-rule.x
                band.x = rule.x
    return merged, hex_color(background)


@lru_cache(maxsize=512)
def load_font(filename, size):
    path = Path("C:/Windows/Fonts")/filename
    if not path.exists():
        candidates = {"msyh.ttc":"/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                      "arial.ttf":"/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
                      "arialbd.ttf":"/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"}
        path = Path(candidates.get(filename,"/nonexistent"))
    return ImageFont.truetype(str(path), size) if path.exists() else None


def font_file(char, choice, bold):
    return choice[4 if bold else 3] if ord(char) < 128 and len(choice) > 3 else choice[2 if bold else 1]


@lru_cache(maxsize=16384)
def render_glyph(char, font_choice, bold, size=40, antialias=False):
    latin = ord(char) < 128
    filename = font_file(char,font_choice,bold)
    synthetic = bold and font_choice[1] == font_choice[2] and not latin
    resolution = 4 if antialias and (synthetic or size != round(size)) else 1
    font = load_font(filename, round(size*resolution))
    if font is None:
        return None
    stroke = max(1,round(size*resolution/(96 if antialias else 48))) if synthetic else 0
    canvas = Image.new("L", (round(size*3*resolution),round(size*3*resolution)))
    ImageDraw.Draw(canvas).text((round(size*resolution/2),round(size*resolution/2)),char,font=font,fill=255,stroke_width=stroke)
    if resolution>1:
        canvas=canvas.resize((round(size*3),round(size*3)),Image.Resampling.LANCZOS)
    box = canvas.getbbox()
    if not box:
        return None
    pixels = np.asarray(canvas.crop(box))
    return pixels.astype(np.float32)/255 if antialias else pixels > 90


def similarity(source, glyph):
    if glyph is None or source.size == 0:
        return 0
    resized = cv2.resize(glyph.astype(np.uint8), (source.shape[1],source.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    # Neighbouring pixels allow for small differences in hinting and antialiasing.
    kernel = np.ones((3,3),np.uint8)
    recall = np.logical_and(source,cv2.dilate(resized.astype(np.uint8),kernel)>0).sum()/max(1,source.sum())
    precision = np.logical_and(resized,cv2.dilate(source.astype(np.uint8),kernel)>0).sum()/max(1,resized.sum())
    density = abs(source.mean()-resized.mean())
    return float((recall+precision)/2-density*.65)


def char_evidence(rgb, text, words):
    result, cursor = [], 0
    h, w = rgb.shape[:2]
    for char, score, quad in words or []:
        if len(char) != 1 or quad is None:
            continue
        index = text.find(char,cursor)
        if index < 0:
            continue
        cursor = index+1
        if not char.isalnum() or score < .85:
            continue
        points = np.asarray(quad)
        x0,y0 = np.floor(points.min(axis=0)).astype(int)
        x1,y1 = np.ceil(points.max(axis=0)).astype(int)
        x0,y0,x1,y1 = max(0,x0),max(0,y0),min(w,x1),min(h,y1)
        if x1-x0 < 3 or y1-y0 < 3:
            continue
        # OCR character boxes are approximate and may cut off the sides of a Chinese glyph.
        # Snap to the complete ink column group around the predicted centre, using a wider
        # patch to estimate the background (a clipped bold glyph can otherwise invert the mask).
        mid = (x0+x1)//2
        radius = max(10,y1-y0)
        patch_left,patch_right = max(0,mid-radius),min(w,mid+radius)
        background = dominant_color(rgb[max(0,y0-5):min(h,y1+5),patch_left:patch_right])
        mask,_ = ink_mask(rgb[y0:y1,patch_left:patch_right],background)
        columns = mask.any(axis=0).astype(np.uint8)[None,:]
        if ord(char)>127:
            columns = cv2.morphologyEx(columns,cv2.MORPH_CLOSE,np.ones((1,3),np.uint8))
        padded = np.pad(columns[0],(1,1))
        transitions = np.diff(padded.astype(int))
        starts,ends = np.where(transitions == 1)[0],np.where(transitions == -1)[0]
        if not len(starts): continue
        target = mid-patch_left
        selected = int(np.argmin([abs((a+b)/2-target) for a,b in zip(starts,ends)]))
        a,b = int(starts[selected]),int(ends[selected])
        mask = mask[:,a:b]
        x0 = patch_left+a
        tight = tight_mask(mask)
        if tight is None:
            continue
        source, bounds = tight
        if source.shape[0] < 5 or source.shape[1]/source.shape[0] > 1.5:
            continue
        result.append((index,char,source,(x0+bounds[0],y0+bounds[1],x0+bounds[2],y0+bounds[3])))
    return result


def infer_font(evidence):
    chinese = [item for item in evidence if ord(item[1]) > 127]
    samples = chinese[:10] if chinese else evidence[:10]
    if not samples:
        return FONT_CHOICES[0]
    scores = []
    for choice in FONT_CHOICES:
        values = [max(similarity(source,render_glyph(char,choice,bold,max(12,source.shape[0]))) for bold in (False,True)) for _,char,source,_ in samples]
        scores.append(float(np.median(values)))
    best = int(np.argmax(scores))
    return FONT_CHOICES[best] if scores[best]-scores[0] > .035 else FONT_CHOICES[0]


def string_mask(text,choice,size,bold):
    size = max(5,round(size))
    measured,_ = text_metrics(text,choice,size,700 if bold else 400,[])
    canvas = Image.new("L", (min(16000,max(16,int(measured+size*2))),size*4),255)
    draw,x = ImageDraw.Draw(canvas),size/2
    for char in text:
        filename = font_file(char,choice,bold)
        font = load_font(filename,size)
        if font is None:
            continue
        stroke = 1 if bold and ord(char)>127 and choice[1] == choice[2] else 0
        draw.text((x,size*2),char,font=font,fill=0,anchor="ls",stroke_width=stroke)
        x += font.getlength(char)
    pixels = np.asarray(canvas)
    tight = tight_mask(pixels < 115)
    return tight[0] if tight else None


def weight_fraction(source,text,choice,size):
    values = []
    for bold in (False,True):
        rendered = string_mask(text,choice,size,bold)
        if rendered is None:
            return 0
        # Occupied-area ratio remains stable after fitting a source line to its original width.
        values.append(float(rendered.mean()))
    return float((source.mean()-values[0])/max(.04,values[1]-values[0]))


def infer_runs(rgb,text,words,choice,size,background,glyph_provider=None,match_info=None):
    # Inspect every recognized glyph, including Chinese phrases in the middle
    # of a sentence. No colon/prefix/English-token assumptions.
    from .typography import _match,indexed_words
    reliable={}
    if glyph_provider is not None and match_info:
        for kind,info in match_info.items():
            scores=sorted(info['scores'])
            reliable[kind]=bool(scores) and scores[-1]>=.9 and (len(scores)<2 or scores[-1]-scores[-2]>=.03)
    samples=[(index,char,quad) for index,char,score,quad in indexed_words(text,words) if score>=.9 and char.isalnum()]
    if reliable:samples=[sample for sample in samples if reliable.get('latin' if sample[1].isascii() else 'chinese',False)]
    if not samples:return []
    points=np.concatenate([quad for _,_,quad in samples])
    bounds=(max(0,int(points[:,0].min())-2),max(0,int(points[:,1].min())-2),min(rgb.shape[1],int(np.ceil(points[:,0].max()))+2),min(rgb.shape[0],int(np.ceil(points[:,1].max()))+2))
    sizes=[float(s) for s in np.arange(max(5,size-1),size+1.1,.5)]
    _,matches,_=_match(rgb,bounds,background,samples,[choice],sizes=sizes,glyph_provider=glyph_provider)
    selected=[m[0] for m in matches if m[2]>=.65 and m[3] and m[7]>=.025]
    # A weak interior character should not split an otherwise consistent bold
    # word. Its own paired-face score must also support bold; no lexical rules.
    strong=set(selected)
    selected += [m[0] for m in matches if m[0] not in strong and m[2]>=.78 and m[3] and m[7]>=.008 and
                 (m[0]-1 in strong and m[0]+1 in strong)]
    selected.sort()
    groups=[]
    for index in selected:
        if groups and (index == groups[-1][-1]+1 or all(not ch.isalnum() for ch in text[groups[-1][-1]+1:index])):
            groups[-1].append(index)
        else:groups.append([index])
    return [TextRun(start=group[0],end=group[-1]+1,fontWeight=700) for group in groups if len(group)>=2]


def text_metrics(text, choice, size, weight, runs):
    widths, heights = [], []
    for index, char in enumerate(text):
        if char == "\n":
            continue
        bold = next((run.fontWeight == 700 for run in runs if run.start <= index < run.end),weight == 700)
        filename = font_file(char,choice,bold)
        font = load_font(filename,max(1,round(size*4)))
        if font is None:
            widths.append(size*(.52 if ord(char)<128 else 1))
            continue
        widths.append(font.getlength(char)/4)
        box = font.getbbox(char)
        if char.isalnum():
            heights.append((box[3]-box[1])/4)
    return sum(widths), max(heights,default=size*.9)


def recover_text(rgb, text, box, words, confidence, factor, page_number, font_choice=None, typography=None,glyph_provider=None):
    from .typography import match_typography, restore_spaces
    text = restore_spaces(text,words)
    choice,matched_size,matched_weight,pixel,match_info = typography or match_typography(rgb,text,box,words,font_choice)
    informative = [info for info in match_info.values() if info['scores'] and info['samples'] >= 3]
    ambiguous = not informative
    for info in informative:
        ordered = sorted(info['scores'],reverse=True)
        if ordered[0] < .65 or len(ordered)>1 and ordered[0]-ordered[1] < .035: ambiguous = True
    h,w = rgb.shape[:2]
    mask,bg,(left,top,right,bottom) = pixel
    crop = rgb[top:bottom,left:right]
    tight = tight_mask(mask)
    if tight is not None:
        _, (x0,y0,x1,y1) = tight
        ink_x,ink_y,ink_width,ink_height = left+x0,top+y0,x1-x0,y1-y0
        pixels = crop[mask]
        luminance = pixels.astype(float).mean(axis=1)
        core = pixels[luminance <= np.percentile(luminance,25)]
        foreground = hex_color(np.median(core,axis=0))
    else:
        ink_x,ink_y,ink_width,ink_height = left,top,max(1,right-left),max(1,bottom-top)
        foreground = "#222222"
    _,probe_height = text_metrics(text,choice,40,400,[])
    initial_size = max(5,min(500,matched_size or ink_height*40/max(1,probe_height)))
    weight = matched_weight if matched_size else 700 if tight and weight_fraction(tight[0],text,choice,initial_size) > .6 else 400
    if weight == 700 and tight is not None and choice[1] != choice[2] and weight_fraction(tight[0],text,choice,initial_size) < .35:
        # A few bold glyphs can dominate the sampled character votes. The full
        # line's occupied area distinguishes a mixed sentence from an all-bold face.
        weight = 400
    runs = infer_runs(rgb,text,words,choice,initial_size,bg,glyph_provider,match_info) if weight == 400 else []
    # Match actual glyph height, then fit the advance width of the recognised line into its source bounds.
    _, probe_height = text_metrics(text,choice,40,weight,runs)
    size = initial_size if matched_size else max(5,min(500,ink_height*40/max(1,probe_height)))
    measured_width,_ = text_metrics(text,choice,size,weight,runs)
    width = ink_width+max(2,size*.08)
    font_scale = float(np.clip((width-1)/max(1,measured_width),.4,2)) if confidence >= .85 else 1
    height = max(size*1.2,ink_height+size*.12)
    return Element(id=new_id("text"),type="text",text=text,textRuns=runs,
                   x=float(ink_x*factor),y=float((ink_y-size*.12)*factor),
                   width=float(width*factor),height=float(height*factor),zIndex=2,
                   style=Style(fontFamily=choice[0],fontSize=float(size*factor),fontScaleX=font_scale,
                               fontWeight=weight,color=foreground,lineHeight=1.15),
                   sourceRegion=SourceRegion(detectedFrom="ocr",page=page_number,confidence=float(confidence),sourceFont=("近似候选 / " if ambiguous else "像素匹配 / ")+choice[0]))


def recover_bullet(rgb,element,box,factor,page_number):
    left,top = np.floor(np.min(box,axis=0)).astype(int)
    right,bottom = np.ceil(np.max(box,axis=0)).astype(int)
    left,top,right,bottom = max(0,left),max(0,top),min(rgb.shape[1],right),min(rgb.shape[0],bottom)
    mask,_ = ink_mask(rgb[top:bottom,left:right])
    if not mask.any(): return None
    first = int(np.where(mask.any(axis=0))[0][0])
    count,_,stats,_ = cv2.connectedComponentsWithStats(mask.astype(np.uint8),8)
    for x,y,width,height,area in stats[1:]:
        minimum,maximum = max(2,mask.shape[0]*.07),max(4,mask.shape[0]*.45)
        if x-first>2 or not minimum<=width<=maximum or not minimum<=height<=maximum or not .6<=width/height<=1.5 or area/(width*height)<.55:
            continue
        if not .25*mask.shape[0] <= y+height/2 <= .8*mask.shape[0]: continue
        following = np.where(mask[:,x+width:].any(axis=0))[0]
        if not len(following) or following[0]<mask.shape[0]*.3: continue
        text_start = x+width+int(following[0])
        remaining = tight_mask(mask[:,text_start:])
        if remaining is None: continue
        _,bounds = remaining
        new_x = left+text_start+bounds[0]
        new_right = left+text_start+bounds[2]
        element.x = float(new_x*factor)
        element.width = float((new_right-new_x+max(2,element.style.fontSize/factor*.08))*factor)
        if element.text.startswith(("•","·","●","∙",".")):
            element.text = element.text[1:]
            element.textRuns = [TextRun(start=max(0,r.start-1),end=r.end-1,fontWeight=r.fontWeight) for r in element.textRuns if r.end>1]
        return Element(id=new_id("bullet"),type="rect",x=float((left+x)*factor),y=float((top+y)*factor),
                       width=float(width*factor),height=float(height*factor),shape="circle",zIndex=2,
                       style=Style(background=element.style.color),
                       sourceRegion=SourceRegion(detectedFrom="pixel-bullet",page=page_number))
    return None
