import {useEffect,useRef,useState} from 'react';
import type {CSSProperties,PointerEvent,ReactNode} from 'react';
import {Tag,theme} from 'antd';
import './WorkbenchFrame.css';

type Props={comparison:boolean;compact:boolean;textLayer:boolean;stage:number;contextKey:string;layerLabel:string;selectedCount:number;
 toolbar:ReactNode;canvas:ReactNode;properties:ReactNode;footer?:ReactNode;alerts?:ReactNode;history:ReactNode;children?:ReactNode};

export function WorkbenchFrame({comparison,compact,textLayer,stage,contextKey,layerLabel,selectedCount,toolbar,canvas,properties,footer,alerts,history,children}:Props){
 const {token}=theme.useToken();
 const frame=useRef<HTMLElement>(null),drag=useRef<{pointer:number}|null>(null);
 const [canvasPercent,setCanvasPercent]=useState(50);
 useEffect(()=>{setCanvasPercent(50);drag.current=null;},[contextKey]);
 useEffect(()=>{
  if(!frame.current||comparison||compact)return;
  const observer=new ResizeObserver(()=>setCanvasPercent(value=>clamp(value)));
  observer.observe(frame.current);return()=>observer.disconnect();
 },[comparison,compact,contextKey]);
 function clamp(value:number){
  const width=frame.current?.getBoundingClientRect().width??1200;
  if(width<840)return value;
  return Math.min(Math.min(78,(width-434)/width*100),Math.max(Math.max(40,406/width*100),value));
 }
 function start(event:PointerEvent<HTMLDivElement>){
  if(event.button!==0)return;
  event.preventDefault();drag.current={pointer:event.pointerId};event.currentTarget.setPointerCapture(event.pointerId);
 }
 function move(event:PointerEvent<HTMLDivElement>){
  if(drag.current?.pointer!==event.pointerId||!frame.current)return;
  const bounds=frame.current.getBoundingClientRect();setCanvasPercent(clamp((event.clientX-bounds.left)/bounds.width*100));
 }
 function stop(event:PointerEvent<HTMLDivElement>){
  if(drag.current?.pointer!==event.pointerId)return;
  drag.current=null;if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);
 }
 return <section className="workbench-layout"><section ref={frame} className={'workbench workbench-frame '+(comparison?'comparison-mode':'single-mode')+(compact?' compact-mode':'')+(textLayer?' text-layer':'')}
  data-stage={stage} style={{'--canvas-share':canvasPercent+'%'} as CSSProperties}>
  {toolbar}
  {alerts&&<div className="workspace-alerts">{alerts}</div>}
  {canvas}
  <div className="workspace-splitter" hidden={comparison||compact} role="separator" aria-label="调整画布与侧栏宽度" aria-orientation="vertical" tabIndex={0}
   aria-valuemin={40} aria-valuemax={78} aria-valuenow={Math.round(canvasPercent)} aria-valuetext={'画布 '+Math.round(canvasPercent)+'%'}
   onPointerDown={start} onPointerMove={move} onPointerUp={stop} onPointerCancel={stop} onLostPointerCapture={()=>{drag.current=null;}}
   onKeyDown={event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();setCanvasPercent(current=>clamp(event.key==='Home'?40:event.key==='End'?78:current+(event.key==='ArrowRight'?1:-1)*(event.shiftKey?5:2)));}}}><span/></div>
  <aside className="workspace-inspector" aria-label="属性与操作">
   <div className="workspace-inspector-heading" style={{fontFamily:token.fontFamily}}><h3>属性与操作</h3><div className="workspace-header-tags"><Tag color="blue">{layerLabel}对象</Tag><Tag>已选 {selectedCount}</Tag></div></div>
   <div className="workspace-property-slot">{properties}</div>
   {children}
   {!comparison&&!compact&&footer&&<div className="workspace-inspector-footer">{footer}</div>}
  </aside>
  {history}
 </section></section>;
}
