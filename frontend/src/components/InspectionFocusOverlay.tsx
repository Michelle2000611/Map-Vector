import {useId} from 'react';
import {geometryPath} from './FeatureGlyph';
import type {Feature,Geometry} from '../services/models';
import './LocatePulse.css';

export const LOCATE_PULSE_DURATION_MS=3200;
export function InspectionFocusOverlay({ids,features,label,nonce,geometries=[],bounds,clipBounds}:{ids:string[];features:Record<string,Feature>;label:string;nonce:number;geometries?:Geometry[];bounds?:number[];clipBounds?:number[]}){
 const clipId=useId().replace(/:/g,'');
 const shapes=ids.map(id=>{
  const feature=features[id];if(!feature)return null;
  const b=feature.feature_type==='text'?feature.display_bbox_px:null;
  const d=b?'M '+b[0]+' '+b[1]+' H '+b[2]+' V '+b[3]+' H '+b[0]+' Z':feature.feature_type==='text'?'M '+(feature.geometry.coordinates[0]-6)+' '+(feature.geometry.coordinates[1]-6)+' h 12 v 12 h -12 Z':geometryPath(feature.geometry);
  return {id,d,line:feature.feature_type==='line'};
 }).filter((item):item is {id:string;d:string;line:boolean}=>!!item);
 const extra=geometries.map((geometry,index)=>({id:String(index),d:geometryPath(geometry),line:geometry.type.includes('Line')}));
 if(!shapes.length&&!extra.length&&bounds){const [x0,y0,x1,y1]=bounds;extra.push({id:'region',d:'M '+x0+' '+y0+' H '+x1+' V '+y1+' H '+x0+' Z',line:false});}
 const region=clipBounds?.length===4&&clipBounds.every(Number.isFinite)&&clipBounds[2]>clipBounds[0]&&clipBounds[3]>clipBounds[1]?{x:clipBounds[0],y:clipBounds[1],width:clipBounds[2]-clipBounds[0],height:clipBounds[3]-clipBounds[1]}:null;
 const context=region?shapes.filter(item=>item.line):[];
 const extent=[Infinity,Infinity,-Infinity,-Infinity];
 const visit=(value:unknown)=>{if(!Array.isArray(value))return;if(typeof value[0]==='number'&&typeof value[1]==='number'){extent[0]=Math.min(extent[0],value[0]);extent[1]=Math.min(extent[1],value[1]);extent[2]=Math.max(extent[2],value[0]);extent[3]=Math.max(extent[3],value[1]);}else value.forEach(visit);};
 if(region){visit([[region.x,region.y],[region.x+region.width,region.y+region.height]]);context.forEach(item=>visit(features[item.id].geometry.coordinates));}
 const contextArea=region?{x:extent[0]-8,y:extent[1]-8,width:extent[2]-extent[0]+16,height:extent[3]-extent[1]+16}:null;
 const pulses=[...shapes.map(item=>({...item,feature:true})),...extra.map(item=>({...item,feature:false}))].map(item=><g key={(item.feature?'feature-':'geometry-')+item.id} className={'locate-pulse-shape'+(region?' is-region-pulse':'')}><path d={item.d} fill="none" stroke="white" strokeOpacity={.95} strokeWidth={7} vectorEffect="non-scaling-stroke"/><path data-inspection-focus-feature={item.feature?item.id:undefined} data-inspection-focus-geometry={!item.feature?item.id:undefined} d={item.d} fill={item.line?'none':'#1677ff'} fillOpacity={.44} fillRule="evenodd" stroke="#1677ff" strokeWidth={3} strokeLinejoin="round" vectorEffect="non-scaling-stroke"/></g>);
 return <g key={nonce} className="inspection-focus-overlay" data-locate-pulse={nonce} aria-label={label} pointerEvents="none">
  {region&&contextArea&&<><defs><clipPath id={clipId+'-inside'} clipPathUnits="userSpaceOnUse"><rect {...region}/></clipPath><mask id={clipId+'-outside'} maskUnits="userSpaceOnUse" maskContentUnits="userSpaceOnUse" {...contextArea} style={{maskType:'luminance'}}><rect {...contextArea} fill="white"/><rect {...region} fill="black"/></mask></defs><g className="inspection-focus-context" mask={'url(#'+clipId+'-outside)'}>{context.map(item=><path key={item.id} data-inspection-context-feature={item.id} d={item.d} fill="none" stroke="#1677ff" strokeOpacity={.28} strokeWidth={1.5} vectorEffect="non-scaling-stroke"/>)}</g></>}
  {region?<g data-inspection-focus-clip="true" clipPath={'url(#'+clipId+'-inside)'}>{pulses}</g>:pulses}
 </g>;
}
