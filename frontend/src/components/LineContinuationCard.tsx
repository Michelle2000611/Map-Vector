import {ReasonList} from './ReasonList';
import {useEffect,useState} from 'react';
import {Button,Checkbox,Radio} from 'antd';
import {InspectionStatus} from './InspectionStatus';
import type {Feature,Point,Style} from '../services/models';
import type {LineCheckCandidate} from '../services/lineChecks';
import './LineContinuationCard.css';

export type LineContinuationCardProps={
 features:Feature[];candidate:LineCheckCandidate|null;busy:boolean;checking:boolean;attempted:boolean;verified:boolean;error?:string;
 connector:Point[];drawing:boolean;choosingSecondLine:boolean;styles?:Style[];reason:(code:string)=>string;
 onChooseSecondLine:()=>void;onCancelChooseSecondLine:()=>void;onReselect:()=>void;
 onDrawPath:()=>void;onFinishPath:()=>void;onClearPath:()=>void;onInspect:()=>void;
 onVerifiedChange:(value:boolean)=>void;onApply:()=>void;onLocateIssue:()=>void;onLocateScope:()=>void;
 onReopen?:()=>void;
};
type Line=Extract<Feature,{feature_type:'line'}>;
const fields=[['stroke_color','颜色'],['stroke_width_px','线宽'],['line_role','用途'],['line_pattern','线型'],['style_ids','图例']] as const;
const names:Record<string,string>={solid:'实线',dashed:'虚线',teeth:'齿形线',unknown:'待定',cover:'覆盖线',split:'分割线'};
/** Reviewer-facing metrics only. gap_stroke_ratio is an auto-detection threshold input and total length is audit data; neither is shown. */
const metricFields:readonly (readonly [key:string,label:string,unit:string])[]=[['gap_px','端点间距',' px'],['connector_length_px','连接路径长度',' px']];
/** Reason codes that only restate the operator's own choice; not worth showing. */
const hiddenReasons=new Set(['EXPLICIT_MANUAL_CONTINUATION','MANUAL_PATH','NEAREST_ENDPOINTS']);
/** Blocking reason -> optional wording override and the remedy offered next to it. New backend codes need no layout change. */
type Remedy='locate'|'differences';
const blockerView:Record<string,{label?:string;remedy?:Remedy}>={SELF_INTERSECTION:{label:'接续结果存在自相交',remedy:'locate'},ATTRIBUTE_MISMATCH:{remedy:'differences'}};
function object(value:unknown):Record<string,unknown>|undefined{return value!==null&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:undefined;}
function property(line:Line,field:string,styles:Style[]):unknown{
 const style=styles.find(item=>item.style_id===line.style_id),override=line.style_override??{};
 if(field==='line_role')return line.line_role;
 if(field==='style_ids')return line.style_id?[line.style_id]:[];
 if(field==='style_id')return line.style_id;
 return override[field]??(style as unknown as Record<string,unknown>|undefined)?.[field]??(line as unknown as Record<string,unknown>)[field];
}
function valueText(value:unknown,field:string,styles:Style[]):string{
 if(value===undefined||value===null||value==='')return '未设置';
 if(Array.isArray(value))return value.length?value.map(item=>valueText(item,'style_id',styles)).join('、'):'未设置';
 if(field==='style_id')return styles.find(item=>item.style_id===value)?.style_name??String(value);
 if(field==='stroke_width_px'&&typeof value==='number')return Number(value.toFixed(3))+' px';
 return names[String(value)]??String(value);
}

/** One explicitly selected pair and proposal; all mutations remain parent-owned. */
export function LineContinuationCard({features,candidate,busy,checking,attempted,verified,error,connector,drawing,choosingSecondLine,styles=[],reason,onChooseSecondLine,onCancelChooseSecondLine,onReselect,onDrawPath,onFinishPath,onClearPath,onInspect,onVerifiedChange,onApply,onLocateIssue,onLocateScope,onReopen}:LineContinuationCardProps){
 const lines=features.filter((item):item is Line=>item.feature_type==='line'&&item.lifecycle_status==='active');
 const pair=lines.length===2&&new Set(lines.map(item=>item.feature_id)).size===2;
 const matches=!!candidate&&pair&&candidate.feature_ids.length===2&&new Set(candidate.feature_ids).size===2&&candidate.feature_ids.every(id=>lines.some(line=>line.feature_id===id));
 const blocked=!!candidate?.blocked_reasons.length;
 const eligible=matches&&candidate?.kind==='join_gap'&&candidate.allowed_action==='join'&&candidate.status==='pending'&&!blocked&&!error;
 const locked=busy||checking;
 const ready=eligible&&verified&&!locked&&!drawing&&!choosingSecondLine;
 const reasonRows=candidate?[...candidate.blocked_reasons.map(code=>({code,blocking:true})),...candidate.reason_codes.filter(code=>!hiddenReasons.has(code)&&!candidate.blocked_reasons.includes(code)).map(code=>({code,blocking:false}))]:[];
 const metrics=metricFields.flatMap(([key,label,unit])=>{if(key==='connector_length_px'&&!connector.length)return [];const value=candidate?.metrics[key];return typeof value==='number'&&Number.isFinite(value)?[{label,text:Number(value.toFixed(2))+unit}]:[];});
 const differences=Array.isArray(candidate?.evidence?.attribute_differences)?candidate.evidence.attribute_differences:[];
 function comparison(line:Line,field:string){
  const entry=differences.map(object).find(item=>item?.field===field);
  const values=Array.isArray(entry?.values)?entry.values:[];
  const value=values.map(object).find(item=>item?.feature_id===line.feature_id);
  return value&&Object.prototype.hasOwnProperty.call(value,'value')?value.value:property(line,field,styles);
 }
 const comparisonFields:readonly (readonly [string,string])[]=differences.some(item=>object(item)?.field==='style_id')?[...fields,['style_id','对象样式']]:fields;
 const [showDifferences,setShowDifferences]=useState(false);
 useEffect(()=>setShowDifferences(false),[candidate?.candidate_id]);
 const locations=Array.isArray(candidate?.evidence?.issue_locations)?candidate.evidence.issue_locations:[];
 const preciseIntersection=locations.some(value=>{const item=object(value);return item?.reason_code==='SELF_INTERSECTION'&&item.precise===true;});
 const link=(label:string,onClick:()=>void,extra:{title?:string;expanded?:boolean;disabled?:boolean}={})=><Button size="small" disabled={extra.disabled??locked} title={extra.title} aria-expanded={extra.expanded} onClick={onClick}>{label}</Button>;
 const hasPath=drawing||connector.length>0;
 return <section className="line-continuation-card" aria-label="断线续接方案">
  <div className="line-continuation-head">
   {lines.length>0&&lines.length<3&&<dl className="line-continuation-roles">{([['起点线',lines[0]],['续接线',lines[1]]] as const).map(([role,line])=><div key={role}><dt>{role}</dt>{line?<dd title={line.feature_id}><span className="line-continuation-swatch" aria-hidden="true" style={{background:String(property(line,'stroke_color',styles)??line.stroke_color)}}/><span>{line.feature_id.slice(0,8)}</span></dd>:<dd className="line-continuation-placeholder">{choosingSecondLine?'请在画布点选另一条线':'未选择'}</dd>}{role==='续接线'&&<div className="line-continuation-actions">{choosingSecondLine?<Button size="small" disabled={locked} onClick={onCancelChooseSecondLine}>取消选择</Button>:lines.length===1?<Button size="small" disabled={locked} onClick={onChooseSecondLine}>选择续接线</Button>:<Button size="small" disabled={locked} onClick={onReselect}>重新选择</Button>}{pair&&<Button size="small" disabled={locked} onClick={onLocateScope}>定位</Button>}</div>}</div>)}</dl>}
  </div>
  {!lines.length&&<p className="line-continuation-note">请选择一条线作为起点。</p>}
  {lines.length>2&&<p className="line-continuation-note">请明确选择两条线。</p>}
  {(choosingSecondLine||pair)&&<>
  <div className="line-continuation-mode">
   <Radio.Group aria-label="连接方式" value={hasPath?'drawn':'direct'} disabled={locked||!pair||choosingSecondLine} onChange={event=>event.target.value==='drawn'?onDrawPath():onClearPath()}><Radio value="direct">端点直连</Radio><Radio value="drawn">手绘路径</Radio></Radio.Group>
   {hasPath&&<p className="line-continuation-note">{drawing?'从一条线的端点绘制，并吸附到另一条线的端点后完成。':`已绘制 ${connector.length} 个路径点；检查后核对接续结果。`}</p>}
   {hasPath&&<div className="line-continuation-links">{drawing?<Button size="small" disabled={locked} onClick={onFinishPath}>完成路径</Button>:link('重新绘制',onDrawPath)}{link('清除路径',onClearPath)}</div>}
  </div>
  <div className="line-continuation-check">
   <InspectionStatus ariaLabel="接续检查状态" state={checking?'checking':candidate||error?'done':'waiting'} attempted={attempted||!!candidate} disabled={locked||!pair||drawing||choosingSecondLine} onCheck={onInspect} extra={metrics.length>0?<dl className="line-continuation-metrics">{metrics.map(item=><div key={item.label}><dt>{item.label}</dt><dd>{item.text}</dd></div>)}</dl>:undefined}/>
  </div>
  {error&&<p className="line-continuation-error" role="alert">{error}</p>}
  {candidate&&!matches&&<p className="line-continuation-error">接续对象已变化，请重新检查。</p>}
  {reasonRows.length>0&&<details key={candidate?.candidate_id} open={blocked} className="line-continuation-details line-continuation-reasons"><summary>检查原因（共 {reasonRows.length} 项{blocked?`，阻断 ${candidate!.blocked_reasons.length} 项`:''}）</summary>
   <table aria-label="接续检查原因" className="line-continuation-table"><thead><tr><th>类型</th><th>原因</th><th>操作</th></tr></thead><tbody>{reasonRows.map(row=>{const view=blockerView[row.code]??{};return <tr key={row.code}><td><span className="line-continuation-badge" data-blocking={row.blocking}>{row.blocking?'阻断':'提示'}</span></td><td><ReasonList items={[view.label??reason(row.code)]}/></td><td>{row.blocking&&view.remedy==='locate'&&link('定位问题',onLocateIssue,{title:preciseIntersection?undefined:'未提供精确交点，将定位到候选范围。'})}{row.blocking&&view.remedy==='differences'&&link(showDifferences?'收起差异':'查看差异',()=>setShowDifferences(value=>!value),{expanded:showDifferences,disabled:false})}</td></tr>;})}</tbody></table>
   {showDifferences&&candidate!.blocked_reasons.includes('ATTRIBUTE_MISMATCH')&&<div className="line-continuation-difference-wrap"><table aria-label="接续对象属性差异" className="line-continuation-differences"><thead><tr><th>属性</th><th>起点线</th><th>续接线</th></tr></thead><tbody>{comparisonFields.map(([field,label])=>{const cells=lines.map(line=>valueText(comparison(line,field),field,styles));return <tr key={field} data-different={cells.length>1&&cells.some(cell=>cell!==cells[0])}><th>{label}</th>{lines.map((line,index)=><td key={line.feature_id}>{cells[index]}</td>)}</tr>;})}</tbody></table><p className="line-continuation-note">调整所选线的属性后重新检查；此处仅展示差异。</p></div>}
  </details>}
  {eligible&&<Checkbox disabled={locked||drawing||choosingSecondLine} checked={verified} onChange={event=>onVerifiedChange(event.target.checked)}>已对照原图核对接续路径</Checkbox>}
  <div className="line-continuation-footer">
   <Button type="primary" disabled={!ready} onClick={onApply}>确认接续</Button>
   {candidate?.status==='kept'&&onReopen&&<Button disabled={locked} onClick={onReopen}>重新纳入核对</Button>}
  </div>
  </>}
 </section>;
}
