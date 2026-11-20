import {ReasonList} from './ReasonList';
import {useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import {Alert,Button,Checkbox,Space,Tag} from 'antd';
import {createPortal} from 'react-dom';
import type {RefObject} from 'react';
import {request} from '../services/client';
import type {Feature,Preview} from '../services/models';
import './ResidueLineReview.css';
import {statusColor} from './statusTags';

export type ResidueReviewGroup={group_id:string;feature_ids:string[];bounds_px:number[];reason_codes:string[];status:'pending'|'kept'|'confirmed';can_confirm:boolean;requires_confirmation?:boolean;evidence_sha256:string};
export type ResidueReviewDisplay=NonNullable<Preview['text_residue_display']>&{review_groups?:ResidueReviewGroup[]};
type Props={features?:Record<string,Feature>;preview:Preview;cleanupDisplay?:Preview['text_residue_display'];projectId:string;assetId:string;busy:boolean;cleanupDisabled?:boolean;explicitCounts?:boolean;cleanupActionRef?:RefObject<HTMLDivElement>;checked:string[];verified:string[];onChecked:(ids:string[])=>void;onVerified:(ids:string[])=>void;
 onLocate:(bounds:number[],ids:string[])=>void;onCleanup:()=>void;guard:()=>Promise<boolean>;onDecided:()=>Promise<void>};
const messages:Record<string,string>={GEOLOGICAL_BOUNDARY:'地质分界线',EXPLICIT_SPLIT_LINE:'地质分界线',MANUAL_LINE:'手工线',SEMANTIC_LINE_PATTERN:'虚线或齿状线',OTHER_TEXT_INTERSECTION:'涉及相邻文字',OTHER_TEXT_OVERLAP:'涉及相邻文字',CROSSES_REVIEW_BOUNDS:'跨出检查范围',CROSSES_REVIEW_REGION:'跨出检查范围',CROSSES_TEXT_REGION:'跨出文字范围',UNCERTAIN_TEXT_LINE:'笔画依据不足',LOW_STROKE_CONFIDENCE:'笔画依据不足',NOT_STRONG_STROKE_EVIDENCE:'笔画依据不足',CROSSING_LINE:'跨框线',CODE_LIKE_TEXT:'地质代号附近线',TEXT_SYMBOL_PROTECTION:'地质符号附近线'};

Object.assign(messages,{COMPLEX_TEXT_FACE_REQUIRES_REVIEW:'较大或粘连字形碎面，暂不自动清理',FACE_CROSSES_TEXT_REGION:'碎面跨出原图文字范围，暂不整面清理',COMPLEX_TEXT_STROKE_REQUIRES_REVIEW:'复杂或较长笔画，需对照原图',TEXT_REGION_EDGE_REQUIRES_REVIEW:'线宽涉及文字框边缘，暂不扩大清理范围',SOURCE_REGION_UNCERTAIN:'原识别范围异常',AMBIGUOUS_TEXT_OWNERSHIP:'涉及多个文字，需核对归属',GEOLOGICAL_SYMBOL:'地质符号线',NON_TEXT_STROKE_COLOR:'线条颜色依据不足',RASTER_PATH_UNSUPPORTED:'原图不支持该残线',RASTER_SOURCE_MISMATCH:'原图依据已变化'});

export function ResidueLineReview({features={},preview,cleanupDisplay,projectId,assetId,busy,cleanupDisabled=false,explicitCounts=false,cleanupActionRef,checked,verified,onChecked,onVerified,onLocate,onCleanup,guard,onDecided}:Props){
 const display=preview.text_residue_display as ResidueReviewDisplay|undefined,groups=display?.review_groups??[];
 const [error,setError]=useState(''),[pending,setPending]=useState(false),[expanded,setExpanded]=useState<'faces'|'lines'|'protected'|null>(null),generation=useRef(0),tableId=useId();
 const scope=JSON.stringify([projectId,assetId,preview.preview_id,preview.base_revision]);
 const [cleanupHost,setCleanupHost]=useState<HTMLDivElement|null>(null);
 // Global review places this same action in the owning row; local review keeps it here.
 useLayoutEffect(()=>{setCleanupHost(cleanupActionRef?.current??null);},[cleanupActionRef,scope]);
 useEffect(()=>{generation.current++;setError('');setPending(false);return()=>{generation.current++;};},[scope]);
 useEffect(()=>{setExpanded(null);},[projectId,assetId,JSON.stringify(preview.feature_ids),preview.feature_ids.length?undefined:JSON.stringify(display?.bounds_px)]);
 const visibleLines=new Set(display?.line_feature_ids??[]),protectedLines=new Set(display?.protected_line_feature_ids??[]);
 const faceIds=new Set(display?.face_feature_ids??[]),lineIds=new Set([...visibleLines,...protectedLines]);
 const confirmed=new Set([...(display?.manually_confirmed_face_feature_ids??[]),...(display?.manually_confirmed_line_feature_ids??[]),...verified]);
 const forbidden=new Set(groups.filter(group=>!group.can_confirm).flatMap(group=>group.feature_ids));
 const allowed=new Set([...faceIds,...lineIds].filter(id=>!forbidden.has(id)));
 const disabled=busy||pending;
 const sections=[{key:'faces' as const,label:'碎面详情',ids:[...new Set(display?.face_feature_ids??[])]},{key:'lines' as const,label:'线段详情',ids:[...visibleLines].filter(id=>!protectedLines.has(id))},{key:'protected' as const,label:'待核对线详情',ids:[...protectedLines]}];
 const currentSection=sections.find(section=>section.key===expanded);
 const selectedInSection=(currentSection?.ids??[]).filter(id=>checked.includes(id));
 const safeChosen=selectedInSection.filter(id=>allowed.has(id)&&!confirmed.has(id));
 const keptIds=new Set([...(display?.kept_face_feature_ids??[]),...groups.filter(group=>group.status==='kept').flatMap(group=>group.feature_ids)]);
 const keepChosen=selectedInSection.filter(id=>!keptIds.has(id));
 async function changeSelection(ids:string[]){const ticket=generation.current;if(disabled||!await guard()||ticket!==generation.current)return;onChecked([...new Set(ids)]);}
 async function verify(){
  const ticket=generation.current;if(disabled||!safeChosen.length||!await guard()||ticket!==generation.current)return;
  if(ticket===generation.current)await decide('confirm',safeChosen);
 }
 async function decide(decision:'keep'|'reopen'|'confirm',ids:string[]){
  const ticket=generation.current;if(disabled||!ids.length||!await guard()||ticket!==generation.current)return;
  setPending(true);setError('');
  try{
   await request('/projects/'+projectId+'/text-residue-decisions',{asset_id:assetId,base_revision:preview.base_revision,preview_id:preview.preview_id,feature_ids:ids,decision},undefined,{quiet:true});
   if(generation.current!==ticket)return;onChecked([]);onVerified(verified.filter(id=>!ids.includes(id)));await onDecided();
  }catch(e){if(generation.current===ticket)setError(e instanceof Error?e.message:String(e));}
  finally{if(generation.current===ticket)setPending(false);}
 }
 if(!display)return null;
 const execution=cleanupDisplay??display;
 const cleanupFaces=new Set(execution.cleanup_face_feature_ids),cleanupLines=new Set(execution.cleanup_line_feature_ids);
 const excludedFaces=[...faceIds].filter(id=>!cleanupFaces.has(id)),excludedLines=[...lineIds].filter(id=>!cleanupLines.has(id));
 const cleanupAction=<Button danger disabled={disabled||cleanupDisabled||cleanupFaces.size+cleanupLines.size===0} onClick={onCleanup}>清理残影</Button>;
 async function locate(id:string){
  const ticket=generation.current;if(disabled||!await guard()||ticket!==generation.current)return;
  let bounds:number[]|undefined;
  const geometry=features[id]?.geometry;
  if(geometry){
   let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
   const visit=(value:unknown):void=>{if(!Array.isArray(value))return;if(value.length>=2&&typeof value[0]==='number'&&typeof value[1]==='number'){if(Number.isFinite(value[0])&&Number.isFinite(value[1])){minX=Math.min(minX,value[0]);minY=Math.min(minY,value[1]);maxX=Math.max(maxX,value[0]);maxY=Math.max(maxY,value[1]);}}else value.forEach(visit);};
   visit(geometry.coordinates);if(Number.isFinite(minX))bounds=[minX,minY,maxX,maxY];
  }
  onLocate(bounds??groups.find(group=>group.feature_ids.includes(id))?.bounds_px??display!.bounds_px,[id]);
 }
 return <section className="residue-line-review" aria-label="残影线段核对">
  <div className="residue-review-actions">
   <div className="residue-cleanup-action"><span className="residue-cleanup-count" aria-label="清理范围" aria-live="polite">{explicitCounts?'本次可清理：':''}碎面 {cleanupFaces.size} 个 · 线段 {cleanupLines.size} 条{!explicitCounts&&<> · 待核对线 {protectedLines.size} 条</>}</span>{cleanupActionRef?(cleanupHost?createPortal(cleanupAction,cleanupHost):null):cleanupAction}</div>
  </div>
  {explicitCounts&&(excludedFaces.length>0||excludedLines.length>0)&&<div className="residue-excluded-summary" aria-label="暂不清理范围">暂不清理：碎面 {excludedFaces.length} 个 · 线段 {excludedLines.length} 条<span>（受保护、已保留、仍待核对或无法归并，依据见详情）</span></div>}
  {(excludedFaces.some(id=>!(execution.unresolved_face_feature_ids??[]).includes(id))||excludedLines.length>0)&&<Alert type="info" message="受保护、已保留或待核对对象需先确认核对后再清理；普通残影可直接清理。"/>}
  {!!execution.unresolved_face_feature_ids?.length&&<Alert type="info" message={'有 '+execution.unresolved_face_feature_ids.length+' 个碎面未找到可归并的相邻面，暂不处理；其他残影仍可清理。'}/>}
  {error&&<Alert type="error" message={error}/>}
  <div className="residue-detail-headings" role="group" aria-label="残影详情分类">{sections.map(section=><Button key={section.key} type="text" size="small" aria-expanded={expanded===section.key} aria-controls={tableId+'-'+section.key} onClick={()=>setExpanded(value=>value===section.key?null:section.key)}><span aria-hidden="true">{expanded===section.key?'▾':'▸'}</span> {section.label} {section.ids.length}</Button>)}</div>
  {sections.filter(section=>expanded===section.key).map(section=><div key={section.key} id={tableId+'-'+section.key} className="residue-detail-panel">
   {selectedInSection.length>0&&<div className="residue-detail-batch-actions" role="group" aria-label={section.label+'批量操作'}><span>已选 {selectedInSection.length} 项</span>{safeChosen.length>0&&<Button size="small" disabled={disabled} onClick={()=>void verify()}>确认核对</Button>}{keepChosen.length>0&&<Button size="small" disabled={disabled} onClick={()=>void decide('keep',keepChosen)}>保留</Button>}</div>}
   <div className="residue-detail-table-wrap"><table className="residue-detail-table" aria-label={section.label}><thead><tr><th><Checkbox aria-label={'全选'+section.label} disabled={disabled||!section.ids.length} checked={section.ids.length>0&&section.ids.every(id=>checked.includes(id))} indeterminate={section.ids.some(id=>checked.includes(id))&&!section.ids.every(id=>checked.includes(id))} onChange={event=>void changeSelection(event.target.checked?[...checked,...section.ids]:checked.filter(id=>!section.ids.includes(id)))}/></th><th>对象</th><th>依据</th><th>状态</th><th>操作</th></tr></thead><tbody>{section.ids.map(id=>{
   const related=groups.filter(group=>group.feature_ids.includes(id));
   const kept=section.key==='faces'?(display.kept_face_feature_ids??[]).includes(id):related.some(group=>group.status==='kept');
   const protectedItem=section.key==='faces'?(display.protected_face_feature_ids??[]).includes(id):related.some(group=>!group.can_confirm||group.requires_confirmation)||section.key==='protected'&&!related.length;
   const label=kept?'已保留':confirmed.has(id)?'已确认':protectedItem?'受保护':'待核对';
   const evidence=section.key==='faces'?(display.protected_face_reasons?.[id]??[]).flatMap(item=>item.reason_codes):related.flatMap(group=>group.reason_codes);
   return <tr key={id} data-residue-feature-id={id}><td><Checkbox aria-label={'选择'+(section.key==='faces'?'碎面 ':'线段 ')+id} disabled={disabled} checked={checked.includes(id)} onChange={event=>void changeSelection(event.target.checked?[...checked,id]:checked.filter(item=>item!==id))}/></td><td title={id}>{section.key==='faces'?'面':'线'} {id.slice(0,8)}</td><td><ReasonList items={evidence.length?[...new Set(evidence)].map(code=>messages[code.toUpperCase()]??'需对照原图'):['需对照原图']}/></td><td><Tag color={statusColor(label)}>{label==='受保护'?'受保护，暂不清理':label}</Tag></td><td><Space size={4} wrap><Button size="small" disabled={disabled} onClick={()=>void locate(id)}>定位</Button><Button size="small" disabled={disabled} onClick={()=>void decide(kept?'reopen':'keep',[id])}>{kept?'重新核对':'保留'}</Button></Space></td></tr>;
  })}</tbody></table></div></div>)}
 </section>;
}
