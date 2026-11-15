"""Colour-class merge protection for thin bands against a large adjacent face.

Not part of the frozen B2c baseline (see source_manifest.json) -- this module wraps
sv_d71.colour_classes without modifying it, so the frozen hashes stay intact while the
merge rule gains a scale-free, shape-aware exception for genuine thin strips (e.g. a
river band) that would otherwise be swallowed into a neighbouring large face purely
because their quantized colours are close in CIE76 dE terms.
"""
import numpy as np
from scipy import ndimage as ndi
from skimage.morphology import skeletonize

from .sv_d71 import pal_lab, S4

AREA_SHARE_MAX = 0.01
ELONG_MIN = 6.0
THIN_BAND_DE = 2.0


def thin_band_labels(lab, used, area_share_max=AREA_SHARE_MAX, elong_min=ELONG_MIN):
    """Labels whose pixels form a small-area, elongated band (a thin strip, not scattered
    noise). Scattered anti-aliasing noise of the same area share is compact (low elongation);
    a real thin strip's connected pixels are long and narrow. Area share uses the label image,
    not the full image, so this is scale-free across crops."""
    total = lab.size; thin = set()
    for u in used:
        mask = lab == u; count = int(mask.sum())
        if count == 0 or count / total > area_share_max: continue
        comp, n = ndi.label(mask, S4)
        if n == 0: continue
        sizes = np.bincount(comp.ravel())[1:]; largest = int(np.argmax(sizes)) + 1
        skeleton = skeletonize(comp == largest); skel_len = int(skeleton.sum())
        width = sizes[largest - 1] / max(skel_len, 1)
        elong = skel_len / max(width, 1e-9)
        if skel_len >= 4 and elong >= elong_min: thin.add(u)
    return thin


def colour_classes_protecting_thin_bands(lab, pal, dE, thin_band_dE=THIN_BAND_DE):
    """Same contract and return shape as sv_d71.colour_classes, but a label flagged by
    thin_band_labels only merges with a neighbour under the stricter thin_band_dE instead
    of the general dE. Ordinary same-colour noise of any shape still merges under dE exactly
    as the frozen colour_classes would."""
    used = [int(u) for u in np.unique(lab)]; PL = pal_lab(pal); parent = {u: u for u in used}
    thin = thin_band_labels(lab, used)
    def f(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in used:
        for j in used:
            if i < j:
                limit = thin_band_dE if (i in thin or j in thin) else dE
                if np.linalg.norm(PL[i] - PL[j]) < limit: parent[f(j)] = f(i)
    roots = sorted({f(u) for u in used}); rid = {r: k for k, r in enumerate(roots)}
    lut = np.full(len(pal), -1, np.int32)
    for u in used: lut[u] = rid[f(u)]
    cnt = np.bincount(lab.ravel(), minlength=len(pal)).astype(np.float64)
    cent = np.zeros((len(roots), 3))
    for k in range(len(roots)):
        m = lut == k; cent[k] = (cnt[m, None] * PL[m]).sum(0) / cnt[m].sum()
    return lut[lab], lut, cent
