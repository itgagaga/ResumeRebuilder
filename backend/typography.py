"""Match installed glyph candidates locally; never identify a template by its text or file name."""
import cv2
import numpy as np

from .image_layout import FONT_CHOICES, ink_mask, load_font, render_glyph

LATIN_CHOICES = [
    ("Arial", "arial.ttf", "arialbd.ttf"),
    ("Times New Roman", "times.ttf", "timesbd.ttf"),
    ("Georgia", "georgia.ttf", "georgiab.ttf"),
    ("Calibri", "calibri.ttf", "calibrib.ttf"),
]


def principal_ink(rgb, box):
    """Keep the row nearest the OCR centre, excluding rules and adjacent-line tails."""
    left,top = np.floor(np.min(box,axis=0)).astype(int)
    right,bottom = np.ceil(np.max(box,axis=0)).astype(int)
    left,top = max(0,min(rgb.shape[1]-1,left)),max(0,min(rgb.shape[0]-1,top))
    right,bottom = max(left+1,min(rgb.shape[1],right)),max(top+1,min(rgb.shape[0],bottom))
    mask,bg = ink_mask(rgb[top:bottom,left:right])
    if mask.size == 0 or not mask.any(): return mask,bg,(left,top,right,bottom)
    profile = mask.sum(axis=1)
    # A near-full horizontal rule is geometry, not a font's cap height.
    active = (profile > max(1,float(profile.max())*.06)) & (profile < mask.shape[1]*.94)
    active = cv2.morphologyEx(active.astype(np.uint8)[:,None],cv2.MORPH_CLOSE,np.ones((3,1),np.uint8))[:,0] > 0
    rows = np.where(active)[0]
    if not len(rows): return mask,bg,(left,top,right,bottom)
    groups = np.split(rows,np.where(np.diff(rows)>1)[0]+1)
    centre = (bottom-top)/2
    best = max(groups,key=lambda g: float(profile[g].sum())/(1+abs(float(g.mean())-centre)/max(1,centre)))
    y0,y1 = max(0,int(best[0])-1),min(mask.shape[0],int(best[-1])+2)
    return mask[y0:y1],bg,(left,top+y0,right,top+y1)


def indexed_words(text, words):
    cursor = 0
    for char,score,quad in words or []:
        if len(char) != 1 or quad is None: continue
        index = text.find(char,cursor)
        if index < 0: continue
        cursor = index+1
        yield index,char,float(score),np.asarray(quad)


def _samples(text,words,latin):
    samples = [(i,ch,q) for i,ch,score,q in indexed_words(text,words) if score >= .9 and
               ((ch.isascii() and ch.isalnum() and ch not in 'Iil1') if latin else '\u4e00' <= ch <= '\u9fff')]
    if len(samples) > 8:
        samples = [samples[i] for i in np.linspace(0,len(samples)-1,8).astype(int)]
    return samples


def _match(rgb,bounds,bg,samples,choices,sizes=None,glyph_provider=None):
    left,top,right,bottom = bounds
    height = bottom-top
    if height < 5 or not samples or not choices: return None,[],{'choices':choices,'scores':[],'details':[],'samples':len(samples)}
    scores,details = [],[]
    sizes = sizes or list(range(max(6,round(height*.7)),max(8,round(height*1.5))))
    patches = []
    for index,char,quad in samples:
        mid = float(quad[:,0].mean())
        x0,x1 = max(0,int(mid-height*2)),min(rgb.shape[1],int(mid+height*2))
        y0,y1 = max(0,top-3),min(rgb.shape[0],bottom+3)
        if x1 <= x0 or y1 <= y0: continue
        patch = rgb[y0:y1,x0:x1]
        contrast = np.linalg.norm(patch.astype(np.float32)-bg.astype(np.float32),axis=2)
        source = np.clip(contrast/max(1,float(np.percentile(contrast,98))),0,1).astype(np.float32)
        source[source < .05] = 0
        patches.append((index,char,mid,x0,y0,source))
    if not patches: return None,[],{'choices':choices,'scores':[],'details':[],'samples':0}
    for choice in choices:
        by_size = {size:[] for size in sizes}
        for index,char,mid,x0,y0,source in patches:
            for size in sizes:
                best = (0.,False,size,x0,y0,0.)
                face_scores = []
                for bold in (False,True):
                    rendered = (glyph_provider or render_glyph)(char,choice,bold,size,antialias=True)
                    variants=rendered if isinstance(rendered,list) else [rendered]
                    face_best=(0.,(0,0))
                    for glyph in variants:
                        if glyph is None:continue
                        # Include the blank perimeter. Matching a tightly cropped
                        # regular glyph inside a bold glyph otherwise ignores its
                        # extra outer strokes and spuriously favors regular weight.
                        glyph=np.pad(glyph,((2,2),(0,0) if char.isascii() else (2,2)))
                        if glyph.shape[0] > source.shape[0] or glyph.shape[1] > source.shape[1]:continue
                        values = cv2.matchTemplate(source,glyph.astype(np.float32),cv2.TM_CCOEFF_NORMED)
                        # Do not explain a glyph by matching an unrelated neighbour or sub-stroke.
                        centres = x0+np.arange(values.shape[1])+glyph.shape[1]/2
                        values -= (np.abs(centres-mid)/max(1,height)*.035).astype(np.float32)[None,:]
                        _,score,_,location = cv2.minMaxLoc(values)
                        if score>face_best[0]:face_best=(score,location)
                    score,location=face_best
                    face_scores.append(score)
                    if score > best[0]: best = (score,bold,size,x0+location[0],y0+location[1],0.)
                best=(*best[:-1],abs(face_scores[1]-face_scores[0]))
                by_size[size].append((index,char,*best))
        # All samples from a line must agree on one size. Independent per-character
        # maxima otherwise make a wrong font look good by using a different size for every letter.
        size_scores = {size:float(np.mean([m[2] for m in matches])) for size,matches in by_size.items()}
        winner = max(by_size,key=size_scores.get)
        matches = by_size[winner]
        scores.append(size_scores[winner])
        details.append(matches)
    best = int(np.argmax(scores))
    return (choices[best] if scores[best] >= .5 else None),details[best],{'choices':choices,'scores':scores,'details':details,'samples':len(samples)}


def match_typography(rgb,text,box,words,fallback=None,glyph_provider=None,sizes=None):
    mask,bg,bounds = principal_ink(rgb,box)
    fallback = fallback or FONT_CHOICES[0]
    raw = np.asarray(box)
    search_bounds = (max(0,int(raw[:,0].min())),max(0,int(raw[:,1].min())),min(rgb.shape[1],int(np.ceil(raw[:,0].max()))),min(rgb.shape[0],int(np.ceil(raw[:,1].max()))))
    ink_height=bounds[3]-bounds[1]
    sizes=sizes or [float(s) for s in np.arange(max(6,round(ink_height*.7)),max(8,round(ink_height*1.5)),.5 if ink_height<26 else 1)]
    chinese,matches,chinese_info = _match(rgb,search_bounds,bg,_samples(text,words,False),FONT_CHOICES,sizes=sizes,glyph_provider=glyph_provider)
    chinese = chinese or fallback
    latin_candidates = [(f'{name}, {chinese[0].split(", ")[1]}, {"serif" if name in {"Times New Roman","Georgia"} else "sans-serif"}',chinese[1],chinese[2],regular,bold)
                        for name,regular,bold in LATIN_CHOICES if load_font(regular,20) is not None]
    latin,latin_matches,latin_info = _match(rgb,search_bounds,bg,_samples(text,words,True),latin_candidates,sizes=sizes,glyph_provider=glyph_provider)
    choice = latin or chinese
    good_chinese = [m for m in matches if m[2] >= .58]
    good = good_chinese if len(good_chinese) >= 3 else [m for m in latin_matches if m[2] >= .58]
    weight_samples = [m for m in matches+latin_matches if m[2] >= .58]
    # Use several matched glyphs instead of the tallest pixel in a potentially contaminated OCR box.
    size = float(np.median([m[4] for m in good])) if len(good) >= 3 else None
    weight = 700 if weight_samples and sum(m[3] for m in weight_samples)/len(weight_samples) > .72 else 400
    return choice,size,weight,(mask,bg,bounds),{'chinese':chinese_info,'latin':latin_info}


def smooth_typography(analyses,pooled_font=None,rgb=None):
    """Use a page's reliable evidence only to resolve ambiguous glyph matches.

    Clearly distinct headings/mixed fonts keep their own result. Chinese and Latin
    priors are independent, so a serif date does not change its Chinese neighbour.
    """
    # Typography cohorts use measured ink color rather than title vocabulary.
    # Distinct colored/darker faces must not inherit the body's weight prior.
    cohorts, membership = [],[]
    if rgb is not None:
        for analysis in analyses:
            mask,_,(left,top,right,bottom) = analysis[3]
            pixels = rgb[top:bottom,left:right][mask]
            if not len(pixels): membership.append(None); continue
            values = pixels.astype(float).mean(axis=1)
            color = np.median(pixels[values<=np.percentile(values,25)],axis=0)
            group = next((i for i,c in enumerate(cohorts) if np.linalg.norm(color-c['color'])<18),None)
            if group is None:
                group=len(cohorts);cohorts.append({'color':color,'indices':[]})
            cohorts[group]['indices'].append(len(membership));membership.append(group)
    weight_priors = {}
    for group,cohort in enumerate(cohorts):
        votes={400:0.,700:0.}
        for index in cohort['indices']:
            analysis=analyses[index]
            stats=[s for s in analysis[4].values() if s['samples']>=3 and s['scores']]
            if not stats: continue
            score=max(max(s['scores']) for s in stats)
            if score<.78:continue
            votes[analysis[2]]+=score
        total=sum(votes.values())
        winner=max(votes,key=votes.get)
        if len(cohort['indices'])>=4 and total>=3 and votes[winner]/total>=.72:
            weight_priors[group]=winner
    priors = {}
    for kind in ('chinese','latin'):
        votes = {}
        for analysis in analyses:
            info = analysis[4][kind]
            if not info['scores']: continue
            order = np.argsort(info['scores']);winner = int(order[-1])
            margin = info['scores'][winner]-(info['scores'][int(order[-2])] if len(order)>1 else 0)
            if info['scores'][winner] < .58 or margin < .025: continue
            choice = info['choices'][winner]
            key = choice[1:3] if kind == 'chinese' else choice[3:5]
            votes[key] = votes.get(key,0)+info['samples']*margin
        if votes:
            winner = max(votes,key=votes.get)
            if votes[winner]/sum(votes.values()) >= .55: priors[kind] = winner
    result = []
    for choice,size,weight,pixel,info in analyses:
        selected,all_matches = {},[]
        for kind in ('chinese','latin'):
            stats = info[kind]
            if not stats['scores']:
                selected[kind] = priors.get(kind,choice[1:3] if kind == 'chinese' else choice[3:5]);continue
            order = np.argsort(stats['scores']);index = int(order[-1])
            margin = stats['scores'][index]-(stats['scores'][int(order[-2])] if len(order)>1 else 0)
            if kind in priors and margin < .065:
                for candidate,candidate_choice in enumerate(stats['choices']):
                    key = candidate_choice[1:3] if kind == 'chinese' else candidate_choice[3:5]
                    if key == priors[kind] and stats['scores'][candidate] >= stats['scores'][index]-.09:
                        index = candidate;break
            # A downsampled glyph may lose its serifs. For small, ambiguous text,
            # use independent pooled stroke evidence rather than letting each line
            # switch to a different, overfitted local family. Large/clear mixed
            # headings still retain their own candidate.
            if kind == 'chinese' and pooled_font is not None and size is not None and size < 20 and margin < .1:
                for candidate,candidate_choice in enumerate(stats['choices']):
                    if candidate_choice[1:3] == pooled_font[1:3] and stats['scores'][candidate] >= max(stats['scores'])-.14:
                        index = candidate;break
            current = stats['choices'][index]
            selected[kind] = current[1:3] if kind == 'chinese' else current[3:5]
            all_matches.extend(m for m in stats['details'][index] if m[2] >= .58)
        chinese = next((c for c in FONT_CHOICES if c[1:3] == selected['chinese']),FONT_CHOICES[0])
        latin = next((c for c in LATIN_CHOICES if c[1:3] == selected['latin']),LATIN_CHOICES[0])
        family = f'{latin[0]}, {chinese[0].split(", ")[1]}, {"serif" if latin[0] in {"Times New Roman","Georgia"} else "sans-serif"}'
        choice = (family,*selected['chinese'],*selected['latin'])
        chinese_matches = [m for m in all_matches if not m[1].isascii()]
        size_matches = chinese_matches if len(chinese_matches)>=3 else all_matches
        if len(size_matches)>=3: size = float(np.median([m[4] for m in size_matches]))
        if all_matches: weight = 700 if sum(m[3] for m in all_matches)/len(all_matches) > .72 else 400
        group=membership[len(result)] if membership else None
        if group in weight_priors:
            # Only uncertain face matches use cohort consensus. Clear local
            # mixed-font/bold evidence remains independent of the page prior.
            stats=[s for s in info.values() if s['samples']>=3 and s['scores']]
            clear=any(max(s['scores'])>=.8 and len(s['scores'])>1 and sorted(s['scores'])[-1]-sorted(s['scores'])[-2]>=.065 for s in stats)
            if not clear:
                weight=weight_priors[group]
                if weight==analyses[len(result)][2]:
                    choice,size=analyses[len(result)][:2]
            else:
                choice,size,weight=analyses[len(result)][:3]
        result.append((choice,size,weight,pixel,info))
    return result


def restore_spaces(text,words):
    """Recover explicit geometric gaps between ASCII words, without language-specific word lists."""
    items = list(indexed_words(text,words))
    gaps = [float(b[3][:,0].min()-a[3][:,0].max()) for a,b in zip(items,items[1:]) if b[0] == a[0]+1]
    baseline = max(0,float(np.median(gaps))) if gaps else 0
    insertions = set()
    for a,b in zip(items,items[1:]):
        if b[0] != a[0]+1 or a[2] < .9 or b[2] < .9: continue
        if not (a[1].isascii() and b[1].isascii() and a[1].isalnum() and b[1].isalnum()): continue
        height = float(np.median([np.ptp(a[3][:,1]),np.ptp(b[3][:,1])]))
        gap = float(b[3][:,0].min()-a[3][:,0].max())
        if gap > max(3,baseline+height*.35): insertions.add(b[0])
    return ''.join((' ' if i in insertions else '')+ch for i,ch in enumerate(text))
