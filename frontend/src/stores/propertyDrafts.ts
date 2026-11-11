import {useSyncExternalStore} from 'react';

export type PropertyValues={text:string;fontSize:number;angle:number;color:string;width:number;role:string;moveX:number;moveY:number;styleId:string|undefined;styleName:string;pattern:string;dash:string;toothSpacing:number;toothHeight:number;toothSide:string};
export type DraftField=keyof PropertyValues;
export type DraftValues=Partial<PropertyValues>&{inputs?:Partial<Record<DraftField,string>>};
export type DraftScope={projectId:string;assetId:string;layer:string;featureIds:string[]};
type Entry={scope:DraftScope;values:DraftValues;updated:number};
const storageKey='mapvector.property-drafts.v1';
const numericBounds:Partial<Record<DraftField,[number,number]>>={fontSize:[1,200],angle:[-180,180],moveX:[-Infinity,Infinity],moveY:[-Infinity,Infinity],width:[.25,50],toothSpacing:[2,200],toothHeight:[.5,50]};
const listeners=new Set<()=>void>();
let storageAvailable=true;
let restoreError='';
let entries:Record<string,Entry>={};
export function draftScopeKey(scope:DraftScope){return JSON.stringify([scope.projectId,scope.assetId,scope.layer,[...scope.featureIds].sort()]);}
const stringFields=new Set(['text','color','role','styleId','styleName','pattern','dash','toothSide']);
function object(value:unknown):value is Record<string,unknown>{return !!value&&typeof value==='object'&&!Array.isArray(value);}
function validEntry(key:string,value:unknown):value is Entry{
 if(!object(value)||!object(value.scope)||!object(value.values)||typeof value.updated!=='number'||!Number.isFinite(value.updated))return false;
 const {scope,values}=value;
 if(typeof scope.projectId!=='string'||!scope.projectId||typeof scope.assetId!=='string'||!scope.assetId||!['face','line','text','isolated_line'].includes(String(scope.layer))||!Array.isArray(scope.featureIds)||scope.featureIds.some(id=>typeof id!=='string'||!id)||new Set(scope.featureIds).size!==scope.featureIds.length)return false;
 if(key!==draftScopeKey(scope as DraftScope))return false;
 for(const [field,item] of Object.entries(values)){
  if(field==='inputs'){if(!object(item)||Object.entries(item).some(([name,raw])=>(!numericBounds[name as DraftField]&&name!=='color')||typeof raw!=='string'))return false;}
  else if(numericBounds[field as DraftField]){const [min,max]=numericBounds[field as DraftField]!;if(typeof item!=='number'||!Number.isFinite(item)||item<min||item>max)return false;}
  else if(!stringFields.has(field)||typeof item!=='string'||(field==='color'&&!/^#[0-9a-f]{6}$/i.test(item)))return false;
 }
 return true;
}
try{
 const saved:unknown=JSON.parse(localStorage.getItem(storageKey)??'{}');
 if(!object(saved)||Object.entries(saved).some(([key,entry])=>!validEntry(key,entry)))throw Error('Invalid property draft record');
 entries=saved as Record<string,Entry>;
}catch{storageAvailable=false;restoreError='浏览器中的属性草稿无法恢复，原始记录已保留。本页新修改只能暂存，请先提交再离开。';}
function publish(){
 // Do not replace unreadable records with an empty or partial recovery.
 if(!restoreError)try{localStorage.setItem(storageKey,JSON.stringify(entries));storageAvailable=true;}catch{storageAvailable=false;}
 for(const notify of listeners)notify();
}
const subscribe=(notify:()=>void)=>{listeners.add(notify);return()=>{listeners.delete(notify);};};
export function propertyDraftCount(projectId?:string,assetId?:string){return Object.values(entries).filter(entry=>(!projectId||entry.scope.projectId===projectId)&&(!assetId||entry.scope.assetId===assetId)).length;}
export function usePropertyDraftCount(projectId?:string,assetId?:string){useSyncExternalStore(subscribe,()=>entries);return propertyDraftCount(projectId,assetId);}
export function usePropertyDraftStatus(){useSyncExternalStore(subscribe,()=>storageAvailable);return {persistent:storageAvailable,restoreError};}
export function propertyDraftScopes(projectId:string,assetId:string){return Object.values(entries).filter(entry=>entry.scope.projectId===projectId&&entry.scope.assetId===assetId).sort((a,b)=>b.updated-a.updated).map(entry=>entry.scope);}

function resolveDraft(defaults:PropertyValues,submitted:DraftValues|undefined){
 const values={...defaults,...submitted},invalidFields:DraftField[]=[];
 // Number('') and Number('-') must never turn an unfinished input into a write.
 for(const [name,raw] of Object.entries(submitted?.inputs??{})){const field=name as DraftField,bounds=numericBounds[field];if(raw===undefined)continue;if(bounds){const number=Number(raw);if(raw.trim()&&Number.isFinite(number)&&number>=bounds[0]&&number<=bounds[1])Object.assign(values,{[field]:number});else invalidFields.push(field);}else if(field==='color'){if(/^#[0-9a-f]{6}$/i.test(raw.trim()))values.color=raw.trim();else invalidFields.push(field);}}
 return {values,invalidFields,submitted};
}

/** Only explicit input creates a draft. Server refreshes provide defaults, never overwrite it. */
export function usePropertyDrafts(scope:DraftScope,defaults:PropertyValues){
 useSyncExternalStore(subscribe,()=>entries);
 const key=draftScopeKey(scope),entry=entries[key],{values,invalidFields}=resolveDraft(defaults,entry?.values);
 function update(patch:DraftValues){const old=entries[key],next={...old?.values,...patch};if(next.inputs&&!Object.keys(next.inputs).length)delete next.inputs;entries={...entries};if(Object.keys(next).length)entries[key]={scope:{...scope,featureIds:[...scope.featureIds]},values:next,updated:Date.now()};else delete entries[key];publish();}
 function set<K extends DraftField>(field:K,value:PropertyValues[K]){update({[field]:value});}
 function input(field:DraftField,value:string|undefined){if(value===undefined&&entries[key]?.values.inputs?.[field]===undefined)return;const inputs={...entries[key]?.values.inputs};if(value===undefined)delete inputs[field];else inputs[field]=value;update({inputs});}
 function capture(){return entries[key]?.values;}
 // Clear just the fields this request actually saved, and preserve input typed while it ran.
 function saved(fields:DraftField[],submitted:DraftValues|undefined){if(!submitted)return;const old=entries[key];if(!old)return;const next={...old.values},inputs={...next.inputs};for(const field of fields){if(Object.is(next[field],submitted[field]))delete next[field];if(inputs[field]===submitted.inputs?.[field])delete inputs[field];}if(Object.keys(inputs).length)next.inputs=inputs;else delete next.inputs;entries={...entries};if(Object.keys(next).length)entries[key]={...old,values:next};else delete entries[key];publish();}
 // A blur or selection event can flush before React renders the last keystroke.
 function read(){return resolveDraft(defaults,entries[key]?.values);}
 return {values,set,input,inputValue:(field:DraftField)=>entry?.values.inputs?.[field],capture,saved,read,invalidFields,dirty:!!entry,count:propertyDraftCount(scope.projectId,scope.assetId),persistent:storageAvailable};
}
