"""Pixel-edge valid regions shared by recognition, quality and exchange."""
import numpy as np
from PIL import Image
from shapely.geometry import box,shape
from shapely import union_all


def valid_region(path):
    with Image.open(path) as image:
        if 'A' not in image.getbands():return box(0,0,image.width,image.height)
        valid=np.asarray(image.getchannel('A'))>0
        if valid.all():return box(0,0,image.width,image.height)
    from rasterio.features import shapes
    return union_all([shape(g) for g,value in shapes(valid.astype(np.uint8),mask=valid) if value])


def white_rgb(image):
    return Image.alpha_composite(Image.new('RGBA',image.size,'white'),image.convert('RGBA')).convert('RGB')
