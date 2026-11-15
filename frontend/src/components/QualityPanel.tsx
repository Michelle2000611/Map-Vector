import {useState} from 'react';
import {Alert,Button,Descriptions,InputNumber,Space,Table,Tabs,Tag} from 'antd';
import {request} from '../services/client';
import type {Asset,Feature,Project,Roi} from '../services/models';
import './QualityPanel.css';

type RoiAuditCounts={inside:number;crossing:number;outside:number};
type RoiAuditResult={roi:Roi|null;counts:Record<'face'|'line'|'text',RoiAuditCounts>};
type QualityReport={target:string;target_area_px2:number;face_count:number;valid_geometry_count:number;coverage_is_valid:boolean|null;covered_area_px2:number;uncovered_area_px2:number;overlap_area_px2:number;recognition_accuracy:number|null;tolerance_px2:number;note:string};
type QualityResult={working_revision:number;quality_report:QualityReport};
type RoiPreviewResult={working_revision:number;coordinate_space:string;roi_id:string;roi_revision:number;keep_crossing:Feature[];clip:Feature[]};
type Props={project:Project;asset:Asset;roi:Roi|null;busy:boolean;onLocate:(bounds:number[])=>void};
const layerNames:Record<string,string>={face:'面',line:'线',text:'文字'};

function featureBounds(feature:Feature):number[]|null{
 const value=feature as unknown as {bbox_min_x_px?:number;bbox_min_y_px?:number;bbox_max_x_px?:number;bbox_max_y_px?:number};
 if(value.bbox_min_x_px===undefined||value.bbox_min_y_px===undefined||value.bbox_max_x_px===undefined||value.bbox_max_y_px===undefined)return null;
 return [value.bbox_min_x_px,value.bbox_min_y_px,value.bbox_max_x_px,value.bbox_max_y_px];
}
function featureMetric(feature:Feature):string{
 const value=feature as unknown as {area_px2?:number;length_px?:number};
 if(typeof value.area_px2==='number')return Number(value.area_px2.toFixed(1))+' px²';
 if(typeof value.length_px==='number')return Number(value.length_px.toFixed(1))+' px';
 return '—';
}

export function QualityPanel({project,asset,roi,busy,onLocate}:Props){
 const [bounds,setBounds]=useState([0,0,100,100]);
 const [auditPending,setAuditPending]=useState(false),[auditError,setAuditError]=useState(''),[audit,setAudit]=useState<RoiAuditResult|null>(null);
 const [qualityPending,setQualityPending]=useState(false),[qualityError,setQualityError]=useState(''),[quality,setQuality]=useState<QualityResult|null>(null);
 const [previewPending,setPreviewPending]=useState(false),[previewError,setPreviewError]=useState(''),[preview,setPreview]=useState<RoiPreviewResult|null>(null),[previewKind,setPreviewKind]=useState<'keep_crossing'|'clip'>('keep_crossing');
 const prefix='/projects/'+project.project_id;
 async function runAudit(){
  if(busy||auditPending)return;
  setAuditPending(true);setAuditError('');
  try{setAudit(await request<RoiAuditResult>(prefix+'/roi-audits',{asset_id:asset.asset_id}));}
  catch(error){setAuditError(error instanceof Error?error.message:String(error));setAudit(null);}
  finally{setAuditPending(false);}
 }
 async function runQuality(){
  if(busy||qualityPending)return;
  setQualityPending(true);setQualityError('');
  try{setQuality(await request<QualityResult>(prefix+'/quality?asset_id='+asset.asset_id));}
  catch(error){setQualityError(error instanceof Error?error.message:String(error));setQuality(null);}
  finally{setQualityPending(false);}
 }
 async function runPreview(){
  if(busy||previewPending)return;
  setPreviewPending(true);setPreviewError('');
  try{setPreview(await request<RoiPreviewResult>(prefix+'/roi-previews',{asset_id:asset.asset_id}));}
  catch(error){setPreviewError(error instanceof Error?error.message:String(error));setPreview(null);}
  finally{setPreviewPending(false);}
 }
 const previewRows=preview?preview[previewKind]:[];
 return <section className="quality-panel" aria-label="质量与范围">
  <p className="review-note">几何覆盖与合法性不代表原图识别正确，真实孔洞需保留。</p>
  <div className="quality-section">
   <h4>ROI 范围</h4>
   <Space wrap>{bounds.map((value,index)=><InputNumber key={index} aria-label={'ROI '+index} value={value} onChange={next=>setBounds(old=>old.map((x,i)=>i===index?Number(next):x))}/>)}</Space>
   {roi&&<p className="review-note">当前 ROI 修订 {String(roi.revision)}。</p>}
  </div>

  <div className="quality-section">
   <h4>ROI 审计</h4>
   <Button disabled={busy||auditPending} onClick={()=>void runAudit()}>{auditPending?'审计中…':'审计当前 ROI'}</Button>
   {auditError&&<Alert type="error" showIcon message={auditError}/>}
   {audit&&!audit.roi&&<Alert type="info" showIcon message="尚未设置 ROI，无法审计。"/>}
   {audit?.roi&&<table className="quality-table" aria-label="ROI 审计结果"><thead><tr><th scope="col">图层</th><th scope="col">完全在内</th><th scope="col">跨界</th><th scope="col">完全在外</th></tr></thead><tbody>{(['face','line','text'] as const).map(kind=><tr key={kind}><td>{layerNames[kind]}</td><td>{audit.counts[kind].inside}</td><td>{audit.counts[kind].crossing}</td><td>{audit.counts[kind].outside}</td></tr>)}</tbody></table>}
  </div>

  <div className="quality-section">
   <h4>几何质量检查</h4>
   <Button disabled={busy||qualityPending} onClick={()=>void runQuality()}>{qualityPending?'检查中…':'检查几何质量'}</Button>
   {qualityError&&<Alert type="error" showIcon message={qualityError}/>}
   {quality&&<Descriptions size="small" column={2} bordered className="quality-descriptions">
    <Descriptions.Item label="覆盖合法性">{quality.quality_report.coverage_is_valid===null?'无面对象':quality.quality_report.coverage_is_valid?<Tag color="green">合法</Tag>:<Tag color="red">不合法（有重叠或缝隙）</Tag>}</Descriptions.Item>
    <Descriptions.Item label="面对象数">{quality.quality_report.face_count}</Descriptions.Item>
    <Descriptions.Item label="有效几何数">{quality.quality_report.valid_geometry_count}</Descriptions.Item>
    <Descriptions.Item label="工作修订">{quality.working_revision}</Descriptions.Item>
    <Descriptions.Item label="已覆盖面积">{Number(quality.quality_report.covered_area_px2.toFixed(1))} px²</Descriptions.Item>
    <Descriptions.Item label="未覆盖面积">{Number(quality.quality_report.uncovered_area_px2.toFixed(1))} px²</Descriptions.Item>
    <Descriptions.Item label="重叠面积">{Number(quality.quality_report.overlap_area_px2.toFixed(1))} px²</Descriptions.Item>
    <Descriptions.Item label="有效范围面积">{Number(quality.quality_report.target_area_px2.toFixed(1))} px²</Descriptions.Item>
   </Descriptions>}
   {quality&&<p className="review-note">{String(quality.quality_report.note)}</p>}
  </div>

  <div className="quality-section">
   <h4>ROI 保留与裁切预览</h4>
   <Button disabled={busy||previewPending} onClick={()=>void runPreview()}>{previewPending?'预览中…':'预览 ROI 保留与裁切'}</Button>
   {previewError&&<Alert type="error" showIcon message={previewError}/>}
   {preview&&<>
    <Tabs activeKey={previewKind} onChange={value=>setPreviewKind(value as 'keep_crossing'|'clip')} items={[{key:'keep_crossing',label:'保留跨界 '+preview.keep_crossing.length},{key:'clip',label:'按 ROI 裁切 '+preview.clip.length}]}/>
    {!previewRows.length&&<p className="review-note">当前分类下没有对象。</p>}
    {previewRows.length>0&&<table className="quality-table" aria-label="ROI 预览对象"><thead><tr><th scope="col">类型</th><th scope="col">对象</th><th scope="col">面积 / 长度</th><th scope="col">操作</th></tr></thead><tbody>{previewRows.map(feature=>{const b=featureBounds(feature);return <tr key={feature.feature_id}><td>{layerNames[feature.feature_type]}</td><td>{feature.feature_id.slice(0,8)}</td><td>{featureMetric(feature)}</td><td><Button size="small" disabled={!b} onClick={()=>b&&onLocate(b)}>定位</Button></td></tr>;})}</tbody></table>}
   </>}
  </div>
 </section>;
}
