import {memo,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {Checkbox} from 'antd';
import {geometryPath,TextGlyph} from './FeatureGlyph';
import {LineGlyph} from './LineGlyph';
import type {Feature,Style} from '../services/models';
import {PreviewImageCopyButton} from './PreviewImageCopyButton';

const LIMIT=200;

export const FeaturePreview=memo(function FeaturePreview({features,styles,color,width}:{features:Feature[];styles:Style[];color?:string;width?:number}){
 const svg=useRef<SVGSVGElement>(null),glyphs=useRef<SVGGElement>(null);
 const [outline,setOutline]=useState(false);
 const shown=useMemo(()=>features.slice(0,LIMIT),[features]);
 const [textBounds,setTextBounds]=useState<{features:Feature[];viewBox:string;box:{x:number;y:number;width:number;height:number}}>();
 const facesOnly=shown.length>0&&shown.every(item=>item.feature_type==='face');
 const textsOnly=shown.length>0&&shown.every(item=>item.feature_type==='text');
 const library=useMemo(()=>new Map(styles.map(item=>[item.style_id,item])),[styles]);
 const geometryViewBox=useMemo(()=>{
  let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  const visit=(value:unknown):void=>{
   if(!Array.isArray(value))return;
   if(typeof value[0]==='number'){const [x,y]=value as number[];x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y);return;}
   value.forEach(visit);
  };
  shown.forEach(item=>visit(item.geometry.coordinates));
  if(!Number.isFinite(x0))return undefined;
  const pad=Math.max(x1-x0,y1-y0)*.06+2;
  return [x0-pad,y0-pad,x1-x0+pad*2,y1-y0+pad*2].join(' ');
 },[shown]);
 useLayoutEffect(()=>{
  if(!shown.some(item=>item.feature_type==='text'))return;
  // Preserve inherited app fonts when this SVG is serialized for the clipboard.
  if(svg.current)svg.current.setAttribute('font-family',getComputedStyle(svg.current).fontFamily);
  let active=true;
  const measure=()=>{
   if(!active||!glyphs.current)return;
   // The group bbox includes the text's real font, structured runs, and rotation.
   const bounds=glyphs.current.getBBox();
   if(![bounds.x,bounds.y,bounds.width,bounds.height].every(Number.isFinite))return;
   const pad=Math.max(bounds.width,bounds.height)*.06+2;
   const viewBox=[bounds.x-pad,bounds.y-pad,Math.max(1,bounds.width)+pad*2,Math.max(1,bounds.height)+pad*2].join(' ');
   const box={x:bounds.x,y:bounds.y,width:Math.max(1,bounds.width),height:Math.max(1,bounds.height)};
   setTextBounds(previous=>previous?.features===shown&&previous.viewBox===viewBox?previous:{features:shown,viewBox,box});
  };
  measure();
  void document.fonts.ready.then(measure);
  return ()=>{active=false;};
 },[shown]);
 const viewBox=textBounds?.features===shown?textBounds.viewBox:geometryViewBox;
 const textBox=textBounds?.features===shown?textBounds.box:undefined;
 if(!viewBox)return null;
 return <div className={'property-source-crop property-feature-preview'+(facesOnly?' property-face-preview':'')}>
  <svg ref={svg} viewBox={viewBox} preserveAspectRatio="xMidYMid meet" role="img" aria-label="所选对象外观预览">
   <g ref={glyphs}>
   {shown.map(item=>{
    const style=item.style_id?library.get(item.style_id):undefined;
    if(item.feature_type==='text')return <TextGlyph key={item.feature_id} feature={item} opacity={1} selected={false}/>;
    if(item.feature_type==='line')return <LineGlyph key={item.feature_id} feature={{...item,stroke_color:color??item.stroke_color,stroke_width_px:width??item.stroke_width_px}} style={style} selected={false} screenStroke/>;
    if(item.feature_type!=='face')return null;
    const borderColor=(item.style_override?.stroke_color as string|undefined)??style?.stroke_color??undefined;
    const borderWidth=(item.style_override?.stroke_width_px as number|undefined)??style?.stroke_width_px??0;
    const border=!!borderColor&&borderWidth>0;
    return <g key={item.feature_id}><path data-face-preview-feature={item.feature_id} d={geometryPath(item.geometry)} fill={color??item.fill_color} fillRule="evenodd" stroke={border?borderColor:'none'} strokeWidth={border?borderWidth:0} vectorEffect="non-scaling-stroke"/>{facesOnly&&outline&&<path data-face-preview-outline={item.feature_id} d={geometryPath(item.geometry)} fill="none" stroke="#1677ff" strokeWidth={1.5} strokeDasharray="3 2" strokeLinejoin="round" vectorEffect="non-scaling-stroke"/>}</g>;
   })}
   </g>
   {textsOnly&&outline&&textBox&&<rect data-text-preview-outline="true" x={textBox.x} y={textBox.y} width={textBox.width} height={textBox.height} fill="none" stroke="#8c8c8c" strokeOpacity={.35} strokeWidth={1} strokeDasharray="3 3" vectorEffect="non-scaling-stroke"/>}
  </svg>
  <div className={'property-face-preview-controls'+(facesOnly||textsOnly?'':' property-line-preview-controls')}>{(facesOnly||textsOnly)&&<Checkbox checked={outline} onChange={event=>setOutline(event.target.checked)}>显示轮廓</Checkbox>}<PreviewImageCopyButton svgRef={svg}/></div>
  {features.length>LIMIT&&<span className="property-preview-note">仅预览前 {LIMIT} 个对象</span>}
 </div>;
});
