"""Relative typography transformations; snapshots never contain source placement."""
import math
from copy import deepcopy

from mapvector.application.ports import load_feature
from mapvector.domain.commands import text_format_glyph
from mapvector.domain.errors import CommandConflict
from mapvector.geometry.text import display_bbox, layout_bbox, layout_font
from mapvector.geometry.text_metrics import font_metrics

LAYOUT_FIELDS=('layout_runs','layout_width_px','layout_height_px','baseline_offset_px','layout_basis')
TEXT_STYLE_FIELDS=('font_size_px','text_color','rotation_deg')


def normalized_rotation(rotation):
    return rotation if -180<=rotation<180 else (rotation+180)%360-180


def scale_layout(feature,size):
    """Scale every relative measure together, keeping scripts and their evidence."""
    ratio=size/feature['font_size_px']
    result={field:deepcopy(feature.get(field)) for field in LAYOUT_FIELDS}
    result['layout_runs']=result['layout_runs'] or []
    for run in result['layout_runs']:
        for field in ('font_size_px','x_offset_px','baseline_offset_px','width_px'):
            run[field]*=ratio
        if run.get('ink_bbox_px') is not None:
            run['ink_bbox_px']=[value*ratio for value in run['ink_bbox_px']]
    for field in ('layout_width_px','layout_height_px','baseline_offset_px'):
        if result[field] is not None:result[field]*=ratio
    return result


def content_signature(feature):
    """Run boundaries and layout geometry do not change semantic script content."""
    runs=feature.get('layout_runs') or []
    if not runs:
        return tuple((glyph,script) for ch in feature['text_value'] if not ch.isspace() for glyph,script in [text_format_glyph(ch)])
    # OCR vertical runs omit whitespace; whitespace is already compared in text_value.
    return tuple((glyph,run['script'] if run['script']!='normal' else script)
                 for run in runs for ch in run['text'] if not ch.isspace()
                 for glyph,script in [text_format_glyph(ch)])


def record_style_override(old,new,fields):
    """Keep binding and only override explicitly edited appearance properties."""
    if old.get('style_id') and fields:
        new['style_override']={**(old.get('style_override') or {}),**{field:new[field] for field in fields}}


def copy_text_content(old,new,sample):
    """Copy script semantics and relative layout at the target's final size."""
    new.update(text_value=sample['text_value'],**scale_layout(sample,new['font_size_px']))
    new['layout_basis']=new['layout_basis'] or 'manual'
    if new['text_value']!=old['text_value'] or content_signature(new)!=content_signature(old):
        new.update(text_content_revision=old['text_content_revision']+1,review_status='manual_edited',
                   review_basis='manual_content_edit',reviewed_content_revision=None,reviewed_at=None,
                   reviewer_id=None,cleanup_status='not_checked')
    return new


def text_display_bbox(feature):
    """Bound actual structured placement around the unchanged feature anchor."""
    x,y=feature['geometry']['coordinates'];rotation=feature['rotation_deg']
    runs=feature.get('layout_runs') or []
    if runs:
        font,_=layout_font();corners=[]
        angle=math.radians(-rotation);c,s=math.cos(angle),math.sin(angle)
        for run in runs:
            if feature.get('layout_basis') in ('ocr_ink_v4','ocr_vertical_ink_v3'):
                bounds=run.get('ink_bbox_px')
                if bounds is None:
                    ink,_=font_metrics(run['text']);factor=run['font_size_px']/1024
                    bounds=[run['x_offset_px']+ink[0]*factor,run['baseline_offset_px']+ink[1]*factor,
                            run['x_offset_px']+ink[2]*factor,run['baseline_offset_px']+ink[3]*factor]
                left,top,right,bottom=bounds
            else:
                top,bottom=font.getbbox(run['text'],anchor='ls')[1::2]
                left=run['x_offset_px'];right=left+run['width_px']
                top=run['baseline_offset_px']+top*run['font_size_px']/1024
                bottom=run['baseline_offset_px']+bottom*run['font_size_px']/1024
            corners.extend((x+u*c-v*s,y+u*s+v*c) for u in (left,right) for v in (top,bottom))
        return [min(p[0] for p in corners),min(p[1] for p in corners),max(p[0] for p in corners),max(p[1] for p in corners)]
    width,height=feature.get('layout_width_px'),feature.get('layout_height_px')
    if width and height:return layout_bbox(x,y,width,height,rotation)
    return display_bbox(x,y,feature['text_value'],feature['font_size_px'],rotation)


def plan_changes(connection,project_id,command,timestamp):
    """Validate the entire selection before persistence by the command service."""
    changes=[];sample=command.sample.model_dump()
    for identity in command.feature_ids:
        row=connection.execute("SELECT feature_id FROM feature WHERE feature_id=? AND project_id=? AND asset_id=? AND feature_type='text' AND lifecycle_status='active'",(identity,project_id,command.asset_id)).fetchone()
        if row is None:raise CommandConflict('RESOURCE_NOT_FOUND')
        old=load_feature(connection,identity)
        size=sample['font_size_px'] if command.copy_size else old['font_size_px']
        new={**old,**scale_layout(old,size),
             'font_size_px':size,'text_color':sample['text_color'] if command.copy_color else old['text_color'],
             'revision':command.base_revision+1,'updated_at':timestamp}
        if command.copy_rotation:new['rotation_deg']=normalized_rotation(sample['rotation_deg'])
        if command.copy_text:copy_text_content(old,new,sample)
        fields=[field for field,enabled in [('font_size_px',command.copy_size),('text_color',command.copy_color),('rotation_deg',command.copy_rotation)] if enabled]
        record_style_override(old,new,fields)
        new['display_bbox_px']=text_display_bbox(new)
        changes.append((old,new))
    return changes
