import {useLayoutEffect,useRef} from 'react';
import type {RefObject} from 'react';
import {useWorkspace} from '../stores/workspace';

// Browser scroll events stay outside React. Programmatic follower updates must
// not become a new leader: different viewport bounds otherwise cause feedback.
export function useCanvasScroll(left:RefObject<HTMLDivElement>,right:RefObject<HTMLDivElement>,comparison:boolean,zoom:number,assetId:string){
 const sync=useRef<()=>void>(()=>{});
 useLayoutEffect(()=>{
  const panels=[right.current,...(comparison?[left.current]:[])].filter((p):p is HTMLDivElement=>!!p);
  const expected=new WeakMap<HTMLDivElement,{left:number;top:number}>();
  let frame=0,source:HTMLDivElement|null=null;
  const write=(panel:HTMLDivElement,x:number,y:number)=>{
   const target={left:Math.max(0,Math.min(x,panel.scrollWidth-panel.clientWidth)),top:Math.max(0,Math.min(y,panel.scrollHeight-panel.clientHeight))};
   expected.set(panel,target);
   if(Math.abs(panel.scrollLeft-target.left)>.5)panel.scrollLeft=target.left;
   if(Math.abs(panel.scrollTop-target.top)>.5)panel.scrollTop=target.top;
  };
  const apply=()=>{if(frame){cancelAnimationFrame(frame);frame=0;}source=null;const position=useWorkspace.getState().scroll;for(const panel of panels)write(panel,position.left,position.top);};
  const scroll=(event:Event)=>{const panel=event.currentTarget as HTMLDivElement,target=expected.get(panel);
   if(target&&Math.abs(panel.scrollLeft-target.left)<1&&Math.abs(panel.scrollTop-target.top)<1)return;
   expected.delete(panel);source=panel;
   if(!frame)frame=requestAnimationFrame(()=>{frame=0;if(!source)return;const leader=source;source=null;for(const follower of panels)if(follower!==leader)write(follower,leader.scrollLeft,leader.scrollTop);});
  };
  for(const panel of panels)panel.addEventListener('scroll',scroll,{passive:true});
  const unsubscribe=useWorkspace.subscribe((state,previous)=>{if(state.scroll!==previous.scroll)apply();});
  sync.current=apply;apply();
  return()=>{unsubscribe();for(const panel of panels)panel.removeEventListener('scroll',scroll);if(frame)cancelAnimationFrame(frame);};
 },[left,right,comparison,assetId]);
 useLayoutEffect(()=>sync.current(),[zoom,comparison]);
}
