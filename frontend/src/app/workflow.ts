// UI stages are independent from legacy persisted stage IDs.
export const stages=['import','recognition','editing','quality','export'];
export const titles=['项目底图','识别任务','编辑审核','质量范围','保存导出'];
export const persistedToUi=(stage:number)=>stage<=1?Math.max(0,stage):stage<=3?2:stage===4?3:4;
export const uiToPersisted=(stage:number)=>[0,1,2,4,5][Math.max(0,Math.min(4,stage))];
export type EditingMode='geometry'|'review';
export function editingUrl(projectId:string,mode:EditingMode){return '/projects/'+projectId+'/editing'+(mode==='review'?'?mode=review':'');}
