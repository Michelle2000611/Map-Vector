import {useEffect,useId,useMemo,useRef,useState} from 'react';
import type {PointerEvent as ReactPointerEvent} from 'react';
import {Button,Checkbox,Space} from 'antd';
import type {Asset,Feature,Style} from '../services/models';
import {FeatureScene,SelectedFeatureOverlay} from './FeatureGlyph';
import './DeliveryPreview.css';

export type DeliveryBounds=[number,number,number,number];
type Props={
 asset:Asset;features:Feature[];styles:Style[];bounds:DeliveryBounds|null;
 onBoundsChange?:(bounds:DeliveryBounds)=>void;drawing:boolean;
 scopeMode:'full'|'keep_crossing'|'clip';previewFeatures?:Feature[];
 highlightIds?:string[];focusBounds?:number[]|null;projectId:string;
};
type View=[number,number,number,number];
type Gesture={pointerId:number;start:[number,number];end:[number,number];key:string};
const layers=[{layer_type:'face',opacity:1},{layer_type:'line',opacity:1},{layer_type:'text',opacity:1},{layer_type:'isolated_line',opacity:1}];

// A clipped line can consist of several parts even when its source was one line.
// Normalize for the existing single-line glyph without changing the API result.
function displayFeatures(features:Feature[]):{features:Feature[];ids:Map<string,string[]>}{
 const shown:Feature[]=[],ids=new Map<string,string[]>();
 for(const feature of features){
  const geometry=feature.geometry as unknown as {type:string;coordinates:unknown};
  if(feature.feature_type==='line'&&geometry.type==='MultiLineString'){
   const partIds:string[]=[];
   (geometry.coordinates as [number,number][][]).forEach((coordinates,index)=>{
    const feature_id=feature.feature_id+':delivery-part:'+index;partIds.push(feature_id);
    shown.push({...feature,feature_id,geometry:{type:'LineString',coordinates}} as Feature);
   });ids.set(feature.feature_id,partIds);
  }else{shown.push(feature);ids.set(feature.feature_id,[feature.feature_id]);}
 }
 return {features:shown,ids};
}
function ordered(a:[number,number],b:[number,number]):DeliveryBounds{
 return [Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])];
}
function framed(bounds:DeliveryBounds):View{
 const width=Math.max(1,bounds[2]-bounds[0]),height=Math.max(1,bounds[3]-bounds[1]),pad=Math.max(width,height)*.035;
 return [bounds[0]-pad,bounds[1]-pad,width+pad*2,height+pad*2];
}

export function DeliveryPreview({asset,features,styles,bounds,onBoundsChange,drawing,scopeMode,previewFeatures,highlightIds=[],focusBounds,projectId}:Props){
 const svg=useRef<SVGSVGElement>(null),gestureRef=useRef<Gesture|null>(null);
 const [gesture,setGesture]=useState<Gesture|null>(null),[original,setOriginal]=useState(true),[objects,setObjects]=useState(true);
 const key=projectId+':'+asset.asset_id+':'+asset.width_px+':'+asset.height_px;
 const full=useMemo(()=>framed([0,0,asset.width_px,asset.height_px]),[asset.width_px,asset.height_px]);
 const [viewState,setViewState]=useState<{key:string;box:View}|null>(null);
 const view=viewState?.key===key?viewState.box:full;
 const scene=useMemo(()=>displayFeatures(previewFeatures??features),[features,previewFeatures]);
 const highlighted=useMemo(()=>highlightIds.flatMap(id=>scene.ids.get(id)??[]),[highlightIds,scene]);
 const maskId='delivery-range-'+useId().replace(/:/g,'');
 const focusKey=focusBounds?.join(',')??'';
 useEffect(()=>{gestureRef.current=null;setGesture(null);},[key,drawing]);
 useEffect(()=>{
  if(drawing||!focusBounds||focusBounds.length!==4||!focusBounds.every(Number.isFinite))return;
  if(focusBounds[2]<focusBounds[0]||focusBounds[3]<focusBounds[1])return;
  setViewState({key,box:framed(focusBounds as DeliveryBounds)});
 },[key,focusKey,drawing]);
 const activeGesture=gesture?.key===key&&drawing?gesture:null;
 const shownBounds=activeGesture?ordered(activeGesture.start,activeGesture.end):bounds;
 const showRange=shownBounds&&(scopeMode!=='full'||drawing);
 function point(event:ReactPointerEvent<SVGSVGElement>):[number,number]|null{
  const matrix=svg.current?.getScreenCTM();if(!matrix)return null;
  const mapped=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());
  return [Math.max(0,Math.min(asset.width_px,mapped.x)),Math.max(0,Math.min(asset.height_px,mapped.y))];
 }
 function cancel(){gestureRef.current=null;setGesture(null);}
 function start(event:ReactPointerEvent<SVGSVGElement>){
  if(!drawing||!onBoundsChange||event.button!==0||!event.isPrimary)return;
  const start=point(event);if(!start)return;
  event.preventDefault();event.currentTarget.focus();event.currentTarget.setPointerCapture(event.pointerId);
  const next={pointerId:event.pointerId,start,end:start,key};gestureRef.current=next;setGesture(next);
 }
 function move(event:ReactPointerEvent<SVGSVGElement>){
  const current=gestureRef.current;if(!current||current.pointerId!==event.pointerId||current.key!==key)return;
  const end=point(event);if(!end)return;
  const next={...current,end};gestureRef.current=next;setGesture(next);
 }
 function finish(event:ReactPointerEvent<SVGSVGElement>){
  const current=gestureRef.current;
  if(!current||current.pointerId!==event.pointerId||current.key!==key)return;
  const end=point(event),next=end?ordered(current.start,end):null;
  cancel();if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);
  if(drawing&&next&&next[2]-next[0]>=1&&next[3]-next[1]>=1)onBoundsChange?.(next);
 }
 function zoom(factor:number){
  const width=Math.min(asset.width_px*4,Math.max(1,view[2]*factor)),height=Math.min(asset.height_px*4,Math.max(1,view[3]*factor));
  setViewState({key,box:[view[0]+(view[2]-width)/2,view[1]+(view[3]-height)/2,width,height]});
 }
 return <section className="delivery-preview" aria-label="交付图面预览">
  <div className="delivery-preview-toolbar">
   <Space size={16} wrap><Checkbox checked={original} onChange={event=>setOriginal(event.target.checked)}>原图</Checkbox><Checkbox checked={objects} onChange={event=>setObjects(event.target.checked)}>识别对象</Checkbox></Space>
   <Space size={4}><Button size="small" aria-label="缩小预览" disabled={!!activeGesture} onClick={()=>zoom(1.4)}>−</Button><Button size="small" aria-label="放大预览" disabled={!!activeGesture} onClick={()=>zoom(1/1.4)}>＋</Button><Button size="small" disabled={!!activeGesture} onClick={()=>setViewState({key,box:full})}>适合图面</Button></Space>
  </div>
  <div className={'delivery-preview-canvas'+(drawing?' is-drawing':'')}>
   <svg ref={svg} className="delivery-preview-svg" viewBox={view.join(' ')} preserveAspectRatio="xMidYMid meet" role="img" aria-label="地图与范围" tabIndex={0} onPointerDown={start} onPointerMove={move} onPointerUp={finish} onPointerCancel={cancel} onLostPointerCapture={cancel} onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();cancel();}}}>
    {original&&<image href={'/api/projects/'+encodeURIComponent(projectId)+'/rasters/source?asset_id='+encodeURIComponent(asset.asset_id)} x={0} y={0} width={asset.width_px} height={asset.height_px} preserveAspectRatio="none"/>}
    {objects&&<FeatureScene features={scene.features} styles={styles} layers={layers} background={original?'original':'blank'}/>}
    {showRange&&<>
     <defs><mask id={maskId} maskUnits="userSpaceOnUse" x={0} y={0} width={asset.width_px} height={asset.height_px}><rect x={0} y={0} width={asset.width_px} height={asset.height_px} fill="white"/><rect x={shownBounds[0]} y={shownBounds[1]} width={Math.max(0,shownBounds[2]-shownBounds[0])} height={Math.max(0,shownBounds[3]-shownBounds[1])} fill="black"/></mask></defs>
     <rect className="delivery-preview-outside" x={0} y={0} width={asset.width_px} height={asset.height_px} fill="#425b76" fillOpacity={.16} mask={'url(#'+maskId+')'} pointerEvents="none"/>
     <rect data-delivery-range="true" x={shownBounds[0]} y={shownBounds[1]} width={Math.max(0,shownBounds[2]-shownBounds[0])} height={Math.max(0,shownBounds[3]-shownBounds[1])} fill="none" stroke="#1677ff" strokeWidth={2} strokeDasharray="7 4" vectorEffect="non-scaling-stroke" pointerEvents="none"/>
    </>}
    {objects&&highlighted.length>0&&<SelectedFeatureOverlay features={scene.features} selected={highlighted} background="blank"/>}
   </svg>
  </div>
  <div className="delivery-preview-caption" aria-live="polite">{drawing?'在图上拖动以设置范围；按 Esc 取消本次拖动。':previewFeatures!==undefined?(scopeMode==='clip'?'当前显示沿范围边界裁切后的对象，文字按定位点保留。':scopeMode==='keep_crossing'?'当前显示与范围相交的完整对象，跨界部分保留。':'当前显示整图对象。'):'范围框用于确定导出区域，现有对象不会因此改变。'}</div>
 </section>;
}
