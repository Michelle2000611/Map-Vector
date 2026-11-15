import {useEffect,useState} from 'react';
import {request} from '../services/client';
import type {Page} from '../services/models';
import {useWorkspace} from '../stores/workspace';

export type FeatureHistoryItem={operation_id:string;operation_type:string;operation_status:string;result_revision:number;created_at:string;project_id?:string;asset_id?:string;feature_id?:string};
type Context={projectId:string;assetId?:string;featureId?:string;active:boolean};
type HistoryState={key:string;items:FeatureHistoryItem[]|null;error:boolean};

export function useFeatureHistory({projectId,assetId,featureId,active}:Context){
 const session=useWorkspace(state=>state.session);
 const workspaceAssetId=useWorkspace(state=>state.asset?.asset_id);
 const revision=useWorkspace(state=>state.project?.project_id===projectId?state.project.working_revision:null);
 const featureRevision=useWorkspace(state=>featureId?state.featuresById[featureId]?.revision:undefined);
 const currentAssetId=assetId??workspaceAssetId;
 const key=JSON.stringify([projectId,currentAssetId,session,featureId,revision,featureRevision]);
 const [history,setHistory]=useState<HistoryState|null>(null);
 useEffect(()=>{
  if(!active||!featureId)return;
  const controller=new AbortController();let live=true;
  setHistory(null);
  request<Page<FeatureHistoryItem>>('/projects/'+encodeURIComponent(projectId)+'/feature-history?feature_id='+encodeURIComponent(featureId),undefined,controller.signal,{quiet:true})
   .then(result=>{
    if(!live)return;
    if(!Array.isArray(result?.items))throw new Error('Invalid feature history');
    const items=result.items.filter(item=>item&&typeof item.operation_id==='string'&&Number.isFinite(item.result_revision)&&(!item.project_id||item.project_id===projectId)&&(!item.asset_id||item.asset_id===currentAssetId)&&(!item.feature_id||item.feature_id===featureId)).sort((a,b)=>b.result_revision-a.result_revision);
    setHistory({key,items,error:false});
   })
   .catch(()=>{if(live)setHistory({key,items:null,error:true});});
  return()=>{live=false;controller.abort();};
 },[active,key,projectId,currentAssetId,featureId]);
 const current=active&&history?.key===key?history:null;
 const items=current?.items??null;
 const latestTime=items?.find(item=>item.created_at&&Number.isFinite(new Date(item.created_at).getTime()))?.created_at;
 return {items,error:current?.error??false,latestTime};
}
