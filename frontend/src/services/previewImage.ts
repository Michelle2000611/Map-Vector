/** Capture the current SVG before asynchronous rasterization, with an opaque white crop. */
export async function previewImagePng(svg:SVGSVGElement):Promise<Blob>{
 const bounds=svg.getBoundingClientRect(),width=Math.max(2,Math.round(bounds.width)),height=Math.max(2,Math.round(bounds.height));
 const copy=svg.cloneNode(true) as SVGSVGElement;
 copy.setAttribute('xmlns','http://www.w3.org/2000/svg');
 copy.setAttribute('width',String(width-2));copy.setAttribute('height',String(height-2));
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
