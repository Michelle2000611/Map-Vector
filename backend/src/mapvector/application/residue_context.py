"""Request-scoped materialization for shared residue consumers. Never process-global geometry."""
from types import SimpleNamespace
from shapely.geometry import shape

def materialize(connection,project_id,asset_id,revision,with_raster=True,*,text_feature_ids=None):
    from mapvector.application.line_checks import snapshot,_raster_image
    from mapvector.geometry.line_checks import _pattern
    from mapvector.geometry.text_residue import scan_text_strokes
    source=snapshot(connection,project_id,asset_id,revision,**({'text_feature_ids':text_feature_ids} if text_feature_ids is not None else {}))
    geometries=[shape(line['geometry']) for line in source['lines']]
    patterns=[_pattern(line,source) for line in source['lines']]
    image=_raster_image(source) if with_raster else None
    patches={}
    try:
        proposals=scan_text_strokes(source,SimpleNamespace(max_short_length_px=12,max_gap_px=8),image,source['lines'],geometries,patterns,set(),text_feature_ids=text_feature_ids)
        if image is not None and text_feature_ids is not None:
            import math
            import numpy as np
            from mapvector.geometry.text_residue import text_residue_regions
            wanted=set(text_feature_ids)
            for entry in text_residue_regions([text for text in source['texts'] if text['feature_id'] in wanted]):
                x0,y0,x1,y1=entry['geometry'].bounds
                bounds=(max(0,math.floor(x0)),max(0,math.floor(y0)),min(image.width,math.ceil(x1)),min(image.height,math.ceil(y1)))
                width,height=bounds[2]-bounds[0],bounds[3]-bounds[1]
                if width>0 and height>0 and width*height<=262144:
                    patches[entry['text']['feature_id']]=np.asarray(image.crop(bounds).convert('RGB'))
    finally:
        if image is not None:image.close()
    by_text={}
    for proposal in proposals:
        for tid in proposal['texts']:by_text.setdefault(tid,[]).append(proposal)
    return {'project_id':project_id,'asset_id':asset_id,'revision':revision,'with_raster':with_raster,'text_feature_ids':None if text_feature_ids is None else frozenset(text_feature_ids),'source':source,'raster_patches':patches,'geometries':geometries,'proposals':proposals,'by_text':by_text}

def checked(context,project_id,asset_id,revision,with_raster,text_feature_ids=None):
    # Callers may reuse only inside the same coherent read transaction.
    if (context['project_id'],context['asset_id'],context['revision'],context['with_raster'])!=(project_id,asset_id,revision,with_raster):
        raise ValueError('Residue context scope mismatch')
    scope=context.get('text_feature_ids')
    if scope is not None and (text_feature_ids is None or not set(text_feature_ids)<=scope):
        raise ValueError('Residue context text scope mismatch')
    return context


def raster_binding(connection,project_id,asset_id):
    """Read the actual source identity, including unavailable/mismatched states."""
    from mapvector.application.line_checks import _raster_source
    row=connection.execute('SELECT asset_id,project_id,raster_rel_path,raster_sha256 FROM asset WHERE project_id=? AND asset_id=?',(project_id,asset_id)).fetchone()
    if row is None:raise KeyError(asset_id)
    source,_=_raster_source(connection,dict(row))
    return source

def validate_raster_binding(connection,project_id,asset_id,stored):
    from mapvector.domain.errors import CommandConflict
    expected=stored.get('residue_raster_source')
    if expected is None or raster_binding(connection,project_id,asset_id)!=expected:raise CommandConflict('PREVIEW_STALE')
