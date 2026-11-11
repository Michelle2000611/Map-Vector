import {memo,useId} from 'react';
import {geometryPath} from './FeatureGlyph';
import type {Feature,TextResidueDisplay} from '../services/models';
export type ResidueVisibility={faces:boolean;lines:boolean;protected:boolean;context:boolean};
export const TextResidueOverlay=memo(function TextResidueOverlay({display,features,shown,focused=[]}:{display:TextResidueDisplay;features:Record<string,Feature>;shown:ResidueVisibility;focused?:string[]}){
 const clip=useId().replace(/:/g,'');const [x0,y0,x1,y1]=display.bounds_px;
 const paths=(ids:string[],kind:string,color:string,fill:string,dashed=false)=>ids.map(id=>{const f=features[id];if(!f||f.feature_type==='text')return null;return <path key={id} data-residue-kind={kind} data-feature-id={id} d={geometryPath(f.geometry)} fill={fill} fillOpacity={.38} fillRule="evenodd" stroke={color} strokeWidth={kind==='line'?2.5:1.5} strokeDasharray={dashed?'5 3':undefined} vectorEffect="non-scaling-stroke"/>;});
 return <g className="text-residue-overlay" pointerEvents="none"><defs><clipPath id={clip}><rect x={x0} y={y0} width={x1-x0} height={y1-y0}/></clipPath></defs><g clipPath={'url(#'+clip+')'}>{shown.protected&&paths(display.protected_line_feature_ids,'protected','#1677ff','none',true)}{shown.faces&&paths(display.face_feature_ids,'face','#d46b08','#fa8c16')}{shown.lines&&paths(display.line_feature_ids,'line','#c41d7f','none')}{paths(focused,'review-selected','#9254de','none')}</g><rect data-residue-region="true" x={x0} y={y0} width={x1-x0} height={y1-y0} fill="none" stroke="#8c8c8c" strokeOpacity={.35} strokeWidth={1} strokeDasharray="3 3" vectorEffect="non-scaling-stroke"/></g>;
});
