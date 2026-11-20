import {memo,useId,useMemo,useRef,useState} from 'react';
import {Checkbox} from 'antd';
import {TextGlyph,geometryPath} from './FeatureGlyph';
import {ResidueCleanupResult} from './ResidueCleanupResult';
import type {ResidueCleanupPlan} from '../hooks/useResidueCleanupPlan';
import type {ResidueScene} from '../services/residueComparison';
import './ResiduePreview.css';
import {TextResidueOverlay} from './TextResidueOverlay';
import {PreviewImageCopyButton} from './PreviewImageCopyButton';
import type {Feature,TextFeature,TextResidueDisplay} from '../services/models';

type Visibility={faces:boolean;lines:boolean;protected:boolean;text:boolean};
type SourceImage={url:string;bounds:number[];onLoad:()=>void;onError:()=>void};
type Props={display:TextResidueDisplay;features:Record<string,Feature>;textFeatureIds:string[];focused?:string[];sourceImage?:SourceImage;cleanupPlan?:ResidueCleanupPlan;actualScene?:ResidueScene};

export const ResiduePreview=memo(function ResiduePreview({display,features,textFeatureIds,focused=[],sourceImage,cleanupPlan,actualScene}:Props){
 const svg=useRef<SVGSVGElement>(null);
 const [shown,setShown]=useState<Visibility>({faces:true,lines:true,protected:true,text:true});
 const [showRegion,setShowRegion]=useState(false),[sourceError,setSourceError]=useState<string|null>(null);
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
  {key:'faces',label:'碎面',swatch:'residue-face',count:display.face_feature_ids.length},
  {key:'lines',label:'线段',swatch:'residue-line',count:display.line_feature_ids.length},
  {key:'protected',label:'待核对线',swatch:'residue-protected',count:display.protected_line_feature_ids.length},
  {key:'text',label:'文字',swatch:'residue-text',count:texts.length}
 ];
 const result=<svg ref={svg} className="residue-preview-canvas" viewBox={viewBox} preserveAspectRatio="xMidYMid meet" role="img" aria-label="文字残影预览">
   <defs><clipPath id={clip}>{display.region_geometry?<path d={geometryPath(display.region_geometry)}/>:<rect x={x0} y={y0} width={width} height={height}/>}</clipPath></defs>
   <TextResidueOverlay display={display} features={features} shown={{...shown,context:false}} focused={focused.filter(id=>visibleIds.has(id))} showRegion={showRegion}/>
   {shown.text&&<g clipPath={'url(#'+clip+')'}>{texts.map(feature=><TextGlyph key={feature.feature_id} feature={feature} opacity={1} selected={false}/>)}</g>}
  </svg>;
 const controls=<div className="property-face-preview-controls"><Checkbox checked={showRegion} onChange={event=>setShowRegion(event.target.checked)}>显示轮廓</Checkbox><PreviewImageCopyButton svgRef={svg}/></div>;
 return <section className={'residue-preview'+(cleanupPlan?' residue-three-preview':'')} aria-label="残影预览">
  {sourceImage?<div className="global-residue-comparison" aria-label="原图与残影对照">
   <figure><figcaption>原图</figcaption><svg className="residue-source-canvas" viewBox={viewBox} preserveAspectRatio="xMidYMid meet" role="img" aria-label="当前文字残影原图"><image href={sourceImage.url} x={sourceImage.bounds[0]} y={sourceImage.bounds[1]} width={sourceImage.bounds[2]-sourceImage.bounds[0]} height={sourceImage.bounds[3]-sourceImage.bounds[1]} preserveAspectRatio="none" onLoad={()=>{setSourceError(null);sourceImage.onLoad();}} onError={()=>{setSourceError(sourceImage.url);sourceImage.onError();}}/></svg>{sourceError===sourceImage.url&&<small className="residue-after-note">原图加载失败，请重新检查</small>}</figure>
   <figure><figcaption>残影预览</figcaption>{result}{controls}</figure>
   {cleanupPlan&&<ResidueCleanupResult plan={cleanupPlan} scene={actualScene} viewBox={viewBox}/>}
  </div>:<>{result}{controls}</>}
  <div className="residue-display-controls" role="group" aria-label="预览图层">
   <span className="residue-preview-label">预览显示</span>
   {layers.map(layer=><Checkbox key={layer.key} checked={shown[layer.key]} onChange={event=>setShown(previous=>({...previous,[layer.key]:event.target.checked}))}><i aria-hidden="true" className={'residue-swatch '+layer.swatch}/>{layer.label} {layer.count}</Checkbox>)}
  </div>
 </section>;
});
