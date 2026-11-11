import {memo,useMemo} from 'react';
import {LineGlyph} from './LineGlyph';
import type {Feature,TextFeature,Geometry,Point,Style} from '../services/models';

const paths=new WeakMap<Geometry,string>();
export function geometryPath(g:Geometry):string{
 const cached=paths.get(g);if(cached!==undefined)return cached;
 let value='';
 if(g.type==='Polygon')value=g.coordinates.map((ring:Point[])=>'M '+ring.map(p=>p.join(' ')).join(' L ')+' Z').join(' ');
 else if(g.type==='MultiPolygon')value=g.coordinates.map((polygon:Point[][])=>geometryPath({type:'Polygon',coordinates:polygon})).join(' ');
 else if(g.type==='LineString')value='M '+g.coordinates.map(p=>p.join(' ')).join(' L ');
 paths.set(g,value);return value;
}

const TextGlyph=memo(function TextGlyph({feature:f,opacity,selected}:{feature:TextFeature;opacity:number;selected:boolean}){
 const placed=['ocr_quad_v2','ocr_ink_v3','ocr_vertical_v1','ocr_vertical_ink_v2'].includes(f.layout_basis??'')&&f.layout_width_px!=null&&f.baseline_offset_px!=null;
 const runs=f.layout_runs??[];const structured=runs.length>0;
 return <g data-feature-type="text" data-feature-id={f.feature_id} opacity={opacity} pointerEvents="none"><text x={f.geometry.coordinates[0]} y={f.geometry.coordinates[1]+(placed?f.baseline_offset_px!:0)} fontFamily={f.font_family} fontSize={f.font_size_px} textLength={placed&&!structured?f.layout_width_px!:undefined} lengthAdjust={placed&&!structured?'spacingAndGlyphs':undefined} dominantBaseline={placed?'alphabetic':'central'} textAnchor={structured?'start':'middle'} fill={selected?'#1677ff':f.text_color} transform={'rotate('+(-(f.rotation_deg??0))+','+f.geometry.coordinates.join(',')+')'}>{structured?runs.map((run,index)=><tspan key={index} data-script={run.script} x={f.geometry.coordinates[0]+run.x_offset_px} y={f.geometry.coordinates[1]+run.baseline_offset_px} fontSize={run.font_size_px} textLength={run.width_px} lengthAdjust="spacingAndGlyphs">{run.text}</tspan>):f.text_value}</text>{selected&&f.display_bbox_px&&<rect x={f.display_bbox_px[0]} y={f.display_bbox_px[1]} width={f.display_bbox_px[2]-f.display_bbox_px[0]} height={f.display_bbox_px[3]-f.display_bbox_px[1]} fill="none" stroke="#1677ff" strokeWidth={1} vectorEffect="non-scaling-stroke"/>}</g>;
});

const FeatureGlyph=memo(function FeatureGlyph({feature:f,style,opacity,selected,background}:{feature:Feature;style:Style|undefined;opacity:number;selected:boolean;background:string}){
 if(f.feature_type==='text')return <TextGlyph feature={f} opacity={opacity} selected={selected}/>;
 if(f.feature_type==='line')return <LineGlyph feature={f} style={style} selected={selected} opacity={opacity}/>;
 return <path data-feature-type="face" pointerEvents="none" d={geometryPath(f.geometry)} fill={background.startsWith('residual')?'none':f.feature_type==='face'?f.fill_color:'none'} fillOpacity={background==='blank'?1:.55} fillRule="evenodd" opacity={opacity} stroke={selected?'#1677ff':background.startsWith('residual')?'#6b7b8c':'none'} strokeWidth={1} vectorEffect="non-scaling-stroke"/>;
});

export const FeatureScene=memo(function FeatureScene({features,styles,layers,background}:{features:Feature[];styles:Style[];layers:{layer_type:string;opacity:number}[];background:string}){
 const library=useMemo(()=>new Map(styles.map(s=>[s.style_id,s])),[styles]);
 const opacity=useMemo(()=>new Map(layers.map(l=>[l.layer_type,l.opacity])),[layers]);
 return <g pointerEvents="none">{features.map(f=><FeatureGlyph key={f.feature_id} feature={f} style={f.style_id?library.get(f.style_id):undefined} opacity={opacity.get(f.feature_type==='line'&&f.lifecycle_status==='isolated'?'isolated_line':f.feature_type)??1} selected={false} background={background}/>)}</g>;
});

export const SelectedFeatureOverlay=memo(function SelectedFeatureOverlay({features,selected,background}:{features:Feature[];selected:string[];background:string}){
 const library=useMemo(()=>new Map(features.map(f=>[f.feature_id,f])),[features]);
 const batches=useMemo(()=>{
  const result:string[]=[];let batch:string[]=[];
  for(const id of selected){const f=library.get(id);if(!f)continue;
   if(f.feature_type==='text'&&f.geometry.type==='Point'){
    const [x0,y0,x1,y1]=f.display_bbox_px??[f.geometry.coordinates[0]-4,f.geometry.coordinates[1]-4,f.geometry.coordinates[0]+4,f.geometry.coordinates[1]+4];
    batch.push('M '+x0+' '+y0+' H '+x1+' V '+y1+' H '+x0+' Z');
   }else batch.push(geometryPath(f.geometry));
   if(batch.length===256){result.push(batch.join(' '));batch=[];}
  }
  if(batch.length)result.push(batch.join(' '));return result;
 },[library,selected]);
 return <g className="selected-feature-overlay" pointerEvents="none" data-selection-count={selected.length}>{batches.map((d,index)=><path key={index} d={d} fill="none" stroke={background.startsWith('residual')?'#1677ff':'#096dd9'} strokeWidth={2} strokeDasharray={selected.length<=100?'6 3':undefined} vectorEffect="non-scaling-stroke"/>)}</g>;
});
