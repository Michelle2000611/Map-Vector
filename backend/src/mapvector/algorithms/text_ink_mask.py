"""Suppress supported glyph ink in derived input, preserving map features."""
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import Polygon, box


def _line_evidence(component):
    """Direction-independent protection for straight or simple curved strokes."""
    points=np.argwhere(component)
    if len(points)<12:return False
    eigen=np.linalg.eigvalsh(np.cov(points.T))
    if eigen[-1]/max(.1,eigen[0])>=64:return True
    from skimage.morphology import skeletonize
    skeleton=skeletonize(component)
    points={tuple(p) for p in np.argwhere(skeleton)}
    degrees=[]
    for y,x in points:
        degrees.append(sum((y+dy,x+dx) in points and not(dx and dy and ((y,x+dx) in points or (y+dy,x) in points)) for dy in (-1,0,1) for dx in (-1,0,1) if dx or dy))
    return len(points)>=15 and sum(d==1 for d in degrees)==2 and not any(d>2 for d in degrees)


def suppress_text_ink(rgb, candidates):
    values = rgb.astype(np.int16)
    chroma = values.max(2) - values.min(2)
    # Gray printing and antialiased dark cores must both seed the component.
    ink = (values.max(2) < 195) & (chroma < 60)
    labels, _ = ndimage.label(ink, np.ones((3, 3)))
    objects = ndimage.find_objects(labels)
    erase = np.zeros(ink.shape, bool)
    protected = np.zeros(ink.shape, bool)
    source_excluded = np.zeros(ink.shape, bool)
    for candidate in candidates:
        if candidate.get('score', 0) < .85:
            continue
        quad = candidate.get('detected_quad_px')
        if not quad or len(quad) != 4:
            continue
        region = Polygon(quad)
        if not region.is_valid or region.area <= 0:
            continue
        region = region.buffer(1)
        x0, y0, x1, y1 = region.bounds
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(rgb.shape[1], int(x1) + 1), min(rgb.shape[0], int(y1) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        permitted = Image.new('1', (x1-x0, y1-y0))
        ImageDraw.Draw(permitted).polygon([(x-x0, y-y0) for x, y in region.exterior.coords], fill=1)
        selected = np.zeros((y1-y0, x1-x0), bool)
        for label in np.unique(labels[y0:y1, x0:x1]):
            if not label:
                continue
            ys, xs = objects[label-1]
            h, w = ys.stop-ys.start, xs.stop-xs.start
            component = labels[ys, xs] == label
            crossing = not region.covers(box(xs.start, ys.start, xs.stop, ys.stop))
            straight = _line_evidence(component)
            if crossing or straight or h*w > region.area*.85:
                protected[ys, xs] |= component
                continue
            selected |= labels[y0:y1, x0:x1] == label
        if not selected.any():
            continue
        permitted = np.asarray(permitted, dtype=bool)
        # Derive the glyph fringe from the local paper/fill color, not a global
        # chroma cutoff: black ink blended into brown geology is itself colored.
        halo = ndimage.binary_dilation(ndimage.binary_fill_holes(selected), iterations=3)
        protected_local = ndimage.binary_dilation(protected[y0:y1, x0:x1], iterations=3)
        local = values[y0:y1, x0:x1].astype(float)
        samples = local[permitted & ~halo & ~protected_local & ~ink[y0:y1, x0:x1]]
        if len(samples) < 8:
            continue
        bins, counts = np.unique((samples // 12).astype(int), axis=0, return_counts=True)
        dominant = bins[counts.argmax()]
        background = np.median(samples[np.all((samples // 12).astype(int) == dominant, axis=1)], axis=0)
        if np.count_nonzero(np.linalg.norm(samples - background, axis=1) > 30) >= max(8, .2 * len(samples)):
            # A second geological fill is substantial: there is no supported
            # single background behind this glyph. Preserve the whole evidence
            # region, including against overlapping candidates, for manual review.
            protected[y0:y1, x0:x1] |= permitted
            continue
        foreground = np.median(local[selected], axis=0)
        direction = background - foreground
        fraction = np.sum((local - foreground) * direction, axis=2) / max(1., float(direction @ direction))
        residual = np.linalg.norm(local - (foreground + fraction[..., None] * direction), axis=2)
        compatible = (fraction >= -.15) & (fraction <= 1.15) & (residual <= 16)
        near_background = np.linalg.norm(local - background, axis=2) <= 12
        # Independent colored faces/lines inside counters or next to a glyph
        # retain their own pixels and antialias support, even within the OCR box.
        protected[y0:y1, x0:x1] |= permitted & ~selected & ~compatible & ~near_background
        erase[y0:y1, x0:x1] |= halo & (compatible | selected) & permitted
        source_excluded[y0:y1, x0:x1] |= permitted & ~near_background
    # Protect complete line support, including light antialias pixels, and never
    # copy a protected dark stroke into a nearby glyph's replacement background.
    # Light fringe can extend beyond the ink threshold. Do not turn that
    # extension into an arbitrary keep-zone for a separate neutral glyph core.
    protected |= ndimage.binary_dilation(protected, iterations=3) & ~ink
    erase &= ~protected
    if not erase.any():
        return rgb, 0
    source_excluded |= erase | protected | ink
    if source_excluded.all():
        return rgb, 0
    _, indices = ndimage.distance_transform_edt(source_excluded, return_indices=True)
    output = rgb.copy()
    output[erase] = rgb[indices[0][erase], indices[1][erase]]
    return output, int(erase.sum())
