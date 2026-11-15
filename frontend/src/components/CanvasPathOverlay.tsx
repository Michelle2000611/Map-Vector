import type {Point} from '../services/models';

/** Nodes and segments stay visible after drawing; pointer events still reach the canvas. */
export function CanvasPathOverlay({points,cursor,zoom}:{points:Point[];cursor:Point|null;zoom:number}){
 if(!points.length)return null;
 const last=points[points.length-1];
 return <g className="canvas-path-overlay" pointerEvents="none">
  {points.length>1&&<path data-drawing-path="true" d={'M '+points.map(point=>point.join(' ')).join(' L ')} fill="none" stroke="#1677ff" strokeWidth={2.5} strokeLinejoin="round" vectorEffect="non-scaling-stroke"/>}
  {cursor&&<path data-drawing-guide="true" d={'M '+last.join(' ')+' L '+cursor.join(' ')} fill="none" stroke="#1677ff" strokeWidth={1.5} strokeDasharray="4 3" vectorEffect="non-scaling-stroke"/>}
  {points.map((point,index)=><circle key={index} data-drawing-node={index} cx={point[0]} cy={point[1]} r={4/zoom} fill="#1677ff" stroke="#fff" strokeWidth={1.5} vectorEffect="non-scaling-stroke"/>)}
 </g>;
}
