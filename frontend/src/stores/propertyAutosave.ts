import type {Command,CommandInput,Feature,TextFeature} from '../services/models';
import type {DraftField,DraftScope,DraftValues,PropertyValues,usePropertyDrafts} from './propertyDrafts';

export type PropertyDrafts=ReturnType<typeof usePropertyDrafts>;
export type AutosaveInput={scope:DraftScope;features:Feature[];drafts:PropertyDrafts;command:Command;delayMs?:number;assetSize?:{width:number;height:number};generation?:number};
export type AutosaveStatus='idle'|'pending'|'saving'|'saved'|'invalid'|'error';
type Snapshot={status:AutosaveStatus;error:string};
type Clock={setTimeout:(fn:()=>void,ms:number)=>ReturnType<typeof setTimeout>;clearTimeout:(id:ReturnType<typeof setTimeout>)=>void};
const fieldsFor=(layer:string):DraftField[]=>layer==='text'?['text','fontSize','angle','color','moveX','moveY']:layer==='face'?['color']:['color','width','role'];
const scopeKey=(scope:DraftScope)=>JSON.stringify([scope.projectId,scope.assetId,scope.layer,[...scope.featureIds].sort()]);
const contextKey=(input:AutosaveInput)=>JSON.stringify([input.generation??0,scopeKey(input.scope)]);
const same=(a:unknown,b:unknown)=>typeof a==='string'&&typeof b==='string'&&a.startsWith('#')&&b.startsWith('#')?a.toLowerCase()===b.toLowerCase():Object.is(a,b);
const canonical=(field:DraftField,value:unknown)=>field==='text'&&typeof value==='string'?value.trim():field==='angle'&&value===180?-180:value;
function valid(field:DraftField,value:unknown){
 if(field==='color')return typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value);
 if(field==='text')return typeof value==='string'&&!!value.trim()&&[...value].length<=200;
 if(field==='role')return ['unknown','cover','split'].includes(String(value));
 if(typeof value!=='number'||!Number.isFinite(value))return false;
 if(field==='fontSize')return value>=1&&value<=200;
 if(field==='angle')return value>=-180&&value<=180;
 if(field==='width')return value>=.25&&value<=50;
 if(field==='moveX'||field==='moveY')return value>=0;
 return true;
}
function original(feature:Feature,field:DraftField):unknown{
 if(field==='color')return feature.feature_type==='text'?feature.text_color:feature.feature_type==='face'?feature.fill_color:feature.stroke_color;
 if(feature.feature_type==='text')return field==='text'?feature.text_value:field==='fontSize'?feature.font_size_px:field==='angle'?feature.rotation_deg:field==='moveX'?feature.geometry.coordinates[0]:field==='moveY'?feature.geometry.coordinates[1]:undefined;
 if(feature.feature_type==='line')return field==='width'?feature.stroke_width_px:field==='role'?feature.line_role:undefined;
}
function textPreview(feature:TextFeature,changes:Partial<PropertyValues>):TextFeature{
 const next={...feature,geometry:{...feature.geometry,coordinates:[...feature.geometry.coordinates]}} as TextFeature;
 const ratio=changes.fontSize===undefined?1:changes.fontSize/feature.font_size_px;
 const [oldX,oldY]=feature.geometry.coordinates,[x,y]=[changes.moveX??oldX,changes.moveY??oldY];
 next.geometry={...feature.geometry,coordinates:[x,y]};
 if(changes.text!==undefined){next.text_value=changes.text;next.layout_runs=[];next.layout_width_px=null;next.layout_height_px=null;next.baseline_offset_px=null;next.display_bbox_px=null;}
 else{
  if(ratio!==1){next.layout_runs=feature.layout_runs?.map(run=>({...run,font_size_px:run.font_size_px*ratio,x_offset_px:run.x_offset_px*ratio,baseline_offset_px:run.baseline_offset_px*ratio,width_px:run.width_px*ratio}));if(feature.layout_width_px!=null)next.layout_width_px=feature.layout_width_px*ratio;if(feature.layout_height_px!=null)next.layout_height_px=feature.layout_height_px*ratio;if(feature.baseline_offset_px!=null)next.baseline_offset_px=feature.baseline_offset_px*ratio;}
  if(feature.display_bbox_px){
   const [x0,y0,x1,y1]=feature.display_bbox_px,angle=-((changes.angle??feature.rotation_deg)-feature.rotation_deg)*Math.PI/180,cos=Math.cos(angle),sin=Math.sin(angle);
   // This display-only envelope follows the rotation without rewriting saved layout.
   const corners=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]].map(([px,py])=>{const dx=(px-oldX)*ratio,dy=(py-oldY)*ratio;return [x+dx*cos-dy*sin,y+dx*sin+dy*cos];});
   next.display_bbox_px=[Math.min(...corners.map(p=>p[0])),Math.min(...corners.map(p=>p[1])),Math.max(...corners.map(p=>p[0])),Math.max(...corners.map(p=>p[1]))];
  }
 }
 if(changes.fontSize!==undefined)next.font_size_px=changes.fontSize;
 if(changes.angle!==undefined)next.rotation_deg=changes.angle;
 if(changes.color!==undefined)next.text_color=changes.color;
 return next;
}

/** Build only explicitly edited, valid fields; a bulk selection remains one command. */
export function buildPropertyPatch(scope:DraftScope,features:Feature[],values:PropertyValues,submitted:DraftValues|undefined,invalidFields:DraftField[]=[],assetSize?:{width:number;height:number}){
 const ids=new Set(scope.featureIds),targets=features.filter(feature=>ids.has(feature.feature_id)&&feature.feature_type===(scope.layer==='isolated_line'?'line':scope.layer));
 const fields=fieldsFor(scope.layer).filter(field=>Object.prototype.hasOwnProperty.call(submitted??{},field)||Object.prototype.hasOwnProperty.call(submitted?.inputs??{},field));
 const invalid=fields.length>0&&(targets.length!==ids.size||!targets.length||(scope.layer==='text'&&scope.featureIds.length!==1)||fields.some(field=>invalidFields.includes(field)||!valid(field,values[field])||(field==='moveX'&&assetSize&&values.moveX>assetSize.width)||(field==='moveY'&&assetSize&&values.moveY>assetSize.height)));
 const changes:Partial<PropertyValues>={};
 for(const field of fields){const value=canonical(field,values[field]);if(!invalidFields.includes(field)&&valid(field,values[field])&&targets.some(feature=>!same(canonical(field,original(feature,field)),value)))Object.assign(changes,{[field]:value});}
 let command:CommandInput|null=null;
 if(targets.length===ids.size&&targets.length&&Object.keys(changes).length&&!invalid){
  if(scope.layer==='text'){
   const body:Record<string,unknown>={operation_type:'update_text',feature_ids:[...scope.featureIds]};
   const map:Partial<Record<DraftField,string>>={text:'text_value',fontSize:'font_size_px',angle:'rotation_deg',color:'text_color',moveX:'x',moveY:'y'};
   for(const field of Object.keys(changes) as DraftField[])body[map[field]!]=changes[field];
   command=body as CommandInput;
  }else{
   command={operation_type:'set_feature_properties',feature_ids:[...scope.featureIds],feature_type:scope.layer==='face'?'face':'line',...(changes.color===undefined?{}:{color:changes.color}),...(changes.width===undefined?{}:{stroke_width_px:changes.width}),...(changes.role===undefined?{}:{line_role:changes.role})} as unknown as CommandInput;
  }
 }
 let previewFeature:Feature|undefined;
 if(targets.length===1&&scope.featureIds.length===1&&Object.keys(changes).length){const feature=targets[0];previewFeature=feature.feature_type==='text'?textPreview(feature,changes):feature.feature_type==='face'?{...feature,fill_color:changes.color??feature.fill_color}:{...feature,stroke_color:changes.color??feature.stroke_color,stroke_width_px:changes.width??feature.stroke_width_px,line_role:(changes.role??feature.line_role) as typeof feature.line_role};}
 return {command,fields,submitted,previewFeature,invalid};
}
type DraftRead=ReturnType<PropertyDrafts['read']>;
type Context={input:AutosaveInput;composing:boolean;version:string;captured?:DraftRead;previous?:Context;error?:string;failed?:{signature:string;key:string;plan:ReturnType<typeof buildPropertyPatch>;input:AutosaveInput};flight?:Promise<boolean>};

/** Independent controller keeps captures bound to their original object during selection changes. */
export class PropertyAutosave {
 private context:Context|undefined;
 private timer:ReturnType<typeof setTimeout>|undefined;
 private state:Snapshot={status:'idle',error:''};
 private listeners=new Set<()=>void>();
 private contexts=new Map<string,Context>();
 constructor(private clock:Clock={setTimeout:(fn,ms)=>setTimeout(fn,ms),clearTimeout:id=>clearTimeout(id)}){}
 subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 getSnapshot=()=>this.state;
 private publish(status:AutosaveStatus,error=''){if(this.state.status===status&&this.state.error===error)return;this.state={status,error};for(const listener of this.listeners)listener();}
 private clearTimer(){if(this.timer!==undefined)this.clock.clearTimeout(this.timer);this.timer=undefined;}
 private plan(context:Context){const {input}=context,{values,submitted,invalidFields}=context.captured??input.drafts.read();return buildPropertyPatch(input.scope,input.features,values,submitted,invalidFields,input.assetSize);}
 private detach(context:Context){
  // A detached save owns only input that existed when the selection changed.
  // Returning to this object starts a new context and must not extend this capture.
  context.captured=structuredClone(context.input.drafts.read());
 }
 private acknowledged(context:Context,fields:DraftField[],submitted:DraftValues|undefined){
  if(!context.captured||!submitted)return;
  const next={...context.captured.submitted},inputs={...next.inputs};
  for(const field of fields){if(Object.is(next[field],submitted[field]))delete next[field];if(inputs[field]===submitted.inputs?.[field])delete inputs[field];}
  if(Object.keys(inputs).length)next.inputs=inputs;else delete next.inputs;
  context.captured={...context.captured,submitted:next};
 }
 private predecessor(context:Context|undefined):Context|undefined{
  if(!context)return;
  const plan=this.plan(context);
  if(context.flight||context.failed||(!context.composing&&!plan.invalid&&plan.command))return context;
  // Invalid/IME drafts remain in the store and can be repaired after returning.
  return this.predecessor(context.previous);
 }
 private prune(context:Context){
  if(context===this.context||context.flight||context.failed||context.previous)return;
  const plan=this.plan(context);
  if(!context.composing&&!plan.invalid&&plan.command)return;
  const key=contextKey(context.input);
  if(this.contexts.get(key)===context)this.contexts.delete(key);
 }
 update(input:AutosaveInput){
  const previousContext=this.context;let context=this.context;
  if(context&&(context.input.generation??0)!==(input.generation??0)){
   // Runtime sessions own command closures; persistent drafts own logical scopes.
   // Keep the drafts, but never retry an obsolete session's command after reload.
   this.clearTimer();this.detach(context);this.contexts.clear();context=undefined;
  }else if(context&&contextKey(context.input)!==contextKey(input)){
   this.clearTimer();const old=context;this.detach(old);
   if(!old.composing&&!old.failed)void this.drain(old);
   context=undefined;
  }
  if(!context){const previous=this.predecessor(this.contexts.get(contextKey(input)));this.context=context={input,composing:false,version:'',previous};this.contexts.set(contextKey(input),context);}else context.input=input;
  if(previousContext&&previousContext!==context)this.prune(previousContext);
  const plan=this.plan(context),version=JSON.stringify([plan.command,plan.invalid,plan.submitted]);
  if(version===context.version)return;
  context.version=version;this.clearTimer();
  if(context.flight){this.publish('saving');return;}
  this.schedule(context);
 }
 private schedule(context:Context){
  if(context.input.scope.featureIds.length!==1){this.publish('idle');return;}
  // Until an unknown outcome is resolved, even the old value may be a new edit.
  if(context.failed){this.publish('error',context.error??'');return;}
  // Do not acknowledge against a baseline that an earlier capture may still change.
  if(context.previous){
   this.publish(context.previous.failed?'error':'pending',context.previous.error??'');
   if(!context.composing&&!context.previous.failed)this.timer=this.clock.setTimeout(()=>{this.timer=undefined;void this.drain(context);},context.input.delayMs??600);
   return;
  }
  const plan=this.plan(context);
  if(plan.invalid){this.publish('invalid');return;}
  if(!plan.command){if(plan.fields.length)context.input.drafts.saved(plan.fields,plan.submitted);this.publish(this.state.status==='saved'?'saved':'idle');return;}
  this.publish('pending');
  if(!context.composing)this.timer=this.clock.setTimeout(()=>{this.timer=undefined;void this.drain(context);},context.input.delayMs??600);
 }
 private save(context:Context,retryFailed=false):Promise<boolean>{
  if(context.input.scope.featureIds.length!==1)return Promise.resolve(true);
  if(context.flight)return context.flight;
  if(context.failed&&!retryFailed)return Promise.resolve(false);
  const failed=retryFailed?context.failed:undefined,plan=failed?.plan??this.plan(context);
  if(context.composing||plan.invalid){if(context===this.context)this.publish(plan.invalid?'invalid':'pending');return Promise.resolve(false);}
  if(!plan.command){if(plan.fields.length)context.input.drafts.saved(plan.fields,plan.submitted);return Promise.resolve(true);}
  const signature=JSON.stringify(plan.command),key=failed?.key??crypto.randomUUID();
  if(context===this.context)this.publish('saving');
  const input=failed?.input??context.input;
  context.flight=(async()=>{
   try{
    const result=await input.command(plan.command!,{quiet:true,idempotencyKey:key});
    if(!result)throw Error('项目或原图已切换，草稿仍保留。');
    const updated=new Map((result.upserted_features??[]).map(feature=>[feature.feature_id,feature]));
    // This also lets a flush drain new input before React publishes the response.
    context.input={...context.input,features:context.input.features.map(feature=>updated.get(feature.feature_id)??feature)};
    input.drafts.saved(plan.fields,plan.submitted);this.acknowledged(context,plan.fields,plan.submitted);context.failed=undefined;context.error=undefined;
    if(context===this.context)this.publish('saved');
    return true;
   }catch(error){context.failed={signature,key,plan,input};context.error=error instanceof Error?error.message:String(error);if(context===this.context)this.publish('error',context.error);return false;}
   finally{context.flight=undefined;if(context===this.context&&!context.failed){context.version='';this.clearTimer();this.schedule(context);}}
  })();
  return context.flight;
 }
 private async drain(context:Context){
  if(context.input.scope.featureIds.length!==1)return true;
  if(context.previous){const previous=context.previous;if(!await this.drain(previous)){context.error=previous.error;if(context===this.context)this.publish('error',context.error);return false;}const updated=new Map(previous.input.features.map(feature=>[feature.feature_id,feature]));context.input={...context.input,features:context.input.features.map(feature=>updated.get(feature.feature_id)??feature)};context.previous=undefined;}
  if(context.composing)return false;
  if(context.failed)return false;
  while(true){if(context.flight&&!await context.flight)return false;if(context===this.context)this.clearTimer();const plan=this.plan(context);if(plan.invalid){if(context===this.context)this.publish('invalid');this.prune(context);return false;}if(!plan.command){if(plan.fields.length){context.input.drafts.saved(plan.fields,plan.submitted);this.acknowledged(context,plan.fields,plan.submitted);}this.prune(context);return true;}if(!await this.save(context))return false;}
 }
 private async drainScope(context:Context,retry:boolean){
  const scope=context.input.scope;
  const otherPending=()=>[...this.contexts.values()].filter(item=>item!==context&&(item.input.generation??0)===(context.input.generation??0)&&item.input.scope.projectId===scope.projectId&&item.input.scope.assetId===scope.assetId).map(item=>this.predecessor(item)).filter((item):item is Context=>!!item);
  let waited=false;
  do{
   // A history action must wait for every old object's tail, including saves
   // started by a selection path that did not await the panel's own flush.
   for(const pending of otherPending()){
    waited=true;if(context===this.context)this.publish('saving');
    const okay=retry?await this.retryContext(pending):await this.drain(pending);
    if(!okay){if(context===this.context)this.publish('error',pending.error??'之前选中对象的属性尚未保存，请重试。');return false;}
   }
   if(!await (retry?this.retryContext(context):this.drain(context)))return false;
  }while(otherPending().length);
  if(waited&&context===this.context)this.publish('saved');
  return true;
 }
 flush=async()=>{this.clearTimer();const context=this.context;return context?this.drainScope(context,false):true;};
 private async retryContext(context:Context):Promise<boolean>{if(context.previous&&!await this.retryContext(context.previous))return false;if(context.failed&&!await this.save(context,true))return false;return this.drain(context);}
 retry=async()=>{const context=this.context;if(!context)return true;this.clearTimer();return this.drainScope(context,true);};
 onCompositionStart=()=>{if(this.context)this.context.composing=true;this.clearTimer();};
 onCompositionEnd=()=>{if(this.context){this.context.composing=false;this.clearTimer();this.schedule(this.context);}};
 onBlur=()=>{void this.flush();};
 dispose=()=>{this.clearTimer();const context=this.context;if(context){this.detach(context);this.context=undefined;if(!context.composing&&!context.failed)void this.drain(context);}this.listeners.clear();};
}
