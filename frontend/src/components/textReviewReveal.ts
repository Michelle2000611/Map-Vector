import {useEffect,useRef,useState} from 'react';
import type {RefObject} from 'react';
import type {TextFeature} from '../services/models';

export type TextReviewRevealRequest={feature_id:string;ticket:number};
export type TextReviewFilter='required'|'skipped'|'confirmed'|'all';
export const needsTextReview=(feature:TextFeature)=>feature.review_status==='required'||feature.review_status==='manual_edited';
export const matchesTextReviewFilter=(feature:TextFeature,filter:TextReviewFilter)=>filter==='all'||(filter==='required'?needsTextReview(feature):feature.review_status===filter);

/** A mounted queue may live inside a hidden layer or a collapsed review panel. */
export function useReviewPanelVisible(panel:RefObject<HTMLDivElement>){
 const [visible,setVisible]=useState(false);
 useEffect(()=>{
  const element=panel.current;if(!element)return;
  const update=()=>setVisible(element.getClientRects().length>0&&getComputedStyle(element).visibility!=='hidden');
  const observer=new MutationObserver(update);
  for(let ancestor:Element|null=element;ancestor;ancestor=ancestor.parentElement)observer.observe(ancestor,{attributes:true,attributeFilter:['hidden','style','class']});
  const resize=new ResizeObserver(update);resize.observe(element);update();
  return()=>{observer.disconnect();resize.disconnect();};
 },[panel]);
 return visible;
}

export function useTextReviewReveal({request,ticket,rows,loadedTicket,visible,panel,filter,setFilter,setOnlySuspects,setPage}:{request:TextReviewRevealRequest|undefined;ticket:string;rows:TextFeature[];loadedTicket:string|null;visible:boolean;panel:RefObject<HTMLDivElement>;filter:TextReviewFilter;setFilter:(filter:TextReviewFilter)=>void;setOnlySuspects:(value:boolean)=>void;setPage:(page:number)=>void}){
 const [highlight,setHighlight]=useState<{ticket:string;id:string}|null>(null);
 const active=useRef<{key:string;ticket:string;handled:boolean}|null>(null);
 const requestKey=request?JSON.stringify([request.feature_id,request.ticket]):null;
 useEffect(()=>{
  if(!requestKey||!request){active.current=null;setHighlight(null);return;}
  if(active.current?.key!==requestKey){active.current={key:requestKey,ticket,handled:false};setHighlight(null);}
  const current=active.current;
  // A revision/asset change invalidates a request even if its queue arrives later.
  if(current.ticket!==ticket){setHighlight(null);return;}
  if(current.handled&&loadedTicket!==ticket){setHighlight(null);return;}
  if(current.handled||!visible||loadedTicket!==ticket)return;
  current.handled=true;
  const target=rows.find(row=>row.feature_id===request.feature_id);
  if(!target){setHighlight(null);return;}
  const nextFilter=matchesTextReviewFilter(target,filter)?filter:'all';
  const eligible=rows.filter(row=>matchesTextReviewFilter(row,nextFilter));
  setOnlySuspects(false);setFilter(nextFilter);setPage(Math.floor(eligible.findIndex(row=>row.feature_id===target.feature_id)/8)+1);
  setHighlight({ticket,id:target.feature_id});
 },[requestKey,request,ticket,rows,loadedTicket,visible,filter,setFilter,setOnlySuspects,setPage]);
 const highlightedId=highlight?.ticket===ticket?highlight.id:null;
 useEffect(()=>{
  if(!highlightedId||!visible)return;
  const frame=requestAnimationFrame(()=>{
   const row=Array.from(panel.current?.querySelectorAll<HTMLElement>('tr[data-row-key]')??[]).find(element=>element.dataset.rowKey===highlightedId);
   row?.scrollIntoView({block:'nearest',inline:'nearest',behavior:'auto'});
  });
  return()=>cancelAnimationFrame(frame);
 },[highlight,highlightedId,visible,panel]);
 return highlightedId;
}
