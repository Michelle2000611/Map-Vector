import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Checkbox,Tag} from 'antd';
import {request} from '../services/client';
import type {Preview} from '../services/models';

export type ResidueReviewGroup={group_id:string;feature_ids:string[];bounds_px:number[];reason_codes:string[];status:'pending'|'kept';can_confirm:boolean;evidence_sha256:string};
export type ResidueReviewDisplay=NonNullable<Preview['text_residue_display']>&{review_groups?:ResidueReviewGroup[]};
type Props={preview:Preview;projectId:string;assetId:string;busy:boolean;checked:string[];verified:string[];onChecked:(ids:string[])=>void;onVerified:(ids:string[])=>void;
 onLocate:(bounds:number[],ids:string[])=>void;onBrush:()=>void;onCleanup:()=>void;guard:()=>Promise<boolean>;onDecided:()=>Promise<void>};
const messages:Record<string,string>={GEOLOGICAL_BOUNDARY:'地质分界线',EXPLICIT_SPLIT_LINE:'地质分界线',MANUAL_LINE:'手工线',SEMANTIC_LINE_PATTERN:'虚线或齿状线',OTHER_TEXT_INTERSECTION:'涉及相邻文字',OTHER_TEXT_OVERLAP:'涉及相邻文字',CROSSES_REVIEW_BOUNDS:'跨出检查范围',CROSSES_REVIEW_REGION:'跨出检查范围',CROSSES_TEXT_REGION:'跨出文字范围',UNCERTAIN_TEXT_LINE:'笔画依据不足',LOW_STROKE_CONFIDENCE:'笔画依据不足',NOT_STRONG_STROKE_EVIDENCE:'笔画依据不足',CROSSING_LINE:'跨框线',CODE_LIKE_TEXT:'地质代号附近线',TEXT_SYMBOL_PROTECTION:'地质符号附近线'};

export function ResidueLineReview({preview,projectId,assetId,busy,checked,verified,onChecked,onVerified,onLocate,onBrush,onCleanup,guard,onDecided}:Props){
 const display=preview.text_residue_display as ResidueReviewDisplay|undefined,groups=display?.review_groups??[];
 const [error,setError]=useState(''),[pending,setPending]=useState(false),generation=useRef(0);
 const scope=JSON.stringify([projectId,assetId,preview.preview_id,preview.base_revision]);
 useEffect(()=>{generation.current++;setError('');setPending(false);return()=>{generation.current++;};},[scope]);
 const allowed=new Set(groups.filter(g=>g.can_confirm&&g.status==='pending').flatMap(g=>g.feature_ids));
 const safeChosen=checked.filter(id=>allowed.has(id)),disabled=busy||pending;
 async function changeSelection(ids:string[]){if(disabled||!await guard())return;onChecked([...new Set(ids)]);}
 async function verify(){if(disabled||!safeChosen.length||!await guard())return;onVerified([...new Set([...verified,...safeChosen])]);}
 async function decide(decision:'keep'|'reopen'){
  if(disabled||!checked.length||!await guard())return;
  const ticket=generation.current;setPending(true);setError('');
  try{
   await request('/projects/'+projectId+'/text-residue-decisions',{asset_id:assetId,base_revision:preview.base_revision,preview_id:preview.preview_id,feature_ids:checked,decision},undefined,{quiet:true});
   if(generation.current!==ticket)return;onChecked([]);onVerified(verified.filter(id=>!checked.includes(id)));await onDecided();
  }catch(e){if(generation.current===ticket)setError(e instanceof Error?e.message:String(e));}
  finally{if(generation.current===ticket)setPending(false);}
 }
 if(!display)return null;
 return <section className="residue-line-review" aria-label="残影线段核对">
  <div className="residue-review-actions">
   <Button disabled={disabled} onClick={onCleanup}>清理所选残影</Button>
   <Button className="property-button-wide" disabled={disabled||!safeChosen.length} onClick={()=>void verify()}>所选确认为残影</Button>
   <Button disabled={disabled||!checked.length} onClick={()=>void decide('keep')}>所选保留</Button>
   <Button disabled={disabled||!checked.length} onClick={()=>void decide('reopen')}>重新核对</Button>
   <Button disabled={disabled||!groups.length} onClick={()=>void guard().then(ok=>{if(ok)onBrush();})}>刷选待核对线</Button>
  </div>
  {error&&<Alert type="error" message={error}/>}
  {groups.length>0&&<>
   <Checkbox disabled={disabled||!allowed.size} checked={allowed.size>0&&[...allowed].every(id=>checked.includes(id))} onChange={event=>void changeSelection(event.target.checked?[...allowed]:[])}>全选可核对线</Checkbox>
   <div className="residue-review-groups"><table aria-label="残影线段分组"><thead><tr><th>选择</th><th>线段</th><th>依据</th><th>状态</th><th>操作</th></tr></thead><tbody>{groups.map(group=>{
    const count=group.feature_ids.filter(id=>checked.includes(id)).length,acknowledged=group.feature_ids.every(id=>verified.includes(id));
    return <tr key={group.group_id} data-residue-review-group={group.group_id}>
     <td><Checkbox aria-label={'选择复核组 '+group.group_id} disabled={disabled} checked={count===group.feature_ids.length} indeterminate={count>0&&count<group.feature_ids.length} onChange={event=>void changeSelection(event.target.checked?[...checked,...group.feature_ids]:checked.filter(id=>!group.feature_ids.includes(id)))}/></td>
     <td>{group.feature_ids.length} 条</td><td>{group.reason_codes.map(code=>messages[code.toUpperCase()]??'需对照原图').join('；')}</td>
     <td><Tag color={!group.can_confirm?'default':acknowledged?'blue':undefined}>{group.status==='kept'?'已保留':!group.can_confirm?'受保护':acknowledged?'已确认':'待核对'}</Tag></td>
     <td><Button size="small" disabled={disabled} onClick={()=>void guard().then(ok=>{if(ok)onLocate(group.bounds_px,group.feature_ids);})}>定位</Button></td>
    </tr>;
   })}</tbody></table></div>
  </>}
 </section>;
}
