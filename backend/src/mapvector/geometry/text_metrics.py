"""Natural font metrics shared by ink fitting and persisted run bounds.

Pillow's getbbox can include advance padding. The alpha mask supplies the actual
ink bearing, while getlength remains the advance used by an ordinary renderer.
All measurements here use the same 1024-unit font selected by layout_font.
"""
from functools import lru_cache


@lru_cache(maxsize=2048)
def font_metrics(text):
    from mapvector.geometry.text import layout_font
    font, _ = layout_font()
    mask, offset = font.getmask2(text or ' ', mode='L', anchor='ls')
    box = mask.getbbox()
    if box is None:
        box = (0, 0, 0, 0)
    else:
        box = tuple(box[i] + offset[i % 2] for i in range(4))
    return box, float(font.getlength(text or ' '))


def fit_run(text, box, *, source_index=0, script='normal', basis='source_ink',
            quality_reasons=()):
    """Fit one glyph/string isotropically into a source ink rectangle."""
    ink, advance = font_metrics(text)
    left, top, right, bottom = box
    size = min((right-left)*1024/max(1, ink[2]-ink[0]),
               (bottom-top)*1024/max(1, ink[3]-ink[1]))
    factor = size/1024
    # Center the natural ink in the measured rectangle; do not stretch its width.
    origin = (left+right-(ink[0]+ink[2])*factor)/2
    baseline = (top+bottom-(ink[1]+ink[3])*factor)/2
    return dict(text=text, script=script, font_size_px=size,
                x_offset_px=origin, baseline_offset_px=baseline,
                width_px=advance*factor, source_index=source_index, basis=basis,
                review_required=bool(quality_reasons),
                quality_reasons=list(quality_reasons),
                ink_bbox_px=[origin+ink[0]*factor, baseline+ink[1]*factor,
                             origin+ink[2]*factor, baseline+ink[3]*factor])


def center_runs(runs):
    """Center final rendered ink, returning its former center and its size."""
    boxes = [run['ink_bbox_px'] for run in runs]
    left = min(b[0] for b in boxes); top = min(b[1] for b in boxes)
    right = max(b[2] for b in boxes); bottom = max(b[3] for b in boxes)
    cx = (left+right)/2; cy = (top+bottom)/2
    for run in runs:
        run['x_offset_px'] -= cx
        run['baseline_offset_px'] -= cy
        run['ink_bbox_px'] = [value-(cx if i % 2 == 0 else cy)
                              for i, value in enumerate(run['ink_bbox_px'])]
    return cx, cy, right-left, bottom-top
