import {memo} from 'react';
import type {Feature,Style} from '../services/models';
type Point=[number,number];
export const LineGlyph=memo(function LineGlyph({feature,style,selected,opacity=1}:{feature:Extract<Feature,{feature_type:'line'}>;style:Style|undefined;selected:boolean;opacity?:number}){
 const parts:Point[][]=[feature.geometry.coordinates];
 const color=selected?'#1677ff':feature.stroke_color,pattern=style?.line_pattern??feature.line_pattern;
 const dash=pattern==='dashed'?(style?.dash_pattern_px??[6,4]).join(' '):undefined;
 const teeth:string[]=[];
 if(pattern==='teeth')for(const points of parts){
  const spacing=style?.tooth_spacing_px??10,height=style?.tooth_height_px??4,side=style?.tooth_side==='right'?-1:1;
  const distances=[0];for(let index=1;index<points.length;index++)distances.push(distances.at(-1)!+Math.hypot(points[index][0]-points[index-1][0],points[index][1]-points[index-1][1]));
  const total=distances.at(-1)!;
  const interpolate=(distance:number):Point=>{for(let i=1;i<points.length;i++)if(distance<=distances[i]){const length=distances[i]-distances[i-1],fraction=length?(distance-distances[i-1])/length:0;return [points[i-1][0]+(points[i][0]-points[i-1][0])*fraction,points[i-1][1]+(points[i][1]-points[i-1][1])*fraction];}return points.at(-1)!;};
  for(let distance=spacing/2;distance<total;distance+=spacing){const a=interpolate(Math.max(0,distance-height/2)),b=interpolate(Math.min(total,distance+height/2)),m=interpolate(distance),dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);if(length>1e-9)teeth.push(a.join(',')+' '+b.join(',')+' '+[m[0]+dy/length*height*side,m[1]-dx/length*height*side].join(','));}
 }
 return <g data-feature-type="line" opacity={opacity} pointerEvents="none">{parts.map((points,index)=><path key={index} d={'M '+points.map(point=>point.join(' ')).join(' L ')} fill="none" stroke={color} strokeWidth={feature.stroke_width_px} strokeDasharray={dash}/>)}{teeth.map((points,index)=><polygon key={index} points={points} fill={color}/>)}</g>;
});
