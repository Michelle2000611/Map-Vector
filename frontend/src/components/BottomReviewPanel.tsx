import {useEffect,useId,useRef,useState} from 'react';
import type {PointerEvent,ReactNode} from 'react';
import {Button,Card} from 'antd';
import './BottomReviewPanel.css';

type Props={title:string;contextKey:string;className?:string;layout?:'sidebar'|'bottom';revealKey?:number;children:ReactNode};
const minimumHeight=240,maximumHeight=960;
const initialHeight=()=>typeof window!=='undefined'&&window.innerWidth<760?420:520;
const clampHeight=(value:number)=>Math.max(minimumHeight,Math.min(maximumHeight,value));

export function BottomReviewPanel({title,contextKey,className='',layout='bottom',revealKey,children}:Props){
 const [collapsed,setCollapsed]=useState(false),[height,setHeight]=useState(initialHeight);
 const drag=useRef<{pointerId:number;y:number;height:number}|null>(null);
 const contentId=useId();
 useEffect(()=>{setCollapsed(false);setHeight(initialHeight());drag.current=null;},[contextKey]);
 useEffect(()=>{if(revealKey!==undefined)setCollapsed(false);},[revealKey]);
 function startResize(event:PointerEvent<HTMLDivElement>){
  if(event.button!==0)return;
  event.preventDefault();drag.current={pointerId:event.pointerId,y:event.clientY,height};
  event.currentTarget.setPointerCapture(event.pointerId);
 }
 function resize(event:PointerEvent<HTMLDivElement>){
  const active=drag.current;
  if(active?.pointerId===event.pointerId)setHeight(clampHeight(active.height+event.clientY-active.y));
 }
 function finishResize(event:PointerEvent<HTMLDivElement>){
  if(drag.current?.pointerId!==event.pointerId)return;
  drag.current=null;
  if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);
 }
 return <Card className={'bottom-review-panel '+(layout==='sidebar'?'review-sidebar-auto ':'')+className} title={title} role="region" aria-label={title}
  extra={<Button size="small" aria-label={(collapsed?'展开':'收起')+title} aria-expanded={!collapsed} aria-controls={contentId} onClick={()=>setCollapsed(value=>!value)}>{collapsed?'展开':'收起'}</Button>}>
  <div id={contentId} className="bottom-review-content" hidden={collapsed} style={{height:layout==='sidebar'?undefined:height}}>{children}</div>
  {!collapsed&&layout==='bottom'&&<div className="bottom-review-resize" role="separator" tabIndex={0} aria-label={'调整'+title+'面板高度'} aria-orientation="horizontal" aria-valuemin={minimumHeight} aria-valuemax={maximumHeight} aria-valuenow={height}
   onPointerDown={startResize} onPointerMove={resize} onPointerUp={finishResize} onPointerCancel={finishResize} onLostPointerCapture={()=>{drag.current=null;}}
   onKeyDown={event=>{const delta=event.shiftKey?60:20;if(event.key==='ArrowUp'||event.key==='ArrowDown'){event.preventDefault();setHeight(value=>clampHeight(value+(event.key==='ArrowDown'?delta:-delta)));}else if(event.key==='Home'||event.key==='End'){event.preventDefault();setHeight(event.key==='Home'?minimumHeight:maximumHeight);}}}><span/></div>}
 </Card>;
}
