"""Persisted OCR typography and pixel-space text geometry."""
import math


def _quad_frame(quad):
    if len(quad)!=4 or not all(len(p)==2 and all(math.isfinite(v) for v in p) for p in quad):raise ValueError('Invalid OCR quadrilateral')
    edges=[(quad[(i+1)%4][0]-quad[i][0],quad[(i+1)%4][1]-quad[i][1]) for i in range(4)]
    lengths=[math.hypot(*edge) for edge in edges]
    axis=0 if lengths[0]+lengths[2]>=lengths[1]+lengths[3] else 1
    dx=(edges[axis][0]-edges[(axis+2)%4][0])/2;dy=(edges[axis][1]-edges[(axis+2)%4][1])/2
    width=(lengths[axis]+lengths[(axis+2)%4])/2
    height=(lengths[(axis+1)%4]+lengths[(axis+3)%4])/2
    if min(width,height)<=0:raise ValueError('Degenerate OCR quadrilateral')
    angle=-math.degrees(math.atan2(dy,dx))
    while angle<=-90:angle+=180
    while angle>90:angle-=180
    return width,height,angle


def ocr_quad_metrics(quad):
    """Compatibility entry point using the same unsnapped OCR geometry."""
    _,height,angle=_quad_frame(quad)
    return height,angle


def ocr_font_size(text,quad):
    return ocr_layout(text,quad)['font_size_px']


def ocr_layout(text,quad,source_image=None):
    """One persisted pixel-space layout used by UI, hit testing, snapshots and exports."""
    # Corner order encodes the reading baseline. A long first edge is a
    # rotated horizontal line, even when its axis is almost vertical.
    _quad_frame(quad)  # Validate before reading coordinates below.
    top=math.dist(quad[0],quad[1]);side=math.dist(quad[0],quad[3])
    tilt=math.degrees(math.atan2(quad[1][1]-quad[0][1],quad[1][0]-quad[0][0]))
    if len(text.strip())>1 and sum(0x2e80<=ord(ch)<=0x9fff for ch in text)/len(text)>.5 and side>top*1.8 and abs(tilt)<20:
        return _vertical_layout(text,quad,source_image)
    if source_image is not None:
        from mapvector.geometry.text_ink import source_ink_layout
        found=source_ink_layout(text,quad,source_image)
        if found is not None:return found
    width,height,angle=_quad_frame(quad)
    font,family=layout_font()
    top,bottom=font.getbbox(text or ' ',anchor='ls')[1::2]
    ink=max(1,bottom-top)
    # Font units use the measured ink height, not a guessed 0.8 multiplier.
    advance=max(1,font.getlength(text or ' '))
    size=min(height*.8,width*1024/advance)
    offset=-(top+bottom)*size/1024/2
    x=sum(p[0] for p in quad)/4;y=sum(p[1] for p in quad)/4
    runs=[]
    from mapvector.geometry.text_ink import _char
    if any(_char(ch)[1]!='normal' for ch in text):
        decoded=[_char(ch) for ch in text]
        metrics=[]
        for glyph,script in decoded:
            ratio=.7 if script!='normal' else 1.
            shift=.2 if script=='subscript' else -.4 if script=='superscript' else 0.
            glyph_top,glyph_bottom=font.getbbox(glyph,anchor='ls')[1::2]
            metrics.append((font.getlength(glyph)*ratio,glyph_top*ratio+shift*1024,glyph_bottom*ratio+shift*1024,ratio,shift))
        advance=sum(m[0] for m in metrics);top=min(m[1] for m in metrics);bottom=max(m[2] for m in metrics)
        size=min(height*.8,height*1024/max(1,bottom-top),width*1024/max(1,advance))
        ink=bottom-top;offset=-(top+bottom)*size/2048;pos=-advance*size/2048
        for index,((glyph,script),metric) in enumerate(zip(decoded,metrics)):
            run_width=metric[0]*size/1024
            runs.append({'text':glyph,'script':script,'font_size_px':size*metric[3],'x_offset_px':pos,'baseline_offset_px':offset+metric[4]*size,'width_px':run_width,'source_index':index,'basis':'unicode_unverified','review_required':script!='normal'})
            pos+=run_width
    return {'x':x,'y':y,'font_size_px':size,'rotation_deg':angle,'font_family':family,'layout_width_px':advance*size/1024,'layout_height_px':ink*size/1024,'baseline_offset_px':offset,'layout_basis':'ocr_quad_v2','layout_runs':runs}


def _vertical_layout(text,quad,source_image):
    font,family=layout_font();chars=[(i,ch) for i,ch in enumerate(text) if not ch.isspace()]
    width=(math.dist(quad[0],quad[1])+math.dist(quad[2],quad[3]))/2
    height=(math.dist(quad[0],quad[3])+math.dist(quad[1],quad[2]))/2
    angle=-math.degrees(math.atan2(quad[1][1]-quad[0][1],quad[1][0]-quad[0][0]))
    cell=height/len(chars);boxes=[];basis='ocr_vertical_v1'
    if source_image is not None:
        import numpy as np
        from scipy import ndimage
        from PIL import Image
        scale=4
        pixels=np.asarray(source_image.convert('RGB').transform((max(2,round(width*scale)),max(2,round(height*scale))),Image.Transform.QUAD,tuple(v for i in (0,3,2,1) for v in quad[i]),resample=Image.Resampling.BICUBIC)).astype(float)
        gray=pixels@np.array([.299,.587,.114]);mask=(pixels.max(2)<178)&(pixels.max(2)-pixels.min(2)<48)
        for number,(index,ch) in enumerate(chars):
            lo=round(number*cell*scale);hi=round((number+1)*cell*scale)
            local=mask[lo:hi];labels,count=ndimage.label(local);components=[]
            for label,section in enumerate(ndimage.find_objects(labels),1):
                if section is None:continue
                sy,sx=section;area=int((labels[section]==label).sum())
                if area<max(4,scale*scale*.2) or sx.stop-sx.start>width*scale*.9 or sy.stop-sy.start>cell*scale*.9:continue
                components.append((area,sx.start,sx.stop,sy.start+lo,sy.stop+lo))
            if not components:break
            cutoff=max(4,max(c[0] for c in components)*.025);components=[c for c in components if c[0]>=cutoff]
            x0=min(c[1] for c in components)/scale;x1=max(c[2] for c in components)/scale
            y0=min(c[3] for c in components)/scale;y1=max(c[4] for c in components)/scale
            if min(x1-x0,y1-y0)<2 or x1-x0>cell*1.6:break
            boxes.append((index,ch,x0,y0,x1,y1))
        if len(boxes)==len(chars):basis='ocr_vertical_ink_v2'
        else:boxes=[]
    if not boxes:
        size=min(width*.9,cell*.85)
        for number,(index,ch) in enumerate(chars):
            top,bottom=font.getbbox(ch,anchor='ls')[1::2];advance=font.getlength(ch)*size/1024;h=(bottom-top)*size/1024
            boxes.append((index,ch,(width-advance)/2,cell*(number+.5)-h/2,(width+advance)/2,cell*(number+.5)+h/2))
    x0=min(b[2] for b in boxes);y0=min(b[3] for b in boxes);x1=max(b[4] for b in boxes);y1=max(b[5] for b in boxes)
    center_u=(x0+x1)/2;center_v=(y0+y1)/2;runs=[]
    for index,ch,left,top,right,bottom in boxes:
        glyph_top,glyph_bottom=font.getbbox(ch,anchor='ls')[1::2]
        size=(bottom-top)*1024/max(1,glyph_bottom-glyph_top)
        runs.append({'text':ch,'script':'normal','font_size_px':size,'x_offset_px':left-center_u,'baseline_offset_px':top-center_v-glyph_top*size/1024,'width_px':right-left,'source_index':index,'basis':'source_ink_vertical' if basis=='ocr_vertical_ink_v2' else 'vertical_quad','review_required':False})
    u=center_u/width;v=center_v/height;p0,p1,p2,p3=quad
    x=(1-u)*(1-v)*p0[0]+u*(1-v)*p1[0]+u*v*p2[0]+(1-u)*v*p3[0]
    y=(1-u)*(1-v)*p0[1]+u*(1-v)*p1[1]+u*v*p2[1]+(1-u)*v*p3[1]
    return {'x':x,'y':y,'font_size_px':sum(r['font_size_px'] for r in runs)/len(runs),'rotation_deg':angle,'font_family':family,'layout_width_px':x1-x0,'layout_height_px':y1-y0,'baseline_offset_px':0.,'layout_basis':basis,'layout_runs':runs}


from functools import lru_cache
@lru_cache(maxsize=1)
def layout_font():
    from PIL import ImageFont
    for name in ('msyh.ttc','NotoSansCJK-Regular.ttc','DejaVuSans.ttf','arial.ttf'):
        try:
            font=ImageFont.truetype(name,1024)
            return font,font.getname()[0]
        except OSError:continue
    raise ValueError('No measurable text font is available')


def layout_bbox(x,y,width,height,rotation):
    a=math.radians(rotation);c,s=abs(math.cos(a)),abs(math.sin(a))
    hw=(width*c+height*s)/2;hh=(width*s+height*c)/2
    return [x-hw,y-hh,x+hw,y+hh]


def half_extent(text,font_size_px):
    em=sum(1.0 if 0x2E80<=ord(char)<=0x9FFF or 0x3000<=ord(char)<=0x303F or 0xFF00<=ord(char)<=0xFFEF else .58 for char in str(text or ''))
    half_height=font_size_px/.8/2
    return max(half_height,font_size_px*em/2),half_height


def display_bbox(x,y,text,font_size_px,rotation_deg):
    width,height=half_extent(text,font_size_px)
    angle=math.radians(rotation_deg)
    c,s=abs(math.cos(angle)),abs(math.sin(angle))
    hw,hh=width*c+height*s,width*s+height*c
    return [x-hw,y-hh,x+hw,y+hh]


def hit_text(feature,x,y,padding=2):
    anchor=feature['geometry']['coordinates'];dx,dy=x-anchor[0],y-anchor[1]
    angle=math.radians(feature['rotation_deg'])
    local_x=dx*math.cos(angle)-dy*math.sin(angle)
    local_y=dx*math.sin(angle)+dy*math.cos(angle)
    width,height=(feature['layout_width_px']/2,feature['layout_height_px']/2) if feature.get('layout_width_px') and feature.get('layout_height_px') else half_extent(feature['text_value'],feature['font_size_px'])
    return abs(local_x)<=width+padding and abs(local_y)<=height+padding
