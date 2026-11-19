"""Fit typography only where source components support a coherent text region."""
import math
import unicodedata
from functools import lru_cache

import numpy as np
from PIL import Image
from scipy import ndimage

from mapvector.geometry.text import _quad_frame, layout_font
from mapvector.geometry.text_metrics import center_runs, fit_run, font_metrics

SUB='₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓ'
SUP='⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾'
NORMAL_SUB='0123456789+-=()aeox'
NORMAL_SUP='0123456789+-=()'
MAX_RECTIFIED_PIXELS=2_000_000


def _sampling_scale(width,height):
    preferred=4 if max(width,height)<300 else 2
    return min(preferred,math.sqrt(MAX_RECTIFIED_PIXELS/width/height),4096/max(width,height))


def _char(char):
    if char in SUB:return NORMAL_SUB[SUB.index(char)],'subscript'
    if char in SUP:return NORMAL_SUP[SUP.index(char)],'superscript'
    name=unicodedata.name(char,'')
    if 'SUBSCRIPT' in name:return unicodedata.normalize('NFKC',char),'subscript'
    if 'SUPERSCRIPT' in name or name.startswith('MODIFIER LETTER SMALL') or name.startswith('MODIFIER LETTER CAPITAL'):
        return unicodedata.normalize('NFKC',char),'superscript'
    return char,'normal'


def _rectify(image,quad,width,height,scale):
    # OCR corner order encodes reading direction, including upright narrow digits.
    # The longest edge is not necessarily a text baseline.
    corners=list(quad)
    left=max(0,math.floor(min(p[0] for p in corners))-2)
    top=max(0,math.floor(min(p[1] for p in corners))-2)
    right=min(image.width,math.ceil(max(p[0] for p in corners))+2)
    bottom=min(image.height,math.ceil(max(p[1] for p in corners))+2)
    shape=(max(2,math.floor(width*scale)),max(2,math.floor(height*scale)))
    if right<=left or bottom<=top:
        return np.full((shape[1],shape[0],3),255.,dtype=float),corners
    # Convert just the bounded crop. A full raster RGB copy per OCR word is costly.
    crop=image.crop((left,top,right,bottom)).convert('RGB')
    local=[(x-left,y-top) for x,y in corners]
    return np.asarray(crop.transform(shape,Image.Transform.QUAD,
        tuple(v for i in (0,3,2,1) for v in local[i]),
        resample=Image.Resampling.BICUBIC,fillcolor=(255,255,255))).astype(float),corners


def _components(mask,scale):
    labels,_=ndimage.label(mask,structure=np.ones((3,3)))
    components=[]
    for number,section in enumerate(ndimage.find_objects(labels),1):
        if section is None:continue
        yy,xx=section;area=int((labels[section]==number).sum())
        if area<max(4,scale*scale*.15):continue
        components.append(dict(x0=xx.start,x1=xx.stop,y0=yy.start,y1=yy.stop,
                               area=area,label=number))
    selected=np.isin(labels,[c['label'] for c in components])
    return selected,components


def _region_reasons(mask,components,scale):
    """Reject conflicting spatial evidence before assigning semantic glyphs."""
    height,width=mask.shape;total=sum(c['area'] for c in components)
    significant=[c for c in components if c['area']>=max(scale*scale*.4,total*.012)]
    reasons=[]
    for c in significant:
        h=c['y1']-c['y0'];w=c['x1']-c['x0']
        top=c['y0']<=scale*.5;bottom=c['y1']>=height-scale*.5
        side=c['x0']<=scale*.5 or c['x1']>=width-scale*.5
        if ((top or bottom) and h>height*.65 or
                side and (top or bottom) and h>max(w*1.8,height*.35)):
            reasons.append('border_connected_ink')
    # Independently occupied rows at the same x cannot both be one glyph.
    for i,a in enumerate(significant):
        for b in significant[i+1:]:
            overlap=min(a['x1'],b['x1'])-max(a['x0'],b['x0'])
            narrow=min(a['x1']-a['x0'],b['x1']-b['x0'])
            gap=max(a['y0'],b['y0'])-min(a['y1'],b['y1'])
            tall=min(a['y1']-a['y0'],b['y1']-b['y0'])
            # Dots and accents belong to their glyph; full neighboring glyphs do not.
            if overlap>narrow*.45 and gap>scale and tall>height*.18:
                reasons.append('multiple_ink_regions')
    return list(dict.fromkeys(reasons))


def _glyph_boxes(mask,nonspace):
    """Column gaps propose assignments; geometry must still validate each one."""
    groups=_ranges(mask.any(0))
    if len(groups)!=len(nonspace):return None
    boxes=[]
    for index,(lo,hi) in zip(nonspace,groups):
        yy,xx=np.where(mask[:,lo:hi])
        boxes.append(dict(index=index,x0=lo+int(xx.min()),x1=lo+int(xx.max())+1,
                          y0=int(yy.min()),y1=int(yy.max())+1))
    return boxes


def _normalized_ink(mask):
    yy,xx=np.where(mask)
    if not len(xx):return np.zeros((64,64),dtype=bool)
    tight=mask[yy.min():yy.max()+1,xx.min():xx.max()+1]
    return np.asarray(Image.fromarray(np.uint8(tight)*255).resize(
        (64,64),Image.Resampling.BILINEAR))>127


@lru_cache(maxsize=512)
def _glyph_template(text):
    font,_=layout_font()
    # Small fixed font size bounds temporary template memory for long labels.
    font=font.font_variant(size=64)
    mask=font.getmask(text,mode='L')
    return _normalized_ink(np.asarray(Image.frombytes('L',mask.size,bytes(mask)))>127)


def _glyph_similarity(mask,text):
    """Tolerant shape support; failure means review, never rewriting OCR text."""
    source=_normalized_ink(mask);template=_glyph_template(text)
    source_support=(source&ndimage.maximum_filter(template,size=5)).sum()/max(1,source.sum())
    template_support=(template&ndimage.maximum_filter(source,size=5)).sum()/max(1,template.sum())
    return 2*source_support*template_support/max(.001,source_support+template_support)


def _script_runs(text,boxes,scale,mask):
    """Accept a glyph correspondence only with shape and baseline agreement."""
    decoded=[_char(ch) for ch in text]
    heights=[b['y1']-b['y0'] for b in boxes]
    main_h=float(np.quantile(heights,.8))
    normal=[b for b in boxes if b['y1']-b['y0']>=main_h*.78
            and decoded[b['index']][1]=='normal'] or boxes
    base_mid=float(np.median([(b['y0']+b['y1'])/2 for b in normal]))
    has_letters=any(glyph.isalpha() for glyph,script in decoded)
    reasons=[];runs=[]
    for b in boxes:
        glyph,script=decoded[b['index']]
        w=b['x1']-b['x0'];h=b['y1']-b['y0'];mid=(b['y0']+b['y1'])/2
        ink,_=font_metrics(glyph)
        ratio=(w/max(1,h))/max(.01,(ink[2]-ink[0])/max(1,ink[3]-ink[1]))
        if not .45<=ratio<=2.1:reasons.append('glyph_shape_mismatch')
        source=mask[b['y0']:b['y1'],b['x0']:b['x1']]
        # Matching counts/aspects/baselines do not identify a glyph. Require
        # tolerant silhouette support before accepting a per-character mapping.
        density=_normalized_ink(source).mean()/max(.001,_glyph_template(glyph).mean())
        # Dilation tolerates scan/font differences but can fill a letter's small
        # counters; ink density prevents a solid block passing as such a letter.
        if _glyph_similarity(source,glyph)<.75 or not .55<=density<=1.55:
            reasons.append('glyph_shape_mismatch')
        if glyph.isdigit() and has_letters and h<main_h*.8:
            measured=('subscript' if mid>base_mid+main_h*.18 else
                      'superscript' if mid<base_mid-main_h*.18 else None)
            if measured is None:reasons.append('script_position_uncertain')
            elif script!='normal' and measured!=script:reasons.append('script_position_uncertain')
            else:script=measured
        elif script!='normal' and h>=main_h*.85:
            reasons.append('script_position_uncertain')
        runs.append(fit_run(glyph,[b[k]/scale for k in ('x0','y0','x1','y1')],
                            source_index=b['index'],script=script))
    # Normal glyphs in one line should agree in baseline and size; no value is
    # forced to a common size to make disagreement disappear.
    normal_runs=[r for r in runs if r['script']=='normal' and r['text'].isalnum()]
    if len(normal_runs)>1:
        sizes=[r['font_size_px'] for r in normal_runs]
        baselines=[r['baseline_offset_px'] for r in normal_runs]
        if max(sizes)>min(sizes)*1.7 or max(baselines)-min(baselines)>main_h/scale*.32:
            reasons.append('inconsistent_glyph_baselines')
    return runs,list(dict.fromkeys(reasons))


def _fallback_runs(text,target,reasons):
    """Keep explicit Unicode scripts even when their source assignment is unsafe."""
    decoded=[_char(ch) for ch in text]
    if all(script=='normal' for _,script in decoded):
        return [fit_run(text,target,quality_reasons=reasons)]
    reasons=list(dict.fromkeys([*reasons,'script_position_unverified']))
    runs=[];position=0.
    for index,(glyph,script) in enumerate(decoded):
        ratio=.7 if script!='normal' else 1.
        shift=205. if script=='subscript' else -410. if script=='superscript' else 0.
        ink,advance=font_metrics(glyph)
        if not glyph.isspace():
            box=[position+ink[0]*ratio,ink[1]*ratio+shift,
                 position+ink[2]*ratio,ink[3]*ratio+shift]
            runs.append(fit_run(glyph,box,script=script,source_index=index,
                                basis='unicode_unverified',quality_reasons=reasons))
        position+=advance*ratio
    _,_,width,height=center_runs(runs)
    factor=min((target[2]-target[0])/max(1,width),(target[3]-target[1])/max(1,height))
    cx=(target[0]+target[2])/2;cy=(target[1]+target[3])/2
    for run in runs:
        run['font_size_px']*=factor;run['width_px']*=factor
        run['x_offset_px']=run['x_offset_px']*factor+cx
        run['baseline_offset_px']=run['baseline_offset_px']*factor+cy
        run['ink_bbox_px']=[v*factor+(cx if i%2==0 else cy)
                             for i,v in enumerate(run['ink_bbox_px'])]
    return runs


def _finish_layout(runs,corners,width,height,angle,reasons):
    center_u,center_v,ink_width,ink_height=center_runs(runs)
    u=center_u/width;v=center_v/height
    p0,p1,p2,p3=corners
    x=(1-u)*(1-v)*p0[0]+u*(1-v)*p1[0]+u*v*p2[0]+(1-u)*v*p3[0]
    y=(1-u)*(1-v)*p0[1]+u*(1-v)*p1[1]+u*v*p2[1]+(1-u)*v*p3[1]
    _,family=layout_font()
    sizes=[r['font_size_px'] for r in runs if r['script']=='normal'] or [r['font_size_px'] for r in runs]
    reasons=list(dict.fromkeys([*reasons,*[reason for r in runs for reason in r.get('quality_reasons',[])]]))
    return dict(x=x,y=y,font_size_px=float(np.median(sizes)),rotation_deg=angle,
                font_family=family,layout_width_px=ink_width,layout_height_px=ink_height,
                baseline_offset_px=float(np.median([r['baseline_offset_px'] for r in runs])),
                layout_basis='ocr_ink_v4',layout_runs=runs,quality_reasons=reasons,
                script_review_required=bool(reasons))


def conservative_layout(text,quad,reasons):
    """Natural, reviewable fallback when source pixels do not support fitting."""
    width,height,angle=_quad_frame(quad,reading_axis=True)
    runs=_fallback_runs(text,[0,height*.1,width,height*.9],reasons)
    return _finish_layout(runs,quad,width,height,angle,reasons)


def source_ink_layout(text,quad,image):
    width,height,angle=_quad_frame(quad,reading_axis=True)
    if not text.strip() or width<2 or height<2:return None
    scale=_sampling_scale(width,height)
    if scale<.5:
        return conservative_layout(text,quad,['raster_budget_exceeded'])
    rgb,corners=_rectify(image,quad,width,height,scale)
    gray=rgb@np.array([.299,.587,.114]);chroma=rgb.max(2)-rgb.min(2)
    neutral=(rgb.max(2)<178)&(chroma<48)
    bg=ndimage.maximum_filter(gray,size=max(3,round(height*scale*.45)))
    contrast=(gray<175)&(bg-gray>48)
    mask=neutral if neutral.sum()>max(12,width*height*scale*scale*.012) else contrast
    mask,components=_components(mask,scale)
    if not components:return None
    yy,xx=np.where(mask);x0=int(xx.min());x1=int(xx.max())+1
    y0=int(yy.min());y1=int(yy.max())+1
    nonspace=[i for i,ch in enumerate(text) if not ch.isspace()]
    if (x1-x0<max(2.5*scale,width*scale*.08) or y1-y0<2*scale or
            len(nonspace)>1 and x1-x0<=4*scale or
            mask.sum()<max(8,scale*scale*2)):
        return None
    if (len(components)==1 and len(nonspace)>1 and any(ch.isalnum() for ch in text)
            and y1-y0<=max(4*scale,height*scale*.1)
            and x1-x0>(y1-y0)*6):
        # An isolated cartographic rule is not evidence for a complete label.
        return None
    # Preserve complete components, including glyph tops/bottoms and dots. Never
    # turn the dense middle row band into the final glyph height.
    reasons=_region_reasons(mask,components,scale)
    decoded=[_char(ch) for ch in text]
    short_code=(len(nonspace)<=12 and any(s!='normal' for _,s in decoded) or
                len(nonspace)<=8 and all(ch.isascii() or s!='normal' or ch in 'αβγδϵЄ'
                                        for ch,s in decoded))
    boxes=_glyph_boxes(mask,nonspace) if short_code and not reasons else None
    runs=None
    if boxes is not None:
        proposed,assignment_reasons=_script_runs(text,boxes,scale,mask)
        reasons.extend(assignment_reasons)
        if not reasons:runs=proposed
    elif short_code:
        reasons.append('glyph_assignment_uncertain')
    if runs is None:
        # Ambiguous/multiregion evidence cannot justify per-glyph layout. Keep the
        # recognized string intact and fit a natural string isotropically.
        target=[x0/scale,y0/scale,x1/scale,y1/scale]
        ink,_=font_metrics(text)
        aspect=((x1-x0)/max(1,y1-y0))/max(.01,(ink[2]-ink[0])/max(1,ink[3]-ink[1]))
        if not .55<=aspect<=1.8 or _glyph_similarity(mask[y0:y1,x0:x1],text)<.55:
            reasons.append('ink_region_shape_mismatch')
        if reasons:
            max_height=min(target[3]-target[1],height*.8)
            mid=(target[1]+target[3])/2
            target[1]=mid-max_height/2;target[3]=mid+max_height/2
        runs=_fallback_runs(text,target,list(dict.fromkeys(reasons)))
    return _finish_layout(runs,corners,rgb.shape[1]/scale,rgb.shape[0]/scale,angle,reasons)


def _ranges(values):
    out=[];start=None
    for i,value in enumerate(values):
        if value and start is None:start=i
        if start is not None and (not value or i==len(values)-1):
            out.append((start,i if not value else i+1));start=None
    return out
