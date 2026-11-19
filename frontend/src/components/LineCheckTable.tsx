import {ReasonList} from './ReasonList';
import {Fragment,useId,useState} from 'react';
import {Button,Checkbox,Tag} from 'antd';
import type {LineCheckCandidate,LineCheckParameters} from '../services/lineChecks';
import {statusColor} from './statusTags';

type Props={items:LineCheckCandidate[];checked:string[];verified:string[];highlighted:string;disabled:boolean;parameters:LineCheckParameters;reason:(code:string)=>string;
 selectAll:{checked:boolean;indeterminate:boolean;disabled:boolean;label:string;onChange:(checked:boolean)=>void};
 onCheck:(id:string,checked:boolean)=>void;onLocate:(item:LineCheckCandidate)=>void;onSelect:(item:LineCheckCandidate)=>void;onReviewResidue?:(item:LineCheckCandidate)=>void};
const rasterLabels:Record<string,string>={supported:'原图支持连接路径',unsupported:'原图不支持连接路径',ambiguous:'原图依据不明确',unavailable:'原图依据暂不可用',source_mismatch:'原图与当前资产不一致',outside_raster:'连接路径超出原图'};
// Keep related measurements together, independent of the API object's property order.
const metricLabels:Record<string,string>={discovery_margin_px:'边缘检索距离',local_length_px:'文字范围内线长',adaptive_length_limit_px:'复杂笔画核对尺度',gap_px:'间距',angle_delta_deg:'方向偏差',gap_stroke_ratio:'间距 / 线宽',connector_length_px:'连接路径长度',attachment_distance_px:'端点贴合距离',tangent_scale_count:'方向采样尺度数',tangent_spread_deg:'多尺度方向差',raster_support_fraction:'原图支持比例',length_px:'长度',segment_count:'线段数',inside_share:'文字范围内占比',source_ink_share:'原图墨迹支持比例',spacing_cv:'间隔变异系数'};
function metricValue(name:string,value:number){
 const rounded=(number:number)=>Number(number.toFixed(2));
 if(name==='raster_support_fraction')return rounded(value*100)+'%';
 return rounded(value)+(name.endsWith('_px')?' px':name.endsWith('_deg')?'°':'');
}
// The object column shows only the first 8 characters of an id (the full id stays in the tooltip); long dash groups are capped.
const maxListedIds=4;
const shortId=(featureId:string)=>featureId.slice(0,8);
function connectionLabel(item:LineCheckCandidate){return (item.connection_mode==='manual'?'人工接续':'自动建议')+' · '+(item.connector_kind==='manual'?'人工路径':item.connector_kind==='smooth'?'曲线连接':'直线连接');}

export function LineCheckTable({items,checked,verified,highlighted,disabled,parameters,reason,selectAll,onCheck,onLocate,onSelect,onReviewResidue}:Props){
 const [expanded,setExpanded]=useState<string|null>(null),id=useId();
 return <div className="line-check-table-wrap"><table className="line-check-table" aria-label="线检查候选">
  <colgroup><col className="line-check-select-column"/><col className="line-check-object-column"/><col/><col className="line-check-status-column"/><col className="line-check-action-column"/></colgroup>
  <thead><tr><th scope="col"><Checkbox aria-label={selectAll.label} title={selectAll.label} checked={selectAll.checked} indeterminate={selectAll.indeterminate} disabled={selectAll.disabled} onChange={event=>selectAll.onChange(event.target.checked)}/></th><th scope="col">对象</th><th scope="col">原因</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead>
  <tbody>{items.map((item,index)=>{
   const key=(item.operation_id??'')+':'+item.candidate_id,open=expanded===key,detailsId=id+'-details-'+index;
   const status=item.status==='applied'?'已处理':item.status==='kept'?'已保留':item.manually_confirmed||verified.includes(item.candidate_id)?'已核对':item.blocked_reasons.length?'受保护':'待核对';
   const color=statusColor(status);
   const metrics=[...Object.keys(metricLabels).filter(name=>name in item.metrics),...Object.keys(item.metrics).filter(name=>!(name in metricLabels)).sort()];
   return <Fragment key={key}>
    <tr data-candidate-id={item.candidate_id} data-operation-id={item.operation_id} className={highlighted===item.candidate_id?'is-highlighted':''}>
     <td><Checkbox aria-label={'选择线候选 '+item.candidate_id} disabled={disabled||item.status==='applied'} checked={item.status!=='applied'&&checked.includes(item.candidate_id)} onChange={event=>onCheck(item.candidate_id,event.target.checked)}/></td>
     <td><span className="line-check-object-count">{item.feature_ids.length} 条线</span>{item.reference_text_ids.length>0?<small>关联文字 {item.reference_text_ids.length}</small>:item.kind==='text_stroke'&&<small>未关联文字 · 需人工核对</small>}
      <div className="line-check-object-ids">{item.feature_ids.slice(0,maxListedIds).map(featureId=><code key={featureId} title={'线 '+featureId}>{shortId(featureId)}</code>)}{item.reference_text_ids.slice(0,maxListedIds).map(featureId=><code key={'text-'+featureId} className="is-text" title={'文字 '+featureId}>{shortId(featureId)}</code>)}{item.feature_ids.length>maxListedIds&&<code className="is-more" title={item.feature_ids.join('\n')}>等共 {item.feature_ids.length} 条</code>}</div></td>
     <td><ReasonList className="line-check-reasons" items={[...item.reason_codes.map(code=><span className="line-check-reason">{reason(code)}</span>),...item.blocked_reasons.map(code=><span className="line-check-reason is-blocked">{reason(code)}</span>),...(!item.reason_codes.length&&!item.blocked_reasons.length?['需对照原图核对']:[])]}/></td>
     <td><Tag className="line-check-status-tag" color={color}>{status}</Tag></td>
     <td><div className="line-check-row-actions">{item.kind==='text_stroke'&&item.status!=='applied'&&item.reference_text_ids.length>0&&onReviewResidue&&<Button size="small" disabled={disabled} onClick={()=>onReviewResidue(item)}>核对文字残影</Button>}<Button size="small" disabled={disabled} onClick={()=>onLocate(item)}>定位</Button><Button size="small" disabled={disabled} aria-expanded={open} aria-controls={detailsId} onClick={()=>setExpanded(open?null:key)}>{open?'收起':'详情'}</Button></div></td>
    </tr>
    {open&&<tr className="line-check-details-row"><td colSpan={5}>
     <section id={detailsId} className="line-check-candidate-details" aria-label={'线候选详情 '+item.candidate_id}>
      <div className="line-check-detail-summary">{item.kind==='join_gap'&&<span>{connectionLabel(item)}</span>}{item.evidence?.raster?.status&&<span>{rasterLabels[item.evidence.raster.status]??'原图依据需核对'}</span>}{item.result_revision!==undefined&&<span>修订 {item.result_revision}</span>}</div>
      {item.status!=='applied'&&item.kind==='join_gap'&&item.connection_mode!=='manual'&&<p className="line-check-detail-settings">检查设置：最大接续间距 {parameters.max_gap_px} px · 方向偏差上限 {parameters.angle_tolerance_deg}°</p>}
      {item.status!=='applied'&&item.kind==='text_stroke'&&<p className="line-check-detail-settings">检查设置：文字残线基础尺度 {parameters.max_short_length_px} px</p>}
      {metrics.length>0&&<dl className="line-check-metrics">{metrics.map(name=><div key={name}><dt>{metricLabels[name]??name}</dt><dd>{metricValue(name,item.metrics[name])}</dd></div>)}</dl>}
      {item.status!=='applied'&&<Button size="small" disabled={disabled} onClick={()=>onSelect(item)}>加入选区</Button>}
     </section>
    </td></tr>}
   </Fragment>;
  })}</tbody>
 </table>{!items.length&&<div className="line-check-empty">当前筛选没有候选。</div>}</div>;
}
