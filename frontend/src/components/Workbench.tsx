import {LoadingImage,LoadingSvgImage} from './LoadingImage';
import {TextResidueOverlay} from './TextResidueOverlay';
import type {ResidueVisibility} from './TextResidueOverlay';
import {FeatureScene,SelectedFeatureOverlay,geometryPath} from './FeatureGlyph';
import {useEffect,useMemo,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import {ObjectAppearanceProperties} from './ObjectAppearanceProperties';
import {FaceRepairOverlay,FaceRepairTools} from './FaceRepairTools';
import {FaceMergeTools} from './FaceMergeTools';
import {WorkbenchFrame} from './WorkbenchFrame';
import './CompactProperties.css';
import {LineCheckOverlay,LineCheckTools} from './LineCheckTools';
import type {LineCheckDisplay} from './LineCheckTools';
import type {FaceRepairDisplay} from './FaceRepairTools';
import {TextActions} from './TextActions';
import {PropertySectionTabs} from './PropertySectionTabs';
import {ResiduePlan} from './ResiduePlan';
import {ResidueLineReview} from './ResidueLineReview';
import type {ResidueReviewDisplay} from './ResidueLineReview';
import './ResidueReview.css';
import {LayerOpacity} from './LayerOpacity';
import {Button,Card,Checkbox,Input,InputNumber,Select,Space,Tag,Modal,Drawer,Alert} from 'antd';
import {useShallow} from 'zustand/react/shallow';
import {useCanvasScroll} from './useCanvasScroll';
import {request,ApiError} from '../services/client';
import {PropertyField} from './PropertyField';
import {operationLabel,operationStatusLabel} from '../services/operationLabels';
import {buildPropertyPatch,usePropertyAutosave} from '../hooks/usePropertyAutosave';

import {useWorkspace} from '../stores/workspace';
import {propertyDraftScopes,usePropertyDrafts} from '../stores/propertyDrafts';
import type {DraftField} from '../stores/propertyDrafts';
import type {Project,Asset,Feature,TextFeature,Style,Layer,Operation,Preview,PreviewItem,CommandInput,Command,Work,Point,Geometry,Page,FeaturePage,JsonObject} from '../services/models';
type Props={project:Project;asset:Asset;features:Feature[];focus:{feature_id:string;ticket:number;residue?:boolean}|null;stage:number;initialTextLayer?:boolean;belowCanvas?:ReactNode|((command:Command,revealRequest?:{feature_id:string;ticket:number},onConfirmNext?:(id:string)=>void)=>ReactNode);belowCanvasVisible?:boolean;onReturnToRecognition:()=>void;busy:boolean;command:Command;work:Work;info:(message:string)=>void;refresh:()=>Promise<void>};

function geometryBounds(geometry:Geometry){const bounds=[Infinity,Infinity,-Infinity,-Infinity];const visit=(v:unknown)=>{if(!Array.isArray(v))return;if(typeof v[0]==='number'&&typeof v[1]==='number'){bounds[0]=Math.min(bounds[0],v[0]);bounds[1]=Math.min(bounds[1],v[1]);bounds[2]=Math.max(bounds[2],v[0]);bounds[3]=Math.max(bounds[3],v[1]);}else v.forEach(visit);};visit(geometry.coordinates);return bounds;}

const layerNames={face:'面',line:'线',text:'文字',isolated_line:'隔离线'};
const basemaps=[{value:'source',label:'原图'},{value:'blank',label:'白底'},{value:'render_compare',label:'识别基线'},{value:'residual_scan_current',label:'原图与当前差异'},{value:'residual_compare_current',label:'基线与当前差异'}];
export function Workbench({project,asset,features,focus,stage,initialTextLayer=false,belowCanvas,belowCanvasVisible=true,onReturnToRecognition,busy,command:rawCommand,work,info,refresh}:Props){
 const [residueShown,setResidueShown]=useState<ResidueVisibility>({faces:true,lines:true,protected:true,context:false});
 const [faceRepair,setFaceRepair]=useState<FaceRepairDisplay|null>(null);
 const [lineCheck,setLineCheck]=useState<LineCheckDisplay|null>(null);
 const previewTicket=useRef(0);
 const objectTicket=useRef(0),cleanupInFlight=useRef(false),reviewInFlight=useRef(false);
 const [cleanupPending,setCleanupPending]=useState(false);
 const [previewError,setPreviewError]=useState(''),[previewPending,setPreviewPending]=useState(false),[historyOpen,setHistoryOpen]=useState(false);
 function clearObjectPreview(){previewTicket.current+=1;setPreview(null);setPreviewPending(false);setPreviewError('');setVerifiedResidueLines([]);setResidueFocusLines([]);if(useWorkspace.getState().layer==='text'&&tool==='residue_lines')setTool('pick');}
 const [allowMixed,setAllowMixed]=useState(false),[compact,setCompact]=useState(window.innerWidth<980),[propertyOpen,setPropertyOpen]=useState(false),[faceAssignments,setFaceAssignments]=useState<Record<string,string>>({});
 useEffect(()=>{const update=()=>{if(window.innerWidth>200)setCompact(window.innerWidth<980);};window.addEventListener('resize',update);return()=>window.removeEventListener('resize',update);},[]);
 const [riskLines,setRiskLines]=useState<string[]>([]),[riskFaces,setRiskFaces]=useState<string[]>([]);
 const [verifiedResidueLines,setVerifiedResidueLines]=useState<string[]>([]),[residueFocusLines,setResidueFocusLines]=useState<string[]>([]);
 const [textReviewRequest,setTextReviewRequest]=useState<{feature_id:string;ticket:number}|undefined>(),[textReviewOpened,setTextReviewOpened]=useState(false);
 const [activePropertySection,setActivePropertySection]=useState('appearance');
 const propertySectionRef=useRef(activePropertySection);propertySectionRef.current=activePropertySection;
 const workspaceSession=useWorkspace(state=>state.session);
 const textReviewTicket=useRef(0);
 const [propertyReveal,setPropertyReveal]=useState<{key:string;ticket:number;identity:string}|undefined>();
 const {layer,setLayer,selected,setSelected,zoom,setZoom,setScroll,gesture,setGesture,preview,setPreview}=useWorkspace(useShallow(state=>({layer:state.layer,setLayer:state.setLayer,selected:state.selected,setSelected:state.setSelected,zoom:state.zoom,setZoom:state.setZoom,setScroll:state.setScroll,gesture:state.gesture,setGesture:state.setGesture,preview:state.preview,setPreview:state.setPreview})));
 useEffect(()=>{setTextReviewRequest(undefined);setVerifiedResidueLines([]);setResidueFocusLines([]);},[project.project_id,asset.asset_id,layer,workspaceSession]);
 useEffect(()=>setTextReviewOpened(false),[project.project_id,asset.asset_id,workspaceSession]);
 const [tool,setTool]=useState('pick'),[mode,setMode]=useState('replace'),[radius,setRadius]=useState(4),[maxArea,setMaxArea]=useState(12),[gap,setGap]=useState(30),[operations,setOperations]=useState<Operation[]>([]),[styles,setStyles]=useState<Style[]>([]),[layers,setLayers]=useState<Layer[]>([]),[leftMode,setLeftMode]=useState('source'),[rightMode,setRightMode]=useState('source'),[threshold,setThreshold]=useState<number|undefined>(),[adoptMode,setAdoptMode]=useState('keep_current');
 const [comparison,setComparison]=useState(false),[shown,setShown]=useState({face:true,line:true,text:true,isolated_line:false}),[canvasErrors,setCanvasErrors]=useState<Record<string,boolean>>({});
 const [regionRule,setRegionRule]=useState<'touch'|'center'|'cover50'>('touch');
 function changeBackground(side:'left'|'right',value:string){setCanvasErrors(old=>({...old,[side]:false}));(side==='left'?setLeftMode:setRightMode)(value);}
 function toggleLayer(kind:keyof typeof shown,value:boolean){setShown(old=>({...old,[kind]:value}));if(!value){setSelected(old=>old.filter(id=>{const feature=featuresById[id];return feature&&itemLayer(feature)!==kind;}));setPreview(null);}}
 const left=useRef<HTMLDivElement>(null),right=useRef<HTMLDivElement>(null),svg=useRef<SVGSVGElement>(null),drawing=useRef(false),panStart=useRef<{x:number;y:number;left:number;top:number}|null>(null),pointerOrigin=useRef<Point|null>(null),latestPan=useRef<{left:number;top:number}>({left:0,top:0});
 function resetView(){
  const panels=[right.current,...(comparison?[left.current]:[])].filter((panel):panel is HTMLDivElement=>!!panel);
  if(!panels.length||panels.some(panel=>panel.clientWidth<1||panel.clientHeight<1))return;
  const fit=Math.min(...panels.map(panel=>Math.min(panel.clientWidth/asset.width_px,panel.clientHeight/asset.height_px)));
  setZoom(Math.max(.01,Math.min(12,fit)));setScroll({left:0,top:0});
  for(const panel of panels){panel.scrollLeft=0;panel.scrollTop=0;}
 }
 function zoomView(factor:number,panel=right.current,client?:{x:number;y:number}){
  const state=useWorkspace.getState(),next=Math.max(.01,Math.min(12,state.zoom*factor));
  if(panel){const rect=panel.getBoundingClientRect(),surface=panel.querySelector('svg,img')?.getBoundingClientRect();
   const px=client?client.x-rect.left:panel.clientWidth/2,py=client?client.y-rect.top:panel.clientHeight/2;
   const originX=surface?surface.left-rect.left:-panel.scrollLeft,originY=surface?surface.top-rect.top:-panel.scrollTop;
   const assetX=(px-originX)/state.zoom,assetY=(py-originY)/state.zoom;
   setScroll({left:Math.max(0,assetX*next+Math.max(0,(panel.clientWidth-asset.width_px*next)/2)-px),top:Math.max(0,assetY*next+Math.max(0,(panel.clientHeight-asset.height_px*next)/2)-py)});
  }
  setZoom(next);
 }
 const wheelZoom=useRef(zoomView);wheelZoom.current=zoomView;
 useEffect(()=>{const panels=[right.current,left.current].filter((p):p is HTMLDivElement=>!!p);let frame=0,delta=0,target:HTMLDivElement|null=null,point={x:0,y:0};
  const wheel=(event:WheelEvent)=>{if(!event.ctrlKey)return;event.preventDefault();delta+=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?300:1);target=event.currentTarget as HTMLDivElement;point={x:event.clientX,y:event.clientY};if(!frame)frame=requestAnimationFrame(()=>{frame=0;const factor=Math.exp(Math.max(-1,Math.min(1,-delta*.002)));delta=0;wheelZoom.current(factor,target,point);});};
  for(const panel of panels)panel.addEventListener('wheel',wheel,{passive:false});return()=>{for(const panel of panels)panel.removeEventListener('wheel',wheel);if(frame)cancelAnimationFrame(frame);};
 },[comparison,asset.asset_id]);
 useEffect(()=>{const update=(event:Event)=>wheelZoom.current((event as CustomEvent<number>).detail);window.addEventListener('mapvector-zoom',update);return()=>window.removeEventListener('mapvector-zoom',update);},[]);
 useEffect(()=>{let fitted=false;const fit=()=>{const panel=right.current;if(!panel||panel.clientWidth<1||panel.clientHeight<1||fitted)return;fitted=true;resetView();};const observer=new ResizeObserver(fit);if(right.current)observer.observe(right.current);fit();return()=>observer.disconnect();},[asset.asset_id,comparison]);
 const metadataSession=useRef(0);useEffect(()=>()=>{metadataSession.current+=1;},[]);
 const prefix='/projects/'+project.project_id;
 const needsReview=(item:TextFeature)=>item.review_status==='required'||item.review_status==='manual_edited';
 useEffect(()=>{objectTicket.current+=1;},[project.project_id,asset.asset_id,stage,layer,JSON.stringify(selected)]);
 function objectContext(){const state=useWorkspace.getState();return {ticket:objectTicket.current,session:state.session,projectId:state.project?.project_id,assetId:state.asset?.asset_id,stage:state.stage,layer:state.layer,selected:[...state.selected]};}
 function sameObject(context:ReturnType<typeof objectContext>){const state=useWorkspace.getState();return context.ticket===objectTicket.current&&context.session===state.session&&context.projectId===state.project?.project_id&&context.assetId===state.asset?.asset_id&&context.stage===state.stage&&context.layer===state.layer&&context.selected.length===state.selected.length&&context.selected.every((id,index)=>id===state.selected[index]);}
 const featuresById=useWorkspace(state=>state.featuresById);const current=featuresById[selected[0]];
 const textFeature=current?.feature_type==='text'?current:undefined,lineFeature=current?.feature_type==='line'?current:undefined;
 const propertyScope=useMemo(()=>({projectId:project.project_id,assetId:asset.asset_id,layer,featureIds:selected}),[project.project_id,asset.asset_id,layer,selected]);
 const drafts=usePropertyDrafts(propertyScope,{text:textFeature?.text_value??'',fontSize:textFeature?.font_size_px??12,angle:textFeature?.rotation_deg??0,color:textFeature?.text_color??lineFeature?.stroke_color??(current?.feature_type==='face'?current.fill_color:undefined)??'#000000',width:lineFeature?.stroke_width_px??2,role:lineFeature?.line_role??'unknown',moveX:textFeature?.geometry.type==='Point'?textFeature.geometry.coordinates[0]:0,moveY:textFeature?.geometry.type==='Point'?textFeature.geometry.coordinates[1]:0,styleId:undefined,styleName:'',pattern:'solid',dash:'6,4',toothSpacing:10,toothHeight:4,toothSide:'left'});
 const autosave=usePropertyAutosave({scope:propertyScope,features,drafts,command:rawCommand,assetSize:{width:asset.width_px,height:asset.height_px},generation:useWorkspace.getState().session});
 const command:Command=async(body,options)=>{if(!await autosave.flush())return;return rawCommand(body,options);};
 const {text,fontSize,angle,color,width}=drafts.values;
 async function propertyCommand(body:CommandInput){
  let fields:DraftField[]=[];
  if(['update_text','create_text'].includes(body.operation_type))fields=['text','fontSize','angle','color','moveX','moveY'];
  else if(body.operation_type==='set_feature_color')fields=['color'];
  else if(body.operation_type==='set_line_width')fields=['width'];
  else if(body.operation_type==='set_line_role')fields=['role'];
  else if(body.operation_type==='create_line')fields=['color','width'];
  else if(body.operation_type==='set_style')fields=['styleId','styleName','color','width','pattern','dash','toothSpacing','toothHeight','toothSide'];
  if(drafts.invalidFields.some(field=>fields.includes(field)))throw Error('有属性输入尚未填写完整，请核对数值或颜色后保存。草稿仍保留。');
  const submitted=drafts.capture(),result=await command(body);
  if(result)drafts.saved(fields,submitted);
  return result;
 }
 const itemLayer=(f:Feature)=>f.feature_type==='line'&&f.lifecycle_status==='isolated'?'isolated_line':f.feature_type;
 const draftScopes=propertyDraftScopes(project.project_id,asset.asset_id);
 const draftAvailable=(scope:(typeof draftScopes)[number])=>scope.featureIds.every(id=>featuresById[id]&&itemLayer(featuresById[id])===scope.layer);
 const unavailableDrafts=draftScopes.filter(scope=>!draftAvailable(scope)).length;
 const visible=useMemo(()=>features.map(f=>autosave.previewFeature?.feature_id===f.feature_id?autosave.previewFeature:f).filter(f=>shown[itemLayer(f) as keyof typeof shown]).sort((a,b)=>(a.feature_type==='face'?0:a.feature_type==='line'?1:2)-(b.feature_type==='face'?0:b.feature_type==='line'?1:2)),[features,shown,autosave.previewFeature]);
 const residueDisplay=preview?.preview_type==='text_residue'?preview.text_residue_display:null;
 const sceneFeatures=useMemo(()=>residueDisplay?(residueShown.context?visible.filter(f=>f.feature_type!=='text'):[]):visible,[visible,residueDisplay,residueShown.context]);
 const counts=useMemo(()=>({face:features.filter(f=>f.feature_type==='face').length,line:features.filter(f=>f.feature_type==='line'&&f.lifecycle_status==='active').length,text:features.filter(f=>f.feature_type==='text').length}),[features]);
 const pendingRun=useWorkspace(state=>state.task);
 const unsavedRecognition=!features.length&&!!pendingRun?.pipeline_id.startsWith('legacy_b2c')&&['completed','completed_with_warnings'].includes(pendingRun.run_status)&&!pendingRun.adopted_operation_id;
 const layerConfig=layers.find(item=>item.layer_type===layer);
 const opacityScope=JSON.stringify([project.project_id,asset.asset_id,layer]);
 const [opacityPreview,setOpacityPreview]=useState<{scope:string;percentage:number}|null>(null);
 useEffect(()=>setOpacityPreview(null),[opacityScope]);
 const displayedLayers=useMemo(()=>{
  if(opacityPreview?.scope!==opacityScope)return layers;
  const display=layers.map(item=>({layer_type:item.layer_type,opacity:item.layer_type===layer?opacityPreview.percentage/100:item.opacity}));
  if(!display.some(item=>item.layer_type===layer))display.push({layer_type:layer,opacity:opacityPreview.percentage/100});
  return display;
 },[layers,opacityPreview,opacityScope,layer]);
 function previewOpacity(percentage:number|null){setOpacityPreview(current=>percentage===null?(current?.scope===opacityScope?null:current):{scope:opacityScope,percentage});}
 async function saveOpacity(percentage:number){return work(async()=>{
  const result=await command({operation_type:'set_layer',layer_type:layer as 'face'|'line'|'text'|'isolated_line',is_visible:layerConfig?.is_visible!==false,opacity:percentage/100});
  if(result){clearObjectPreview();const settings=await request<Page<Layer>>(prefix+'/layers?asset_id='+asset.asset_id);const currentState=useWorkspace.getState();if(currentState.project?.project_id===project.project_id&&currentState.asset?.asset_id===asset.asset_id)setLayers(settings.items);}
  return result;
 });}
 const enabled=!busy&&!!asset&&!unsavedRecognition;
 const editableLayerVisible=shown[layer as keyof typeof shown];
 async function reloadHistory(){const ticket=++metadataSession.current;const history=await request<Page<Operation>>(prefix+'/operations?include_results=false&asset_id='+asset.asset_id);if(ticket===metadataSession.current){setOperations(history.items);if(['set_style','bind_style','set_layer','undo','redo'].includes(history.items[0]?.operation_type)){const [library,settings]=await Promise.all([request<Page<Style>>(prefix+'/styles'),request<Page<Layer>>(prefix+'/layers?asset_id='+asset.asset_id)]);if(ticket===metadataSession.current){setStyles(library.items);setLayers(settings.items);}}}}
 useEffect(()=>{let active=true;void Promise.all([request<Page<Style>>(prefix+'/styles'),request<Page<Layer>>(prefix+'/layers?asset_id='+asset.asset_id)]).then(([library,settings])=>{if(active){setStyles(library.items);setLayers(settings.items);}}).catch(error=>info(String(error)));return()=>{active=false;};},[project.project_id,asset.asset_id]);
 useEffect(()=>{const draft=draftScopes.find(scope=>draftAvailable(scope)&&(!initialTextLayer||scope.layer==='text'));if(draft){setLayer(draft.layer);setSelected(draft.featureIds);}else{setSelected([]);if(initialTextLayer)setLayer('text');}setPreview(null);setScroll({left:0,top:0});},[project.project_id,asset.asset_id]);
 useEffect(()=>{setPreview(null);void reloadHistory().catch(error=>info(String(error)));},[project.project_id,asset.asset_id,project.working_revision]);
 useCanvasScroll(left,right,comparison,zoom,asset.asset_id);
 useEffect(()=>{if(!focus)return;setPreview(null);setPreviewError('');const f=featuresById[focus.feature_id];if(!f||f.feature_type!=='text')return;setLayer('text');setShown(old=>({...old,text:true}));setSelected([focus.feature_id]);setTool('pick');const panel=right.current;if(panel&&f.geometry.type==='Point'){const bbox=f.display_bbox_px;const next=Math.min(12,Math.max(zoom,Math.min(panel.clientWidth/Math.max(160,bbox?bbox[2]-bbox[0]+80:200),panel.clientHeight/Math.max(120,bbox?bbox[3]-bbox[1]+60:160))));const x=bbox?(bbox[0]+bbox[2])/2:f.geometry.coordinates[0],y=bbox?(bbox[1]+bbox[3])/2:f.geometry.coordinates[1];setZoom(next);setScroll({left:Math.max(0,x*next-panel.clientWidth/2),top:Math.max(0,y*next-panel.clientHeight/2)});}if(!focus.residue)previewTicket.current+=1;setPreviewPending(false);if(focus.residue)void work(()=>makePreview('text_residue',{feature_ids:[f.feature_id]}));},[focus]);
 const submit=(body:CommandInput)=>work(async()=>{const result=await propertyCommand(body);if(result)clearObjectPreview();return result;});
 async function select(body:Record<string,unknown>){if(!await autosave.flush())return;const result=await request<{feature_ids:string[]}>(prefix+'/selections',{asset_id:asset.asset_id,feature_type:layer==='isolated_line'?'line':layer,lifecycle_status:layer==='isolated_line'?'isolated':'active',feature_ids:mode==='replace'&&['pick','box','gesture','text_pick'].includes(String(body.selection_type))?[]:useWorkspace.getState().selected,selection_mode:mode,...body});if(useWorkspace.getState().project?.project_id===project.project_id)setSelected(result.feature_ids);setPreview(null);}
 async function applyProperties(){return work(async()=>{
  const patch=buildPropertyPatch(propertyScope,features,drafts.values,drafts.capture(),drafts.invalidFields,{width:asset.width_px,height:asset.height_px});
  if(patch.invalid){info('有属性输入尚未填写完整，请核对数值或颜色。');return;}
  if(!patch.command){drafts.saved(patch.fields,patch.submitted);return;}
  const result=await rawCommand(patch.command);if(result){drafts.saved(patch.fields,patch.submitted);clearObjectPreview();}return result;
 });}
 async function historyAction(kind:'undo'|'redo'){return work(async()=>{
  if(!await autosave.flush())return;
  const context=objectContext(),history=await request<Page<Operation>>(prefix+'/operations?include_results=false&asset_id='+asset.asset_id);
  if(!sameObject(context))return;
  setOperations(history.items);const target=history.items.find(item=>kind==='undo'?item.can_undo:item.can_redo);if(!target)return;
  const result=await rawCommand({operation_type:kind,target_operation_id:target.operation_id});if(result)clearObjectPreview();return result;
 });}
 async function locateSelected(){
  const context=objectContext();if(!await autosave.flush()||!sameObject(context))return;
  const state=useWorkspace.getState(),picked=state.selected.map(id=>state.featuresById[id]).filter((item):item is Feature=>!!item);
  if(!picked.length)return;
  const boxes=picked.map(item=>item.feature_type==='text'&&item.display_bbox_px?item.display_bbox_px:geometryBounds(item.geometry));
  locateRegion([Math.min(...boxes.map(box=>box[0])),Math.min(...boxes.map(box=>box[1])),Math.max(...boxes.map(box=>box[2])),Math.max(...boxes.map(box=>box[3]))]);
 }
 function locateRegion(bounds:number[]){const panel=right.current;if(!panel)return;const [x0,y0,x1,y1]=bounds,next=Math.max(.01,Math.min(12,panel.clientWidth/Math.max(60,x1-x0+50),panel.clientHeight/Math.max(60,y1-y0+50)));setZoom(next);setScroll({left:Math.max(0,(x0+x1)*next/2+Math.max(0,(panel.clientWidth-asset.width_px*next)/2)-panel.clientWidth/2),top:Math.max(0,(y0+y1)*next/2+Math.max(0,(panel.clientHeight-asset.height_px*next)/2)-panel.clientHeight/2)});}
 async function syncPreviewRevision(session:number){
  const latest=await request<Project>(prefix);const state=useWorkspace.getState();
  if(state.session!==session||state.project?.project_id!==project.project_id)throw new DOMException('页面已切换','AbortError');
  if(latest.current_asset_id!==asset.asset_id)throw Error('当前原图已切换，请重新打开项目后再生成残影预览。');
  const items:Feature[]=[];let cursor:string|null=null;
  do{const page:FeaturePage=await request<FeaturePage>(prefix+'/features?asset_id='+asset.asset_id+'&limit=2000'+(cursor?'&cursor='+cursor:''));if(page.working_revision!==latest.working_revision)throw Error('加载期间项目再次更新，请重新点击生成预览。');items.push(...page.items);cursor=page.next_cursor;}while(cursor);
  if(useWorkspace.getState().session!==session)throw new DOMException('页面已切换','AbortError');
  const available=new Set(items.map(feature=>feature.feature_id));
  state.setProject(latest);state.setFeatures(items);state.setSelected(ids=>ids.filter(id=>available.has(id)));
  return latest.working_revision;
 }
 async function makePreview(kind:string,extra:Record<string,unknown>={},options:{reveal?:boolean}={}){
  if(!await autosave.flush())return;
  const ticket=++previewTicket.current,start=useWorkspace.getState(),session=start.session,sectionAtStart=propertySectionRef.current;
  const ids=Array.isArray(extra.feature_ids)?extra.feature_ids as string[]:[...start.selected];
  const selection=kind==='text_residue'&&ids.length?[...ids]:[...start.selected];setPreviewError('');setPreviewPending(true);setPreview(null);
  try{
   let revision=start.project?.working_revision??project.working_revision;let result:Preview|undefined;
   for(let attempt=0;attempt<2;attempt++){
    const state=useWorkspace.getState();
    if(ticket!==previewTicket.current||state.session!==session||state.asset?.asset_id!==asset.asset_id)return;
    for(const id of ids)if(!state.featuresById[id])throw Error('所选对象已不在当前结果中，请重新选择文字。');
    try{result=await request<Preview>(prefix+'/edit-previews',{asset_id:asset.asset_id,base_revision:revision,preview_type:kind,feature_ids:ids,...extra});break;}
    catch(error){if(attempt===0&&error instanceof ApiError&&error.code==='REVISION_CONFLICT'){revision=await syncPreviewRevision(session);continue;}throw error;}
   }
   const state=useWorkspace.getState();
   if(!result||ticket!==previewTicket.current||state.session!==session||state.asset?.asset_id!==asset.asset_id||state.project?.working_revision!==revision||selection.length!==state.selected.length||selection.some((id,index)=>id!==state.selected[index]))return;
   setPreview(result);setRiskLines([]);setVerifiedResidueLines([]);setResidueFocusLines([]);setRiskFaces([]);setFaceAssignments({});setPropertyOpen(true);
   if(result.text_residue_display){if(!ids.length)setPropertyReveal({key:'residue',ticket:++textReviewTicket.current,identity:JSON.stringify([project.project_id,asset.asset_id,state.layer,[...state.selected].sort()])});setResidueShown({faces:true,lines:true,protected:true,context:false});changeBackground('right','source');locateRegion(result.text_residue_display.bounds_px);}
   if(kind!=='text_residue'&&options.reveal!==false&&propertySectionRef.current===sectionAtStart)setPropertyReveal({key:kind.startsWith('merge_')?'face_merge':kind==='heal_faces'?'face_repair':'line_edit',ticket:++textReviewTicket.current,identity:JSON.stringify([project.project_id,asset.asset_id,state.layer,[...state.selected].sort()])});
   return result;
  }catch(error){if(ticket===previewTicket.current&&!(error instanceof DOMException&&error.name==='AbortError')){setPreviewError(String(error));setPropertyOpen(true);}throw error;}
  finally{if(ticket===previewTicket.current)setPreviewPending(false);}
 }
 async function nextReview(context:ReturnType<typeof objectContext>,completed=false,afterId=context.selected[0]){
  if(!await autosave.flush()||!sameObject(context))return;
  let queue:Page<TextFeature>;
  try{queue=await request<Page<TextFeature>>(prefix+'/reviews?asset_id='+asset.asset_id+'&include_all=true');}
  catch(error){if(sameObject(context)&&!(error instanceof DOMException&&error.name==='AbortError'))info(completed?'处理已保存，列表暂未刷新。':'列表暂未刷新，请重试。');return;}
  if(!sameObject(context))return;
  const state=useWorkspace.getState(),index=queue.items.findIndex(item=>item.feature_id===afterId);
  state.setReviews(queue.items);
  const ordered=index<0?queue.items:[...queue.items.slice(index+1),...queue.items.slice(0,index)];
  const next=ordered.find(item=>needsReview(item)&&state.featuresById[item.feature_id]?.feature_type==='text');
  if(!next){if(completed)info('当前待核对文字已处理完。');return;}
  clearObjectPreview();setLayer('text');setSelected([next.feature_id]);setTool('pick');
  if(next.geometry.type==='Point')setScroll({left:Math.max(0,next.geometry.coordinates[0]*zoom-150),top:Math.max(0,next.geometry.coordinates[1]*zoom-150)});
 }
 async function reviewText(action:'confirm'|'skip',targetId?:string){
  if(busy||reviewInFlight.current)return;
  const context=objectContext(),id=targetId??context.selected[0],feature=useWorkspace.getState().featuresById[id];
  if(context.layer!=='text'||feature?.feature_type!=='text'||feature.lifecycle_status!=='active')return;
  reviewInFlight.current=true;
  try{await work(async()=>{
   if(!await autosave.flush()||!sameObject(context))return;
   const result=await command({operation_type:action==='confirm'?'confirm_text':'skip_text',feature_ids:[id]});
   if(!result||!sameObject(context))return;
   clearObjectPreview();
   // New typing made while saving remains on this object instead of being navigated away.
   if(action==='confirm'&&drafts.capture()){info('文字已确认，新输入仍保留为草稿。');return;}
   await nextReview(context,true,id);
  });}finally{reviewInFlight.current=false;}
 }
 async function openResidueReview(){
  setTextReviewOpened(true);
  const context=objectContext();if(!await autosave.flush()||!sameObject(context)||propertySectionRef.current!=='residue')return;
  const state=useWorkspace.getState(),existing=state.preview,id=state.selected[0];
  const validPreview=existing?.preview_type==='text_residue'&&existing.base_revision===state.project?.working_revision&&(!existing.expires_at||Date.parse(existing.expires_at)>Date.now());
  if(validPreview&&existing.feature_ids.length===0&&existing.text_residue_display?.preserves_existing_text){setTextReviewRequest(undefined);return;}
  if(state.selected.length!==1||state.featuresById[id]?.feature_type!=='text')return;
  setTextReviewRequest({feature_id:id,ticket:++textReviewTicket.current});
  if(validPreview&&existing.feature_ids.length===1&&existing.feature_ids[0]===id)return;
  return makePreview('text_residue',{feature_ids:[id]});
 }
 const residueEntry=useRef(openResidueReview);residueEntry.current=openResidueReview;
 useEffect(()=>{
  if(layer!=='text'||activePropertySection!=='residue')return;
  const timer=window.setTimeout(()=>void work(()=>residueEntry.current()),0);
  return()=>{window.clearTimeout(timer);previewTicket.current+=1;setPreviewPending(false);};
 },[project.project_id,asset.asset_id,workspaceSession,layer,activePropertySection,JSON.stringify(selected)]);
 async function guardResiduePreview(){
  const plan=useWorkspace.getState().preview,context=objectContext();
  if(plan?.preview_type!=='text_residue'||!await autosave.flush()||!sameObject(context))return false;
  const state=useWorkspace.getState();
  if(state.preview?.preview_id!==plan.preview_id||state.project?.working_revision!==plan.base_revision||(plan.expires_at&&Date.parse(plan.expires_at)<=Date.now())){clearObjectPreview();info('残影检查已更新，请重新查看。');return false;}
  return true;
 }
 async function refreshResiduePreview(){const state=useWorkspace.getState(),plan=state.preview;if(plan?.preview_type==='text_residue'&&plan.feature_ids.length===0&&plan.text_residue_display?.preserves_existing_text)await makePreview('text_residue',{feature_ids:[],bounds_px:plan.text_residue_display.bounds_px});else if(state.selected.length===1&&state.featuresById[state.selected[0]]?.feature_type==='text')await makePreview('text_residue',{feature_ids:[state.selected[0]]});}
 async function cleanupResidue(){
  if(busy||cleanupInFlight.current)return;
  const context=objectContext(),state=useWorkspace.getState(),feature=state.featuresById[context.selected[0]],reviewPlan=state.preview?.preview_type==='text_residue'?state.preview:null,range=reviewPlan?.text_residue_display,verified=[...verifiedResidueLines];
  const regionReview=reviewPlan?.feature_ids.length===0;
  const ids=!regionReview&&context.selected.length===1&&feature?.feature_type==='text'?[feature.feature_id]:[];
  if(!ids.length&&!(regionReview&&range?.preserves_existing_text))return;
  cleanupInFlight.current=true;setCleanupPending(true);
  try{await work(async()=>{
   const plan=await makePreview('text_residue',{feature_ids:ids,complete_region:true,...(verified.length?{verified_line_feature_ids:verified,line_review_preview_id:reviewPlan?.preview_id}:{}),...(!ids.length&&range?{bounds_px:range.bounds_px}:{})});
   if(!plan||!sameObject(context))return;
   const display=plan.text_residue_display;
   if(!display?.complete_region||!display.preserves_existing_text)throw Error('无法确定对应文字，请缩小范围后重试。');
   if(display.cleanup_face_feature_ids.length+display.cleanup_line_feature_ids.length===0){info('未发现可清理的残影。');return;}
   const result=await command({operation_type:'cleanup_text_residue',preview_id:plan.preview_id,complete_region:true,...(verified.length?{verified_line_feature_ids:verified}:{})});
   if(result&&sameObject(context)){clearObjectPreview();info('残影已清理，可撤销。');if(ids.length){setTextReviewRequest({feature_id:ids[0],ticket:++textReviewTicket.current});await refreshResiduePreview();}}
  });}finally{cleanupInFlight.current=false;setCleanupPending(false);}
 }
 function pixel(event:React.PointerEvent<SVGSVGElement>):Point{const bounds=event.currentTarget.getBoundingClientRect();return [(event.clientX-bounds.left)/zoom,(event.clientY-bounds.top)/zoom];}
 function down(event:React.PointerEvent<SVGSVGElement>){if(!enabled||(!editableLayerVisible&&tool!=='pan'))return;const point=pixel(event);pointerOrigin.current=point;if(!['pick','text','split','pan'].includes(tool))setGesture([point]);if(tool==='pan'){const panel=right.current;panStart.current={x:event.clientX,y:event.clientY,left:panel?.scrollLeft??0,top:panel?.scrollTop??0};}drawing.current=true;event.currentTarget.setPointerCapture(event.pointerId);}
 function move(event:React.PointerEvent<SVGSVGElement>){if(!drawing.current)return;if(tool==='pan'&&panStart.current){const panel=right.current;if(panel){latestPan.current={left:Math.max(0,panStart.current.left-(event.clientX-panStart.current.x)),top:Math.max(0,panStart.current.top-(event.clientY-panStart.current.y))};panel.scrollLeft=latestPan.current.left;panel.scrollTop=latestPan.current.top;}return;}if(['pick','text','split'].includes(tool))return;const point=pixel(event);setGesture(old=>tool==='box'||tool==='roi'||tool==='ocr'||tool==='residue'?[old[0],point]:[...old,point]);}
  function up(event:React.PointerEvent<SVGSVGElement>){if(!drawing.current)return;drawing.current=false;if(tool==='pan'){panStart.current=null;return;}const point=pixel(event),start=pointerOrigin.current??point,points=gesture.length>1?[...gesture,point]:[start,point];if(!['pick','text','split','pan'].includes(tool))setGesture([]);panStart.current=null;if(tool==='pan')return;void work(async()=>{
    if(!await autosave.flush())return;
   if(tool==='residue_lines'){
    const context=objectContext(),plan=useWorkspace.getState().preview;if(!await guardResiduePreview()||!sameObject(context)||!plan?.text_residue_display)return;
    const groups=(plan.text_residue_display as ResidueReviewDisplay).review_groups??[],allowed=new Set(groups.filter(g=>g.can_confirm&&g.status==='pending').flatMap(g=>g.feature_ids));
    const result=await request<{feature_ids:string[]}>(prefix+'/selections',{asset_id:asset.asset_id,selection_type:'gesture',gesture_kind:'brush',feature_type:'line',lifecycle_status:'active',points,radius_px:radius,feature_ids:mode==='replace'?[]:riskLines,selection_mode:mode},undefined,{quiet:true});
    if(sameObject(context)&&useWorkspace.getState().preview?.preview_id===plan.preview_id){const ids=result.feature_ids.filter(id=>allowed.has(id));setRiskLines(ids);setResidueFocusLines(ids);}return;
   }
   if(tool==='draw'){await propertyCommand({operation_type:'create_line',coordinates:points,stroke_width_px:width,stroke_color:color,snap_px:3});return;}
   if(tool==='text'){if(!text.trim())throw Error('请先输入补录文字。');await propertyCommand({operation_type:'create_text',x:point[0],y:point[1],text_value:text,font_size_px:fontSize,rotation_deg:angle,text_color:color});return;}
   if(tool==='split'){if(selected.length!==1)throw Error('请先选中一条线，再点击切分位置。');await command({operation_type:'split_line',feature_ids:selected,x:point[0],y:point[1]});return;}
   const bounds=[Math.min(start[0],point[0]),Math.min(start[1],point[1]),Math.max(start[0],point[0]),Math.max(start[1],point[1])];
   if(tool==='roi'){await command({operation_type:'set_roi',bounds_px:bounds as [number,number,number,number]});info('ROI 已保存；请保存新快照后导出。');return;}
   if(tool==='ocr'){const run=await request<{run_id:string}>(prefix+'/runs',{pipeline_id:'ocr_rapid',input_region_px:bounds});info('局部 OCR 已受理。请在识别任务中查看进度、在文字审核中采用候选。');await refresh();return;}
   if(tool==='residue'){await makePreview('text_residue',{feature_ids:[],bounds_px:bounds as [number,number,number,number]});return;}
   if(tool==='heal'){await makePreview('heal_faces',{feature_ids:[],points,radius_px:radius,max_area_px2:maxArea});return;}
   if(tool==='box'){await select({selection_type:'box',bounds_px:bounds as [number,number,number,number]});return;}
   if(tool==='brush'||tool==='lasso'){await select({selection_type:'gesture',gesture_kind:tool==='brush'?'brush':'lasso',points,radius_px:radius,rule:layer==='face'?regionRule:'touch',max_area_px2:layer==='face'?maxArea:null});return;}
   const result=await request<{feature_ids:string[]}>(prefix+'/selections',{asset_id:asset.asset_id,selection_type:layer==='text'?'text_pick':'pick',feature_type:layer==='isolated_line'?'line':layer,lifecycle_status:layer==='isolated_line'?'isolated':'active',feature_ids:event.shiftKey||mode!=='replace'?useWorkspace.getState().selected:[],selection_mode:event.shiftKey?'add':mode,x:point[0],y:point[1]});const ids=result.feature_ids;
   if(layer==='text'&&ids.length>1&&mode==='replace'&&!event.shiftKey){Modal.info({title:'此位置有多个文字，请明确选择',content:<Space direction="vertical">{ids.map(id=><Button key={id} onClick={()=>{previewTicket.current+=1;setPreview(null);setPreviewPending(false);setPreviewError('');setSelected([id]);Modal.destroyAll();}}>{featuresById[id]?.feature_type==='text'?featuresById[id].text_value:id}</Button>)}</Space>});return;}if(useWorkspace.getState().project?.project_id!==project.project_id||useWorkspace.getState().asset?.asset_id!==asset.asset_id)return;previewTicket.current+=1;setPreviewPending(false);setPreviewError('');setSelected(ids);setPreview(null);
 },{quiet:['pick','box','brush','lasso','residue_lines'].includes(tool)});}
 const paths=geometryPath;
 function rasterUrl(type:string){return '/api'+prefix+'/rasters/'+type+'?asset_id='+asset.asset_id+'&revision='+project.working_revision+(threshold===undefined||!type.startsWith('residual_')?'':'&threshold='+threshold);}
 function panel(side:'left'|'right'){
  const renderMode=side==='left'?leftMode:rightMode;
  return <Card title={side==='left'?'原图与基线对照':'当前结果与差异'} className={'canvas-card '+(side==='left'?'reference-card':'result-card')} extra={<Space size={8} wrap>{side==='left'?<Select aria-label="对照底图" value={leftMode} className="canvas-mode" onChange={value=>changeBackground('left',value)} options={basemaps}/>:null}<Space className="canvas-zoom-controls" size={8}><Button disabled={zoom>=12} onClick={()=>zoomView(1.25,side==='left'?left.current:right.current)}>放大</Button><Button disabled={zoom<=.01} onClick={()=>zoomView(1/1.25,side==='left'?left.current:right.current)}>缩小</Button>{side==='right'&&<Button disabled={busy||selected.length===0} onClick={()=>void work(locateSelected,{quiet:true})}>定位</Button>}<Button onClick={resetView}>复位</Button><span aria-label="当前缩放比例" className="zoom-percentage">{Math.round(zoom*1000)/10}%</span></Space></Space>}>
   {renderMode.startsWith('residual')&&<Alert type="info" showIcon className="canvas-view-hint" message="差异图只比较面和线，不包含独立文字；不能表示完整外观。" description="核对真实提取请在右侧切换白底，分别显示面、线；独立文字另行核对。" action={side==='right'?<Button size="small" onClick={()=>{changeBackground('right','blank');setShown({face:true,line:true,text:false,isolated_line:false});}}>查看白底面线</Button>:undefined}/>}
   {canvasErrors[side]&&<Alert className="canvas-load-error" type="warning" showIcon message="该底图暂不可用，请切换原图或白底。"/>}
   {side==='right'&&unsavedRecognition&&<Alert type="info" className="canvas-view-hint" message="识别结果尚未保存，当前显示识别预览" action={<Button size="small" onClick={onReturnToRecognition}>返回步骤 2 保存</Button>}/>}
   <div className="canvas" ref={side==='left'?left:right}><div className="canvas-content">
    {side==='left'?<svg className="reference-canvas" width={asset.width_px*zoom} height={asset.height_px*zoom} viewBox={'0 0 '+asset.width_px+' '+asset.height_px}><rect width={asset.width_px} height={asset.height_px} fill="white"/>{renderMode!=='blank'&&<LoadingSvgImage key={renderMode} href={rasterUrl(renderMode)} width={asset.width_px} height={asset.height_px} onLoad={()=>setCanvasErrors(old=>({...old,[side]:false}))} onError={()=>setCanvasErrors(old=>({...old,[side]:true}))}/>}{layer==='line'&&shown.line&&lineCheck&&<LineCheckOverlay display={lineCheck} features={featuresById}/>}</svg>:unsavedRecognition?<LoadingImage alt="待保存的识别结果" style={{width:asset.width_px*zoom}} src={rasterUrl('render_compare')}/>:<svg ref={svg} width={asset.width_px*zoom} height={asset.height_px*zoom} viewBox={'0 0 '+asset.width_px+' '+asset.height_px} onDoubleClick={()=>{if(current?.feature_type==='text'){setPropertyOpen(true);window.setTimeout(()=>document.querySelector<HTMLInputElement>('input[aria-label="编辑文字"]')?.focus(),100);}}} onPointerDown={down} onPointerMove={move} onPointerUp={up} style={{touchAction:'none',cursor:tool==='pan'?'grab':editableLayerVisible?'crosshair':'default'}}><rect width={asset.width_px} height={asset.height_px} fill="white"/>{renderMode!=='blank'&&<LoadingSvgImage key={renderMode} href={rasterUrl(renderMode)} x={0} y={0} width={asset.width_px} height={asset.height_px} onLoad={()=>setCanvasErrors(old=>({...old,[side]:false}))} onError={()=>setCanvasErrors(old=>({...old,[side]:true}))}/>}<FeatureScene features={sceneFeatures} styles={styles} layers={displayedLayers} background={renderMode}/>{layer==='line'&&shown.line&&lineCheck&&<LineCheckOverlay display={lineCheck} features={featuresById}/>}{layer==='face'&&faceRepair&&<FaceRepairOverlay display={faceRepair} features={featuresById}/>}{residueDisplay?<TextResidueOverlay display={residueDisplay} features={featuresById} shown={residueShown} focused={residueFocusLines}/>:<><SelectedFeatureOverlay features={visible} selected={selected} background={renderMode}/>{preview?.affected_feature_ids?.filter(id=>visible.some(f=>f.feature_id===id)).map((id:string)=>{const item=featuresById[id];return item&&item.feature_type!=='text'?<path key={'preview-'+id} d={paths(item.geometry)} fill="none" stroke="#fa8c16" strokeWidth={2/zoom} strokeDasharray="4 2" pointerEvents="none"/>:null;})}</>}{gesture.length>1&&<path d={'M '+gesture.map(p=>p.join(' ')).join(' L ')} stroke="#1677ff" strokeWidth={Math.max(1/zoom,['brush','residue_lines'].includes(tool)?radius*2:1/zoom)} opacity={.5} fill="none"/>}</svg>}
   </div></div>
  </Card>;
 }
 const selectedFeatures=selected.map(id=>featuresById[id]).filter((item):item is Feature=>!!item);
 const hasSelection=selectedFeatures.length>0,creationMode=tool==='text'||tool==='draw';
 const canEditAppearance=hasSelection&&(layer!=='text'||selected.length===1)||creationMode;
 const otherDrafts=Math.max(0,drafts.count-(drafts.dirty?1:0));
 const deleteLabel='删除 '+selected.length+' 个'+(layer==='face'?'面':layer==='text'?'文字':'线')+'对象';
 const deleteAction=hasSelection?<Button danger className="property-delete-action" disabled={busy} onClick={()=>Modal.confirm({title:deleteLabel,okText:'删除',cancelText:'取消',okButtonProps:{danger:true},content:(layer==='face'?'删除后原位置将留下空缺。':'')+'本次删除记录进入历史，可通过撤销恢复。',onOk:()=>submit({operation_type:layer==='face'?'delete_faces':layer==='text'?'delete_text':'delete_lines',feature_ids:selected})})}>{deleteLabel}</Button>:null;
 const textActionProps={busy,selected:selected.length===1&&!!textFeature,
  onSkip:()=>void reviewText('skip'),
  onAdd:()=>{clearObjectPreview();setLayer('text');setSelected([]);setTool('text');setPropertyReveal({key:'appearance',ticket:++textReviewTicket.current,identity:JSON.stringify([project.project_id,asset.asset_id,'text',[]])});info('输入补录文字后，点击结果画布放置。');}};
 const propertyIdentity=JSON.stringify([project.project_id,asset.asset_id,layer,[...selected].sort()]);
 const geometryPreview=preview&&!['text_residue','merge_faces','merge_suggest'].includes(preview.preview_type)&&<Card size="small" title="预览结果">{!residueDisplay&&<p className="review-note">预览涉及 {preview.affected_feature_ids?.length??0} 个对象。核对画布后再执行。</p>}{residueDisplay&&<ResiduePlan preview={preview} busy={busy||cleanupPending} onLocate={()=>locateRegion(residueDisplay.bounds_px)} onCleanup={!textFeature&&residueDisplay.preserves_existing_text?()=>void cleanupResidue():undefined}/>}{!residueDisplay&&<details><summary>查看详细依据</summary><pre>{JSON.stringify(preview.legacy_report,null,2)}</pre></details>}{preview.preview_type==='heal_faces'&&preview.legacy_report.candidates?.filter((item:PreviewItem)=>item.decision==='uncertain').map((item:PreviewItem)=><Checkbox key={item.feature_id} checked={riskFaces.includes(item.feature_id??'')} onChange={e=>setRiskFaces(old=>e.target.checked?[...old,item.feature_id??'']:old.filter(id=>id!==item.feature_id))}>明确接受待定碎面 {item.feature_id?.slice(0,8)} · {item.reason}</Checkbox>)}{preview.preview_type==='line_to_face'&&<Button onClick={()=>Modal.confirm({title:'确认沿线宽恢复窄面',content:'影响 '+(preview.legacy_report.affected_face_feature_ids??[]).length+' 个面，并移除 '+preview.feature_ids.length+' 条源线。',onOk:()=>submit({operation_type:'line_to_face',preview_id:preview.preview_id,feature_ids:preview.feature_ids,stroke_width_px:width,fill_color:color})})}>确认线转面</Button>}{['heal_faces','split_faces'].includes(preview.preview_type)&&<Button disabled={busy} onClick={()=>void submit({operation_type:preview.preview_type as 'heal_faces'|'split_faces',preview_id:preview.preview_id,accept_uncertain_feature_ids:riskFaces,allow_mixed_algorithm_labels:allowMixed})}>确认本次编辑</Button>}</Card>;
 const propertyPanel=<Card title={<div className="property-title"><span>属性与操作</span><Tag color="blue">{layerNames[layer as keyof typeof layerNames]}对象</Tag><Tag>已选 {selected.length}</Tag></div>} className="property-card">
  <div className="object-property-content" onBlur={autosave.onBlur} onCompositionStart={autosave.onCompositionStart} onCompositionEnd={autosave.onCompositionEnd}>
   {otherDrafts>0&&<Alert type="warning" showIcon message={'另有 '+otherDrafts+' 组属性草稿未提交，切换后可继续编辑。'}/>}
   {!drafts.persistent&&drafts.dirty&&<Alert type="warning" showIcon message="草稿暂存在当前页面，浏览器未能持久保存。"/>}
   {hasSelection&&layer==='text'&&selected.length>1&&<p className="property-empty">选择一个文字对象以编辑或核对。</p>}
   {creationMode&&!hasSelection&&<p className="property-creation-hint">{tool==='text'?'输入文字参数后，点击画布放置。':'设置线参数后，在画布绘制。'}</p>}
   {(leftMode.startsWith('residual')||rightMode.startsWith('residual'))&&<><small>差异图不包含文字字形。</small><InputNumber aria-label="差异阈值" placeholder="差异阈值" min={0} max={255} value={threshold} onChange={value=>setThreshold(value===null?undefined:Number(value))}/></>}
   {autosave.status!=='idle'&&(hasSelection&&selected.length===1||autosave.status==='error'||autosave.status==='saving')&&<div className={'property-save-status property-save-'+autosave.status} role="status" aria-live="polite">
    <span>{({idle:'',pending:'等待自动保存…',saving:'保存中…',saved:'已保存',invalid:'请将数值或颜色填写完整，草稿已保留。',error:'保存失败，草稿已保留。'})[autosave.status]}</span>
    {autosave.status==='error'&&<><Button size="small" onClick={()=>void autosave.retry()}>重试保存</Button>{autosave.error&&<small>{autosave.error}</small>}</>}
   </div>}
   {selected.length>1&&layer!=='text'&&<div className="property-batch-apply"><p className="review-note">仅应用本次改动的属性。</p><Button block disabled={busy||!drafts.dirty||drafts.invalidFields.length>0} onClick={()=>void applyProperties()}>应用到 {selected.length} 个对象</Button></div>}
   {previewError&&activePropertySection!=='face_merge'&&<Alert className="preview-inline-error" type="error" showIcon message="操作未完成" description={previewError}/ >}
   <PropertySectionTabs contextKey={JSON.stringify([project.project_id,asset.asset_id,workspaceSession,layer])} onActiveChange={setActivePropertySection} revealRequest={propertyReveal?.identity===propertyIdentity?propertyReveal:undefined} items={[
    {key:'appearance',label:'外观属性',children:<>{canEditAppearance&&<ObjectAppearanceProperties disabled={busy} layer={layer} feature={current} selectedFeatures={selectedFeatures} drafts={drafts} cropSrc={textFeature?.display_bbox_px?'/api'+prefix+'/assets/'+asset.asset_id+'/crop?bounds_px='+textFeature.display_bbox_px.map((value,index)=>value+(index<2?-6:6)).join(','):undefined}/>}{layer==='text'&&<TextActions {...textActionProps}/>}</>},
     {key:'residue',label:'残影处理',visible:layer==='text',children:<div className="residue-workspace">
      <div className="text-review-container" hidden={!belowCanvasVisible||!belowCanvas||!textReviewOpened}>{typeof belowCanvas==='function'?belowCanvas(command,textReviewRequest,id=>void reviewText('confirm',id)):belowCanvas}</div>
      <div className="residue-current-object" hidden={!previewPending&&!previewError&&!residueDisplay}>
      {previewPending&&<div role="status">正在检查残影…</div>}
      {previewError&&<Button disabled={busy||previewPending} onClick={()=>void work(openResidueReview)}>重新检查残影</Button>}
      {residueDisplay&&preview&&<><div className="residue-display-controls"><Checkbox checked={residueShown.faces} onChange={e=>setResidueShown(old=>({...old,faces:e.target.checked}))}><i className="residue-swatch residue-face"/>疑似碎面 {residueDisplay.face_feature_ids.length}</Checkbox><Checkbox checked={residueShown.lines} onChange={e=>setResidueShown(old=>({...old,lines:e.target.checked}))}><i className="residue-swatch residue-line"/>疑似线段 {residueDisplay.line_feature_ids.length}</Checkbox><Checkbox checked={residueShown.protected} onChange={e=>setResidueShown(old=>({...old,protected:e.target.checked}))}><i className="residue-swatch residue-protected"/>待核对线 {residueDisplay.protected_line_feature_ids.length}</Checkbox><Checkbox checked={residueShown.context} onChange={e=>setResidueShown(old=>({...old,context:e.target.checked}))}>其他面线</Checkbox><Button onClick={clearObjectPreview}>退出预览</Button></div>
       <ResiduePlan preview={preview} busy={busy||cleanupPending} onLocate={()=>locateRegion(residueDisplay.bounds_px)}/>
       <ResidueLineReview preview={preview} projectId={project.project_id} assetId={asset.asset_id} busy={busy||cleanupPending} checked={riskLines} verified={verifiedResidueLines} onChecked={ids=>{setRiskLines(ids);setResidueFocusLines(ids);}} onVerified={setVerifiedResidueLines} onLocate={(bounds,ids)=>{setResidueFocusLines(ids);locateRegion(bounds);}} onBrush={()=>setTool('residue_lines')} onCleanup={()=>void cleanupResidue()} guard={guardResiduePreview} onDecided={refreshResiduePreview}/></>}

      </div>
     </div>},
    {key:'selection',label:'选择与编组',visible:hasSelection&&layer!=='text',children:<div className="property-actions">
     {layer==='face'&&<><PropertyField label="碎面面积上限（px²）"><InputNumber aria-label="碎面面积上限" min={.1} value={maxArea} onChange={value=>setMaxArea(Number(value??12))}/></PropertyField><Button block disabled={busy} onClick={()=>void work(async()=>{if(!await autosave.flush())return;setSelected(features.filter(item=>item.feature_type==='face'&&item.area_px2<=maxArea).map(item=>item.feature_id));setPreview(null);},{quiet:true})}>按面积选择</Button></>}
     <div className="property-button-grid">
      {layer==='face'&&<Button className="property-full-width property-button-wide" disabled={busy} onClick={()=>void work(()=>select({selection_type:'same_color',feature_type:'face'}),{quiet:true})}>选择相邻同色面</Button>}
      <Button disabled={busy} onClick={()=>void work(()=>select({selection_type:'group'}),{quiet:true})}>选择整组</Button>
      {layer==='face'&&<><Button disabled={busy} onClick={()=>void work(()=>select({selection_type:'grow',feature_type:'face'}),{quiet:true})}>扩大选区</Button><Button disabled={busy} onClick={()=>void work(()=>select({selection_type:'shrink',feature_type:'face'}),{quiet:true})}>缩小选区</Button></>}
      <Button disabled={busy} onClick={()=>void submit({operation_type:'group_features',feature_ids:selected,group_name:'逻辑组'})} title="建立逻辑编组，保留各对象几何">创建编组</Button>
      <Button disabled={busy} onClick={()=>void submit({operation_type:'ungroup_features',feature_ids:selected})}>解除编组</Button>
     </div>
    </div>},
    {key:'face_merge',label:'面合并',visible:layer==='face',children:<FaceMergeTools project={project} asset={asset} selected={selected} active={layer==='face'&&editableLayerVisible&&!unsavedRecognition} busy={busy} features={featuresById} work={work} command={command} flush={async()=>{if(drafts.invalidFields.length||selected.length>1&&drafts.dirty){info('请先应用或修正批量属性草稿，再操作面合并。');return false;}return autosave.flush();}} allowMixed={allowMixed} onAllowMixed={setAllowMixed} onApplied={clearObjectPreview} preview={(kind,ids)=>makePreview(kind,{feature_ids:ids},{reveal:false})} onLocate={locateRegion} info={info} onAdopt={async ids=>{const context=objectContext();if(!await autosave.flush()||!sameObject(context))return;clearObjectPreview();setSelected(ids);setTool('pick');}}/>},
    {key:'face_repair',label:'面修复',visible:layer==='face',children:<div className="geometry-workspace">{preview?.preview_type==='heal_faces'&&geometryPreview}
     <div className="face-review-container"><FaceRepairTools project={project} asset={asset} feature={layer==='face'&&selected.length===1?current:undefined} active={layer==='face'&&editableLayerVisible&&!unsavedRecognition&&drafts.invalidFields.length===0&&autosave.status!=='error'} busy={busy||!editableLayerVisible||unsavedRecognition} command={command} work={work} info={info} flush={autosave.flush} onPreview={setFaceRepair} onLocate={locateRegion}/></div>
    </div>},
    {key:'line_edit',label:'线编辑',visible:layer==='line'||layer==='isolated_line',children:<div className="geometry-workspace">{preview&&['join_lines','line_to_face','split_faces'].includes(preview.preview_type)&&geometryPreview}<div className="property-actions">
     {hasSelection&&layer==='line'&&<>
      <PropertyField label="最大连接间距（px）"><InputNumber aria-label="接线最大间距" min={0} value={gap} onChange={value=>setGap(Number(value??30))}/></PropertyField>
      <div className="property-operation-group"><Button block disabled={selected.length<2||busy} onClick={()=>void work(()=>makePreview('join_lines'))}>预览接线</Button>
      <Button block disabled={selected.length<2||busy} onClick={()=>void submit({operation_type:'join_lines',preview_id:preview?.preview_id,feature_ids:selected,max_gap_px:gap})}>连接所选</Button></div>
      <div className="property-operation-group"><Button block disabled={busy} onClick={()=>void submit({operation_type:'isolate_lines',feature_ids:selected,isolation_reason:'manual'})}>移入隔离层</Button>
      <Button block disabled={busy} onClick={()=>void work(()=>makePreview('line_to_face',{stroke_width_px:width,fill_color:color}))}>按线宽生成面</Button>
      <Button block disabled={selected.length!==1||busy} onClick={()=>void work(()=>makePreview('split_faces'))}>沿线分割面</Button></div>
     </>}
     {hasSelection&&layer==='isolated_line'&&<Button block disabled={busy} onClick={()=>void submit({operation_type:'restore_lines',feature_ids:selected})}>恢复隔离线</Button>}
    </div></div>},
    {key:'line_check',label:'线检查',visible:layer==='line',children:<div className="line-review-container"><LineCheckTools project={project} asset={asset} active={layer==='line'&&editableLayerVisible&&!unsavedRecognition} busy={busy} command={command} flush={autosave.flush} onPreview={setLineCheck} onLocate={locateRegion} onSelect={ids=>{clearObjectPreview();setSelected(ids);setTool('pick');}}/></div>},
    {key:'source',label:'对象来源',visible:hasSelection,children:(active:boolean)=><div className="object-property-source"><pre>{active&&current?JSON.stringify({...current,geometry:{type:current.geometry.type,bounds_px:[current.bbox_min_x_px,current.bbox_min_y_px,current.bbox_max_x_px,current.bbox_max_y_px]}},null,2):null}</pre><Button disabled={!current||busy} onClick={()=>void work(async()=>{if(!await autosave.flush())return;info(JSON.stringify(await request<JsonObject>(prefix+'/feature-lineage?feature_id='+current!.feature_id)));})}>查询来源链</Button></div>}
   ]}/>
   {comparison&&!compact&&deleteAction&&<div className="property-delete-footer">{deleteAction}</div>}
  </div>
 </Card>;
 const undo=operations.find(item=>item.can_undo),redo=operations.find(item=>item.can_redo);
 return <WorkbenchFrame comparison={comparison} compact={compact} textLayer={layer==='text'} stage={stage} contextKey={project.project_id+':'+asset.asset_id} layerLabel={layerNames[layer as keyof typeof layerNames]} selectedCount={selected.length} footer={deleteAction}
  toolbar={<Card title="工具" className="tool-card">
   <div className="toolbar-groups">
    <div className="toolbar-group"><span className="toolbar-group-title">查看</span><div className="view-controls"><label className="view-field"><Select aria-label="底图" value={rightMode} onChange={value=>changeBackground('right',value)} options={basemaps}/></label><div className="visible-layers">{(['face','line','text',...(layer==='isolated_line'||shown.isolated_line?['isolated_line'] as const:[])] as const).map(kind=><Checkbox key={kind} checked={shown[kind]} onChange={e=>toggleLayer(kind,e.target.checked)}>{layerNames[kind]}</Checkbox>)}</div><LayerOpacity key={opacityScope} value={Math.round((layerConfig?.opacity??1)*100)} busy={busy} layerName={layerNames[layer as keyof typeof layerNames]} onPreview={previewOpacity} onCommit={saveOpacity}/><Button onClick={()=>setComparison(value=>!value)}>{comparison?'返回单画布':'双图对照'}</Button></div></div>
    <div className="toolbar-group"><span className="toolbar-group-title">选择与工具</span><div className="toolbar-controls"><Select aria-label="编辑图层" value={layer} options={Object.entries(layerNames).map(([value,label])=>({value,label}))} onChange={value=>{clearObjectPreview();setLayer(value);setTool('pick');setSelected([]);}}/><Select aria-label="画布工具" value={tool} onChange={value=>{setTool(value);if(value==='text'||value==='draw'){clearObjectPreview();setSelected([]);info(value==='text'?'输入补录文字后，点击结果画布放置。':'设置线参数后，在结果画布绘制。');}}} options={[
 {value:'pick',label:'点选'},{value:'pan',label:'平移'},
 {value:'box',label:'框选'},{value:'brush',label:'刷选'},{value:'lasso',label:'套索'},
 ...(layer==='line'?[{value:'draw',label:'补画线'},{value:'split',label:'拆线位置'}]:[]),
 ...(layer==='text'?[...(residueDisplay?[{value:'residue_lines',label:'刷选待核对线'}]:[]),{value:'text',label:'补录文字'},{value:'ocr',label:'框选局部 OCR'},{value:'residue',label:'框选文字残影'}]:[]),
 ...(layer==='face'?[{value:'heal',label:'碎面修复刷'}]:[]),
 {value:'roi',label:'框选 ROI'}
 ]}/><Select aria-label="选择方式" value={mode} onChange={setMode} options={[{value:'replace',label:'替换选择'},{value:'add',label:'增加选择'},{value:'subtract',label:'减去选择'}]}/>{layer==='face'&&['brush','lasso'].includes(tool)&&<label className="compact-tool-param"><span>命中规则</span><Select aria-label="刷选规则" style={{width:160}} value={regionRule} onChange={setRegionRule} options={[{value:'touch',label:'接触即选整面'},{value:'center',label:'内部代表点落入'},{value:'cover50',label:'覆盖至少50%'}]}/></label>}{['brush','heal','residue_lines'].includes(tool)&&<label className="compact-tool-param"><span>刷半径</span><InputNumber aria-label="刷半径" min={1} max={100} value={radius} onChange={v=>setRadius(Number(v??4))}/></label>}{layer==='face'&&['brush','lasso','heal'].includes(tool)&&<label className="compact-tool-param"><span>碎面上限</span><InputNumber aria-label="碎面面积上限" min={.1} value={maxArea} onChange={v=>setMaxArea(Number(v??12))}/></label>}</div></div>
    <div className="toolbar-group toolbar-history"><span className="toolbar-group-title">历史</span><Space wrap><Button onClick={()=>setHistoryOpen(true)}>项目操作历史</Button><Button disabled={busy||(!undo&&!drafts.dirty&&autosave.status!=='saving')} onClick={()=>void historyAction('undo')}>撤销</Button><Button disabled={busy||!redo} onClick={()=>void historyAction('redo')}>重做</Button>{compact&&<Button onClick={()=>setPropertyOpen(true)}>属性与操作</Button>}</Space></div>
   </div>
   {!editableLayerVisible&&<Alert className="toolbar-layer-status" type="warning" showIcon message={layerNames[layer as keyof typeof layerNames]+'图层已隐藏，当前仅可平移查看。'} action={<Button size="small" onClick={()=>toggleLayer(layer as keyof typeof shown,true)}>{'显示'+layerNames[layer as keyof typeof layerNames]+'图层'}</Button>}/>}
   {layer==='face'&&['brush','lasso'].includes(tool)&&<p className="review-note">按整面选择，不裁切面；碎面面积上限仍生效。内部代表点保证位于面内。</p>}
  </Card>}
  alerts={unavailableDrafts>0?<Alert type="warning" showIcon message={unavailableDrafts+' 组草稿对应的对象已不在当前结果或已切换图层，未自动恢复；原始草稿仍保留。'}/>:undefined}
  canvas={<div className="comparison">{comparison&&panel('left')}{panel('right')}</div>}
  properties={compact?<Drawer className="property-drawer" title="属性与操作" width={Math.min(420,window.innerWidth)} open={propertyOpen} onClose={()=>setPropertyOpen(false)} footer={deleteAction}>{propertyPanel}</Drawer>:propertyPanel}
  history={<Drawer title="项目操作历史" placement="bottom" height={Math.min(380,window.innerHeight*.55)} open={historyOpen} onClose={()=>setHistoryOpen(false)}><p className="review-note">记录整个项目的操作，涵盖各对象及原图资产；撤销与重做按项目顺序执行。</p><div className="project-history-list">{operations.map(item=><p key={item.operation_id}>{item.result_revision} · {operationLabel(item.operation_type)} · {operationStatusLabel(item.operation_status)}</p>)}</div></Drawer>}>
 </WorkbenchFrame>;
}




