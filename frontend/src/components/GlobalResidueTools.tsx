import {useEffect,useRef,useState} from 'react';
import type {ReactNode,RefObject} from 'react';
import './TextReviewPanel.css';
import {Alert,Button} from 'antd';
import {request} from '../services/client';
import {residueCleanupMessage} from '../services/residueBatch';
import {useWorkspace} from '../stores/workspace';
import {residueSourceCrop} from '../services/residueSourceCrop';
import {useResidueCleanupPlan} from '../hooks/useResidueCleanupPlan';
import {ResiduePreview} from './ResiduePreview';
import {ResidueLineReview} from './ResidueLineReview';
import type {Asset,Command,Preview,Project,TextLayerAssessmentReport} from '../services/models';

export type TextResidueReview={targetId:string;content:ReactNode;cleanupActionRef:RefObject<HTMLDivElement>;locked:boolean;report:TextLayerAssessmentReport|null;open:(id:string)=>Promise<void>;close:()=>void};
type Props={children?:(review:TextResidueReview)=>ReactNode;project:Project;asset:Asset;busy:boolean;command:Command;active:boolean;flush?:()=>Promise<boolean>;revealRequest?:{feature_id:string;ticket:number};onLocate:(bounds:number[],ids:string[])=>void};

/** Global and individual review use the same preview and reversible cleanup command. */
export function GlobalResidueTools({children,project,asset,busy,command,active,flush,revealRequest,onLocate}:Props){
 const session=useWorkspace(s=>s.session),features=useWorkspace(s=>s.featuresById);
 const [cleanupBusy,setCleanupBusy]=useState(false);
 const cleanupActionRef=useRef<HTMLDivElement>(null);
 const [sourceImageState,setSourceImageState]=useState<{previewId:string;status:'ready'|'failed'}|null>(null);
 const sourcePreviewId=useRef<string|undefined>();
 const [report,setReport]=useState<TextLayerAssessmentReport|null>(null),[preview,setPreview]=useState<Preview|null>(null),[target,setTarget]=useState('');
 const [pending,setPending]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
 const [checked,setChecked]=useState<string[]>([]),[verified,setVerified]=useState<string[]>([]);
 const scope=JSON.stringify([project.project_id,asset.asset_id,session,active]),scopeRef=useRef(scope),generation=useRef(0),mounted=useRef(true),inFlight=useRef(false),applying=useRef(false),applyEpoch=useRef(0),flushing=useRef(false),readRevision=useRef<number|null>(null);
 scopeRef.current=scope;
 const prefix='/projects/'+project.project_id;
 const cleanupPlan=useResidueCleanupPlan({projectId:project.project_id,assetId:asset.asset_id,revision:project.working_revision,session,review:preview,verified,assignments:{},enabled:active,refreshReview:()=>open(target)});
 const readAbort=useRef<AbortController|null>(null),targetRef=useRef(target);targetRef.current=target;
 function current(expected:string){const state=useWorkspace.getState();return mounted.current&&scopeRef.current===expected&&active&&state.session===session&&state.project?.project_id===project.project_id&&state.asset?.asset_id===asset.asset_id;}
 function close(){if(applying.current)return;generation.current++;readAbort.current?.abort();inFlight.current=false;flushing.current=false;readRevision.current=null;setPending(false);resetPreview();setTarget('');setError('');setMessage('');}
 function resetPreview(){setSourceImageState(null);setPreview(null);setChecked([]);setVerified([]);}
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;generation.current++;applyEpoch.current++;readAbort.current?.abort();};},[]);
 useEffect(()=>{readAbort.current?.abort();generation.current++;applyEpoch.current++;applying.current=false;flushing.current=false;readRevision.current=null;inFlight.current=false;setReport(null);resetPreview();setTarget('');setError('');setMessage('');setPending(false);setCleanupBusy(false);},[scope]);
 useEffect(()=>{const saving=flushing.current||readRevision.current===project.working_revision;if(!saving)generation.current++;resetPreview();setReport(value=>value?.working_revision===project.working_revision?value:null);if(!applying.current&&!saving){readAbort.current?.abort();setTarget('');inFlight.current=false;setPending(false);}},[project.working_revision]);
 async function open(id:string){
  if(busy||applying.current)return;
  readAbort.current?.abort();const controller=new AbortController();readAbort.current=controller;
  const expected=scope,serial=++generation.current;inFlight.current=true;setPending(true);setError('');setMessage('');resetPreview();setTarget(id);
  try{flushing.current=true;if(flush&&!await flush())throw Error('属性草稿未能保存，请先修正或重试。');if(!current(expected)||serial!==generation.current)return;readRevision.current=useWorkspace.getState().project?.working_revision??null;flushing.current=false;const result=await request<Preview>(prefix+'/edit-previews',{asset_id:asset.asset_id,base_revision:useWorkspace.getState().project?.working_revision,preview_type:'text_residue',feature_ids:[id]},controller.signal);
   if(!current(expected)||serial!==generation.current)return;
   if(result.base_revision!==useWorkspace.getState().project?.working_revision)throw Error('项目已更新，请重新核对。');
   setPreview(result);if(result.text_residue_display)onLocate(result.text_residue_display.bounds_px,[id]);
  }catch(e){if(current(expected)&&serial===generation.current&&!(e instanceof DOMException&&e.name==='AbortError'))setError(e instanceof Error?e.message:String(e));}
  finally{if(current(expected)&&serial===generation.current){flushing.current=false;readRevision.current=null;inFlight.current=false;setPending(false);}}
 }
 useEffect(()=>{if(active&&revealRequest)void open(revealRequest.feature_id);},[revealRequest?.ticket,scope]);
 async function guard(){return targetRef.current===target&&current(scope)&&!!preview&&preview.base_revision===useWorkspace.getState().project?.working_revision&&(!preview.expires_at||Date.parse(preview.expires_at)>Date.now());}
 async function cleanup(){
  if(busy||inFlight.current||!sourceReady||!cleanupPlan.plan||!await guard()||!preview)return;
  const expected=scope,serial=++generation.current,epoch=++applyEpoch.current,id=target,confirmation=[...verified];applying.current=true;inFlight.current=true;setPending(true);setCleanupBusy(true);setError('');
  try{
   const plan=cleanupPlan.plan;
   if(plan.expires_at&&Date.parse(plan.expires_at)<=Date.now())throw Error('清理方案已过期，请重新生成预览。');
   if(!current(expected)||serial!==generation.current)return;
   if(plan.base_revision!==useWorkspace.getState().project?.working_revision)throw Error('项目已更新，请重新检查。');
   const display=plan.text_residue_display;
   if(!display?.complete_region||!display.preserves_existing_text)throw Error('清理范围不完整，请重新核对。');
   if(!display.cleanup_face_feature_ids.length&&!display.cleanup_line_feature_ids.length)throw Error('当前没有可清理的残影。');
   const result=await command({operation_type:'cleanup_text_residue',preview_id:plan.preview_id,complete_region:true,face_assignments:{},...(confirmation.length?{verified_line_feature_ids:confirmation}:{})});
   if(!result||!current(expected)||epoch!==applyEpoch.current)return;
   resetPreview();
   const latest=await request<TextLayerAssessmentReport>(prefix+'/text-layer-assessments?asset_id='+asset.asset_id);
   if(!current(expected)||epoch!==applyEpoch.current)return;
   if(latest.working_revision!==useWorkspace.getState().project?.working_revision)throw Error('清理已保存，项目再次更新，请重新检查。');
   setReport(latest);
   // Refresh the same text; advancing the queue here loses the user's context.
   applying.current=false;inFlight.current=false;setPending(false);await open(id);
   if(current(expected)&&epoch===applyEpoch.current)setMessage((residueCleanupMessage(plan,true)??'已清理当前文字的残影')+'；可撤销，当前条目已重新检查。');
  }catch(e){if(current(expected)&&epoch===applyEpoch.current){setError(String(e));}}
  finally{if(current(expected)&&epoch===applyEpoch.current){applying.current=false;inFlight.current=false;setPending(false);setCleanupBusy(false);}}
 }
 const disabled=busy||pending||cleanupBusy;
 sourcePreviewId.current=preview?.preview_id;
 const sourceReady=!!preview&&sourceImageState?.previewId===preview.preview_id&&sourceImageState.status==='ready';
 const sourceFailed=!!preview&&sourceImageState?.previewId===preview.preview_id&&sourceImageState.status==='failed';
 function sourceLoaded(previewId:string,status:'ready'|'failed'){if(sourcePreviewId.current===previewId)setSourceImageState({previewId,status});}
 const content=<section className="global-residue-tools" aria-label="文字残影详情" aria-busy={pending}>
  {pending&&!preview&&<div role="status">正在加载残影详情…</div>}
  {error&&<Alert type="error" message={error} action={!preview?<Button aria-label="重试" disabled={busy||cleanupBusy} onClick={()=>void open(target)}>重试</Button>:undefined}/>}
  {message&&<Alert type="success" message={message}/>}
  {preview?.text_residue_display&&<section aria-label="当前残影清理方案">
   {!children&&<header className="global-residue-review-header"><Button disabled={busy||cleanupBusy} onClick={close}>收起详情</Button></header>}
   <ResiduePreview key={preview.preview_id} display={preview.text_residue_display} features={features} textFeatureIds={[target]} focused={checked} cleanupPlan={cleanupPlan} sourceImage={{...residueSourceCrop(project.project_id,asset,preview),onLoad:()=>sourceLoaded(preview.preview_id,'ready'),onError:()=>sourceLoaded(preview.preview_id,'failed')}}/>
   {sourceFailed&&<Alert type="warning" message="原图加载失败，请重试后再核对。" action={<Button disabled={disabled} onClick={()=>void open(target)}>重新加载</Button>}/>}

   <ResidueLineReview features={features} preview={preview} cleanupDisplay={cleanupPlan.plan?.text_residue_display} projectId={project.project_id} assetId={asset.asset_id} busy={disabled} explicitCounts cleanupDisabled={!sourceReady||!cleanupPlan.plan||!cleanupPlan.plan.cleanup_preview?.has_changes} cleanupActionRef={children?cleanupActionRef:undefined} checked={checked} verified={verified} onChecked={setChecked} onVerified={setVerified} onLocate={onLocate} guard={guard} onDecided={()=>open(target)} onCleanup={()=>void cleanup()}/>
  </section>}
 </section>;
 const review={targetId:target,content,cleanupActionRef,locked:busy||cleanupBusy,report,open,close};
 return children?children(review):content;
}
