import {useLayoutEffect,useRef} from 'react';
import type {RefObject} from 'react';
import {useWorkspace} from '../stores/workspace';

type Center={x:number;y:number};
// Store offsets belong to the editing canvas. The original follows the same image
// center, even when its viewport has a different width. Followers never lead back.
export function useCanvasScroll(left:RefObject<HTMLDivElement>,right:RefObject<HTMLDivElement>,comparison:boolean,zoom:number,assetId:string){
 const sync=useRef<()=>void>(()=>{}),viewport=useRef<{assetId:string;width:number;height:number;center:Center}|null>(null);
 useLayoutEffect(()=>{
  const main=right.current;if(!main)return;
  const panels=[main,...(comparison&&left.current?[left.current]:[])];
  const expected=new WeakMap<HTMLDivElement,{left:number;top:number}>();
  let frame=0,source:HTMLDivElement|null=null;
  const size=(panel:HTMLDivElement)=>{const surface=panel.querySelector('svg,img');return {width:surface?.getBoundingClientRect().width??0,height:surface?.getBoundingClientRect().height??0};};
  const center=(panel:HTMLDivElement):Center=>{const image=size(panel);return {x:panel.scrollLeft+panel.clientWidth/2-Math.max(0,(panel.clientWidth-image.width)/2),y:panel.scrollTop+panel.clientHeight/2-Math.max(0,(panel.clientHeight-image.height)/2)};};
  const write=(panel:HTMLDivElement,x:number,y:number)=>{
   const target={left:Math.max(0,Math.min(x,panel.scrollWidth-panel.clientWidth)),top:Math.max(0,Math.min(y,panel.scrollHeight-panel.clientHeight))};
   expected.set(panel,target);panel.scrollLeft=target.left;panel.scrollTop=target.top;
  };
  const writeCenter=(panel:HTMLDivElement,value:Center)=>{const image=size(panel);write(panel,value.x-panel.clientWidth/2+Math.max(0,(panel.clientWidth-image.width)/2),value.y-panel.clientHeight/2+Math.max(0,(panel.clientHeight-image.height)/2));};
  const remember=()=>{viewport.current={assetId,width:main.clientWidth,height:main.clientHeight,center:center(main)};};
  const follow=()=>{const value=center(main);for(const follower of panels)if(follower!==main)writeCenter(follower,value);remember();};
  const save=()=>{const state=useWorkspace.getState();if(Math.abs(state.scroll.left-main.scrollLeft)>.5||Math.abs(state.scroll.top-main.scrollTop)>.5)state.setScroll({left:main.scrollLeft,top:main.scrollTop});};
  const apply=()=>{if(frame){cancelAnimationFrame(frame);frame=0;}source=null;const position=useWorkspace.getState().scroll;write(main,position.left,position.top);follow();};
  const scroll=(event:Event)=>{const panel=event.currentTarget as HTMLDivElement,target=expected.get(panel);
   if(target&&Math.abs(panel.scrollLeft-target.left)<1&&Math.abs(panel.scrollTop-target.top)<1)return;
   expected.delete(panel);source=panel;
   if(!frame)frame=requestAnimationFrame(()=>{frame=0;if(!source)return;const leader=source;source=null;if(leader!==main)writeCenter(main,center(leader));follow();save();});
  };
  // Opening/closing the dock changes viewport geometry, not the user's map location.
  const previous=viewport.current;
  if(previous?.assetId===assetId&&(previous.width!==main.clientWidth||previous.height!==main.clientHeight))writeCenter(main,previous.center);
  else {const position=useWorkspace.getState().scroll;write(main,position.left,position.top);}
  follow();save();
  for(const panel of panels)panel.addEventListener('scroll',scroll,{passive:true});
  const resize=new ResizeObserver(()=>{const last=viewport.current;if(last&&(last.width!==main.clientWidth||last.height!==main.clientHeight)){writeCenter(main,last.center);follow();save();}else follow();});
  for(const panel of panels)resize.observe(panel);
  const unsubscribe=useWorkspace.subscribe((state,previousState)=>{if(state.scroll!==previousState.scroll)apply();});
  sync.current=apply;
  return()=>{unsubscribe();resize.disconnect();for(const panel of panels)panel.removeEventListener('scroll',scroll);if(frame)cancelAnimationFrame(frame);};
 },[left,right,comparison,assetId]);
 useLayoutEffect(()=>sync.current(),[zoom]);
}
