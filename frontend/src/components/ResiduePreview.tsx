import {memo,useId,useMemo,useRef,useState} from 'react';
import {Checkbox} from 'antd';
import {TextGlyph} from './FeatureGlyph';
import {TextResidueOverlay} from './TextResidueOverlay';
import {PreviewImageCopyButton} from './PreviewImageCopyButton';
import type {Feature,TextFeature,TextResidueDisplay} from '../services/models';

type Visibility={faces:boolean;lines:boolean;protected:boolean;text:boolean};
type Props={display:TextResidueDisplay;features:Record<string,Feature>;textFeatureIds:string[];focused?:string[]};

export const ResiduePreview=memo(function ResiduePreview({display,features,textFeatureIds,focused=[]}:Props){
 const svg=useRef<SVGSVGElement>(null);
 const [shown,setShown]=useState<Visibility>({faces:true,lines:true,protected:true,text:true});
 const clip=useId().replace(/:/g,''),[x0,y0,x1,y1]=display.bounds_px;
 const width=Math.max(1,x1-x0),height=Math.max(1,y1-y0),pad=Math.max(width,height)*.06+2;
 // Keep the inspection extent fixed when layers are hidden, including when all are off.
 const viewBox=[x0-pad,y0-pad,width+pad*2,height+pad*2].join(' ');
 const texts=useMemo(()=>{
  const targets=new Set(textFeatureIds);
  return Object.values(features).filter((feature):feature is TextFeature=>{
   if(feature.feature_type!=='text'||feature.lifecycle_status!=='active')return false;
   if(targets.has(feature.feature_id))return true;
   const [x,y]=feature.geometry.coordinates;
   const bounds=feature.display_bbox_px??[x,y,x,y];
   return bounds[0]<=x1&&bounds[2]>=x0&&bounds[1]<=y1&&bounds[3]>=y0;
  });
 },[features,textFeatureIds,x0,y0,x1,y1]);
 const visibleIds=new Set([...(shown.faces?display.face_feature_ids:[]),...(shown.lines?display.line_feature_ids:[]),...(shown.protected?display.protected_line_feature_ids:[])]);
 const layers:{key:keyof Visibility;label:string;swatch:string;count:number}[]=[
  {key:'faces',label:'疑似碎面',swatch:'residue-face',count:display.face_feature_ids.length},
  {key:'lines',label:'疑似线段',swatch:'residue-line',count:display.line_feature_ids.length},
  {key:'protected',label:'待核对线',swatch:'residue-protected',count:display.protected_line_feature_ids.length},
  {key:'text',label:'文字',swatch:'residue-text',count:texts.length}
 ];
 return <section className="residue-preview" aria-label="残影预览">
  <svg ref={svg} className="residue-preview-canvas" viewBox={viewBox} preserveAspectRatio="xMidYMid meet" role="img" aria-label="文字残影预览">
   <defs><clipPath id={clip}><rect x={x0} y={y0} width={width} height={height}/></clipPath></defs>
   <TextResidueOverlay display={display} features={features} shown={{...shown,context:false}} focused={focused.filter(id=>visibleIds.has(id))}/>
   {shown.text&&<g clipPath={'url(#'+clip+')'}>{texts.map(feature=><TextGlyph key={feature.feature_id} feature={feature} opacity={1} selected={false}/>)}</g>}
  </svg>
  <div className="property-face-preview-controls property-line-preview-controls"><PreviewImageCopyButton svgRef={svg}/></div>
  <div className="residue-display-controls" role="group" aria-label="预览图层">
   <span className="residue-preview-label">预览显示</span>
   {layers.map(layer=><Checkbox key={layer.key} checked={shown[layer.key]} onChange={event=>setShown(previous=>({...previous,[layer.key]:event.target.checked}))}><i aria-hidden="true" className={'residue-swatch '+layer.swatch}/>{layer.label} {layer.count}</Checkbox>)}
  </div>
 </section>;
});
