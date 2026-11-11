import io
import math
import warnings
from pathlib import Path

import numpy as np
from PIL import Image,ImageOps

from mapvector.domain.errors import CommandConflict

MAX_PIXELS = 120_000_000
MAX_BYTES = 500 * 1024 * 1024


def sniff(data: bytes) -> str:
    if data.startswith(b'%PDF-'):
        return 'PDF'
    if data[:4] in (bytes((73,73,42,0)),bytes((77,77,0,42)),bytes((73,73,43,0)),bytes((77,77,0,43))):
        return 'TIFF'
    if data.startswith(bytes((137,80,78,71,13,10,26,10))):
        return 'PNG'
    if data.startswith(bytes((255,216,255))):
        return 'JPEG'
    if data[:2]==b'BM':
        return 'BMP'
    if data[:4]==b'RIFF' and data[8:12]==b'WEBP':
        return 'WEBP'
    if data[:4]==bytes((255,79,255,81)) or data[:12]==bytes((0,0,0,12,106,80,32,32,13,10,135,10)):
        return 'JP2'
    raise CommandConflict('SOURCE_DECODE_FAILED', {'reason':'Unrecognized file signature'})


def check_pixels(width, height):
    if width<=0 or height<=0 or width*height>MAX_PIXELS:
        raise CommandConflict('SOURCE_PIXEL_LIMIT', {'width_px':width,'height_px':height,'max_pixels':MAX_PIXELS})


def probe(data: bytes):
    kind=sniff(data)
    try:
        if kind=='PDF':
            import pypdfium2 as pdfium
            pdf=pdfium.PdfDocument(data)
            try:
                pages=[]
                for index in range(len(pdf)):
                    page=pdf[index]
                    try:
                        width,height=page.get_size()
                        pages.append({'page_index':index,'width_pt':width,'height_pt':height})
                    finally:
                        page.close()
            finally:
                pdf.close()
        else:
            with Image.open(io.BytesIO(data)) as image:
                pages=[]
                for index in range(getattr(image,'n_frames',1)):
                    image.seek(index)
                    check_pixels(image.width,image.height)
                    pages.append({'page_index':index,'width_px':image.width,'height_px':image.height})
                    image.load()
        if not pages:
            raise ValueError('Source has no pages')
        return kind,pages
    except CommandConflict:
        raise
    except Exception as exc:
        raise CommandConflict('SOURCE_DECODE_FAILED',{'source_type':kind,'reason':str(exc)}) from exc


def decode(path: Path, kind: str, page_index: int, dpi: float):
    crs=affine=None
    decoder='pillow'
    details={}
    try:
        if kind=='PDF':
            if not 36<=dpi<=600:
                raise CommandConflict('NORMALIZATION_CONFIG_INVALID',{'dpi_range':[36,600]})
            import pypdfium2 as pdfium
            pdf=pdfium.PdfDocument(str(path))
            try:
                page=pdf[page_index]
                try:
                    width,height=page.get_size()
                    check_pixels(math.ceil(width*dpi/72),math.ceil(height*dpi/72))
                    bitmap=page.render(scale=dpi/72)
                    try:
                        image=bitmap.to_pil().convert('RGB').copy()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            finally:
                pdf.close()
            decoder='pdfium'
        elif kind in ('TIFF','JP2'):
            import rasterio
            from rasterio.errors import NotGeoreferencedWarning
            dataset=str(path) if page_index==0 else f'GTIFF_DIR:{page_index+1}:{path}'
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', NotGeoreferencedWarning)
                with rasterio.open(dataset) as source:
                    check_pixels(source.width,source.height)
                    from rasterio.enums import ColorInterp
                    mask=source.dataset_mask()>0
                    if ColorInterp.palette in source.colorinterp:
                        indices=source.read(1);palette=source.colormap(1)
                        lut=np.zeros((max(palette)+1,4),np.uint8)
                        for index,rgba in palette.items():lut[index]=rgba
                        rgba=lut[indices]
                        image=Image.fromarray(rgba,'RGBA')
                        mask&=rgba[:,:,3]>0
                        details['palette_expanded']=True
                    else:
                        rgb=[source.colorinterp.index(channel)+1 for channel in (ColorInterp.red,ColorInterp.green,ColorInterp.blue)] if all(channel in source.colorinterp for channel in (ColorInterp.red,ColorInterp.green,ColorInterp.blue)) else None
                        indexes=rgb or ([1] if source.count<=2 else [1,2,3])
                        bands=source.read(indexes)
                        if len(bands)==1:bands=np.repeat(bands,3,axis=0)
                        pixels=np.moveaxis(bands,0,-1)
                        mask&=np.isfinite(pixels).all(axis=2)
                        if pixels.dtype!=np.uint8:
                            values=pixels[mask].astype(np.float64)
                            lo,hi=np.nanpercentile(values,(.5,99.5)) if values.size else (0,1)
                            pixels=np.nan_to_num(np.clip((pixels.astype(float)-lo)/max(hi-lo,1e-9)*255,0,255)).astype(np.uint8)
                            details['display_stretch']={'percentiles':[.5,99.5],'minimum':float(lo),'maximum':float(hi)}
                        image=Image.fromarray(pixels)
                        details['display_bands']=indexes
                        if ColorInterp.alpha in source.colorinterp:
                            alpha=source.read(source.colorinterp.index(ColorInterp.alpha)+1)
                            image=image.convert('RGBA');image.putalpha(Image.fromarray(alpha.astype(np.uint8)))
                    image=display_image(image,mask,details)
                    if source.crs and not source.transform.is_identity:
                        crs=source.crs.to_wkt();affine=list(source.transform)[:6]
                        if not all(math.isfinite(value) for value in affine) or abs(affine[0]*affine[4]-affine[1]*affine[3])==0:
                            raise ValueError('Invalid georeferencing affine')
            decoder='rasterio'
        else:
            with Image.open(path) as source:
                source.seek(page_index)
                check_pixels(source.width,source.height)
                orientation=source.getexif().get(274,1)
                image=ImageOps.exif_transpose(source)
                details.update(exif_orientation_applied=orientation,original_width_px=source.width,original_height_px=source.height)
                image=display_image(image,None,details)
        check_pixels(image.width,image.height)
        normalization={'dpi':dpi,'decoder':decoder,'source_format':kind,'resampling':'none' if kind!='PDF' else 'pdf_render','color_mode':image.mode,**details}
        if crs and affine:
            normalization['pixel_convention']='pixel edge origin; center=(col+0.5,row+0.5)'
        return image,crs,affine,normalization
    except CommandConflict:
        raise
    except Exception as exc:
        raise CommandConflict('SOURCE_DECODE_FAILED',{'source_type':kind,'page_index':page_index,'reason':str(exc)}) from exc


def display_image(image,valid,details):
    """White display background, with binary alpha carrying the immutable valid region."""
    alpha=np.asarray(image.convert('RGBA'))[:,:,3]
    valid=(alpha>0) if valid is None else valid&(alpha>0)
    background=Image.new('RGBA',image.size,'white')
    rgb=Image.alpha_composite(background,image.convert('RGBA')).convert('RGB')
    details.update(invalid_pixel_count=int((~valid).sum()),alpha_policy='white_composite_with_validity')
    if not valid.all():
        rgb=rgb.convert('RGBA');rgb.putalpha(Image.fromarray(valid.astype(np.uint8)*255))
    return rgb
