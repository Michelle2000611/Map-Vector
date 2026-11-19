import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Collapse,Select,Table,Tag} from 'antd';
import type {TableColumnsType} from 'antd';
import {useWorkspace} from '../stores/workspace';
import {feedback} from '../services/feedback';
import type {Command,Feature,Style} from '../services/models';
import {PropertyField} from './PropertyField';
import {StyleSwatch} from './ObjectAppearanceProperties';
import './StyleReplacementPanel.css';

type Props={kind:'face'|'line'|'text';projectId:string;assetId:string;features:Feature[];styles:Style[];busy:boolean;command:Command;guard:()=>Promise<boolean>;onLocate:(featureId:string)=>Promise<boolean>;onReplaced:()=>Promise<void>};
export function StyleReplacementPanel({kind,projectId,assetId,features,styles,busy,command,guard,onLocate,onReplaced}:Props){
 const session=useWorkspace(state=>state.session),revision=useWorkspace(state=>state.project?.working_revision);
 const context=JSON.stringify([projectId,assetId,session,kind]);
 const [from,setFrom]=useState<string>(),[to,setTo]=useState<string>(),[selected,setSelected]=useState<string[]>([]),[page,setPage]=useState(1),[pending,setPending]=useState(false),[error,setError]=useState(''),[located,setLocated]=useState<string>();
 const key=JSON.stringify([context,revision,from,to]),current=useRef(key),mounted=useRef(false),inFlight=useRef(false);current.current=key;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 useEffect(()=>{setFrom(undefined);setTo(undefined);setSelected([]);setPage(1);setLocated(undefined);setError('');},[context]);
 useEffect(()=>{setSelected([]);setLocated(undefined);setPage(1);setError('');},[revision,from]);
 const items=styles.filter(style=>style.feature_type===kind),source=items.find(style=>style.style_id===from),target=items.find(style=>style.style_id===to);
 const rows=features.filter(feature=>feature.feature_type===kind&&(!feature.asset_id||feature.asset_id===assetId)&&(!feature.project_id||feature.project_id===projectId)&&feature.style_id===from&&!!source&&['active','isolated'].includes(feature.lifecycle_status));
 const allowed=new Set(rows.map(feature=>feature.feature_id)),checked=selected.filter(id=>allowed.has(id));
 const disabled=busy||pending;
 function same(expected:string){const state=useWorkspace.getState();return mounted.current&&current.current===expected&&state.session===session&&state.project?.project_id===projectId&&state.asset?.asset_id===assetId&&state.project.working_revision===revision;}
 async function replace(){
  if(disabled||inFlight.current||!source||!target||source.style_id===target.style_id||!checked.length)return;
  const expected=key,ids=[...checked];inFlight.current=true;setPending(true);setError('');
  try{
   if(!await guard()||!same(expected))return;
   const state=useWorkspace.getState();if(ids.some(id=>{const f=state.featuresById[id];return !f||f.asset_id&&f.asset_id!==assetId||f.feature_type!==kind||f.style_id!==source.style_id||!['active','isolated'].includes(f.lifecycle_status);})){setError('对象或原样式已更新，请重新选择。');return;}
   // bind_style applies only these explicit IDs in one undoable transaction.
   // Binding intentionally clears per-object overrides, as with the format brush.
   const result=await command({operation_type:'bind_style',style_id:target.style_id,feature_ids:ids});
   if(result&&mounted.current&&useWorkspace.getState().session===session&&useWorkspace.getState().project?.project_id===projectId&&useWorkspace.getState().asset?.asset_id===assetId){setSelected([]);setLocated(undefined);await onReplaced();feedback.success('已替换 '+ids.length+' 个对象的样式，可撤销。');}
  }catch(e){if(mounted.current&&current.current===expected)setError(e instanceof Error?e.message:String(e));}
  finally{inFlight.current=false;if(mounted.current)setPending(false);}
 }
 async function locate(id:string){const expected=key;if(disabled||!allowed.has(id)||!await guard()||!same(expected))return;if(await onLocate(id)&&same(expected))setLocated(id);}
 const columns:TableColumnsType<Feature>=[
  {title:'对象',render:(_,feature)=><span title={feature.feature_id}>{kind==='face'?'面':kind==='text'?'文字':'线'} {feature.feature_id.slice(0,8)}</span>},
  {title:'状态',width:90,render:(_,feature)=><Tag>{feature.lifecycle_status==='isolated'?'已隔离':'使用中'}</Tag>},
  {title:'单独调整',width:100,render:(_,feature)=>feature.style_override&&Object.keys(feature.style_override).length?'有':'—'},
  {title:'操作',width:80,render:(_,feature)=><Button size="small" disabled={disabled} onClick={()=>void locate(feature.feature_id)}>定位</Button>}
 ];
 const options=(list:Style[])=>list.map(style=>({value:style.style_id,label:<span className="style-option"><StyleSwatch style={style}/>{style.style_name}</span>,title:style.style_name}));
 return <Collapse ghost className="line-edit-groups style-library-rebind" items={[{key:'replace',label:'批量替换'+(kind==='face'?'面':kind==='text'?'文字':'线')+'样式',children:<div className="style-replacement-body">
  <div className="style-replacement-fields"><PropertyField label="原样式"><Select aria-label="原样式" value={source?.style_id} disabled={disabled||!items.length} placeholder="选择样式" options={options(items)} onChange={value=>{setFrom(value);setTo(undefined);setSelected([]);setLocated(undefined);}}/></PropertyField><PropertyField label="替换为"><Select aria-label="替换为" value={target?.style_id} disabled={disabled||!source} placeholder="选择样式" options={options(items.filter(style=>style.style_id!==from))} onChange={value=>{setTo(value);setError('');}}/></PropertyField></div>
  {error&&<Alert type="error" showIcon message={error}/>}
  {source&&<Table className="style-replacement-table" aria-label="使用原样式的对象" rowKey="feature_id" size="small" dataSource={rows} columns={columns} rowClassName={feature=>feature.feature_id===located?'style-replacement-located':''} onRow={feature=>({'aria-selected':feature.feature_id===located})} rowSelection={{selectedRowKeys:checked,onChange:ids=>setSelected(ids.map(String).filter(id=>allowed.has(id))),getCheckboxProps:()=>({disabled}),columnWidth:40}} pagination={{current:page,pageSize:10,showSizeChanger:false,total:rows.length,onChange:setPage}} scroll={{x:480}} locale={{emptyText:'没有使用此样式的对象'}}/>}
  <div className="style-replacement-actions">{source&&<span>已选 {checked.length} / {rows.length} 个对象</span>}<Button className="style-replacement-submit" disabled={disabled||!source||!target||source.style_id===target.style_id||!checked.length} loading={pending} onClick={()=>void replace()}>执行替换</Button></div>
 </div>}]} />;
}
