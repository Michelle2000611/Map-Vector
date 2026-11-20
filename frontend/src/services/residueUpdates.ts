import type {EditResult,ResidueUpdate,TextLayerAssessmentReport} from './models';
import {useWorkspace} from '../stores/workspace';

export type ResidueUpdateEntry=ResidueUpdate&{projectId:string;session:number};
export function validResidueUpdate(value:ResidueUpdate|null|undefined,assetId:string,resultRevision:number):value is ResidueUpdate{
 if(!value||!value.assessment||value.asset_id!==assetId||!Number.isSafeInteger(value.base_revision)||value.base_revision<0||value.result_revision!==value.base_revision+1||value.result_revision!==resultRevision||value.assessment?.working_revision!==resultRevision||!Array.isArray(value.text_feature_ids)||!Array.isArray(value.assessment.items))return false;
 if(value.text_feature_ids.some(id=>typeof id!=='string'||!id)||value.assessment.items.some(item=>!item||typeof item.text_feature_id!=='string'))return false;
 const ids=new Set(value.text_feature_ids),items=value.assessment.items;
 return ids.size===value.text_feature_ids.length&&items.length===ids.size&&new Set(items.map(item=>item.text_feature_id)).size===items.length&&items.every(item=>ids.has(item.text_feature_id));
}
/** A bounded session journal bridges batched React renders and sequential commands. */
export function publishResidueUpdate(result:Pick<EditResult,'result_revision'|'residue_update'>){
 const state=useWorkspace.getState(),update=result.residue_update;
 if(!state.project||!state.asset||!validResidueUpdate(update,state.asset.asset_id,result.result_revision)||state.project.working_revision<update.base_revision||state.project.working_revision>update.result_revision)return false;
 const entry={...update,projectId:state.project.project_id,session:state.session};
 state.setResidueUpdates(previous=>previous.some(item=>item.projectId===entry.projectId&&item.session===entry.session&&item.asset_id===entry.asset_id&&item.result_revision===entry.result_revision)?previous:[...previous,entry].slice(-64));
 return true;
}
export function residueRevisionCovered(from:number,updates:ResidueUpdate[],assetId:string,target:number){
 if(from>target)return false;
 for(let revision=from;revision<target;revision++)if(!validResidueUpdate(updates.find(item=>item.asset_id===assetId&&item.base_revision===revision),assetId,revision+1))return false;
 return true;
}
export function replaceResidueAssessments(report:TextLayerAssessmentReport,patch:TextLayerAssessmentReport){
 if(report.working_revision!==patch.working_revision)return null;
 const byId=new Map(patch.items.map(item=>[item.text_feature_id,item]));
 const items=report.items.map(item=>byId.get(item.text_feature_id)??item);
 return {...report,items,summary:{...report.summary,text_count:items.length,content_auto_accepted:items.filter(item=>item.content_status==='auto_accepted_unverified').length,content_review_required:items.filter(item=>item.content_status==='required').length,cleanup_review_required:items.filter(item=>item.cleanup_status==='review_required').length}};
}
/** No revision can be skipped: foreign/unknown edits must invalidate the old check. */
export function mergeResidueAssessment(report:TextLayerAssessmentReport,updates:ResidueUpdate[],assetId:string,targetRevision:number):TextLayerAssessmentReport|null{
 if(report.working_revision===targetRevision)return report;
 if(report.working_revision>targetRevision)return null;
 let current=report;
 while(current.working_revision<targetRevision){
  const update=updates.find(item=>item.asset_id===assetId&&item.base_revision===current.working_revision);
  if(!validResidueUpdate(update,assetId,current.working_revision+1)||update.result_revision>targetRevision)return null;
  const byId=new Map(update.assessment.items.map(item=>[item.text_feature_id,item]));
  const items=current.items.map(item=>byId.get(item.text_feature_id)??item);
  const existing=new Set(current.items.map(item=>item.text_feature_id));
  if(update.assessment.items.some(item=>!existing.has(item.text_feature_id)))return null;
  current={...current,working_revision:update.result_revision,items,summary:{...current.summary,text_count:items.length,content_auto_accepted:items.filter(item=>item.content_status==='auto_accepted_unverified').length,content_review_required:items.filter(item=>item.content_status==='required').length,cleanup_review_required:items.filter(item=>item.cleanup_status==='review_required').length}};
 }
 return current;
}
