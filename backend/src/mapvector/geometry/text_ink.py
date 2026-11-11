"""Fit semantic glyphs to source ink instead of stretching them into OCR padding."""
import math
import unicodedata
import numpy as np
from PIL import Image
from scipy import ndimage
from mapvector.geometry.text import _quad_frame,layout_font

SUB='₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓ'
SUP='⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾'
NORMAL_SUB='0123456789+-=()aeox'
NORMAL_SUP='0123456789+-=()'


def _char(char):
    if char in SUB:return NORMAL_SUB[SUB.index(char)],'subscript'
    if char in SUP:return NORMAL_SUP[SUP.index(char)],'superscript'
    name=unicodedata.name(char,'')
    if 'SUBSCRIPT' in name:return unicodedata.normalize('NFKC',char),'subscript'
    if 'SUPERSCRIPT' in name or name.startswith('MODIFIER LETTER SMALL') or name.startswith('MODIFIER LETTER CAPITAL'):
        return unicodedata.normalize('NFKC',char),'superscript'
    return char,'normal'


def _rectify(image,quad,width,height,scale):
    # Use the principal text axis; correct all four corners to an upright crop.
    axis=0 if math.dist(quad[0],quad[1])+math.dist(quad[2],quad[3])>=math.dist(quad[1],quad[2])+math.dist(quad[3],quad[0]) else 1
    corners=[quad[(axis+i)%4] for i in range(4)]
    dx=corners[1][0]-corners[0][0];dy=corners[1][1]-corners[0][1]
    if dx<-.001 or abs(dx)<.001 and dy<0:corners=corners[2:]+corners[:2]
    return np.asarray(image.convert('RGB').transform((max(2,round(width*scale)),max(2,round(height*scale))),Image.Transform.QUAD,tuple(v for i in (0,3,2,1) for v in corners[i]),resample=Image.Resampling.BICUBIC)).astype(float),corners


def source_ink_layout(text,quad,image):
    width,height,angle=_quad_frame(quad)
    if not text.strip() or width<2 or height<2:return None
    scale=4 if max(width,height)<300 else 2
    rgb,corners=_rectify(image,quad,width,height,scale)
    gray=rgb@np.array([.299,.587,.114]);chroma=rgb.max(2)-rgb.min(2)
    neutral=(rgb.max(2)<178)&(chroma<48)
    bg=ndimage.maximum_filter(gray,size=max(3,round(height*scale*.45)))
    contrast=(gray<175)&(bg-gray>48)
    # Prefer neutral dark type over colored map boundaries. Fall back to local contrast.
    mask=neutral if neutral.sum()>max(12,width*height*scale*scale*.012) else contrast
    if mask.sum()<max(8,width*height*scale*scale*.004):return None
    row_mass=ndimage.gaussian_filter1d(mask.sum(1).astype(float),max(1,scale*.45))
    if np.argmax(row_mass)<len(row_mass)*.18 or row_mass.max()<width*scale*.05:
        mask=contrast
        row_mass=ndimage.gaussian_filter1d(mask.sum(1).astype(float),max(1,scale*.45))
    # OCR padding and crossing lines near the crop edge must not outrank the central text band.
    weights=np.clip(np.minimum(np.arange(len(row_mass))/max(1,len(row_mass)*.25),(len(row_mass)-1-np.arange(len(row_mass)))/max(1,len(row_mass)*.18)),.12,1)
    peak=int(np.argmax(row_mass*weights));floor=float(np.quantile(row_mass,.25));active=row_mass>max(2,floor+(row_mass[peak]-floor)*.30)
    y0=y1=peak
    while y0>0 and active[y0-1]:y0-=1
    while y1+1<len(active) and active[y1+1]:y1+=1
    y1+=1
    if y1-y0<max(3,height*scale*.20):return None
    band=mask[y0:y1];xs=np.where(band)[1]
    if not len(xs):return None
    x0=int(np.quantile(xs,.012));x1=int(np.quantile(xs,.988))+1
    if x1-x0<max(2,width*scale*.4):return None
    # Preserve true script components outside the dominant baseline band for short codes.
    decoded=[_char(ch) for ch in text]
    has_letters=any(glyph.isalpha() for glyph,script in decoded)
    short_code=(len(text.strip())<=12 and any(script!='normal' for ch,script in decoded)) or (len(text.strip())<=8 and all(ch.isascii() or script!='normal' or ch in 'αβγδϵЄ' for ch,script in decoded))
    if short_code and any(ch.isdigit() or script!='normal' for ch,script in decoded) and any(ch.isalpha() for ch,script in decoded):
        columns=mask.sum(0);occupied=columns>=max(1,(y1-y0)*.025)
        for lo,hi in _ranges(occupied):
            if hi<x0-scale or lo>x1+scale:continue
            yy=np.where(mask[:,max(lo,x0):min(hi,x1)])[0]
            if len(yy)>=5:y0=min(y0,int(np.quantile(yy,.01)));y1=max(y1,int(np.quantile(yy,.99))+1)
    # Remove sparse border noise and collect character bins from vertical ink gaps.
    col=mask[y0:y1,x0:x1].sum(0);groups=_ranges(col>max(1,(y1-y0)*.035))
    nonspace=[i for i,ch in enumerate(text) if not ch.isspace()]
    exact_chars=short_code and len(groups)==len(nonspace)
    if exact_chars:
        bins={index:(x0+g[0],x0+g[1]) for index,g in zip(nonspace,groups)}
    else:
        weights=[(.4 if ch.isspace() else 1 if ord(ch)>0x2e80 and _char(ch)[1]=='normal' else .62 if _char(ch)[1]!='normal' else .65) for ch in text]
        total=sum(weights);pos=x0;bins={}
        for index,weight in enumerate(weights):
            end=pos+(x1-x0)*weight/total;bins[index]=(round(pos),round(end));pos=end
    boxes=[]
    for index,ch in enumerate(text):
        if ch.isspace():continue
        lo,hi=bins[index];lo=max(x0,lo);hi=min(x1,max(lo+1,hi))
        ys,xs=np.where(mask[y0:y1,lo:hi])
        if len(xs)<4:continue
        boxes.append({'index':index,'char':ch,'x0':lo+int(np.quantile(xs,.01)),'x1':lo+int(np.quantile(xs,.99))+1,'y0':y0+int(np.quantile(ys,.01)),'y1':y0+int(np.quantile(ys,.99))+1})
    if not boxes:return None
    missing_chars=len(boxes)!=len(nonspace)
    if missing_chars and any(script!='normal' for char,script in decoded):return None
    # Baseline statistics use the tallest normal glyphs; small displaced digits are scripts.
    heights=[b['y1']-b['y0'] for b in boxes];main_h=float(np.quantile(heights,.8))
    normal_boxes=[b for b in boxes if b['y1']-b['y0']>=main_h*.78 and _char(b['char'])[1]=='normal'] or boxes
    base_top=float(np.median([b['y0'] for b in normal_boxes]));base_bottom=float(np.median([b['y1'] for b in normal_boxes]));base_mid=(base_top+base_bottom)/2
    font,family=layout_font();all_x0=min(b['x0'] for b in boxes);all_x1=max(b['x1'] for b in boxes);all_y0=min(b['y0'] for b in boxes);all_y1=max(b['y1'] for b in boxes)
    center_u=(all_x0+all_x1)/2;center_v=(all_y0+all_y1)/2
    runs=[];ambiguous=False
    for b in boxes:
        glyph,script=_char(b['char']);h=b['y1']-b['y0'];mid=(b['y0']+b['y1'])/2
        if short_code and has_letters and glyph.isdigit() and h<main_h*.8:
            if mid>base_mid+main_h*.18:script='subscript'
            elif mid<base_mid-main_h*.18:script='superscript'
            else:ambiguous=True
        elif short_code and glyph.isdigit() and script!='normal':
            ambiguous=True
        top,bottom=font.getbbox(glyph,anchor='ls')[1::2];ink=max(1,bottom-top);size=h/scale*1024/ink
        baseline=(b['y0']-center_v)/scale-top*size/1024
        runs.append({'text':glyph,'script':script,'font_size_px':size,'x_offset_px':(b['x0']-center_u)/scale,'baseline_offset_px':baseline,'width_px':(b['x1']-b['x0'])/scale,'source_index':b['index'],'basis':'source_ink','review_required':bool(ambiguous or not exact_chars) if short_code else False})
    u=center_u/(rgb.shape[1]);v=center_v/(rgb.shape[0]);p0,p1,p2,p3=corners
    x=(1-u)*(1-v)*p0[0]+u*(1-v)*p1[0]+u*v*p2[0]+(1-u)*v*p3[0]
    y=(1-u)*(1-v)*p0[1]+u*(1-v)*p1[1]+u*v*p2[1]+(1-u)*v*p3[1]
    if short_code:
        anchors=[r for r in runs if r['script']=='normal' and r['text'].isupper()] or sorted([r for r in runs if r['script']=='normal'],key=lambda r:r['font_size_px'],reverse=True)[:1]
        if anchors:
            common_size=float(np.median([r['font_size_px'] for r in anchors]))
            common_baseline=float(np.median([r['baseline_offset_px'] for r in anchors]))
            for run in runs:
                if run['script']=='normal':
                    run['font_size_px']=common_size;run['baseline_offset_px']=common_baseline
                elif run.get('review_required'):
                    run['font_size_px']=min(run['font_size_px'],common_size*.7)
                    run['baseline_offset_px']=common_baseline+(main_h/scale*.2 if run['script']=='subscript' else -main_h/scale*.45)
    if not short_code or missing_chars or short_code and not exact_chars and all(_char(ch)[1]=='normal' for ch in text):
        top,bottom=font.getbbox(text,anchor='ls')[1::2];size=(all_y1-all_y0)/scale*1024/max(1,bottom-top)
        runs=[{'text':text,'script':'normal','font_size_px':size,'x_offset_px':(all_x0-center_u)/scale,'baseline_offset_px':(all_y0-center_v)/scale-top*size/1024,'width_px':(all_x1-all_x0)/scale,'source_index':0,'basis':'source_ink','review_required':False}]
    sizes=[r['font_size_px'] for r in runs if r['script']=='normal'] or [r['font_size_px'] for r in runs]
    return {'x':x,'y':y,'font_size_px':float(np.median(sizes)),'rotation_deg':angle,'font_family':family,'layout_width_px':(all_x1-all_x0)/scale,'layout_height_px':(all_y1-all_y0)/scale,'baseline_offset_px':float(np.median([r['baseline_offset_px'] for r in runs])),'layout_basis':'ocr_ink_v3','layout_runs':runs,'script_review_required':ambiguous}


def _ranges(values):
    out=[];start=None
    for i,value in enumerate(values):
        if value and start is None:start=i
        if start is not None and (not value or i==len(values)-1):
            out.append((start,i if not value else i+1));start=None
    return out
