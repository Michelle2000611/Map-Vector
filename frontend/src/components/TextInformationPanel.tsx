import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Form,Input,InputNumber,Modal,Segmented,Table,Tag} from 'antd';
import type {TableColumnsType} from 'antd';
import type {Asset,CommandInput,Project,TextFeature} from '../services/models';
import {statusColor} from './statusTags';
import './TextInformationPanel.css';

type Props={project:Project;asset:Asset;rows:TextFeature[];ready:boolean;busy:boolean;mutate:(input:CommandInput)=>Promise<boolean>;focus:(id:string)=>void};
type Filter='all'|'required'|'confirmed';
type Editor={kind:'create'|'edit'|'bulk'|'delete';ids:string[];revision:number};
type Values={text_value?:string;x?:number|null;y?:number|null;font_size_px?:number|null;text_color?:string;rotation_deg?:number|null};
const pending=(row:TextFeature)=>row.review_status!=='confirmed';
const label=(row:TextFeature)=>row.review_status==='confirmed'?'已确认':row.review_status==='auto_accepted_unverified'?'自动通过':row.review_status==='pipeline_complete_unverified'?'流程通过':'待核对';
const format=(value:number)=>Number(value.toFixed(2));

/** Text CRUD uses existing reversible commands; residue decisions stay in their own tab. */
export function TextInformationPanel({project,asset,rows,ready,busy,mutate,focus}:Props){
 const [query,setQuery]=useState(''),[filter,setFilter]=useState<Filter>('all'),[page,setPage]=useState(1),[selected,setSelected]=useState<string[]>([]);
 const [editor,setEditor]=useState<Editor|null>(null),[saving,setSaving]=useState(false),[error,setError]=useState('');
 const [form]=Form.useForm<Values>(),mounted=useRef(true),writing=useRef(false),revision=useRef(project.working_revision);revision.current=project.working_revision;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 useEffect(()=>{setSelected([]);},[project.working_revision]);
 const search=query.trim().toLocaleLowerCase();
 const visibleRows=rows.filter(row=>(filter==='all'||(filter==='confirmed'?row.review_status==='confirmed':pending(row)))&&(!search||row.text_value.toLocaleLowerCase().includes(search)||(row.original_text??'').toLocaleLowerCase().includes(search)));
 useEffect(()=>{setPage(current=>Math.min(current,Math.max(1,Math.ceil(visibleRows.length/10))));},[visibleRows.length]);
 const pageIds=JSON.stringify(visibleRows.slice((page-1)*10,page*10).map(row=>row.feature_id));
 useEffect(()=>{const available=new Set<string>(JSON.parse(pageIds));setSelected(current=>current.filter(id=>available.has(id)));},[pageIds]);
 const disabled=busy||saving||!ready,stale=!!editor&&editor.revision!==project.working_revision;
 function open(kind:Editor['kind'],ids:string[]=[]){
  if(disabled)return;
  setError('');form.resetFields();setEditor({kind,ids:[...ids],revision:project.working_revision});
  const row=rows.find(item=>item.feature_id===ids[0]);
  if(kind==='create')form.setFieldsValue({text_value:'',x:asset.width_px/2,y:asset.height_px/2,font_size_px:12,text_color:'#000000',rotation_deg:0});
  if(kind==='edit'&&row)form.setFieldsValue({text_value:row.text_value,x:row.geometry.coordinates[0],y:row.geometry.coordinates[1],font_size_px:row.font_size_px,text_color:row.text_color,rotation_deg:row.rotation_deg});
 }
 async function perform(input:CommandInput){
  if(writing.current||disabled)return false;
  writing.current=true;setSaving(true);setError('');
  try{return await mutate(input);}
  catch(exc){if(mounted.current)setError(exc instanceof Error?exc.message:String(exc));return false;}
  finally{writing.current=false;if(mounted.current)setSaving(false);}
 }
 async function save(){
  const draft=editor;if(!draft||stale||disabled)return;
  if(draft.kind==='delete'){
   if(await perform({operation_type:'delete_text',feature_ids:draft.ids})&&mounted.current){setEditor(null);setSelected([]);}return;
  }
  let values:Values;
  try{values=await form.validateFields();}catch{return;}
  if(revision.current!==draft.revision){setError('项目已更新，请关闭后重新打开编辑。');return;}
  let input:CommandInput;
  if(draft.kind==='bulk'){
   const size=values.font_size_px??undefined,angle=values.rotation_deg??undefined,color=values.text_color?.trim()||undefined;
   if(size===undefined&&angle===undefined&&!color){setError('请填写至少一个需要修改的外观属性。');return;}
   // The sample supplies only explicit scalar values. Each target keeps its own
   // content, coordinates, OCR binding and relative script layout.
   input={operation_type:'apply_text_format',feature_ids:draft.ids,sample:{text_value:'外观修改',font_size_px:size??12,text_color:color??'#000000',rotation_deg:angle??0,layout_runs:[]},copy_size:size!==undefined,copy_color:!!color,copy_rotation:angle!==undefined,copy_text:false};
  }else{
   const patch={text_value:values.text_value!.trim(),x:values.x!,y:values.y!,font_size_px:values.font_size_px!,rotation_deg:values.rotation_deg!,text_color:values.text_color!.trim()};
   input=draft.kind==='create'?{operation_type:'create_text',...patch}:{operation_type:'update_text',feature_ids:draft.ids,...patch};
  }
  if(await perform(input)&&mounted.current){setEditor(null);setSelected([]);}
 }
 const columns:TableColumnsType<TextFeature>=[
  {title:'文字',dataIndex:'text_value',render:(value:string,row)=><span title={row.original_text?'原始识别：'+row.original_text:undefined}>{value||'（空文字）'}</span>},
  {title:'核对状态',render:(_,row)=><Tag color={statusColor(label(row))}>{label(row)}</Tag>},
  {title:'字号',dataIndex:'font_size_px',render:(value:number)=>format(value)},
  {title:'颜色',dataIndex:'text_color',render:(value:string)=><span className="text-information-color"><i style={{background:value}}/>{value}</span>},
  {title:'角度',dataIndex:'rotation_deg',render:(value:number)=>format(value)+'°'},
  {title:'位置',render:(_,row)=>row.geometry.coordinates.map(format).join(', ')},
  {title:'操作',render:(_,row)=><div className="text-information-actions"><Button disabled={disabled} onClick={()=>focus(row.feature_id)}>定位</Button><Button disabled={disabled} onClick={()=>open('edit',[row.feature_id])}>编辑</Button><Button danger disabled={disabled} onClick={()=>open('delete',[row.feature_id])}>删除</Button></div>}
 ];
 return <section className="text-information-panel" aria-label="文字信息">
  <div className="text-information-toolbar"><Input aria-label="搜索文字" placeholder="搜索文字或原始识别内容" allowClear value={query} disabled={saving} onChange={event=>{setQuery(event.target.value);setPage(1);setSelected([]);}}/><Button disabled={disabled} onClick={()=>open('create')}>新增文字</Button></div>
  <Segmented role="group" aria-label="文字信息核对状态" value={filter} disabled={saving} options={[{value:'all',label:'全部 '+rows.length},{value:'required',label:'待核对 '+rows.filter(pending).length},{value:'confirmed',label:'已确认 '+rows.filter(row=>row.review_status==='confirmed').length}]} onChange={value=>{setFilter(value as Filter);setPage(1);setSelected([]);}}/>
  {selected.length>0&&<div className="text-review-selection" role="group" aria-label="所选文字操作"><span>已选 {selected.length} 项</span><Button disabled={disabled||!selected.some(id=>rows.some(row=>row.feature_id===id&&pending(row)))} onClick={()=>void perform({operation_type:'confirm_text',feature_ids:selected.filter(id=>rows.some(row=>row.feature_id===id&&pending(row)))})}>确认核对</Button><Button disabled={disabled} onClick={()=>open('bulk',selected)}>批量修改</Button><Button danger disabled={disabled} onClick={()=>open('delete',selected)}>删除所选文字</Button><small>仅选择当前页</small></div>}
  {error&&!editor&&<Alert showIcon type="error" message={error}/>}
  <Table className="text-information-table" aria-label="文字信息列表" size="small" rowKey="feature_id" dataSource={visibleRows} columns={columns} loading={!ready} rowSelection={{columnWidth:40,selectedRowKeys:selected,onChange:keys=>setSelected(keys.map(String)),getCheckboxProps:()=>({disabled})}} pagination={{pageSize:10,current:page,onChange:next=>{setPage(next);setSelected([]);},showSizeChanger:false,disabled:saving}} scroll={{x:760}}/>
  <Modal open={!!editor} title={editor?.kind==='create'?'新增文字':editor?.kind==='edit'?'编辑文字':editor?.kind==='bulk'?'批量修改文字外观':'删除文字'} okText={editor?.kind==='delete'?'删除':'保存'} cancelText="取消" confirmLoading={saving} okButtonProps={{danger:editor?.kind==='delete',disabled:disabled||stale}} onOk={()=>void save()} onCancel={()=>{if(!saving){setEditor(null);setError('');}}} destroyOnClose>
   {stale&&<Alert type="warning" showIcon message="项目已更新，请关闭后重新打开编辑。"/>}
   {error&&<Alert type="error" showIcon message={error}/>}
   {editor?.kind==='delete'?<p>删除所选的 {editor.ids.length} 项文字，关联碎面和线段保留。本次操作可撤销。</p>:<Form form={form} layout="vertical" preserve={false} disabled={saving||stale}>
    {editor?.kind==='bulk'?<p>只应用填写的属性，留空的属性保持原值。各条文字的内容和位置保留。</p>:<>
     <Form.Item name="text_value" label="文字内容" rules={[{required:true,whitespace:true,message:'请输入文字内容'},{max:200}]}><Input.TextArea aria-label="文字内容" maxLength={200} autoSize={{minRows:1,maxRows:4}}/></Form.Item>
     <div className="text-information-fields"><Form.Item name="x" label="X（px）" rules={[{required:true,type:'number',min:0,max:asset.width_px}]}><InputNumber aria-label="文字X位置" min={0} max={asset.width_px}/></Form.Item><Form.Item name="y" label="Y（px）" rules={[{required:true,type:'number',min:0,max:asset.height_px}]}><InputNumber aria-label="文字Y位置" min={0} max={asset.height_px}/></Form.Item></div>
    </>}
    <div className="text-information-fields"><Form.Item name="font_size_px" label="字号（px）" rules={[{required:editor?.kind!=='bulk',type:'number',min:1,max:200}]}><InputNumber aria-label="文字字号" min={1} max={200} placeholder={editor?.kind==='bulk'?'保持原值':undefined}/></Form.Item><Form.Item name="rotation_deg" label="角度（°）" rules={[{required:editor?.kind!=='bulk',type:'number'}]}><InputNumber aria-label="文字角度" placeholder={editor?.kind==='bulk'?'保持原值':undefined}/></Form.Item></div>
    <Form.Item name="text_color" label="颜色" rules={[{required:editor?.kind!=='bulk'},{pattern:/^#[0-9a-f]{6}$/i,message:'请输入 #RRGGBB 格式的颜色'}]}><Input aria-label="文字颜色" maxLength={7} placeholder={editor?.kind==='bulk'?'保持原值':'#000000'}/></Form.Item>
   </Form>}
  </Modal>
 </section>;
}
