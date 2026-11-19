let measuredFontDataUrl:Promise<string>|undefined;

function previewFont():Promise<string>{
 if(!measuredFontDataUrl)measuredFontDataUrl=(async()=>{
  const response=await fetch('/api/text-layout/font');
  if(!response.ok)throw Error('文字字体加载失败');
  const font=await response.blob();
  return new Promise<string>((resolve,reject)=>{
   const reader=new FileReader();
   reader.onload=()=>resolve(String(reader.result));
   reader.onerror=()=>reject(Error('文字字体加载失败'));
   reader.readAsDataURL(font);
  });
 })().catch(error=>{measuredFontDataUrl=undefined;throw error;});
 return measuredFontDataUrl;
}

/** Capture the current SVG before asynchronous rasterization, with an opaque white crop. */
export async function previewImagePng(svg:SVGSVGElement):Promise<Blob>{
 const bounds=svg.getBoundingClientRect(),width=Math.max(2,Math.round(bounds.width)),height=Math.max(2,Math.round(bounds.height));
 const copy=svg.cloneNode(true) as SVGSVGElement;
 copy.setAttribute('xmlns','http://www.w3.org/2000/svg');
 copy.setAttribute('width',String(width-2));copy.setAttribute('height',String(height-2));
 if(Array.from(copy.querySelectorAll('[font-family]')).some(node=>node.getAttribute('font-family')?.includes('"MapVector OCR"'))){
  // An SVG image cannot inherit the page's @font-face or load its external URL.
  // Embed the same measured bytes in this already captured selection.
  const font=await previewFont(),style=document.createElementNS('http://www.w3.org/2000/svg','style');
  style.textContent='@font-face{font-family:"MapVector OCR";src:url("'+font+'");font-weight:400;font-style:normal}';
  copy.prepend(style);
 }
 const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml;charset=utf-8'}));
 try{
  const image=new Image();
  await new Promise<void>((resolve,reject)=>{image.onload=()=>resolve();image.onerror=()=>reject(Error('预览图像生成失败'));image.src=url;});
  const canvas=document.createElement('canvas'),scale=3;
  canvas.width=width*scale;canvas.height=height*scale;
  const context=canvas.getContext('2d');if(!context)throw Error('预览图像生成失败');
  context.scale(scale,scale);context.fillStyle='#fff';context.fillRect(0,0,width,height);
  context.drawImage(image,1,1,width-2,height-2);
  context.strokeStyle='#000';context.lineWidth=1;context.strokeRect(.5,.5,width-1,height-1);
  return await new Promise<Blob>((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(Error('预览图像生成失败')),'image/png'));
 }finally{URL.revokeObjectURL(url);}
}
