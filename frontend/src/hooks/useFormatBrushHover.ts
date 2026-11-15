import {useEffect,useRef,useState} from 'react';
import {request} from '../services/client';
import type {Point} from '../services/models';

type Options={enabled:boolean;projectId:string;assetId:string;layer:string;session:number;revision:number};
/** A read-only hit test; never alters the real canvas selection or writes styles. */
export function useFormatBrushHover({enabled,projectId,assetId,layer,session,revision}:Options){
 const scope=JSON.stringify([enabled,projectId,assetId,layer,session,revision]);
 const current=useRef(scope),serial=useRef(0),timer=useRef<number>(),controller=useRef<AbortController|null>(null),mounted=useRef(false),point=useRef<Point|null>(null);
 const [hit,setHit]=useState<{scope:string;id:string}|null>(null);current.current=scope;
 function clear(){serial.current++;if(timer.current!==undefined)window.clearTimeout(timer.current);timer.current=undefined;point.current=null;controller.current?.abort();controller.current=null;setHit(null);}
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;serial.current++;if(timer.current!==undefined)window.clearTimeout(timer.current);controller.current?.abort();};},[]);
 useEffect(()=>{clear();},[scope]);
 function move(next:Point){
  if(!enabled||!['face','line'].includes(layer))return;
  point.current=next;
  if(timer.current!==undefined)return;
  const expected=scope;
  timer.current=window.setTimeout(()=>{
   timer.current=undefined;const position=point.current;if(!position||!mounted.current||current.current!==expected)return;
   controller.current?.abort();const abort=new AbortController(),ticket=++serial.current;controller.current=abort;
   void request<{feature_ids:string[]}>('/projects/'+projectId+'/selections',{asset_id:assetId,selection_type:'pick',feature_type:layer,lifecycle_status:'active',feature_ids:[],selection_mode:'replace',x:position[0],y:position[1]},abort.signal,{quiet:true})
    .then(result=>{if(mounted.current&&!abort.signal.aborted&&current.current===expected&&serial.current===ticket)setHit(result.feature_ids[0]?{scope:expected,id:result.feature_ids[0]}:null);})
    .catch(()=>{if(mounted.current&&current.current===expected&&serial.current===ticket)setHit(null);});
  },60);
 }
 return {id:enabled&&hit?.scope===scope?hit.id:null,move,clear};
}
