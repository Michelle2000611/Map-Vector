import {LoadingImage,LoadingSvgImage} from './LoadingImage';
import {TextResidueOverlay} from './TextResidueOverlay';
import type {ResidueVisibility} from './TextResidueOverlay';
import {ResiduePreview} from './ResiduePreview';
import {FeatureScene,SelectedFeatureOverlay,geometryPath} from './FeatureGlyph';
import {InspectionFocusOverlay,LOCATE_PULSE_DURATION_MS} from './InspectionFocusOverlay';
import './InspectionTable.css';
import {useEffect,useMemo,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import {ObjectAppearanceProperties} from './ObjectAppearanceProperties';
import {ObjectSourcePanel} from './ObjectSourcePanel';
import {FeatureHistoryPanel} from './FeatureHistoryPanel';
import {InspectionStatus} from './InspectionStatus';
import {FaceRepairOverlay,FaceRepairTools} from './FaceRepairTools';
import {FaceCheckTools} from './FaceCheckTools';
import {FaceSplitTools,FaceSplitOverlay} from './FaceSplitTools';
import {CanvasPathOverlay} from './CanvasPathOverlay';
import type {FaceSplitDisplay} from './FaceSplitTools';
import {FaceMergeTools} from './FaceMergeTools';
import {FaceMergeOverlay} from './FaceMergeOverlay';
import type {FaceMergePreview} from '../services/faceMerges';
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
import {StyleLibraryPanel} from './StyleLibraryPanel';
import {GlobalToolPanel} from './GlobalToolPanel';
import {Button,Card,Checkbox,Collapse,Input,InputNumber,Select,Space,Tag,Modal,Drawer,Alert} from 'antd';
import {useShallow} from 'zustand/react/shallow';
import {useCanvasScroll} from './useCanvasScroll';
import {request,ApiError} from '../services/client';
import {feedback} from '../services/feedback';
import {PropertyField} from './PropertyField';
import {PropertyNumber} from './PropertyNumber';
import {operationLabel,operationStatusLabel} from '../services/operationLabels';
import {lineStyleProperties} from '../services/lineStyle';
import {buildPropertyPatch,usePropertyAutosave} from '../hooks/usePropertyAutosave';
import {useFormatBrushHover} from '../hooks/useFormatBrushHover';

import {useWorkspace} from '../stores/workspace';
import {propertyDraftScopes,usePropertyDrafts} from '../stores/propertyDrafts';
import type {DraftField} from '../stores/propertyDrafts';
import type {Project,Asset,Feature,TextFeature,Style,Layer,Operation,Preview,PreviewItem,CommandInput,Command,Work,Point,Geometry,Page,FeaturePage,JsonObject} from '../services/models';
type Props={project:Project;asset:Asset;features:Feature[];focus:{feature_id:string;ticket:number;residue?:boolean}|null;stage:number;initialTextLayer?:boolean;belowCanvas?:ReactNode|((command:Command,revealRequest?:{feature_id:string;ticket:number},onConfirmNext?:(id:string)=>void)=>ReactNode);belowCanvasVisible?:boolean;onReturnToRecognition:()=>void;busy:boolean;command:Command;work:Work;info:(message:string)=>void;refresh:()=>Promise<void>};

function geometryBounds(geometry:Geometry){const bounds=[Infinity,Infinity,-Infinity,-Infinity];const visit=(v:unknown)=>{if(!Array.isArray(v))return;if(typeof v[0]==='number'&&typeof v[1]==='number'){bounds[0]=Math.min(bounds[0],v[0]);bounds[1]=Math.min(bounds[1],v[1]);bounds[2]=Math.max(bounds[2],v[0]);bounds[3]=Math.max(bounds[3],v[1]);}else v.forEach(visit);};visit(geometry.coordinates);return bounds;}

const layerNames={face:'面',line:'线',text:'文字',isolated_line:'隔离线'};
const canvasToolNames:Record<string,string>={pan:'平移',box:'框选',brush:'刷选',lasso:'套索',draw:'补画线',split:'拆线',text:'补录文字',ocr:'局部识别',residue:'文字残影框选',format_brush:'格式刷',heal:'涂画修复',residue_lines:'刷选待核对线',roi:'框选 ROI',face_split_path:'面分割',join_path:'接续路径'};
const basemaps=[{value:'source',label:'原图'},{value:'blank',label:'白底'},{value:'render_compare',label:'识别基线'},{value:'residual_scan_current',label:'原图与当前差异'},{value:'residual_compare_current',label:'基线与当前差异'}];
const residueCanvasShown:ResidueVisibility={faces:true,lines:true,protected:true,context:false};
export function Workbench({project,asset,features,focus,stage,initialTextLayer=false,belowCanvas,belowCanvasVisible=true,onReturnToRecognition,busy,command:rawCommand,work,info,refresh}:Props){
 const [inspectionFocus,setInspectionFocus]=useState<{scope:string;owner:string;ids:string[];label:string;selectionKey:string;previewId?:string;nonce:number;geometries?:Geometry[];bounds?:number[];clipBounds?:number[]}|null>(null);
 const [faceRepair,setFaceRepair]=useState<FaceRepairDisplay|null>(null);
 const [faceSplit,setFaceSplit]=useState<FaceSplitDisplay|null>(null);
 const [mergeModesPreview,setMergeModesPreview]=useState<FaceMergePreview|null>(null);
 const [splitPath,setSplitPath]=useState<Point[]>([]),[manualJoinPath,setManualJoinPath]=useState<Point[]>([]);
 const [lineCheck,setLineCheck]=useState<LineCheckDisplay|null>(null);
 const previewTicket=useRef(0);
 const locatePulseTicket=useRef(0);
 const objectTicket=useRef(0),cleanupInFlight=useRef(false),reviewInFlight=useRef(false);
 const [cleanupPending,setCleanupPending]=useState(false);
 const [residueCheckAttempted,setResidueCheckAttempted]=useState(false),[residueChecking,setResidueChecking]=useState(false);
 const residueCheckSerial=useRef(0),residueCheckInFlight=useRef(false);
 const residueRegionOwner=useRef<{previewId:string;scope:string}|null>(null);
 const [previewError,setPreviewError]=useState(''),[previewPending,setPreviewPending]=useState(false),[historyOpen,setHistoryOpen]=useState(false);
 const [activeGlobalTool,setActiveGlobalTool]=useState<'style_library'|'line_check'|'face_check'|'text_check'|null>(null);
 function clearObjectPreview(){setInspectionFocus(null);previewTicket.current+=1;setPreview(null);setPreviewPending(false);setPreviewError('');setVerifiedResidueLines([]);setResidueFocusLines([]);if(useWorkspace.getState().layer==='text'&&tool==='residue_lines')setTool('pick');}
 const [allowMixed,setAllowMixed]=useState(false),[compact,setCompact]=useState(window.innerWidth<980),[propertyOpen,setPropertyOpen]=useState(false),[faceAssignments,setFaceAssignments]=useState<Record<string,string>>({});
 const [copiedTextAppearance,setCopiedTextAppearance]=useState<{fontSize:number;angle:number;color:string}|null>(null);
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
 const [tool,setTool]=useState('pick'),[mode,setMode]=useState('replace'),[radius,setRadius]=useState(4),[maxArea,setMaxArea]=useState(12),[operations,setOperations]=useState<Operation[]>([]),[styles,setStyles]=useState<Style[]>([]),[layers,setLayers]=useState<Layer[]>([]),[leftMode,setLeftMode]=useState('source'),[rightMode,setRightMode]=useState('source'),[threshold,setThreshold]=useState<number|undefined>(),[adoptMode,setAdoptMode]=useState('keep_current');
 const styleSaveAttempt=useRef<{key:string;createKey:string;bindKey:string;style?:Style}|null>(null);
 const [formatBrushStyleId,setFormatBrushStyleId]=useState<string|null>(null);
 useEffect(()=>{if(tool!=='format_brush'){setFormatBrushStyleId(null);return;}if(layer!=='face'&&layer!=='line')setTool('pick');},[tool,layer]);
 const pendingSplitPath=layer==='face'&&activePropertySection==='face_split'&&!activeGlobalTool&&splitPath.length>0;
 const canvasModeLabel=tool!=='pick'?canvasToolNames[tool]??'编辑':pendingSplitPath?'面分割':mode==='add'?'增加选择':mode==='subtract'?'减去选择':null;
 const [comparison,setComparison]=useState(false),[shown,setShown]=useState({face:true,line:true,text:true,isolated_line:false}),[canvasErrors,setCanvasErrors]=useState<Record<string,boolean>>({});
 useEffect(()=>{setSplitPath([]);setManualJoinPath([]);setFaceSplit(null);if(['face_split_path','join_path'].includes(tool)){setGesture([]);drawing.current=false;setTool('pick');}},[project.project_id,asset.asset_id,workspaceSession,layer,JSON.stringify(selected)]);
 useEffect(()=>{if(tool==='face_split_path'&&(layer!=='face'||activePropertySection!=='face_split'||activeGlobalTool)||tool==='join_path'&&(layer!=='line'||activeGlobalTool!=='line_check')){setGesture([]);drawing.current=false;setTool('pick');}},[tool,layer,activePropertySection,activeGlobalTool]);
 useEffect(()=>{if(tool==='heal'&&(layer!=='face'||activePropertySection!=='face_repair'||activeGlobalTool)){setGesture([]);drawing.current=false;setTool('pick');}},[tool,layer,activePropertySection,activeGlobalTool]);
 useEffect(()=>()=>{setGesture([]);drawing.current=false;setPathCursor(null);panStart.current=null;},[tool]);
 function finishGeometryPath(points:Point[]):Point[]{const distinct=points.filter((point,index)=>index===0||point[0]!==points[index-1][0]||point[1]!==points[index-1][1]);if(distinct.length<2)return [];if(tool==='face_split_path')setSplitPath(distinct);else if(tool==='join_path')setManualJoinPath(distinct);setGesture([]);setPathCursor(null);setTool('pick');drawing.current=false;return distinct;}
 useEffect(()=>{const handle=(event:KeyboardEvent)=>{
  if(event.key==='Escape'&&!event.repeat&&!event.defaultPrevented&&(tool!=='pick'||mode!=='replace'||pendingSplitPath)){
   event.preventDefault();drawing.current=false;panStart.current=null;pointerOrigin.current=null;setGesture([]);setPathCursor(null);setBrushCursor(null);
   if(tool==='face_split_path'||pendingSplitPath)setSplitPath([]);if(tool==='join_path')setManualJoinPath([]);
   setTool('pick');setMode('replace');
   if(tool==='format_brush')feedback.info('已退出取样模式',6);else if(tool==='heal')feedback.info('已退出画笔修复',6);
   return;
  }
  if(!['face_split_path','join_path'].includes(tool)||['INPUT','TEXTAREA'].includes((event.target as HTMLElement)?.tagName)||(event.target as HTMLElement)?.isContentEditable)return;
  if(event.key==='Enter'){event.preventDefault();finishGeometryPath(gesture);}else if(event.key==='Backspace'){event.preventDefault();setGesture(old=>old.slice(0,-1));}
 };window.addEventListener('keydown',handle);return()=>window.removeEventListener('keydown',handle);},[tool,mode,gesture,pendingSplitPath]);
 const [regionRule,setRegionRule]=useState<'touch'|'center'|'cover50'>('touch');
 function changeBackground(side:'left'|'right',value:string){setCanvasErrors(old=>({...old,[side]:false}));(side==='left'?setLeftMode:setRightMode)(value);}
 function toggleLayer(kind:keyof typeof shown,value:boolean){setShown(old=>({...old,[kind]:value}));if(!value){setSelected(old=>old.filter(id=>{const feature=featuresById[id];return feature&&itemLayer(feature)!==kind;}));setPreview(null);}}
 const left=useRef<HTMLDivElement>(null),right=useRef<HTMLDivElement>(null),svg=useRef<SVGSVGElement>(null),drawing=useRef(false),panStart=useRef<{x:number;y:number;left:number;top:number}|null>(null),pointerOrigin=useRef<Point|null>(null),latestPan=useRef<{left:number;top:number}>({left:0,top:0});
 const [brushCursor,setBrushCursor]=useState<Point|null>(null),[pathCursor,setPathCursor]=useState<Point|null>(null);
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
 const inspectionScope=JSON.stringify([project.project_id,asset.asset_id,workspaceSession,layer,project.working_revision]);
 const inspectionOwner=activeGlobalTool??activePropertySection;
 const explicitInspectionFocus=inspectionFocus?.scope===inspectionScope&&inspectionFocus.owner===inspectionOwner&&inspectionFocus.selectionKey===JSON.stringify([...selected].sort())&&(!inspectionFocus.previewId||inspectionFocus.previewId===preview?.preview_id)?inspectionFocus:null;
 const currentInspectionFocus=!shown[layer as keyof typeof shown]?null:explicitInspectionFocus;
 useEffect(()=>setInspectionFocus(old=>old&&(old.scope!==inspectionScope||old.owner!==inspectionOwner)?null:old),[inspectionScope,inspectionOwner]);
 useEffect(()=>{const key=JSON.stringify([...selected].sort());setInspectionFocus(old=>old&&old.selectionKey!==key?null:old);},[JSON.stringify(selected)]);
 useEffect(()=>{if(!inspectionFocus)return;const nonce=inspectionFocus.nonce;const timer=window.setTimeout(()=>setInspectionFocus(old=>old?.nonce===nonce?null:old),LOCATE_PULSE_DURATION_MS);return()=>window.clearTimeout(timer);},[inspectionFocus?.nonce]);
 function focusInspection(ids:string[],label:string,owner:string,bounds?:number[],previewId?:string,geometries?:Geometry[],clipBounds?:number[]){if(!ids.length&&!bounds&&!geometries?.length)return;const state=useWorkspace.getState();if(state.project?.project_id!==project.project_id||state.asset?.asset_id!==asset.asset_id||state.session!==workspaceSession)return;const scope=JSON.stringify([project.project_id,asset.asset_id,state.session,state.layer,state.project.working_revision]);setInspectionFocus({scope,owner,ids,label,previewId,geometries,bounds,clipBounds,nonce:++locatePulseTicket.current,selectionKey:JSON.stringify([...state.selected].sort())});if(bounds)locateRegion(bounds,false);}
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
 const residueOwnerScope=JSON.stringify([project.project_id,asset.asset_id,workspaceSession,layer,[...selected].sort()]);
 const residuePreviewCurrent=preview?.preview_type==='text_residue'&&preview.base_revision===project.working_revision&&(!preview.expires_at||Date.parse(preview.expires_at)>Date.now())&&(preview.feature_ids.length===0?residueRegionOwner.current?.previewId===preview.preview_id&&residueRegionOwner.current.scope===residueOwnerScope:preview.feature_ids.length===1&&selected.length===1&&preview.feature_ids[0]===selected[0]);
 const residueDisplay=residuePreviewCurrent?preview.text_residue_display:null;
 const sceneFeatures=useMemo(()=>residueDisplay?[]:visible,[visible,residueDisplay]);
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
 const brushHover=useFormatBrushHover({enabled:tool==='format_brush'&&editableLayerVisible&&!busy,projectId:project.project_id,assetId:asset.asset_id,layer,session:workspaceSession,revision:project.working_revision});
 const hoveredBrushFeature=brushHover.id?featuresById[brushHover.id]:undefined;
 async function reloadHistory(){const ticket=++metadataSession.current;const history=await request<Page<Operation>>(prefix+'/operations?include_results=false&asset_id='+asset.asset_id);if(ticket===metadataSession.current){setOperations(history.items);if(['set_style','bind_style','clear_style_override','set_layer','undo','redo'].includes(history.items[0]?.operation_type)){const [library,settings]=await Promise.all([request<Page<Style>>(prefix+'/styles'),request<Page<Layer>>(prefix+'/layers?asset_id='+asset.asset_id)]);if(ticket===metadataSession.current){setStyles(library.items);setLayers(settings.items);}}}}
 useEffect(()=>{let active=true;void Promise.all([request<Page<Style>>(prefix+'/styles'),request<Page<Layer>>(prefix+'/layers?asset_id='+asset.asset_id)]).then(([library,settings])=>{if(active){setStyles(library.items);setLayers(settings.items);}}).catch(error=>info(String(error)));return()=>{active=false;};},[project.project_id,asset.asset_id]);
 useEffect(()=>{const draft=draftScopes.find(scope=>draftAvailable(scope)&&(!initialTextLayer||scope.layer==='text'));if(draft){setLayer(draft.layer);setSelected(draft.featureIds);}else{setSelected([]);if(initialTextLayer)setLayer('text');}setPreview(null);setScroll({left:0,top:0});},[project.project_id,asset.asset_id]);
 useEffect(()=>{setPreview(null);void reloadHistory().catch(error=>info(String(error)));},[project.project_id,asset.asset_id,project.working_revision]);
 useCanvasScroll(left,right,comparison,zoom,asset.asset_id);
 useEffect(()=>{if(!focus)return;setPreview(null);setPreviewError('');const f=featuresById[focus.feature_id];if(!f||f.feature_type!=='text')return;setLayer('text');setShown(old=>({...old,text:true}));setSelected([focus.feature_id]);focusInspection([focus.feature_id],'文字 '+f.text_value,inspectionOwner);setTool('pick');const panel=right.current;if(panel&&f.geometry.type==='Point'){const bbox=f.display_bbox_px;const next=Math.min(12,Math.max(zoom,Math.min(panel.clientWidth/Math.max(160,bbox?bbox[2]-bbox[0]+80:200),panel.clientHeight/Math.max(120,bbox?bbox[3]-bbox[1]+60:160))));const x=bbox?(bbox[0]+bbox[2])/2:f.geometry.coordinates[0],y=bbox?(bbox[1]+bbox[3])/2:f.geometry.coordinates[1];setZoom(next);setScroll({left:Math.max(0,x*next-panel.clientWidth/2),top:Math.max(0,y*next-panel.clientHeight/2)});}if(!focus.residue)previewTicket.current+=1;setPreviewPending(false);if(focus.residue)void work(()=>makePreview('text_residue',{feature_ids:[f.feature_id]}));},[focus]);
 const submit=(body:CommandInput)=>work(async()=>{const result=await propertyCommand(body);if(result)clearObjectPreview();return result;});
 async function select(body:Record<string,unknown>){if(!await autosave.flush())return;const result=await request<{feature_ids:string[]}>(prefix+'/selections',{asset_id:asset.asset_id,feature_type:layer==='isolated_line'?'line':layer,lifecycle_status:layer==='isolated_line'?'isolated':'active',feature_ids:mode==='replace'&&['pick','box','gesture','text_pick'].includes(String(body.selection_type))?[]:useWorkspace.getState().selected,selection_mode:mode,...body});if(useWorkspace.getState().project?.project_id===project.project_id)setSelected(result.feature_ids);setPreview(null);}
 async function selectByStyle(styleId:string){return work(async()=>{
  if(!await autosave.flush())return;
  const style=styles.find(item=>item.style_id===styleId);if(!style)return;
  const result=await request<{feature_ids:string[]}>(prefix+'/selections',{asset_id:asset.asset_id,selection_type:'by_style',style_id:styleId,feature_type:style.feature_type,lifecycle_status:'active',selection_mode:'replace'});
  if(useWorkspace.getState().project?.project_id!==project.project_id)return;
  clearObjectPreview();setLayer(style.feature_type as 'face'|'line');setSelected(result.feature_ids);setTool('pick');
 });}
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
 async function saveStyle(styleName:string,color:string):Promise<boolean>{return (await work(async()=>{
  const context=objectContext();if(!await autosave.flush()||!sameObject(context))return false;
  const state=useWorkspace.getState(),ids=[...context.selected],sample=state.featuresById[ids[0]];
  if(!ids.length||!sample||(sample.feature_type!=='face'&&sample.feature_type!=='line'))return false;
  const existing=styles.find(item=>item.style_id===sample.style_id),override=sample.style_override??{};
  const body:CommandInput=sample.feature_type==='face'?{operation_type:'set_style',feature_type:'face',style_name:styleName,fill_color:color,stroke_color:(override.stroke_color as string|undefined)??existing?.stroke_color??undefined,stroke_width_px:(override.stroke_width_px as number|undefined)??existing?.stroke_width_px??undefined}:{operation_type:'set_style',feature_type:'line',style_name:styleName,...lineStyleProperties(sample,existing),stroke_color:color};
  const attemptKey=JSON.stringify([context.projectId,context.assetId,context.session,ids,body]);
  const attempt=styleSaveAttempt.current?.key===attemptKey?styleSaveAttempt.current:{key:attemptKey,createKey:crypto.randomUUID(),bindKey:crypto.randomUUID(),style:undefined};
  styleSaveAttempt.current=attempt;
  if(!attempt.style){
   const created=await command(body,{idempotencyKey:attempt.createKey});if(!created)return false;
   attempt.style=created.changed_styles?.find(item=>item.feature_type===sample.feature_type);
  }
  const style=attempt.style;
  if(!style)throw Error('样式已保存，但未取得新样式编号，尚未绑定对象。');
  const current=useWorkspace.getState();if(current.session!==context.session||current.project?.project_id!==context.projectId||current.asset?.asset_id!==context.assetId)return false;
  setStyles(old=>[...old.filter(item=>item.style_id!==style.style_id),style]);
  if(!sameObject(context)){info('新样式已保存，选区已变化，尚未绑定对象。');return false;}
  const bound=await command({operation_type:'bind_style',style_id:style.style_id,feature_ids:ids},{idempotencyKey:attempt.bindKey});
  if(!bound)return false;
  if(styleSaveAttempt.current===attempt)styleSaveAttempt.current=null;
  info('新样式已保存并绑定所选对象。');return true;
 }))===true;}
 async function applyStyle(styleId:string){return work(async()=>{
  if(!selected.length)return;
  const result=await submit({operation_type:'bind_style',style_id:styleId,feature_ids:selected});
  if(result){const library=await request<Page<Style>>(prefix+'/styles');setStyles(library.items);}
  return result;
 });}
 async function brushFromStyle(styleId:string){
  const context=objectContext();if(!await autosave.flush()||!sameObject(context))return;
  const style=styles.find(item=>item.style_id===styleId);if(!style||(style.feature_type!=='face'&&style.feature_type!=='line'))return;
  clearObjectPreview();setLayer(style.feature_type);setShown(old=>({...old,[style.feature_type]:true}));setSelected([]);setTool('format_brush');setFormatBrushStyleId(styleId);feedback.info('已设为格式刷，点击或框选对象应用，Esc退出');
 }
 async function sampleBrush(point:Point){
  const context=objectContext(),kind=layer as 'face'|'line';
  const hit=await request<{feature_ids:string[]}>(prefix+'/selections',{asset_id:asset.asset_id,selection_type:'pick',feature_type:kind,lifecycle_status:'active',feature_ids:[],selection_mode:'replace',x:point[0],y:point[1]},undefined,{quiet:true});
  if(!sameObject(context))return;
  const sample=featuresById[hit.feature_ids[0]];
  if(!sample||sample.feature_type==='text'){info('此处没有可取样的'+(kind==='face'?'面':'线')+'，请点击对象或在样式库中选择图例。');return;}
  if(sample.style_id&&!sample.style_override){setFormatBrushStyleId(sample.style_id);info('已取样，点击或框选对象即可应用；按 Esc 退出。');return;}
  const bound=sample.style_id?styles.find(item=>item.style_id===sample.style_id):undefined;
  const known=new Set(styles.map(item=>item.style_id)),name=(kind==='face'?'面样式 ':'线样式 ')+(styles.filter(item=>item.feature_type===kind).length+1);
  const created=await command(sample.feature_type==='face'?{operation_type:'set_style',feature_type:'face',style_name:name,fill_color:sample.fill_color,stroke_color:(sample.style_override?.stroke_color as string|undefined)??bound?.stroke_color??undefined,stroke_width_px:(sample.style_override?.stroke_width_px as number|undefined)??bound?.stroke_width_px??undefined}:{operation_type:'set_style',feature_type:'line',style_name:name,...lineStyleProperties(sample,bound)});
  if(!created)return;
  const library=await request<Page<Style>>(prefix+'/styles'),style=library.items.find(item=>!known.has(item.style_id));
  setStyles(library.items);if(!style)return;
  const rebound=await command({operation_type:'bind_style',style_id:style.style_id,feature_ids:[sample.feature_id]});
  if(!rebound)return;
  setFormatBrushStyleId(style.style_id);info('已新建图例“'+name+'”并取样，点击或框选对象即可应用；按 Esc 退出。');
 }
 async function applyBrush(start:Point,point:Point,bounds:number[]){
  const style=styles.find(item=>item.style_id===formatBrushStyleId);if(!style)return;
  const context=objectContext(),dragged=Math.abs(point[0]-start[0])*zoom>3||Math.abs(point[1]-start[1])*zoom>3;
  const hit=await request<{feature_ids:string[]}>(prefix+'/selections',{asset_id:asset.asset_id,feature_type:style.feature_type,lifecycle_status:'active',feature_ids:[],selection_mode:'replace',...(dragged?{selection_type:'box',bounds_px:bounds}:{selection_type:'pick',x:point[0],y:point[1]})},undefined,{quiet:true});
  if(!sameObject(context))return;
  const ids=hit.feature_ids.filter(id=>{const item=featuresById[id];return item&&item.feature_type!=='text'&&(item.style_id!==style.style_id||!!item.style_override);});
  if(!ids.length){if(!hit.feature_ids.length)info('此处没有'+(style.feature_type==='face'?'面':'线')+'对象。');return;}
  const result=await command({operation_type:'bind_style',style_id:style.style_id,feature_ids:ids});
  if(result){clearObjectPreview();const library=await request<Page<Style>>(prefix+'/styles');setStyles(library.items);}
 }
 async function locateSelected(){
  const context=objectContext();if(!await autosave.flush()||!sameObject(context))return;
  const state=useWorkspace.getState(),picked=state.selected.map(id=>state.featuresById[id]).filter((item):item is Feature=>!!item);
  if(!picked.length)return;
  const boxes=picked.map(item=>item.feature_type==='text'&&item.display_bbox_px?item.display_bbox_px:geometryBounds(item.geometry));
  focusInspection(picked.map(item=>item.feature_id),'所选 '+picked.length+' 个对象',inspectionOwner,[Math.min(...boxes.map(box=>box[0])),Math.min(...boxes.map(box=>box[1])),Math.max(...boxes.map(box=>box[2])),Math.max(...boxes.map(box=>box[3]))]);
 }
 function locateRegion(bounds:number[],pulse=true){if(pulse)focusInspection([],'检查范围',inspectionOwner,undefined,undefined,[{type:'Polygon',coordinates:[[[bounds[0],bounds[1]],[bounds[2],bounds[1]],[bounds[2],bounds[3]],[bounds[0],bounds[3]],[bounds[0],bounds[1]]]]}]);const panel=right.current;if(!panel)return;const [x0,y0,x1,y1]=bounds,next=Math.max(.01,Math.min(12,panel.clientWidth/Math.max(60,x1-x0+50),panel.clientHeight/Math.max(60,y1-y0+50)));setZoom(next);setScroll({left:Math.max(0,(x0+x1)*next/2+Math.max(0,(panel.clientWidth-asset.width_px*next)/2)-panel.clientWidth/2),top:Math.max(0,(y0+y1)*next/2+Math.max(0,(panel.clientHeight-asset.height_px*next)/2)-panel.clientHeight/2)});}
 useEffect(()=>{const handle=(event:Event)=>{const bounds=(event as CustomEvent<number[]>).detail;if(Array.isArray(bounds)&&bounds.length===4)locateRegion(bounds);};window.addEventListener('map-vector-locate-bounds',handle);return()=>window.removeEventListener('map-vector-locate-bounds',handle);},[]);
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
   if(result.preview_type==='text_residue'&&result.feature_ids.length===0)residueRegionOwner.current={previewId:result.preview_id,scope:JSON.stringify([project.project_id,asset.asset_id,state.session,state.layer,[...state.selected].sort()])};
   setPreview(result);setRiskLines([]);setVerifiedResidueLines([]);setResidueFocusLines([]);setRiskFaces([]);setFaceAssignments({});setPropertyOpen(true);
   if(result.text_residue_display){if(!ids.length)setPropertyReveal({key:'text_residue',ticket:++textReviewTicket.current,identity:JSON.stringify([project.project_id,asset.asset_id,state.layer,[...state.selected].sort()])});changeBackground('right','source');focusInspection(ids,'文字残影范围',activeGlobalTool==='text_check'?'text_check':ids.length?inspectionOwner:'residue',result.text_residue_display.bounds_px);}
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
  clearObjectPreview();setLayer('text');setSelected([next.feature_id]);setTool('pick');focusInspection([next.feature_id],'文字 '+next.text_value,inspectionOwner);
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
 async function openResidueReview(force=false){
  setTextReviewOpened(true);
  const context=objectContext();if(!await autosave.flush()||!sameObject(context)||propertySectionRef.current!=='text_residue')return;
  const state=useWorkspace.getState(),existing=state.preview,id=state.selected[0];
  const validPreview=existing?.preview_type==='text_residue'&&existing.base_revision===state.project?.working_revision&&(!existing.expires_at||Date.parse(existing.expires_at)>Date.now());
  if(validPreview&&existing.feature_ids.length===0&&existing.text_residue_display?.preserves_existing_text){setTextReviewRequest(undefined);return force?makePreview('text_residue',{feature_ids:[],bounds_px:existing.text_residue_display.bounds_px}):undefined;}
  if(state.selected.length!==1||state.featuresById[id]?.feature_type!=='text')return;
  setTextReviewRequest({feature_id:id,ticket:++textReviewTicket.current});
  if(!force&&validPreview&&existing.feature_ids.length===1&&existing.feature_ids[0]===id)return;
  return makePreview('text_residue',{feature_ids:[id]});
 }
 async function inspectCurrentTextResidue(){
  if(busy||previewPending||cleanupPending||residueCheckInFlight.current)return;
  const state=useWorkspace.getState();
  if(state.layer!=='text'||propertySectionRef.current!=='text_residue'||!(state.selected.length===1&&state.featuresById[state.selected[0]]?.feature_type==='text')&&!residueDisplay)return;
  const serial=++residueCheckSerial.current;residueCheckInFlight.current=true;setResidueCheckAttempted(true);setResidueChecking(true);
  try{await work(()=>openResidueReview(true));}
  finally{if(serial===residueCheckSerial.current){residueCheckInFlight.current=false;setResidueChecking(false);}}
 }
 useEffect(()=>{setResidueCheckAttempted(false);},[project.project_id,asset.asset_id,workspaceSession,layer,JSON.stringify(selected)]);
 useEffect(()=>{
  if(layer!=='text'||activePropertySection!=='text_residue'||activeGlobalTool)return;
  return()=>{residueCheckSerial.current+=1;residueCheckInFlight.current=false;setResidueChecking(false);previewTicket.current+=1;setPreviewPending(false);};
 },[project.project_id,asset.asset_id,workspaceSession,layer,activePropertySection,activeGlobalTool,JSON.stringify(selected)]);
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
   if(result&&sameObject(context)){clearObjectPreview();info('残影已清理，可撤销。');await openResidueReview();}
  });}finally{cleanupInFlight.current=false;setCleanupPending(false);}
 }
 function pixel(event:React.PointerEvent<SVGSVGElement>):Point{const bounds=event.currentTarget.getBoundingClientRect();return [(event.clientX-bounds.left)/zoom,(event.clientY-bounds.top)/zoom];}
 function down(event:React.PointerEvent<SVGSVGElement>){if(event.button!==0||!enabled||(!editableLayerVisible&&tool!=='pan'))return;brushHover.clear();if(activeGlobalTool==='style_library')setActiveGlobalTool(null);const point=pixel(event);if(tool==='face_split_path'||tool==='join_path'){setGesture(old=>{const last=old.at(-1);return last&&last[0]===point[0]&&last[1]===point[1]?old:[...old,point];});return;}pointerOrigin.current=point;if(!['pick','text','split','pan'].includes(tool))setGesture([point]);if(tool==='pan'){const panel=right.current;panStart.current={x:event.clientX,y:event.clientY,left:panel?.scrollLeft??0,top:panel?.scrollTop??0};}drawing.current=true;event.currentTarget.setPointerCapture(event.pointerId);}
 function move(event:React.PointerEvent<SVGSVGElement>){if(tool==='face_split_path'||tool==='join_path'){setPathCursor(pixel(event));return;}if(['brush','heal','residue_lines'].includes(tool))setBrushCursor(pixel(event));if(!drawing.current){if(tool==='format_brush')brushHover.move(pixel(event));return;}if(tool==='pan'&&panStart.current){const panel=right.current;if(panel){latestPan.current={left:Math.max(0,panStart.current.left-(event.clientX-panStart.current.x)),top:Math.max(0,panStart.current.top-(event.clientY-panStart.current.y))};panel.scrollLeft=latestPan.current.left;panel.scrollTop=latestPan.current.top;}return;}if(['pick','text','split'].includes(tool))return;const point=pixel(event);setGesture(old=>tool==='box'||tool==='roi'||tool==='ocr'||tool==='residue'||tool==='format_brush'?[old[0],point]:[...old,point]);}
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
   if(tool==='format_brush'){if(formatBrushStyleId)await applyBrush(start,point,bounds);else await sampleBrush(point);return;}
   if(tool==='roi'){await command({operation_type:'set_roi',bounds_px:bounds as [number,number,number,number]});info('ROI 已保存；请保存新快照后导出。');return;}
   if(tool==='ocr'){const run=await request<{run_id:string}>(prefix+'/runs',{pipeline_id:'ocr_rapid',input_region_px:bounds});info('局部 OCR 已受理。请在识别任务中查看进度、在文字审核中采用候选。');await refresh();return;}
   if(tool==='residue'){await makePreview('text_residue',{feature_ids:[],bounds_px:bounds as [number,number,number,number]});return;}
   if(tool==='heal'){if(selected.length!==1)throw Error('请先选中单个面，再开始涂画修复。');await makePreview('heal_faces',{feature_ids:selected,points,radius_px:radius,max_area_px2:maxArea});return;}
   if(tool==='box'){await select({selection_type:'box',bounds_px:bounds as [number,number,number,number]});return;}
   if(tool==='brush'||tool==='lasso'){await select({selection_type:'gesture',gesture_kind:tool==='brush'?'brush':'lasso',points,radius_px:radius,rule:layer==='face'?regionRule:'touch',max_area_px2:layer==='face'?maxArea:null});return;}
   const result=await request<{feature_ids:string[]}>(prefix+'/selections',{asset_id:asset.asset_id,selection_type:layer==='text'?'text_pick':'pick',feature_type:layer==='isolated_line'?'line':layer,lifecycle_status:layer==='isolated_line'?'isolated':'active',feature_ids:event.shiftKey||mode!=='replace'?useWorkspace.getState().selected:[],selection_mode:event.shiftKey?'add':mode,x:point[0],y:point[1]});const ids=result.feature_ids;
   if(layer==='text'&&ids.length>1&&mode==='replace'&&!event.shiftKey){Modal.info({title:'此位置有多个文字，请明确选择',content:<Space direction="vertical">{ids.map(id=><Button key={id} onClick={()=>{previewTicket.current+=1;setPreview(null);setPreviewPending(false);setPreviewError('');setSelected([id]);Modal.destroyAll();}}>{featuresById[id]?.feature_type==='text'?featuresById[id].text_value:id}</Button>)}</Space>});return;}if(useWorkspace.getState().project?.project_id!==project.project_id||useWorkspace.getState().asset?.asset_id!==asset.asset_id)return;previewTicket.current+=1;setPreviewPending(false);setPreviewError('');setSelected(ids);setPreview(null);
 },{quiet:['pick','box','brush','lasso','residue_lines','format_brush'].includes(tool)});}
 const paths=geometryPath;
 function rasterUrl(type:string){return '/api'+prefix+'/rasters/'+type+'?asset_id='+asset.asset_id+'&revision='+project.working_revision+(threshold===undefined||!type.startsWith('residual_')?'':'&threshold='+threshold);}
 function panel(side:'left'|'right'){
  const renderMode=side==='left'?leftMode:rightMode;
  return <Card title={side==='left'?'原图与基线对照':'当前结果与差异'} className={'canvas-card '+(side==='left'?'reference-card':'result-card')} extra={<Space size={8} wrap>{side==='left'?<Select aria-label="对照底图" value={leftMode} className="canvas-mode" onChange={value=>changeBackground('left',value)} options={basemaps}/>:null}<Space className="canvas-zoom-controls" size={8}>{canvasModeLabel&&<Tag color="blue" data-canvas-mode={tool==='pick'&&pendingSplitPath?'face_split_path':tool} className="canvas-mode-tag">{canvasModeLabel}模式，按 Esc 退出</Tag>}<Button disabled={zoom>=12} onClick={()=>zoomView(1.25,side==='left'?left.current:right.current)}>放大</Button><Button disabled={zoom<=.01} onClick={()=>zoomView(1/1.25,side==='left'?left.current:right.current)}>缩小</Button>{side==='right'&&currentInspectionFocus&&<Tag className="inspection-location-tag">定位：{currentInspectionFocus.label}</Tag>}{side==='right'&&<Button disabled={busy||selected.length===0} onClick={()=>void work(locateSelected,{quiet:true})}>定位</Button>}<Button onClick={resetView}>复位</Button><span aria-label="当前缩放比例" className="zoom-percentage">{Math.round(zoom*1000)/10}%</span></Space></Space>}>
   {renderMode.startsWith('residual')&&<Alert type="info" showIcon className="canvas-view-hint" message="差异图只比较面和线，不包含独立文字；不能表示完整外观。" description="核对真实提取请在右侧切换白底，分别显示面、线；独立文字另行核对。" action={side==='right'?<Button size="small" onClick={()=>{changeBackground('right','blank');setShown({face:true,line:true,text:false,isolated_line:false});}}>查看白底面线</Button>:undefined}/>}
   {canvasErrors[side]&&<Alert className="canvas-load-error" type="warning" showIcon message="该底图暂不可用，请切换原图或白底。"/>}
   {side==='right'&&unsavedRecognition&&<Alert type="info" className="canvas-view-hint" message="识别结果尚未保存，当前显示识别预览" action={<Button size="small" onClick={onReturnToRecognition}>返回步骤 2 保存</Button>}/>}
   <div className="canvas" ref={side==='left'?left:right}><div className="canvas-content">
    {side==='left'?<svg className="reference-canvas" width={asset.width_px*zoom} height={asset.height_px*zoom} viewBox={'0 0 '+asset.width_px+' '+asset.height_px}><rect width={asset.width_px} height={asset.height_px} fill="white"/>{renderMode!=='blank'&&<LoadingSvgImage key={renderMode} href={rasterUrl(renderMode)} width={asset.width_px} height={asset.height_px} onLoad={()=>setCanvasErrors(old=>({...old,[side]:false}))} onError={()=>setCanvasErrors(old=>({...old,[side]:true}))}/>}{layer==='line'&&shown.line&&lineCheck&&<LineCheckOverlay display={currentInspectionFocus?lineCheck:{...lineCheck,highlighted:''}} features={featuresById}/>} {currentInspectionFocus&&<InspectionFocusOverlay ids={currentInspectionFocus.ids} features={featuresById} label={currentInspectionFocus.label} nonce={currentInspectionFocus.nonce} geometries={currentInspectionFocus.geometries} bounds={currentInspectionFocus.bounds} clipBounds={currentInspectionFocus.clipBounds}/>}</svg>:unsavedRecognition?<LoadingImage alt="待保存的识别结果" style={{width:asset.width_px*zoom}} src={rasterUrl('render_compare')}/>:<svg ref={svg} width={asset.width_px*zoom} height={asset.height_px*zoom} viewBox={'0 0 '+asset.width_px+' '+asset.height_px} onDoubleClick={()=>{if(tool==='face_split_path'||tool==='join_path'){finishGeometryPath(gesture);return;}if(current?.feature_type==='text'){setPropertyOpen(true);window.setTimeout(()=>document.querySelector<HTMLInputElement>('input[aria-label="编辑文字"]')?.focus(),100);}}} onPointerLeave={()=>{brushHover.clear();setBrushCursor(null);setPathCursor(null);}} onPointerDown={down} onPointerMove={move} onPointerUp={up} style={{touchAction:'none',cursor:tool==='pan'?'grab':!editableLayerVisible?'default':tool==='format_brush'?'copy':['brush','heal','residue_lines'].includes(tool)?'none':'crosshair'}}><rect width={asset.width_px} height={asset.height_px} fill="white"/>{renderMode!=='blank'&&<LoadingSvgImage key={renderMode} href={rasterUrl(renderMode)} x={0} y={0} width={asset.width_px} height={asset.height_px} onLoad={()=>setCanvasErrors(old=>({...old,[side]:false}))} onError={()=>setCanvasErrors(old=>({...old,[side]:true}))}/>}<FeatureScene features={sceneFeatures} styles={styles} layers={displayedLayers} background={renderMode}/>{layer==='line'&&shown.line&&lineCheck&&<LineCheckOverlay display={currentInspectionFocus?lineCheck:{...lineCheck,highlighted:''}} features={featuresById}/>}{layer==='face'&&activePropertySection==='face_split'&&!activeGlobalTool&&faceSplit&&<FaceSplitOverlay display={faceSplit}/>} {layer==='face'&&activePropertySection==='face_repair'&&!activeGlobalTool&&faceRepair&&<FaceRepairOverlay display={faceRepair} features={featuresById}/>}{layer==='face'&&shown.face&&activePropertySection==='face_merge'&&!activeGlobalTool&&mergeModesPreview&&mergeModesPreview.asset_id===asset.asset_id&&mergeModesPreview.base_revision===project.working_revision&&<FaceMergeOverlay preview={mergeModesPreview}/>}{residueDisplay?<TextResidueOverlay display={residueDisplay} features={featuresById} shown={residueCanvasShown} focused={residueFocusLines}/>:<><g opacity={currentInspectionFocus ? .2 : 1}><SelectedFeatureOverlay features={visible} selected={currentInspectionFocus?selected.filter(id=>!currentInspectionFocus.ids.includes(id)):selected} background={renderMode}/></g>{!activeGlobalTool&&!['merge_faces','merge_suggest'].includes(preview?.preview_type??'')&&preview?.affected_feature_ids?.filter(id=>visible.some(f=>f.feature_id===id)).map((id:string)=>{const item=featuresById[id];return item&&item.feature_type!=='text'?<path opacity={currentInspectionFocus ? .15 : 1} data-preview-feature={id} key={'preview-'+id} d={paths(item.geometry)} fill="none" stroke="#fa8c16" strokeWidth={2/zoom} strokeDasharray="4 2" pointerEvents="none"/>:null;})}</>}{currentInspectionFocus&&<InspectionFocusOverlay ids={currentInspectionFocus.ids} features={featuresById} label={currentInspectionFocus.label} nonce={currentInspectionFocus.nonce} geometries={currentInspectionFocus.geometries} bounds={currentInspectionFocus.bounds} clipBounds={currentInspectionFocus.clipBounds}/>} {tool==='format_brush'&&hoveredBrushFeature&&hoveredBrushFeature.feature_type!=='text'&&<path data-format-brush-hover-feature={hoveredBrushFeature.feature_id} d={paths(hoveredBrushFeature.geometry)} fill="none" stroke="#1677ff" strokeWidth={1.5} vectorEffect="non-scaling-stroke" pointerEvents="none"/>} <CanvasPathOverlay points={tool==='face_split_path'||tool==='join_path'?gesture:layer==='face'&&activePropertySection==='face_split'&&!activeGlobalTool?splitPath:[]} cursor={tool==='face_split_path'||tool==='join_path'?pathCursor:null} zoom={zoom}/> {gesture.length>1&&!['face_split_path','join_path'].includes(tool)&&<path d={'M '+gesture.map(p=>p.join(' ')).join(' L ')} stroke={tool==='heal'?'#fa541c':'#1677ff'} strokeWidth={Math.max(1/zoom,['brush','heal','residue_lines'].includes(tool)?radius*2:1/zoom)} strokeLinecap="round" strokeLinejoin="round" opacity={.4} fill="none" pointerEvents="none"/>} {['brush','heal','residue_lines'].includes(tool)&&brushCursor&&<circle cx={brushCursor[0]} cy={brushCursor[1]} r={radius} fill={tool==='heal'?'#fa541c':'#1677ff'} fillOpacity={.15} stroke={tool==='heal'?'#fa541c':'#1677ff'} strokeWidth={1/zoom} pointerEvents="none"/>}</svg>}
   </div></div>
  </Card>;
 }
 const selectedFeatures=selected.map(id=>featuresById[id]).filter((item):item is Feature=>!!item);
 const hasSelection=selectedFeatures.length>0,creationMode=tool==='text'||tool==='draw';
 const canEditAppearance=hasSelection&&(layer!=='text'||selected.length===1)||creationMode;
 const propertyContentVisible=hasSelection||creationMode&&activePropertySection==='appearance'||!!residueDisplay&&activePropertySection==='text_residue';
 const otherDrafts=Math.max(0,drafts.count-(drafts.dirty?1:0));
 const deleteLabel='删除 '+selected.length+' 个'+(layer==='face'?'面':layer==='text'?'文字':'线')+'对象';
 const deleteAction=hasSelection?<Button danger className="property-delete-action" disabled={busy} onClick={()=>Modal.confirm({title:deleteLabel,okText:'删除',cancelText:'取消',okButtonProps:{danger:true},content:(layer==='face'?'删除后原位置将留下空缺。':'')+'本次删除记录进入历史，可通过撤销恢复。',onOk:()=>submit({operation_type:layer==='face'?'delete_faces':layer==='text'?'delete_text':'delete_lines',feature_ids:selected})})}>{deleteLabel}</Button>:null;
 const singleTextResidueSection=(selected.length===1&&!!textFeature||!!residueDisplay&&preview?.feature_ids.length===0)&&<div className="property-action-section residue-workspace">
  <InspectionStatus ariaLabel="文字残影检查状态" state={residueChecking||previewPending?'checking':residueDisplay?'done':'waiting'} attempted={residueCheckAttempted||!!residueDisplay} disabled={busy||cleanupPending||!editableLayerVisible||unsavedRecognition} onCheck={()=>void inspectCurrentTextResidue()}/>
  <div className="residue-current-object" hidden={!residueDisplay}>
   {residueDisplay&&preview&&<><ResiduePreview key={preview.preview_id} display={residueDisplay} features={featuresById} textFeatureIds={preview.feature_ids} focused={residueFocusLines}/>
    <ResiduePlan preview={preview} busy={busy||cleanupPending} onLocate={()=>focusInspection([],'文字残影范围',inspectionOwner,residueDisplay.bounds_px)}/>
    <ResidueLineReview preview={preview} projectId={project.project_id} assetId={asset.asset_id} busy={busy||cleanupPending} checked={riskLines} verified={verifiedResidueLines} onChecked={ids=>{setRiskLines(ids);setResidueFocusLines(ids);}} onVerified={setVerifiedResidueLines} onLocate={(bounds,ids)=>{setResidueFocusLines(ids);focusInspection(ids,'待核对线 · '+ids.length+' 条',inspectionOwner,bounds,preview.preview_id,undefined,residueDisplay.bounds_px);}} onCleanup={()=>void cleanupResidue()} guard={guardResiduePreview} onDecided={refreshResiduePreview}/></>}
  </div>
 </div>;
 const textActionProps={busy,selected:selected.length===1&&!!textFeature,
  onSkip:()=>void reviewText('skip'),
  onAdd:()=>{clearObjectPreview();setLayer('text');setSelected([]);setTool('text');setPropertyReveal({key:'appearance',ticket:++textReviewTicket.current,identity:JSON.stringify([project.project_id,asset.asset_id,'text',[]])});info('输入补录文字后，点击结果画布放置。');},
  hasCopiedAppearance:!!copiedTextAppearance,
  onCopyAppearance:()=>{if(textFeature)setCopiedTextAppearance({fontSize:textFeature.font_size_px,angle:textFeature.rotation_deg,color:textFeature.text_color});},
  onPasteAppearance:()=>void work(async()=>{
   if(!copiedTextAppearance||!await autosave.flush())return;
   const targets=selectedFeatures.filter((item):item is TextFeature=>item.feature_type==='text');
   if(!targets.length)return;
   let result;
   for(const target of targets)result=await rawCommand({operation_type:'update_text',feature_ids:[target.feature_id],font_size_px:copiedTextAppearance.fontSize,rotation_deg:copiedTextAppearance.angle,text_color:copiedTextAppearance.color});
   if(result)clearObjectPreview();
   return result;
  }),
  residueSection:singleTextResidueSection};
 const propertyIdentity=JSON.stringify([project.project_id,asset.asset_id,layer,[...selected].sort()]);
 const brushReasonLabels:Record<string,string>={'under a SPLIT/UNKNOWN line':'涉及分界线或待定线','under a COVER line':'位于覆盖线下','same colour as neighbour':'与相邻面同色','distinct colour':'与相邻面颜色不同','no edge neighbour':'无共边相邻面',check:'需人工核对'};
 async function locateBrushFragment(featureId:string){
  const context=objectContext(),plan=useWorkspace.getState().preview;
  if(busy||plan?.preview_type!=='heal_faces'||!await autosave.flush()||!sameObject(context))return;
  const state=useWorkspace.getState(),feature=state.featuresById[featureId];
  if(state.preview?.preview_id!==plan.preview_id||state.project?.working_revision!==plan.base_revision||plan.expires_at&&Date.parse(plan.expires_at)<=Date.now()||feature?.feature_type!=='face'||feature.lifecycle_status!=='active')return;
  focusInspection([featureId],'涂画修复碎面','face_repair',geometryBounds(feature.geometry),plan.preview_id);
 }
 const brushCandidates=preview?.preview_type==='heal_faces'?(preview.legacy_report.candidates??[]).filter(item=>item.decision==='uncertain'):[];
 const brushPreviewTable=brushCandidates.length>0&&<div className="face-repair-table-wrap"><table className="face-repair-table heal-uncertain-table" aria-label="待定碎面"><thead><tr><th scope="col">选择</th><th scope="col">碎面</th><th scope="col">原因</th><th scope="col">操作</th></tr></thead><tbody>{brushCandidates.map(item=><tr key={item.feature_id} data-heal-feature={item.feature_id}><td><Checkbox aria-label={'选择待定碎面 '+item.feature_id} disabled={busy||!item.feature_id} checked={riskFaces.includes(item.feature_id??'')} onChange={event=>setRiskFaces(old=>event.target.checked?[...old,item.feature_id??'']:old.filter(id=>id!==item.feature_id))}/></td><td title={item.feature_id}>{item.feature_id?.slice(0,8)}</td><td>{brushReasonLabels[item.reason??'']??'需人工核对'}</td><td><Button disabled={busy||!item.feature_id||!featuresById[item.feature_id]} onClick={()=>void work(()=>locateBrushFragment(item.feature_id!),{quiet:true})}>定位</Button></td></tr>)}</tbody></table></div>;
 const geometryPreview=preview&&!['text_residue','merge_faces','merge_suggest'].includes(preview.preview_type)&&<Card size="small" title="预览结果">{!residueDisplay&&<p className="review-note">预览涉及 {preview.affected_feature_ids?.length??0} 个对象。核对画布后再执行。</p>}{residueDisplay&&<ResiduePlan preview={preview} busy={busy||cleanupPending} onLocate={()=>focusInspection([],'文字残影范围',inspectionOwner,residueDisplay.bounds_px)} onCleanup={!textFeature&&residueDisplay.preserves_existing_text?()=>void cleanupResidue():undefined}/>}{!residueDisplay&&<details><summary>查看详细依据</summary><pre>{JSON.stringify(preview.legacy_report,null,2)}</pre></details>}{brushPreviewTable}{preview.preview_type==='line_to_face'&&<Button onClick={()=>Modal.confirm({title:'确认沿线宽恢复窄面',content:'影响 '+(preview.legacy_report.affected_face_feature_ids??[]).length+' 个面，并移除 '+preview.feature_ids.length+' 条源线。',onOk:()=>submit({operation_type:'line_to_face',preview_id:preview.preview_id,feature_ids:preview.feature_ids,stroke_width_px:width,fill_color:color})})}>确认线转面</Button>}{['heal_faces','split_faces'].includes(preview.preview_type)&&<Button disabled={busy} onClick={()=>void submit({operation_type:preview.preview_type as 'heal_faces'|'split_faces',preview_id:preview.preview_id,accept_uncertain_feature_ids:riskFaces,allow_mixed_algorithm_labels:allowMixed})}>确认本次编辑</Button>}</Card>;
 const propertyPanel=<Card title={<div className="property-title"><span>单对象属性与操作</span><Tag color="blue">{layerNames[layer as keyof typeof layerNames]}对象</Tag><Tag>已选 {selected.length}</Tag></div>} className="property-card">
  <div className="object-property-content" onBlur={autosave.onBlur} onCompositionStart={autosave.onCompositionStart} onCompositionEnd={autosave.onCompositionEnd}>
   {propertyContentVisible&&<>
   {otherDrafts>0&&<Alert type="warning" showIcon message={'另有 '+otherDrafts+' 组属性草稿未提交，切换后可继续编辑。'}/>}
   {!drafts.persistent&&drafts.dirty&&<Alert type="warning" showIcon message="草稿暂存在当前页面，浏览器未能持久保存。"/>}
   {hasSelection&&layer==='text'&&selected.length>1&&<p className="property-empty">选择一个文字对象以编辑或核对。</p>}
   {(leftMode.startsWith('residual')||rightMode.startsWith('residual'))&&<><small>差异图不包含文字字形。</small><InputNumber aria-label="差异阈值" placeholder="差异阈值" min={0} max={255} value={threshold} onChange={value=>setThreshold(value===null?undefined:Number(value))}/></>}
   {autosave.status!=='idle'&&(hasSelection&&selected.length===1||autosave.status==='error'||autosave.status==='saving')&&<div className={'property-save-status property-save-'+autosave.status} role="status" aria-live="polite">
    <span>{({idle:'',pending:'等待自动保存…',saving:'保存中…',saved:'已保存',invalid:'请将数值或颜色填写完整，草稿已保留。',error:'保存失败，草稿已保留。'})[autosave.status]}</span>
    {autosave.status==='error'&&<><Button size="small" onClick={()=>void autosave.retry()}>重试保存</Button>{autosave.error&&<small>{autosave.error}</small>}</>}
   </div>}
   {previewError&&activePropertySection!=='face_merge'&&<Alert className="preview-inline-error" type="error" showIcon message="操作未完成" description={previewError}/ >}
   </>}
   <PropertySectionTabs empty={!propertyContentVisible} contextKey={JSON.stringify([project.project_id,asset.asset_id,workspaceSession,layer])} onActiveChange={setActivePropertySection} revealRequest={propertyReveal?.identity===propertyIdentity?propertyReveal:undefined} items={[
    {key:'appearance',label:'外观属性',children:<>{canEditAppearance&&<ObjectAppearanceProperties key={propertyIdentity+workspaceSession} disabled={busy} layer={layer} feature={current} selectedFeatures={selectedFeatures} previewFeatures={selectedFeatures.map(item=>autosave.previewFeature?.feature_id===item.feature_id?autosave.previewFeature:item)} drafts={drafts} cropSrc={textFeature?.display_bbox_px?'/api'+prefix+'/assets/'+asset.asset_id+'/crop?bounds_px='+textFeature.display_bbox_px.map((value,index)=>value+(index<2?-6:6)).join(','):undefined} styles={styles} onSaveStyle={saveStyle} onApplyStyle={styleId=>void applyStyle(styleId)} onClearOverride={ids=>void submit({operation_type:'clear_style_override',feature_ids:ids})}/>}{selected.length>1&&layer!=='text'&&<div className="property-batch-apply"><p className="review-note">仅应用本次改动的属性。</p><Button block disabled={busy||!drafts.dirty||drafts.invalidFields.length>0} onClick={()=>void applyProperties()}>应用到 {selected.length} 个对象</Button></div>}{layer==='text'&&<TextActions {...textActionProps}/>}</>},
    {key:'text_residue',label:'残影处理',visible:layer==='text',children:singleTextResidueSection},
    {key:'selection',label:'选择与编组',visible:layer!=='text',children:layer==='face'?<Collapse ghost defaultActiveKey={['select','group']} className="line-edit-groups" items={[
      {key:'select',label:'选择',children:<div className="property-actions">
       <PropertyField label="碎面面积上限（px²）"><InputNumber aria-label="碎面面积上限" min={.1} value={maxArea} onChange={value=>setMaxArea(Number(value??12))}/></PropertyField>
       <Button block disabled={busy} onClick={()=>void work(async()=>{if(!await autosave.flush())return;setSelected(features.filter(item=>item.feature_type==='face'&&item.area_px2<=maxArea).map(item=>item.feature_id));setPreview(null);},{quiet:true})}>按面积选择</Button>
       <div className="property-button-grid">
        <Button className="property-full-width property-button-wide" disabled={busy} onClick={()=>void work(()=>select({selection_type:'same_color',feature_type:'face'}),{quiet:true})}>选择相邻同色面</Button>
        <Button disabled={busy} onClick={()=>void work(()=>select({selection_type:'group'}),{quiet:true})}>选择整组</Button>
        <Button disabled={busy} onClick={()=>void work(()=>select({selection_type:'grow',feature_type:'face'}),{quiet:true})}>扩大选区</Button>
        <Button disabled={busy} onClick={()=>void work(()=>select({selection_type:'shrink',feature_type:'face'}),{quiet:true})}>缩小选区</Button>
       </div>
      </div>},
      {key:'group',label:'编组',children:<div className="property-button-grid">
       <Button disabled={busy||selected.length<2} title={selected.length<2?'编组至少需要选中 2 个对象':'建立逻辑编组，保留各对象几何'} onClick={()=>void submit({operation_type:'group_features',feature_ids:selected,group_name:'逻辑组'})}>创建编组</Button>
       <Button disabled={busy} onClick={()=>void submit({operation_type:'ungroup_features',feature_ids:selected})}>解除编组</Button>
      </div>}
     ]}/>:<div className="property-actions">
     <div className="property-button-grid">
      <Button disabled={busy} onClick={()=>void work(()=>select({selection_type:'group'}),{quiet:true})}>选择整组</Button>
      <Button disabled={busy||selected.length<2} title={selected.length<2?'编组至少需要选中 2 个对象':'建立逻辑编组，保留各对象几何'} onClick={()=>void submit({operation_type:'group_features',feature_ids:selected,group_name:'逻辑组'})}>创建编组</Button>
      <Button disabled={busy} onClick={()=>void submit({operation_type:'ungroup_features',feature_ids:selected})}>解除编组</Button>
     </div>
    </div>},
    {key:'face_merge',label:'面合并',visible:layer==='face',children:<FaceMergeTools onPreview={setMergeModesPreview} visible={hasSelection&&activePropertySection==='face_merge'&&!activeGlobalTool} project={project} asset={asset} selected={selected} active={layer==='face'&&editableLayerVisible&&!unsavedRecognition} busy={busy} features={featuresById} work={work} command={command} flush={async()=>{if(drafts.invalidFields.length||selected.length>1&&drafts.dirty){info('请先应用或修正批量属性草稿，再操作面合并。');return false;}return autosave.flush();}} onApplied={clearObjectPreview} preview={(kind,ids)=>makePreview(kind,{feature_ids:ids},{reveal:false})} onClearFocus={()=>setInspectionFocus(old=>old?.owner==='face_merge'?null:old)} onLocate={(bounds,ids,label,geometries)=>focusInspection(ids,label,'face_merge',bounds,preview?.preview_id,geometries)} info={info} onAdopt={async ids=>{const context=objectContext();if(!await autosave.flush()||!sameObject(context))return;clearObjectPreview();setSelected(ids);setTool('pick');}}/>},
    {key:'face_repair',label:'面修复',visible:layer==='face',children:<div className="geometry-workspace">
     <div className="face-review-container"><FaceRepairTools project={project} asset={asset} feature={layer==='face'&&selected.length===1?current:undefined} active={layer==='face'&&editableLayerVisible&&!unsavedRecognition&&drafts.invalidFields.length===0&&autosave.status!=='error'} busy={busy||!editableLayerVisible||unsavedRecognition} command={command} work={work} info={info} flush={autosave.flush} onPreview={display=>{setFaceRepair(display);if(!display)setInspectionFocus(old=>old?.owner==='face_repair'?null:old);}} onLocate={(bounds,geometry)=>focusInspection([],'面修复候选','face_repair',bounds,undefined,geometry?[geometry]:undefined)} brush={{preview:preview?.preview_type==='heal_faces'?geometryPreview:null,brushing:tool==='heal',radius,maxArea,onRadiusChange:setRadius,onMaxAreaChange:setMaxArea,onStartBrush:()=>{setPreview(null);setTool('heal');info('按住鼠标在碎面上拖动涂刷，松开后将生成修复预览，确认后再执行。Esc退出。');},onStopBrush:()=>{setTool('pick');setGesture([]);}}}/></div>
    </div>},
    {key:'face_split',label:'面分割',visible:layer==='face',children:<FaceSplitTools project={project} asset={asset} selected={selectedFeatures} features={features} busy={busy} active={layer==='face'&&editableLayerVisible&&!unsavedRecognition&&activePropertySection==='face_split'&&!activeGlobalTool} work={work} command={command} flush={async()=>{if(drafts.invalidFields.length||selected.length>1&&drafts.dirty){info('请先应用或修正属性草稿。');return false;}return autosave.flush();}} path={tool==='face_split_path'?gesture:splitPath} onFinishDraw={()=>tool==='face_split_path'?finishGeometryPath(gesture):splitPath} onCancelDraw={()=>{if(tool==='face_split_path'){setGesture([]);setTool('pick');}}} onDraw={()=>{setSplitPath([]);setGesture([]);setTool('face_split_path');info('点击画布添加切分节点，点击“完成分割”执行；Esc取消，Backspace撤销上一个节点。');}} onPreview={setFaceSplit} onLocate={(geometry,label)=>focusInspection([],label,'face_split',geometryBounds(geometry),undefined,[geometry])} onApplied={()=>{setFaceSplit(null);setSplitPath([]);clearObjectPreview();info('面分割已完成，可撤销。');}}/>},
    {key:'line_edit',label:'线编辑',visible:layer==='line'||layer==='isolated_line',children:<div className="geometry-workspace">{preview&&['line_to_face'].includes(preview.preview_type)&&geometryPreview}<div className="property-actions">
     {hasSelection&&layer==='line'&&<Collapse ghost defaultActiveKey={['convert','archive']} className="line-edit-groups" items={[
      {key:'convert',label:'转面',children:<div className="property-operation-group">
       <PropertyNumber disabled={busy} label="线宽（px）" ariaLabel="生成面的线宽" min={.25} max={50} value={drafts.values.width} draftValue={drafts.inputValue('width')} onDraftChange={value=>drafts.input('width',value)} onChange={value=>drafts.set('width',value)}/>
       <Button block disabled={busy} onClick={()=>void work(()=>makePreview('line_to_face',{stroke_width_px:drafts.values.width,fill_color:color}))}>按线宽生成面</Button>
      </div>},
      {key:'archive',label:'归档',children:<Button block disabled={busy} onClick={()=>void submit({operation_type:'isolate_lines',feature_ids:selected,isolation_reason:'manual'})}>移入隔离层</Button>}
     ]}/>}
     {hasSelection&&layer==='isolated_line'&&<Button block disabled={busy} onClick={()=>void submit({operation_type:'restore_lines',feature_ids:selected})}>恢复隔离线</Button>}
    </div></div>},
    {key:'source',label:'对象来源',children:(active:boolean)=><ObjectSourcePanel projectId={project.project_id} assetId={asset.asset_id} features={selectedFeatures} active={active}/>},
    {key:'history',label:'操作历史',children:(active:boolean)=>selected.length===1?<FeatureHistoryPanel projectId={project.project_id} featureId={selected[0]} active={active}/>:null}
   ]}/>
   {comparison&&!compact&&deleteAction&&<div className="property-delete-footer">{deleteAction}</div>}
  </div>
 </Card>;
 const globalToolTitle=activeGlobalTool==='style_library'?'样式库':activeGlobalTool==='line_check'?'全局线检查':activeGlobalTool==='face_check'?'全局面检查':'全局文字检查';
 function goInspectSelected(nextLayer:'face'|'text',featureId?:string){setActiveGlobalTool(null);if(layer!==nextLayer){clearObjectPreview();setLayer(nextLayer);setTool('pick');setSelected(featureId?[featureId]:[]);}else if(featureId){clearObjectPreview();setSelected([featureId]);setTool('pick');}setPropertyOpen(true);}
 const globalToolContent=activeGlobalTool==='style_library'
  ?<StyleLibraryPanel assetId={asset.asset_id} features={features} guard={async()=>{if(drafts.invalidFields.length||selected.length>1&&drafts.dirty){info('请先应用或修正属性草稿。');return false;}const context=objectContext();return await autosave.flush()&&sameObject(context);}} onLocate={async id=>{const context=objectContext();if(!await autosave.flush()||!sameObject(context))return false;const f=featuresById[id];if(!f||f.feature_type==='text')return false;setShown(old=>({...old,[f.lifecycle_status==='isolated'?'isolated_line':f.feature_type]:true}));focusInspection([id],(f.feature_type==='face'?'面 ':'线 ')+id.slice(0,8),'style_library',geometryBounds(f.geometry));return true;}} projectId={project.project_id} styles={styles} busy={busy} command={command} onStylesChanged={setStyles} onSelectByStyle={styleId=>void selectByStyle(styleId)} onUseAsBrush={styleId=>void brushFromStyle(styleId)}/>
  :activeGlobalTool==='line_check'
  ?<div className="line-review-container"><LineCheckTools manualConnector={manualJoinPath} drawingManualConnector={tool==='join_path'} onCancelManualConnector={()=>{if(tool==='join_path'){setTool('pick');setGesture([]);}}} onDrawManualConnector={()=>{setManualJoinPath([]);setGesture([]);setTool('join_path');info('点击绘制接续路径，双击或按 Enter 完成，Esc取消。');}} project={project} asset={asset} active={layer==='line'&&editableLayerVisible&&!unsavedRecognition&&activeGlobalTool==='line_check'} busy={busy} command={command} flush={autosave.flush} onPreview={display=>{setLineCheck(display);if(!display?.highlighted)setInspectionFocus(old=>old?.owner==='line_check'?null:old);}} onLocate={(bounds,ids)=>{if(ids?.length)focusInspection(ids,'线候选 · '+ids.length+' 条线','line_check',bounds);}} onSelect={ids=>{clearObjectPreview();setSelected(ids);setTool('pick');}}/></div>
  :activeGlobalTool==='face_check'
  ?<div className="face-check-container"><FaceCheckTools project={project} asset={asset} active={editableLayerVisible&&!unsavedRecognition&&activeGlobalTool==='face_check'} busy={busy} onClearFocus={()=>setInspectionFocus(null)} onLocateFace={async featureId=>{const context=objectContext();if(!await autosave.flush()||!sameObject(context))return false;const feature=featuresById[featureId];if(feature?.feature_type!=='face')return false;focusInspection([featureId],'面 '+featureId.slice(0,8),'face_check',geometryBounds(feature.geometry));return true;}} onSelectFace={featureId=>{goInspectSelected('face',featureId);setPropertyReveal({key:'face_repair',ticket:++textReviewTicket.current,identity:JSON.stringify([project.project_id,asset.asset_id,'face',[featureId]])});}}/></div>
  :activeGlobalTool==='text_check'
  ?<div className="residue-workspace">
    <div className="text-review-container" hidden={!belowCanvasVisible||!belowCanvas||!textReviewOpened}>{typeof belowCanvas==='function'?belowCanvas(command,textReviewRequest,id=>void reviewText('confirm',id)):belowCanvas}</div>
    {!(selected.length===1&&!!textFeature)&&<div className="global-tool-scope-redirect"><p className="review-note">尚未选中单个文字对象，无法开始残影核对。</p><Button onClick={()=>goInspectSelected('text')}>切到文字图层并打开属性面板</Button></div>}
    <div className="residue-current-object" hidden={!previewPending&&!previewError&&!residueDisplay}>
    {previewPending&&<div role="status">正在检查残影…</div>}
    {previewError&&<Button disabled={busy||previewPending} onClick={()=>void work(openResidueReview)}>重新检查残影</Button>}
    {residueDisplay&&preview&&<><ResiduePreview key={preview.preview_id} display={residueDisplay} features={featuresById} textFeatureIds={preview.feature_ids} focused={residueFocusLines}/><Button onClick={clearObjectPreview}>退出预览</Button>
     <ResiduePlan preview={preview} busy={busy||cleanupPending} onLocate={()=>focusInspection([],'文字残影范围',inspectionOwner,residueDisplay.bounds_px)}/>
     <ResidueLineReview preview={preview} projectId={project.project_id} assetId={asset.asset_id} busy={busy||cleanupPending} checked={riskLines} verified={verifiedResidueLines} onChecked={ids=>{setRiskLines(ids);setResidueFocusLines(ids);}} onVerified={setVerifiedResidueLines} onLocate={(bounds,ids)=>{setResidueFocusLines(ids);focusInspection(ids,'待核对线 · '+ids.length+' 条',inspectionOwner,bounds,preview.preview_id,undefined,residueDisplay.bounds_px);}} onCleanup={()=>void cleanupResidue()} guard={guardResiduePreview} onDecided={refreshResiduePreview}/></>}
    </div>
   </div>
  :null;
 const undo=operations.find(item=>item.can_undo),redo=operations.find(item=>item.can_redo);
 return <WorkbenchFrame comparison={comparison} compact={compact} textLayer={layer==='text'} stage={stage} contextKey={project.project_id+':'+asset.asset_id} layerLabel={layerNames[layer as keyof typeof layerNames]} selectedCount={selected.length} footer={deleteAction}
  toolbar={<Card title="工具" className="tool-card">
   <div className="toolbar-groups">
    <div className="toolbar-group"><span className="toolbar-group-title">查看</span><div className="view-controls"><label className="view-field"><Select aria-label="底图" value={rightMode} onChange={value=>changeBackground('right',value)} options={basemaps}/></label><div className="visible-layers">{(['face','line','text',...(layer==='isolated_line'||shown.isolated_line?['isolated_line'] as const:[])] as const).map(kind=><Checkbox key={kind} checked={shown[kind]} onChange={e=>toggleLayer(kind,e.target.checked)}>{layerNames[kind]}</Checkbox>)}</div><LayerOpacity key={opacityScope} value={Math.round((layerConfig?.opacity??1)*100)} busy={busy} layerName={layerNames[layer as keyof typeof layerNames]} onPreview={previewOpacity} onCommit={saveOpacity}/><Button onClick={()=>setComparison(value=>!value)}>{comparison?'返回单画布':'双图对照'}</Button></div></div>
    <div className="toolbar-group"><span className="toolbar-group-title">选择与工具</span><div className="toolbar-controls"><Select aria-label="编辑图层" value={layer} options={Object.entries(layerNames).map(([value,label])=>({value,label}))} onChange={value=>{clearObjectPreview();setLayer(value);setTool('pick');setSelected([]);}}/><Select aria-label="画布工具" value={tool} labelRender={({value,label})=>({heal:'涂画修复',face_split_path:'绘制切分路径',join_path:'绘制接续路径'} as Record<string,string>)[String(value)]??label} onChange={value=>{setTool(value);if(value==='text'||value==='draw'){clearObjectPreview();setSelected([]);setPropertyReveal({key:'appearance',ticket:++textReviewTicket.current,identity:JSON.stringify([project.project_id,asset.asset_id,layer,[]])});info(value==='text'?'输入补录文字后，点击结果画布放置。':'设置线参数后，在结果画布绘制。');}}} options={[
 {value:'pick',label:'点选'},{value:'pan',label:'平移'},
 {value:'box',label:'框选'},{value:'brush',label:'刷选'},{value:'lasso',label:'套索'},
 ...(layer==='line'?[{value:'draw',label:'补画线'},{value:'split',label:'拆线位置'}]:[]),
 ...(layer==='text'?[...(residueDisplay?[{value:'residue_lines',label:'刷选待核对线'}]:[]),{value:'text',label:'补录文字'},{value:'ocr',label:'框选局部 OCR'},{value:'residue',label:'框选文字残影'}]:[]),
 ...(layer==='face'||layer==='line'?[{value:'format_brush',label:'格式刷'}]:[]),
 {value:'roi',label:'框选 ROI'}
 ]}/><Select aria-label="选择方式" value={mode} onChange={setMode} options={[{value:'replace',label:'替换选择'},{value:'add',label:'增加选择'},{value:'subtract',label:'减去选择'}]}/>{layer==='face'&&['brush','lasso'].includes(tool)&&<label className="compact-tool-param"><span>命中规则</span><Select aria-label="刷选规则" style={{width:160}} value={regionRule} onChange={setRegionRule} options={[{value:'touch',label:'接触即选整面'},{value:'center',label:'内部代表点落入'},{value:'cover50',label:'覆盖至少50%'}]}/></label>}{['brush','residue_lines'].includes(tool)&&<label className="compact-tool-param"><span>刷半径</span><InputNumber aria-label="刷半径" min={1} max={100} value={radius} onChange={v=>setRadius(Number(v??4))}/></label>}{layer==='face'&&['brush','lasso'].includes(tool)&&<label className="compact-tool-param"><span>碎面上限</span><InputNumber aria-label="碎面面积上限" min={.1} value={maxArea} onChange={v=>setMaxArea(Number(v??12))}/></label>}</div></div>
    <div className="toolbar-group toolbar-global"><span className="toolbar-group-title">全局工具</span><Space wrap><Button onClick={()=>setActiveGlobalTool('style_library')}>样式库</Button>{(layer==='face'||layer==='line')&&<Button aria-pressed={tool==='format_brush'} disabled={busy} onClick={()=>{if(tool==='format_brush'){setTool('pick');return;}clearObjectPreview();setSelected([]);setTool('format_brush');info('点击对象取样，Esc退出');}}>格式刷</Button>}{layer==='line'&&<Button onClick={()=>setActiveGlobalTool('line_check')}>线检查</Button>}{layer==='face'&&<Button onClick={()=>setActiveGlobalTool('face_check')}>面检查</Button>}{layer==='text'&&<Button onClick={()=>{setTextReviewOpened(true);setActiveGlobalTool('text_check');}}>文字检查</Button>}{layer==='text'&&residueDisplay&&<Button disabled={busy} onClick={()=>setTool('residue_lines')}>刷选待核对线</Button>}</Space></div>
    <div className="toolbar-group toolbar-history"><span className="toolbar-group-title">全局历史</span><Space wrap><Button onClick={()=>setHistoryOpen(true)}>项目操作历史</Button><Button disabled={busy||(!undo&&!drafts.dirty&&autosave.status!=='saving')} onClick={()=>void historyAction('undo')}>撤销</Button><Button disabled={busy||!redo} onClick={()=>void historyAction('redo')}>重做</Button>{compact&&<Button onClick={()=>setPropertyOpen(true)}>单对象属性与操作</Button>}</Space></div>
   </div>
   {!editableLayerVisible&&<Alert className="toolbar-layer-status" type="warning" showIcon message={layerNames[layer as keyof typeof layerNames]+'图层已隐藏，当前仅可平移查看。'} action={<Button size="small" onClick={()=>toggleLayer(layer as keyof typeof shown,true)}>{'显示'+layerNames[layer as keyof typeof layerNames]+'图层'}</Button>}/>}
   {layer==='face'&&['brush','lasso'].includes(tool)&&<p className="review-note">按整面选择，不裁切面；碎面面积上限仍生效。内部代表点保证位于面内。</p>}
  </Card>}
  alerts={unavailableDrafts>0?<Alert type="warning" showIcon message={unavailableDrafts+' 组草稿对应的对象已不在当前结果或已切换图层，未自动恢复；原始草稿仍保留。'}/>:undefined}
  canvas={<div className="comparison">{comparison&&panel('left')}{panel('right')}</div>}
  properties={propertyPanel}
  propertiesOverride={compact
   ?<>
     <Drawer className="property-drawer" title="单对象属性与操作" width={Math.min(420,window.innerWidth)} open={propertyOpen&&!activeGlobalTool} onClose={()=>setPropertyOpen(false)} footer={deleteAction}>{propertyPanel}</Drawer>
     <Drawer title={globalToolTitle} width={Math.min(420,window.innerWidth)} open={!!activeGlobalTool} onClose={()=>setActiveGlobalTool(null)}>{globalToolContent}</Drawer>
    </>
   :(activeGlobalTool?<GlobalToolPanel title={globalToolTitle} onClose={()=>setActiveGlobalTool(null)}>{globalToolContent}</GlobalToolPanel>:undefined)}
  history={<Drawer title="项目操作历史" placement="bottom" height={Math.min(380,window.innerHeight*.55)} open={historyOpen} onClose={()=>setHistoryOpen(false)}><p className="review-note">记录整个项目的操作，涵盖各对象及原图资产；撤销与重做按项目顺序执行。</p><div className="project-history-list">{operations.map(item=><p key={item.operation_id}>{item.result_revision} · {operationLabel(item.operation_type)} · {operationStatusLabel(item.operation_status)}</p>)}</div></Drawer>}>
 </WorkbenchFrame>;
}




