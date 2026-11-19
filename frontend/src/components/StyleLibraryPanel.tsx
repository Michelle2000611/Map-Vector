import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Modal,Space,Tabs,Tag} from 'antd';
import {request} from '../services/client';
import {useWorkspace} from '../stores/workspace';
import {feedback} from '../services/feedback';
import type {Command,Feature,Page,Style} from '../services/models';
import {StyleSwatch} from './ObjectAppearanceProperties';
import {textStyleSummary} from '../services/textStyles';
import {StyleReplacementPanel} from './StyleReplacementPanel';

type Props={projectId:string;assetId:string;features:Feature[];guard:()=>Promise<boolean>;onLocate:(featureId:string)=>Promise<boolean>;styles:Style[];busy:boolean;command:Command;onStylesChanged:(styles:Style[])=>void;onSelectByStyle:(styleId:string)=>void;onUseAsBrush?:(styleId:string)=>void};
type Kind='face'|'line'|'text';

export function StyleLibraryPanel({projectId,assetId,features,guard,onLocate,styles,busy,command,onStylesChanged,onSelectByStyle,onUseAsBrush}:Props){
 const prefix='/projects/'+projectId;
 const session=useWorkspace(state=>state.session);
 const [kind,setKind]=useState<Kind>('face');
 const [deleting,setDeleting]=useState<Style|null>(null),[deletePending,setDeletePending]=useState(false),[deleteError,setDeleteError]=useState('');
 const context=JSON.stringify([projectId,assetId,session]),currentContext=useRef(context),deleteInFlight=useRef(false);currentContext.current=context;
 useEffect(()=>{setDeleting(null);setDeleteError('');setDeletePending(false);},[context]);
 const [usage,setUsage]=useState<Record<string,number>>({});
 useEffect(()=>{
  let active=true;
  void Promise.all(styles.map(style=>request<{style_id:string;feature_count:number}>(prefix+'/styles/'+style.style_id+'/usage'))).then(results=>{
   if(!active)return;
   setUsage(Object.fromEntries(results.map(item=>[item.style_id,item.feature_count])));
  }).catch(()=>{});
  return()=>{active=false;};
 },[projectId,styles]);
 async function refreshStyles(){const library=await request<Page<Style>>(prefix+'/styles');const state=useWorkspace.getState();if(state.project?.project_id===projectId&&state.asset?.asset_id===assetId&&state.session===session)onStylesChanged(library.items);}
 async function rename(style:Style){
  let name=style.style_name;
  Modal.confirm({title:'重命名样式',content:<input defaultValue={style.style_name} style={{width:'100%'}} onChange={event=>{name=event.target.value;}}/>,okText:'保存',cancelText:'取消',onOk:async()=>{
   if(!name.trim()||name.trim()===style.style_name)return;
   const body=style.feature_type==='text'?{operation_type:'set_style' as const,style_id:style.style_id,feature_type:'text' as const,style_name:name.trim(),font_size_px:style.font_size_px??undefined,text_color:style.text_color??undefined,rotation_deg:style.rotation_deg??undefined}:style.feature_type==='face'?{operation_type:'set_style' as const,style_id:style.style_id,feature_type:'face' as const,style_name:name.trim(),fill_color:style.fill_color!,stroke_color:style.stroke_color??undefined,stroke_width_px:style.stroke_width_px??undefined}:{operation_type:'set_style' as const,style_id:style.style_id,feature_type:'line' as const,style_name:name.trim(),stroke_color:style.stroke_color!,stroke_width_px:style.stroke_width_px!,line_pattern:style.line_pattern as 'solid'|'dashed'|'teeth',dash_pattern_px:style.dash_pattern_px,tooth_spacing_px:style.tooth_spacing_px??undefined,tooth_height_px:style.tooth_height_px??undefined,tooth_side:style.tooth_side as 'left'|'right'|undefined};
   const result=await command(body);
   if(result)await refreshStyles();
  }});
 }
 function remove(style:Style){setDeleteError('');setDeleting(style);}
 async function confirmDelete(){
  if(!deleting||busy||deleteInFlight.current)return;
  const expected=context,style=deleting;deleteInFlight.current=true;setDeletePending(true);setDeleteError('');
  try{
   if(!await guard()||currentContext.current!==expected){setDeleteError('操作尚未提交，请先保存有效的属性修改。');return;}
   const result=await command({operation_type:'delete_style',style_id:style.style_id});
   const state=useWorkspace.getState();
   if(!result){setDeleteError('删除尚未完成，请重试。');return;}
   if(currentContext.current!==expected||state.session!==session||state.project?.project_id!==projectId||state.asset?.asset_id!==assetId)return;
   // Close immediately after server acknowledgement. A later refresh failure
   // must never keep a successful deletion's confirmation dialog open.
   onStylesChanged(styles.filter(item=>item.style_id!==style.style_id));setDeleting(null);
   feedback.success('样式已删除，可撤销。');
   try{await refreshStyles();}catch{if(currentContext.current===expected)feedback.warning('样式已删除，列表同步失败，请重新打开样式库。');}
  }catch(error){if(currentContext.current===expected){const message=error instanceof Error?error.message:String(error);setDeleteError(message);feedback.error(message);}}
  finally{deleteInFlight.current=false;if(currentContext.current===expected)setDeletePending(false);}
 }
 const label=kind==='face'?'面样式':kind==='text'?'文字样式':'线样式',items=styles.filter(item=>item.feature_type===kind);
 return <div className="style-library-panel" aria-label="样式库">
  <Tabs activeKey={kind} onChange={value=>{setKind(value as Kind);}} items={[{key:'face',label:'面样式'},{key:'line',label:'线样式'},{key:'text',label:'文字样式'}]}/>
  <div className="style-library-group">
   {!items.length&&<p className="review-note">暂无{label}。</p>}
   {items.map(style=><div key={style.style_id} className="style-library-row">
    <StyleSwatch style={style}/>
    <span className="style-library-name">{style.style_name}{style.feature_type==='text'&&<small className="text-style-library-summary">{textStyleSummary(style)}</small>}</span>
    <Tag>引用 {usage[style.style_id]??0}</Tag>
    <Space size={6}>
     <Button disabled={busy} onClick={()=>onSelectByStyle(style.style_id)}>选中使用对象</Button>
     {onUseAsBrush&&<Button disabled={busy} onClick={()=>onUseAsBrush(style.style_id)}>设为格式刷</Button>}
     <Button disabled={busy} onClick={()=>void rename(style)}>改名</Button>
     <Button danger disabled={busy} onClick={()=>void remove(style)}>删除</Button>
    </Space>
   </div>)}
  </div>
  <StyleReplacementPanel kind={kind} projectId={projectId} assetId={assetId} features={features} styles={styles} busy={busy} command={command} guard={guard} onLocate={onLocate} onReplaced={refreshStyles}/>
  <Modal open={!!deleting} title={'删除样式 '+(deleting?.style_name??'')} okText="删除" cancelText="取消" okButtonProps={{danger:true,disabled:busy}} confirmLoading={deletePending} cancelButtonProps={{disabled:deletePending}} closable={!deletePending} keyboard={!deletePending} onCancel={()=>{if(!deletePending)setDeleting(null);}} onOk={()=>void confirmDelete()}>
   <p>{deleting&&(usage[deleting.style_id]??0)>0?'有 '+usage[deleting!.style_id]+' 个对象正在使用此样式，删除后保留对象当前外观，可撤销。':'删除后可通过撤销恢复。'}</p>{deleteError&&<Alert type="error" showIcon message={deleteError}/>}
  </Modal>
 </div>;
}

