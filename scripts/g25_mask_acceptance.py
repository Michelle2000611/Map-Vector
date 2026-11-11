"""Compare the reviewed mask fix against immutable real-source pixels."""
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Polygon

from mapvector.algorithms.text_ink_mask import suppress_text_ink


root = Path(__file__).resolve().parents[1]
directory = root/'runtime/n9-gis/mask-real'
directory.mkdir(parents=True, exist_ok=True)
source = root/'runtime/n9-joint/real/input.png'
rgb = np.asarray(Image.open(source).convert('RGB'))
candidates = json.loads((source.parent/'ocr_candidates.json').read_text(encoding='utf-8'))['items']
spec = importlib.util.spec_from_file_location('mask_before_review', root/'runtime/remediation-20261109/mask-review-before/text_ink_mask.py')
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
previous, previous_count = old.suppress_text_ink(rgb, candidates)
result, count = suppress_text_ink(rgb, candidates)
Image.fromarray(result).save(directory/'suppressed.png')
permitted = Image.new('1', (rgb.shape[1], rgb.shape[0]))
draw = ImageDraw.Draw(permitted)
for candidate in candidates:
    if candidate.get('score', 0) < .85:
        continue
    polygon = Polygon(candidate['detected_quad_px'])
    if polygon.is_valid and polygon.area > 0:
        draw.polygon(list(polygon.buffer(1).exterior.coords), fill=1)
outside_changes = int(np.count_nonzero(np.any(result != rgb, axis=2) & ~np.asarray(permitted, dtype=bool)))
assert outside_changes == 0
evidence = {'previous_erase_mask_pixels': previous_count, 'current_erase_mask_pixels': count,
            'outside_ocr_evidence_changes': outside_changes, 'beta_q': []}
for index, candidate in enumerate(c for c in candidates if c['raw_text'] == '\u03b2Q'):
    quad = np.asarray(candidate['detected_quad_px'])
    x0, y0 = np.floor(quad.min(0)).astype(int)
    x1, y1 = np.ceil(quad.max(0)).astype(int)
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    samples = rgb[y0:y1, x0:x1].reshape(-1, 3)
    colors, counts = np.unique(samples, axis=0, return_counts=True)
    background = colors[counts.argmax()].astype(int)
    details = {'quad': candidate['detected_quad_px'], 'modal_background_rgb': background.tolist()}
    for label, array in [('source', rgb), ('previous', previous), ('current', result)]:
        crop = array[y0:y1, x0:x1].astype(int)
        details[label+'_pixels_over_12_from_background'] = int(np.count_nonzero(np.max(np.abs(crop-background), axis=2) > 12))
        details[label+'_max_background_deviation'] = int(np.max(np.abs(crop-background)))
    crops = [Image.fromarray(array[max(0,y0-8):y1+8, max(0,x0-8):x1+8]).resize(((x1-x0+16)*5, (y1-y0+16)*5)) for array in (rgb, previous, result)]
    comparison = Image.new('RGB', (sum(c.width for c in crops), crops[0].height))
    x = 0
    for crop in crops:
        comparison.paste(crop, (x, 0)); x += crop.width
    path = directory/f'beta-q-{index}-source-previous-current.png'
    comparison.save(path)
    details['comparison'] = str(path)
    evidence['beta_q'].append(details)
(directory/'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(evidence, ensure_ascii=False, indent=2))
