import {useEffect,useRef,useState} from 'react';
import {ApiError,request} from '../services/client';
import type {Preview} from '../services/models';

type Options={projectId:string;assetId:string;revision:number;session:number;review:Preview|null;verified:string[];assignments:Record<string,string>;enabled:boolean;refreshReview?:()=>Promise<void>};
type State={key:string;status:'loading'|'ready'|'error';plan?:Preview;message?:string};
/** Both residue entries display and submit one frozen backend cleanup plan. */
export function useResidueCleanupPlan({projectId,assetId,revision,session,review,verified,assignments,enabled,refreshReview}:Options){
 const refresh=useRef(refreshReview);refresh.current=refreshReview;
 const [state,setState]=useState<State|null>(null),[retry,setRetry]=useState(0);
 const source=JSON.stringify([projectId,assetId,session,review?.preview_id]);
 const key=JSON.stringify([source,revision,enabled,[...verified].sort(),Object.entries(assignments).sort(),retry]);
 const current=useRef(key);current.current=key;
 const active=enabled&&review?.preview_type==='text_residue'&&!!review.text_residue_display&&review.base_revision===revision;
 useEffect(()=>{
  if(!active||!review){setState(null);return;}
  if(review.expires_at&&Date.parse(review.expires_at)<=Date.now()){setState({key,status:'error',message:'检查已过期，请重新检查。'});return;}
  const controller=new AbortController(),expected=key;
  setState({key,status:'loading'});
  const display=review.text_residue_display!;
  const body={asset_id:assetId,base_revision:revision,preview_type:'text_residue',feature_ids:review.feature_ids,complete_region:true,face_assignments:assignments,
   ...(verified.length?{verified_line_feature_ids:verified,line_review_preview_id:review.preview_id}:{}),
   ...(!review.feature_ids.length?{bounds_px:display.bounds_px}:{})};
  void request<Preview>('/projects/'+projectId+'/edit-previews',body,controller.signal,{quiet:true}).then(plan=>{
   if(controller.signal.aborted||current.current!==expected)return;
   if(plan.base_revision!==revision||!plan.text_residue_display?.complete_region||!plan.cleanup_preview)throw Error('当前后端未返回清理后预览，需要重新加载后端后再检查。');
   if(plan.expires_at&&Date.parse(plan.expires_at)<=Date.now())throw Error('清理方案已过期，请重新生成预览。');
   setState({key:expected,status:'ready',plan});
  }).catch(error=>{
   if(controller.signal.aborted||current.current!==expected)return;
   if(error instanceof ApiError&&error.code==='RESIDUE_GROUND_AMBIGUOUS'&&error.detail.receiver_options){
    setState({key:expected,status:'error',message:'当前后端尚未加载自动清理功能，需要重新加载后端后再检查。'});
   }else setState({key:expected,status:'error',message:error instanceof Error?error.message:String(error)});
  });
  return()=>controller.abort();
 },[key]);
 const selected=state?.key===key?state:null;
 useEffect(()=>{
  const expiries=[review?.expires_at,selected?.plan?.expires_at].filter((value):value is string=>!!value).map(value=>Date.parse(value)).filter(Number.isFinite);if(!active||!expiries.length)return;
  const remaining=Math.min(...expiries)-Date.now();if(remaining>2147483647)return;
  const timer=window.setTimeout(()=>setState(old=>old?.key===key?{key,status:'error',message:review?.expires_at&&Date.parse(review.expires_at)<=Date.now()?'检查已过期，请重新检查。':'清理方案已过期，请重新生成预览。'}:old),Math.max(0,remaining));
  return()=>window.clearTimeout(timer);
 },[key,active,review?.expires_at,selected?.plan?.preview_id]);
 return {status:active?(selected?.status??'loading'):'idle',plan:selected?.status==='ready'?selected.plan:undefined,message:selected?.message,
  retry:()=>{if(review?.expires_at&&Date.parse(review.expires_at)<=Date.now()&&refresh.current){void refresh.current();}else setRetry(value=>value+1);}};
}
export type ResidueCleanupPlan=ReturnType<typeof useResidueCleanupPlan>;
