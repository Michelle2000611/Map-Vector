import {useEffect,useRef,useState} from 'react';
import {ApiError,request} from '../services/client';
import {captureTextFormat} from '../services/textFormat';
import type {TextFormatSource} from '../services/textFormat';
import {textStyleFields} from '../services/textStyles';
import type {TextStyleField} from '../services/textStyles';
import {useWorkspace} from '../stores/workspace';
import type {Command,CommandInput,Point,Style,Work,Page} from '../services/models';

type Options={projectId:string;assetId:string;session:number;layer:string;enabled:boolean;styles:Style[];onStylesChanged:(styles:Style[])=>void;flush:()=>Promise<boolean>;command:Command;work:Work;onEnter:()=>void;onSampled:(id:string)=>void;onApplied:(ids:string[])=>void};
export function useTextFormatBrush({projectId,assetId,session,layer,enabled,styles,onStylesChanged,flush,command,work,onEnter,onSampled,onApplied}:Options){
 const [source,setSource]=useState<TextFormatSource|null>(null),[styleId,setStyleId]=useState<string>(),[copySize,setCopySize]=useState(true),[copyColor,setCopyColor]=useState(true),[copyRotation,setCopyRotation]=useState(false),[copyText,setCopyText]=useState(false),[pending,setPending]=useState(false),[error,setError]=useState('');
 const baseScope=JSON.stringify([projectId,assetId,session]),scope=JSON.stringify([baseScope,layer,enabled,styleId,copySize,copyColor,copyRotation,copyText]);
 const current=useRef(scope),sample=useRef(source),stylesRef=useRef(styles),mounted=useRef(false),serial=useRef(0),inFlight=useRef(false),controller=useRef<AbortController|null>(null),retry=useRef<{payload:string;key:string}|null>(null),saveRetry=useRef<{payload:string;createKey:string;bindKey:string;style?:Style}|null>(null);current.current=scope;stylesRef.current=styles;
 const selectedStyle=styles.find(style=>style.style_id===styleId&&style.feature_type==='text');
 const selectionIdentity=useWorkspace(state=>JSON.stringify(state.selected.map(id=>[id,state.featuresById[id]?.style_id])));
 const adoptedBinding=useRef<string>();
 function cancel(){serial.current++;controller.current?.abort();controller.current=null;inFlight.current=false;if(mounted.current)setPending(false);}
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;serial.current++;controller.current?.abort();};},[]);
 useEffect(()=>{cancel();},[scope]);
 useEffect(()=>{sample.current=null;setSource(null);setStyleId(undefined);setCopySize(true);setCopyColor(true);setCopyRotation(false);setCopyText(false);setError('');retry.current=null;saveRetry.current=null;},[baseScope]);
 useEffect(()=>{if(styleId&&!styles.some(style=>style.style_id===styleId&&style.feature_type==='text')){setStyleId(undefined);retry.current=null;}},[styles,styleId]);
 function same(expected:string){const state=useWorkspace.getState();return mounted.current&&current.current===expected&&state.session===session&&state.project?.project_id===projectId&&state.asset?.asset_id===assetId&&state.layer==='text';}
 function begin(){if(inFlight.current)return null;const expected=scope,ticket=++serial.current;inFlight.current=true;setPending(true);setError('');return {expected,ticket};}
 function requested(job:{expected:string;ticket:number}){return serial.current===job.ticket&&same(job.expected);}
 function finish(job:{expected:string;ticket:number}){if(serial.current===job.ticket){inFlight.current=false;controller.current=null;if(mounted.current)setPending(false);}}
 async function prepare(job:{expected:string;ticket:number}){if(!await flush()){if(requested(job))setError('属性草稿未能保存，请先修正或重试保存。');return false;}return requested(job);}
 function saveSample(id:string){const feature=useWorkspace.getState().featuresById[id];if(!feature||feature.feature_type!=='text'||feature.lifecycle_status!=='active')throw Error('此处没有可取样的文字。');const captured=captureTextFormat(feature);sample.current=captured;setSource(captured);setStyleId(undefined);retry.current=null;onSampled(id);onEnter();}
 function startSampling(){cancel();sample.current=null;setSource(null);setStyleId(undefined);setCopySize(true);setCopyColor(true);setCopyRotation(false);setCopyText(false);setError('');retry.current=null;onEnter();}
 function chooseStyle(id:string|undefined,brush=false){cancel();adoptedBinding.current=baseScope+selectionIdentity;const style=stylesRef.current.find(item=>item.style_id===id&&item.feature_type==='text');setStyleId(style?.style_id);setError('');retry.current=null;if(style){setCopySize(style.font_size_px!=null);setCopyColor(style.text_color!=null);setCopyRotation(style.rotation_deg!=null);}setCopyText(false);if(brush&&style)onEnter();}
 useEffect(()=>{const key=baseScope+selectionIdentity;if(inFlight.current||sample.current||styleId||adoptedBinding.current===key)return;const state=useWorkspace.getState(),ids=state.selected,binding=ids.length?state.featuresById[ids[0]]?.style_id:undefined;if(binding&&ids.every(id=>state.featuresById[id]?.feature_type==='text'&&state.featuresById[id]?.style_id===binding)&&stylesRef.current.some(style=>style.style_id===binding&&style.feature_type==='text')){adoptedBinding.current=key;chooseStyle(binding);}},[baseScope,selectionIdentity,styles]);
 function selectedFields(style?:Style):TextStyleField[]{const available:TextStyleField[]=style?textStyleFields(style):['font_size_px','text_color','rotation_deg'];return available.filter(field=>field==='font_size_px'?copySize:field==='text_color'?copyColor:copyRotation);}
 async function execute(body:CommandInput){const payload=JSON.stringify(body);if(retry.current?.payload!==payload)retry.current={payload,key:crypto.randomUUID()};try{return await command(body,{quiet:true,idempotencyKey:retry.current.key});}catch(exc){if(exc instanceof ApiError&&['REVISION_CONFLICT','RESOURCE_NOT_FOUND','IDEMPOTENCY_CONFLICT'].includes(exc.code))retry.current=null;throw exc;}}
 async function saveCommand(body:CommandInput,attempt:NonNullable<typeof saveRetry.current>,stage:'createKey'|'bindKey'){try{return await command(body,{quiet:true,idempotencyKey:attempt[stage]});}catch(exc){if(exc instanceof ApiError&&['REVISION_CONFLICT','RESOURCE_NOT_FOUND','IDEMPOTENCY_CONFLICT'].includes(exc.code)){attempt[stage]=crypto.randomUUID();if(stage==='bindKey'&&exc.code==='RESOURCE_NOT_FOUND'){attempt.style=undefined;attempt.createKey=crypto.randomUUID();}}throw exc;}}
 async function submit(ids:string[],job:{expected:string;ticket:number},revision:number){
  if(!requested(job))return;const state=useWorkspace.getState(),captured=sample.current,style=stylesRef.current.find(item=>item.style_id===styleId&&item.feature_type==='text');
  if(state.project?.working_revision!==revision)throw Error('项目已更新，请重新选择目标文字。');
  const targets=[...new Set(ids)].filter(id=>state.featuresById[id]?.feature_type==='text'&&state.featuresById[id]?.lifecycle_status==='active').sort();
  if(!targets.length){setError('此处没有可应用的文字。');return;}if(targets.length>2000)throw Error('每次最多应用到 2000 条文字，请缩小选择范围。');
  if(!selectedFields(style).length&&!(copyText&&captured))throw Error('请至少勾选一个要应用的项目。');
  let body:CommandInput;
  if(style)body={operation_type:'bind_style',style_id:style.style_id,feature_ids:targets,text_fields:selectedFields(style),...(copyText&&captured?{text_content:captured.sample}:{})};
  else{if(!captured)throw Error('请先在全局格式刷取样文字，或选择文字样式。');body={operation_type:'apply_text_format',feature_ids:targets,sample:captured.sample,copy_size:copySize,copy_color:copyColor,copy_rotation:copyRotation,copy_text:copyText};}
  const result=await execute(body);if(result&&requested(job)){retry.current=null;onApplied(targets);}
 }
 async function applySelected(){const ids=[...useWorkspace.getState().selected],job=begin();if(!job)return;try{await work(async()=>{try{if(!await prepare(job)||JSON.stringify(useWorkspace.getState().selected)!==JSON.stringify(ids))return;await submit(ids,job,useWorkspace.getState().project!.working_revision);}catch(exc){if(requested(job))setError(exc instanceof Error?exc.message:String(exc));}},{quiet:true});}finally{finish(job);}}
 async function saveStyle(name:string):Promise<boolean>{
  const ids=[...useWorkspace.getState().selected],job=begin();if(!job)return false;
  try{return (await work(async()=>{try{
   if(!await prepare(job)||JSON.stringify(useWorkspace.getState().selected)!==JSON.stringify(ids))return false;
   const state=useWorkspace.getState(),feature=ids.length===1?state.featuresById[ids[0]]:undefined,origin=feature?.feature_type==='text'?captureTextFormat(feature):sample.current;
   if(!origin||!selectedFields().length)throw Error('请选择单个文字和需要保存的格式属性。');
   const body:CommandInput={operation_type:'set_style',feature_type:'text',style_name:name.trim(),...(copySize?{font_size_px:origin.sample.font_size_px}:{}),...(copyColor?{text_color:origin.sample.text_color}:{}),...(copyRotation?{rotation_deg:origin.sample.rotation_deg}:{})};
   const payload=JSON.stringify([body,ids]);if(saveRetry.current?.payload!==payload)saveRetry.current={payload,createKey:crypto.randomUUID(),bindKey:crypto.randomUUID()};const attempt=saveRetry.current;
   if(!attempt.style){const result=await saveCommand(body,attempt,'createKey');if(!result)return false;if(!same(job.expected))return false;const library=await request<Page<Style>>('/projects/'+projectId+'/styles',undefined,undefined,{quiet:true});attempt.style=(result.changed_styles??[]).find(style=>style.feature_type==='text')??library.items.find(style=>!stylesRef.current.some(old=>old.style_id===style.style_id)&&style.style_name===name.trim());if(!same(job.expected))return false;onStylesChanged(library.items);}
   const style=attempt.style;if(!style)throw Error('样式已保存，但暂未取得样式编号，请重试。');
   if(JSON.stringify(useWorkspace.getState().selected)!==JSON.stringify(ids))throw Error('样式已保存，选区已变化，尚未绑定对象。');
   if(ids.length){const bound=await saveCommand({operation_type:'bind_style',style_id:style.style_id,feature_ids:ids,text_fields:textStyleFields(style)},attempt,'bindKey');if(!bound)return false;}
   if(!requested(job))return false;saveRetry.current=null;setStyleId(style.style_id);return true;
  }catch(exc){if(requested(job))setError(exc instanceof Error?exc.message:String(exc));return false;}},{quiet:true}))===true;}finally{finish(job);}
 }
 async function gesture(start:Point,end:Point,bounds:number[],zoom:number){
  if(!enabled)return;const job=begin();if(!job)return;
  try{if(!await prepare(job))return;const revision=useWorkspace.getState().project!.working_revision,captured=sample.current,hasStyle=!!stylesRef.current.find(item=>item.style_id===styleId&&item.feature_type==='text'),dragged=Math.abs(end[0]-start[0])*zoom>3||Math.abs(end[1]-start[1])*zoom>3;
   const abort=new AbortController();controller.current=abort;const hit=await request<{feature_ids:string[]}>('/projects/'+projectId+'/selections',{asset_id:assetId,feature_type:'text',lifecycle_status:'active',feature_ids:[],selection_mode:'replace',...((captured||hasStyle)&&dragged?{selection_type:'box',bounds_px:bounds}:{selection_type:'text_pick',x:end[0],y:end[1]})},abort.signal,{quiet:true});
   if(!requested(job))return;if(useWorkspace.getState().project?.working_revision!==revision)throw Error('项目已更新，请重新点选文字。');
   if(!captured&&!hasStyle){if(hit.feature_ids.length!==1)throw Error(hit.feature_ids.length?'此处有多条文字，请点选一条明确的取样文字。':'此处没有可取样的文字。');saveSample(hit.feature_ids[0]);}else await submit(hit.feature_ids,job,revision);
  }catch(exc){if(requested(job)&&!(exc instanceof DOMException&&exc.name==='AbortError'))setError(exc instanceof Error?exc.message:String(exc));}finally{finish(job);}
 }
 function change(setter:(value:boolean)=>void,value:boolean){cancel();retry.current=null;setter(value);}
 return {source,styleId,selectedStyle,copySize,copyColor,copyRotation,copyText,pending,error,cancel,startSampling,chooseStyle,applySelected,saveStyle,gesture,setCopySize:(value:boolean)=>change(setCopySize,value),setCopyColor:(value:boolean)=>change(setCopyColor,value),setCopyRotation:(value:boolean)=>change(setCopyRotation,value),setCopyText:(value:boolean)=>change(setCopyText,value)};
}
