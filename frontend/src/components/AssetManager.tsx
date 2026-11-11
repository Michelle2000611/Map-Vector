import {useEffect,useState} from 'react';
import {Button,Card,Collapse,InputNumber,Select,Space,Table,Tag} from 'antd';
import {request} from '../services/client';

import type {Project,Source,Asset,Page,Work} from '../services/models';
export function AssetManager({project,busy,work,refresh,info}:{project:Project;busy:boolean;work:Work;refresh:()=>Promise<void>;info:(message:string)=>void}){
 const [sources,setSources]=useState<Source[]>([]),[assets,setAssets]=useState<Asset[]>([]),[sourceId,setSourceId]=useState<string>(),[page,setPage]=useState(1),[dpi,setDpi]=useState(200);
 const prefix='/projects/'+project.project_id;
 async function load(){const [s,a]=await Promise.all([request<Page<Source>>(prefix+'/sources'),request<Page<Asset>>(prefix+'/assets')]);setSources(s.items);setAssets(a.items);if(!sourceId&&s.items[0])setSourceId(s.items[0].source_id);}
 useEffect(()=>{let active=true;void Promise.all([request<Page<Source>>(prefix+'/sources'),request<Page<Asset>>(prefix+'/assets')]).then(([s,a])=>{if(!active)return;setSources(s.items);setAssets(a.items);setSourceId(s.items[0]?.source_id);}).catch(error=>{if(active)info(String(error));});return()=>{active=false;};},[project.project_id,project.current_asset_id]);
 const selected=sources.find(item=>item.source_id===sourceId);
 async function adopt(a:Asset){if(a.asset_id!==project.current_asset_id)await request(prefix+'/assets/'+a.asset_id+'/adopt',{base_revision:project.working_revision});await refresh();}
 if(!sources.length||!assets.length)return null;
 return <Card title="文件与页面" className="source-card">
  <Table rowKey="asset_id" size="small" pagination={assets.length>5?{pageSize:5}:false} dataSource={assets} scroll={{x:620}} columns={[
   {title:'文件名',render:(_:unknown,a:Asset)=>sources.find(s=>s.source_id===a.source_id)?.source_file_name??'—'},
   {title:'格式',render:(_:unknown,a:Asset)=><Tag>{sources.find(s=>s.source_id===a.source_id)?.source_type??'—'}</Tag>},
   {title:'页码',render:(_:unknown,a:Asset)=>a.page_index+1},
   {title:'像素尺寸',render:(_:unknown,a:Asset)=>a.width_px+' × '+a.height_px},
   {title:'状态',render:(_:unknown,a:Asset)=>a.asset_id===project.current_asset_id?<Tag color="blue">当前页面</Tag>:'可选页面'},
   {title:'操作',render:(_:unknown,a:Asset)=>a.asset_id===project.current_asset_id?'—':<Button disabled={busy} onClick={()=>void work(()=>adopt(a))}>使用此页</Button>}
  ]}/>
  {sources.some(s=>s.page_count>1||s.source_type==='PDF')&&<Collapse ghost items={[{key:'pages',label:'页面设置',children:<Space wrap>
   <Select aria-label="源文件" value={sourceId} options={sources.map(item=>({value:item.source_id,label:item.source_file_name+' · '+item.page_count+' 页'}))} onChange={value=>{setSourceId(value);setPage(1);}} style={{width:250}}/>
   <span>页码</span><InputNumber aria-label="页码" min={1} max={selected?.page_count??1} value={page} onChange={value=>setPage(Number(value??1))}/>
   {selected?.source_type==='PDF'&&<><span>渲染 DPI</span><InputNumber aria-label="PDF渲染DPI" min={36} max={600} value={dpi} onChange={value=>setDpi(Number(value??200))}/></>}
   <Button disabled={!sourceId||busy} onClick={()=>void work(async()=>{const existing=assets.find(a=>a.source_id===sourceId&&a.page_index===page-1&&(selected?.source_type!=='PDF'||a.normalization_config.dpi===dpi));const a=existing??await request<Asset>(prefix+'/assets',{source_id:sourceId,page_index:page-1,normalization_config:{dpi}});await load();await adopt(a);})}>打开所选页</Button>
  </Space>}]}/>} 
 </Card>;
}
