import type {CommandInput} from './models';
export type CommandTarget={projectId:string;assetId:string;session:number};

/** Unknown network outcomes must retry the exact same request, including its revision. */
export class CommandPayloads {
 private entries=new Map<string,{signature:string;body:CommandInput&{asset_id:string;base_revision:number;idempotency_key:string}}>();
 prepare(target:CommandTarget,input:CommandInput,revision:number,key:string){
  const cacheKey=JSON.stringify([target.projectId,target.assetId,target.session,key]),signature=JSON.stringify(input),previous=this.entries.get(cacheKey);
  if(previous){if(previous.signature!==signature)throw Error('同一请求键不能用于不同的编辑。');return previous.body;}
  const body={...structuredClone(input),asset_id:target.assetId,base_revision:revision,idempotency_key:key};
  this.entries.set(cacheKey,{signature,body});return body;
 }
}

/** Each edit starts after the preceding edit has published its new revision. */
export class ProjectCommandQueue {
 private tail:Promise<unknown>=Promise.resolve();
 enqueue<T>(_target:CommandTarget,isCurrent:()=>boolean,execute:()=>Promise<T>):Promise<T>{
  const run=this.tail.catch(()=>{}).then(()=>{
   if(!isCurrent())throw new DOMException('项目或原图已切换，草稿仍保留。','AbortError');
   return execute();
  });
  this.tail=run.catch(()=>{});
  return run;
 }
}
