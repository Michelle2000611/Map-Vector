import {useRef,useState} from 'react';
import type {RefObject} from 'react';
import {Button} from 'antd';
import {feedback} from '../services/feedback';
import {previewImagePng} from '../services/previewImage';

export function PreviewImageCopyButton({svgRef}:{svgRef:RefObject<SVGSVGElement>}){
 const pending=useRef(false),[copying,setCopying]=useState(false);
 async function copyImage(){
  const svg=svgRef.current;
  if(pending.current||!svg)return;
  if(!navigator.clipboard?.write||typeof ClipboardItem==='undefined'){feedback.error('当前浏览器不支持复制图像。');return;}
  pending.current=true;setCopying(true);
  try{
   svg.setAttribute('font-family',getComputedStyle(svg).fontFamily);
   // Snapshot immediately; the PNG promise keeps this view if layers or selection change.
   await navigator.clipboard.write([new ClipboardItem({'image/png':previewImagePng(svg)})]);
   feedback.success('图像已复制。');
  }catch{feedback.error('复制图像失败，请允许剪贴板访问后重试。');}
  finally{pending.current=false;setCopying(false);}
 }
 return <Button loading={copying} disabled={copying} onClick={()=>void copyImage()}>复制图像</Button>;
}
