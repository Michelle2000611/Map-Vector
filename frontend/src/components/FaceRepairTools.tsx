import {useEffect, useRef, useState} from 'react';
import type {ReactNode} from 'react';
import {Alert, Button, Checkbox, Collapse, InputNumber, Pagination, Select, Tag} from 'antd';
import {request} from '../services/client';
import {useWorkspace} from '../stores/workspace';
import {geometryPath} from './FeatureGlyph';
import {PropertyNumber} from './PropertyNumber';
import type {Asset, Command, CommandInput, Feature, Geometry, Project, Work} from '../services/models';
import './FaceRepairTools.css';

type Candidate = {
 candidate_id: string;
 kind: 'spur' | 'void' | 'occupied_hole' | 'boundary_gap';
 geometry: Geometry;
 area_px2: number;
 receiver_options: {feature_id: string; color: string; shared_edge_px: number; recommendation_score?: number; color_distance?: number; recommendation_reason_codes?: string[]}[];
 blocked_reason?: string;
 occupying_feature_ids?: string[];
 protected_feature_ids?: string[];
 mergeable?: boolean;
 merging_feature_ids?: string[];
 review_required?: boolean;
 review_reason_codes?: string[];
 reference_line_ids?: string[];
 reference_text_ids?: string[];
 risk_level?: 'blocked' | 'review' | 'ready';
 raster_evidence?: {status: string; sample_count?: number; reason_codes?: string[]; bounds_px?: number[]; sha256?: string; median_rgb?: number[]};
 owner_raster_evidence?: {feature_id:string;status:string}[];
 evidence?: {reason_codes?: string[]; geometry_method?: string; semantic_ownership_inferred?: boolean};
 recommended_receiver_id?: string | null;
 delta_geometry?: {removed?: Geometry | null; added?: Geometry | null; transferred?: Geometry | null};
 metrics?: Record<string, number>;
};
type Plan = {
 preview_id: string;
 base_revision: number;
 feature_id: string;
 expires_at: string;
 candidates: Candidate[];
 summary: {spur_count: number; void_count: number; occupied_hole_count: number; boundary_gap_count?: number};
};
type HistoryItem = Omit<Candidate, 'geometry'> & {
 geometry?: Geometry | null;
 operation_id: string;
 result_revision: number;
 created_at: string;
 operation_status: string;
 source_feature_id?: string;
};
type Row = {key: string; candidate: Candidate | HistoryItem; history?: HistoryItem};
type Kind = Candidate['kind'];
export type FaceRepairDisplay = {plan: Plan; checked: string[]; assignments: Record<string, string>; highlighted?: string};
type BrushProps = {brushing: boolean; radius: number; maxArea: number; onRadiusChange: (value: number) => void; onMaxAreaChange: (value: number) => void; onStartBrush: () => void; onStopBrush: () => void; preview?: ReactNode};
type Props = {project: Project; asset: Asset; feature?: Feature; active?: boolean; busy: boolean; command: Command; work: Work; info: (message: string) => void; flush: () => Promise<boolean>; onPreview: (display: FaceRepairDisplay | null) => void; onLocate: (bounds: number[], geometry?: Geometry) => void; brush: BrushProps};

const evidenceLabels: Record<string, string> = {
 VECTOR_APPENDAGE_SEMANTICS_UNCONFIRMED: '几何候选不能确定地质归属',
 STROKE_LIKE_GEOMETRY: '形状窄长，可能为线状附着', MISSING_INDEPENDENT_REFERENCE: '缺少独立线或文字依据',
 INTERSECTS_INDEPENDENT_LINE: '与独立线相交，需保留线表达', INTERSECTS_TEXT_DISPLAY: '与文字范围相交，需保留文字',
 BOUNDARY_GAP: '开口缺口的地质归属需核对', RASTER_DISTINCT_HOLE_REGION: '孔洞存在独立色块，需核对是否为真实地质区域',
 RASTER_DISTINCT_HOLE_OWNER: '内部碎面包含独立色块，需核对归属',
 RASTER_DARK_STROKE: '原图存在深色笔画', RASTER_MATCHES_RECEIVER_COLOR: '原图颜色接近建议接收面',
 RASTER_COLOR_CONTRADICTS_SOURCE: '原图显示独立色块', RASTER_EVIDENCE_AMBIGUOUS: '原图依据不足以确定归属',
 RASTER_EVIDENCE_UNAVAILABLE: '原图依据暂不可用', RASTER_EVIDENCE_WINDOW_LIMIT: '候选范围较大，未采集原图依据',
 RASTER_INSUFFICIENT_SAMPLES: '原图有效像素不足', SHARED_BOUNDARY: '与候选区域共边', RASTER_COLOR_DISTANCE: '原图颜色相近',
};
const rasterLabels: Record<string, string> = {stroke_supported: '原图存在笔画依据', receiver_color_supported: '原图颜色支持接收面建议', distinct_region: '原图显示独立色块', distinct_hole_region: '原图孔洞存在独立色块', ambiguous: '原图依据不明确', unavailable: '原图依据暂不可用'};
const pageSize = 25;

function boundsOf(geometry: Geometry | null | undefined) {
 const points: number[][] = [];
 const visit = (value: unknown) => {
  if (!Array.isArray(value)) return;
  if (value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number') points.push(value as number[]);
  else value.forEach(visit);
 };
 if (geometry) visit(geometry.coordinates);
 if (!points.length) return null;
 return [Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1])), Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))];
}
function mergeable(item: Candidate | HistoryItem) {
 const advisory = item.kind === 'occupied_hole' ? 'OCCUPIED_HOLE_REQUIRES_MERGE' : 'BOUNDARY_GAP_REQUIRES_REVIEW';
 return (item.kind === 'occupied_hole' || item.kind === 'boundary_gap') && item.mergeable === true &&
  item.blocked_reason === advisory && Array.isArray(item.merging_feature_ids) && item.merging_feature_ids.length > 0 &&
  item.merging_feature_ids.every(id => typeof id === 'string' && id.length > 0);
}
function hardBlocked(item: Candidate | HistoryItem) {
 if (item.risk_level === 'blocked') return true;
 if (item.kind === 'occupied_hole' || item.kind === 'boundary_gap') return !mergeable(item);
 if (item.kind === 'spur' && !item.receiver_options?.length) return true;
 return !!item.blocked_reason && !(item.kind === 'spur' && item.blocked_reason === 'PROTECTED_LINE_OR_TEXT');
}
function needsReview(item: Candidate | HistoryItem) {
 // Older previews incorrectly called the occupied-hole merge instruction a
 // review risk, even with review_required=false and no review reasons.
 const ownershipOnly = item.kind === 'occupied_hole' && mergeable(item) &&
  item.review_required === false && !(item.review_reason_codes?.length) &&
  (item.merging_feature_ids?.length === 1 || item.owner_raster_evidence?.length === item.merging_feature_ids?.length);
 const distinctRegion = (item.kind === 'void' || item.kind === 'occupied_hole') &&
  ['distinct_region','distinct_hole_region'].includes(item.raster_evidence?.status ?? '');
 return distinctRegion || item.risk_level === 'review' && !ownershipOnly || item.review_required === true || item.kind === 'boundary_gap' ||
  (item.kind === 'spur' && item.blocked_reason === 'PROTECTED_LINE_OR_TEXT');
}
function kindLabel(item: Candidate | HistoryItem) {
 return item.kind === 'spur' ? '线状附着' : item.kind === 'boundary_gap' ? '边界缺口' : '孔洞';
}
function involvedIds(item: Candidate | HistoryItem, source: string | undefined, receiver?: string) {
 return [source, ...(item.merging_feature_ids ?? item.occupying_feature_ids ?? []), receiver].filter((id): id is string => !!id);
}
const kinds: {kind: Kind; label: string}[] = [{kind: 'spur', label: '线状附着'}, {kind: 'void', label: '孔洞'}, {kind: 'occupied_hole', label: '内部碎面'}, {kind: 'boundary_gap', label: '边界缺口'}];
const allKindsShown: Record<Kind, boolean> = {spur: true, void: true, occupied_hole: true, boundary_gap: true};
// Spurs always need a human-chosen receiver: geometry alone cannot decide which geological face owns the area.
function automatic(item: Candidate | HistoryItem) {
 return !hardBlocked(item) && !needsReview(item) && item.kind !== 'spur';
}
function reasonTexts(item: Candidate | HistoryItem) {
 const raster = item.raster_evidence ? rasterLabels[item.raster_evidence.status] ?? '原图依据需核对' : undefined;
 const codes = [...(item.evidence?.reason_codes ?? []), ...(item.review_reason_codes ?? []), ...(item.raster_evidence?.reason_codes ?? [])];
 return [...new Set([raster, ...codes.map(code => evidenceLabels[code])].filter((text): text is string => !!text))];
}

export function FaceRepairTools({project, asset, feature, active = true, busy, command, work, info, flush, onPreview, onLocate, brush}: Props) {
 const [width, setWidth] = useState<number | null>(2), [maxArea, setMaxArea] = useState<number | null>(150);
 const [widthDraft, setWidthDraft] = useState('2'), [areaDraft, setAreaDraft] = useState('150');
 const [parametersOpen, setParametersOpen] = useState(false), [plan, setPlan] = useState<Plan | null>(null);
 const [verified, setVerified] = useState<string[]>([]);
 const [checked, setChecked] = useState<string[]>([]);
 const [assignments, setAssignments] = useState<Record<string, string>>({});
 const [shown, setShown] = useState(allKindsShown), [detailsOpen, setDetailsOpen] = useState(false);
 const [page, setPage] = useState(1), [highlighted, setHighlighted] = useState('');
 const [pending, setPending] = useState(false), [error, setError] = useState('');
 const [errorAction, setErrorAction] = useState<'diagnose' | 'apply'>('diagnose');
 const [history, setHistory] = useState<HistoryItem[]>([]), [historyError, setHistoryError] = useState('');
 const [historyLoading, setHistoryLoading] = useState(false), [historyRetry, setHistoryRetry] = useState(0);
 const [checkStatus, setCheckStatus] = useState<'idle' | 'checking' | 'checked' | 'error'>('idle');
 const [checkAttempted, setCheckAttempted] = useState(false);
 const session = useWorkspace(state => state.session);
 const inputScope = JSON.stringify([project.project_id, asset.asset_id, feature?.feature_id, session]);
 const scope = JSON.stringify([inputScope, project.working_revision]);
 const scopeRef = useRef(scope), ticket = useRef(0), historyTicket = useRef(0), inFlight = useRef(false);
 scopeRef.current = scope;
 const singleFace = feature?.feature_type === 'face';
 const completeNumber = (value: string) => /^\+?(?:\d+|\d*\.\d+)$/.test(value.trim());
 const validParameters = width !== null && Number.isFinite(width) && width >= 1 && width <= 4 && completeNumber(widthDraft) &&
  maxArea !== null && Number.isFinite(maxArea) && maxArea >= 1 && maxArea <= 2000 && completeNumber(areaDraft);
 const inspectionScope = JSON.stringify([inputScope, active, width, maxArea, widthDraft, areaDraft, validParameters]);
 const inspectionRef = useRef(inspectionScope), attempted = useRef(''), previewAbort = useRef<AbortController | null>(null);
 inspectionRef.current = inspectionScope;
 const checking = checkStatus === 'checking';
 useEffect(() => {setCheckAttempted(false);}, [project.project_id, asset.asset_id, feature?.feature_id, session]);

 // Manual-only by design: this panel's check runs a real geometry diagnosis
 // (face-repair-previews) and stays mounted whenever the face layer is
 // active regardless of which property tab is on screen. Auto-firing on
 // selection change made every face click anywhere trigger it in the
 // background; the user starts each diagnosis explicitly.
 useEffect(() => {
  ticket.current++;
  previewAbort.current?.abort(); attempted.current = ''; setCheckStatus('idle');
  setPlan(null); setChecked([]); setVerified([]); setAssignments({}); setHighlighted('');
  setError(''); setPage(1);
  onPreview(null);
  return () => {ticket.current++; previewAbort.current?.abort(); onPreview(null);};
 }, [inspectionScope]);

 useEffect(() => {
  setPlan(null); setChecked([]); setVerified([]); setAssignments({}); setHighlighted('');
  setError(''); setPage(1);
  // A save awaited by diagnose() may advance the revision. Keep that explicit
  // check alive; it captures the saved revision after flush and validates it
  // again when the response arrives. Existing reports still become stale.
  setCheckStatus(value => value === 'checking' ? value : 'idle');
  onPreview(null);
 }, [project.working_revision]);

 useEffect(() => {
  const start = ++historyTicket.current, context = scope;
  setHistoryError(''); setHistory([]);
  if (!singleFace || !feature) {setHistoryLoading(false); return;}
  setHistoryLoading(true);
  const query = new URLSearchParams({asset_id: asset.asset_id, feature_id: feature.feature_id});
  void request<{items?: HistoryItem[]}>('/projects/' + project.project_id + '/face-repair-history?' + query, undefined, undefined, {quiet: true}).then(result => {
   if (historyTicket.current !== start || scopeRef.current !== context) return;
   setHistory(Array.isArray(result?.items) ? result.items.filter(item => item.operation_status === 'applied' && (!item.source_feature_id || item.source_feature_id === feature.feature_id)) : []);
  }).catch(e => {
   if (historyTicket.current === start && scopeRef.current === context) setHistoryError(e instanceof Error ? e.message : String(e));
  }).finally(() => {
   if (historyTicket.current === start && scopeRef.current === context) setHistoryLoading(false);
  });
  return () => {historyTicket.current++;};
 }, [scope, historyRetry]);

 const current = plan?.candidates ?? [];
 const ready = (item: Candidate) => !hardBlocked(item) && (!needsReview(item) || verified.includes(item.candidate_id)) &&
  (item.kind !== 'spur' || item.receiver_options.some(option => option.feature_id === assignments[item.candidate_id]));
 const selectable = current.filter(item=>!hardBlocked(item));
 const selectedCandidates = selectable.filter(item=>checked.includes(item.candidate_id));
 const selectedReview = selectedCandidates.filter(item=>needsReview(item)&&!verified.includes(item.candidate_id));
 const pendingReview = selectable.filter(item=>!ready(item));
 const chosen = selectedCandidates.filter(ready);
 const allSelected = selectable.length>0&&selectable.every(item=>checked.includes(item.candidate_id));
 const retained = current.filter(hardBlocked);
 const rows: Row[] = [
  ...current.map((candidate): Row => ({key: candidate.candidate_id, candidate})),
  ...history.map((item): Row => ({key: item.operation_id + ':' + item.candidate_id, candidate: item, history: item})),
 ];
 useEffect(() => {
  setPage(currentPage => Math.min(currentPage, Math.max(1, Math.ceil(rows.length / pageSize))));
 }, [rows.length]);
 const involvedCount = new Set(chosen.flatMap(item => involvedIds(item, plan?.feature_id, assignments[item.candidate_id]))).size;
 const disabled = busy || pending || checking;

 useEffect(() => {
  if (plan) {
   const focused = rows.find(row => row.key === highlighted)?.candidate;
   const visible = current.filter(item => shown[item.kind] || item.candidate_id === focused?.candidate_id);
   onPreview({plan: {...plan, candidates: visible}, checked: chosen.map(item => item.candidate_id), assignments, highlighted: focused?.candidate_id});
  } else {
   const focused = history.find(item => item.operation_id + ':' + item.candidate_id === highlighted);
   if (focused?.geometry) onPreview({plan: {preview_id: '', base_revision: project.working_revision, feature_id: feature?.feature_id ?? '', expires_at: '', summary: {spur_count: 0, void_count: 0, occupied_hole_count: 0}, candidates: [focused as Candidate]}, checked: [], assignments: {}, highlighted: focused.candidate_id});
   else onPreview(null);
  }
 }, [plan, shown, assignments, highlighted, checked, verified, history]);

 function clearPreview() {
  ticket.current++;
  previewAbort.current?.abort(); attempted.current = inspectionRef.current; setCheckStatus('idle');
  setPlan(null); setChecked([]); setVerified([]); setAssignments({}); setHighlighted('');
  onPreview(null);
 }
 async function locate(row: Row) {
  const expected=scopeRef.current;
  if(!active||busy||!await flush()||scopeRef.current!==expected||useWorkspace.getState().project?.working_revision!==project.working_revision)return;
  setHighlighted(row.key);
  const bounds = boundsOf(row.candidate.geometry);
  if (bounds) onLocate(bounds,row.candidate.geometry??undefined);
 }
 async function verify(ids: string[]) {
  if (disabled || !active || inFlight.current || !plan || !ids.length) return;
  const context=scopeRef.current,inspectionContext=inspectionRef.current;
  const allowed=ids.filter(id=>current.some(item=>item.candidate_id===id&&!hardBlocked(item)&&needsReview(item)));
  if(!allowed.length)return;
  inFlight.current=true;setPending(true);setError('');
  try{
   if(!await flush()){if(scopeRef.current===context)setError('属性草稿未能保存，请先修正或重试保存。');return;}
   const state=useWorkspace.getState(),expires=Date.parse(plan.expires_at);
   if(scopeRef.current!==context||inspectionRef.current!==inspectionContext||state.session!==session||
    state.project?.project_id!==project.project_id||state.asset?.asset_id!==asset.asset_id||state.layer!=='face'||
    state.selected.length!==1||state.selected[0]!==plan.feature_id||state.project.working_revision!==plan.base_revision||!Number.isFinite(expires)||expires<=Date.now()){
    if(inspectionRef.current===inspectionContext){clearPreview();setError('检查结果已更新或过期，请重新检查。');setErrorAction('diagnose');}return;
   }
   setVerified(old=>[...new Set([...old,...allowed])]);info('已确认核对 '+allowed.length+' 项。');
  }catch(e){if(scopeRef.current===context)setError(e instanceof Error?e.message:String(e));}
  finally{inFlight.current=false;setPending(false);}
 }
 function cancelReview(id: string) {
  setVerified(old => old.filter(value => value !== id));
 }
 async function diagnose() {
  if (busy || inFlight.current || !active || !singleFace || !feature || !validParameters) return;
  previewAbort.current?.abort();
  const controller = new AbortController(), context = inspectionRef.current, start = ++ticket.current;
  previewAbort.current = controller; attempted.current = context;
  setCheckAttempted(true);
  setCheckStatus('checking'); setError(''); setErrorAction('diagnose');
  setPlan(null); setChecked([]); setVerified([]); setAssignments({}); setHighlighted('');
  onPreview(null);
  const identity = feature.feature_id, session = useWorkspace.getState().session;
  const currentRequest = () => {
   const state = useWorkspace.getState();
   return ticket.current === start && inspectionRef.current === context && !controller.signal.aborted &&
    state.session === session && state.project?.project_id === project.project_id && state.asset?.asset_id === asset.asset_id &&
    state.layer === 'face' && state.selected.length === 1 && state.selected[0] === identity;
  };
  try {
   if (!await flush()) {if (currentRequest()) {setError('属性草稿未能保存，请先修正或重试保存。'); setCheckStatus('error');} return;}
   if (!currentRequest()) return;
   const state = useWorkspace.getState(), revision = state.project?.working_revision;
   if (typeof revision !== 'number') return;
   const result = await request<Plan>('/projects/' + project.project_id + '/face-repair-previews', {asset_id: asset.asset_id, feature_id: identity, width_px: width, min_length_px: 12, max_area_px2: maxArea}, controller.signal, {quiet: true});
   const latest = useWorkspace.getState();
   if (!currentRequest() || latest.session !== session || latest.layer !== 'face' || latest.selected.length !== 1 || latest.selected[0] !== identity) return;
   if (result.feature_id !== identity || result.base_revision !== revision || latest.project?.working_revision !== revision) {
    setError('检查结果已失效，请重新检查。'); setCheckStatus('error'); return;
   }
   setPlan(result); setChecked(result.candidates.filter(automatic).map(item=>item.candidate_id)); setVerified([]); setAssignments({}); setHighlighted(''); setPage(1); setCheckStatus('checked');
  } catch (e) {
   if (currentRequest() && useWorkspace.getState().session === session && !(e instanceof DOMException && e.name === 'AbortError')) {
    setError(e instanceof Error ? e.message : String(e)); setCheckStatus('error');
   }
  } finally {
   if (currentRequest()) setCheckStatus(value => value === 'checking' ? 'idle' : value);
  }
 }
 async function apply() {
  if (!plan || !chosen.length || busy || inFlight.current) return;
  inFlight.current = true; setPending(true); setError(''); setErrorAction('apply');
  const context = scopeRef.current, inspectionContext = inspectionRef.current, ids = chosen.map(item => item.candidate_id), session = useWorkspace.getState().session;
  try {
   await work(async () => {
    if (!await flush()) {if (inspectionRef.current === inspectionContext) setError('属性草稿未能保存，请先修正或重试保存。'); return;}
    const state = useWorkspace.getState(), expires = Date.parse(plan.expires_at);
    if (scopeRef.current !== context || inspectionRef.current !== inspectionContext || state.session !== session ||
     state.project?.project_id !== project.project_id || state.asset?.asset_id !== asset.asset_id || state.layer !== 'face' ||
     state.selected.length !== 1 || state.selected[0] !== plan.feature_id || state.project.working_revision !== plan.base_revision ||
     !Number.isFinite(expires) || expires <= Date.now()) {
     if (inspectionRef.current === inspectionContext && state.session === session && state.project?.project_id === project.project_id && state.asset?.asset_id === asset.asset_id) {
      clearPreview(); setError('项目或预览已更新，请重新检查。'); setErrorAction('diagnose');
     }
     return;
    }
    const result = await command({
     operation_type: 'repair_face_geometry', feature_ids: [plan.feature_id], preview_id: plan.preview_id,
     candidate_ids: ids, merge_occupied_candidate_ids: chosen.filter(mergeable).map(item => item.candidate_id),
     assignments: Object.fromEntries(chosen.filter(item => item.kind === 'spur').map(item => [item.candidate_id, assignments[item.candidate_id]])),
     verified_protected_candidate_ids: chosen.filter(item => item.kind === 'spur' && item.blocked_reason === 'PROTECTED_LINE_OR_TEXT' && verified.includes(item.candidate_id)).map(item => item.candidate_id),
     verified_review_candidate_ids: chosen.filter(item => item.review_required === true || item.kind === 'boundary_gap').filter(item => verified.includes(item.candidate_id)).map(item => item.candidate_id),
    } as CommandInput);
    const latest = useWorkspace.getState();
    if (result && latest.session === session && latest.project?.project_id === project.project_id && latest.asset?.asset_id === asset.asset_id) {
     if (context === scopeRef.current) clearPreview();
     setHistoryRetry(value => value + 1);
     info('面几何已修复，可撤销。');
    }
   });
  } catch (e) {
   if (context === scopeRef.current) setError(e instanceof Error ? e.message : String(e));
  } finally {inFlight.current = false; setPending(false);}
 }

 const selectionResults = <>
  {error && <Alert type="error" showIcon message={error} action={<Button size="small" disabled={disabled || (errorAction === 'apply' && !chosen.length)} onClick={() => errorAction === 'apply' ? void apply() : void diagnose()}>重试</Button>} />}
  {plan && historyError && <Alert type="warning" showIcon message={'处理历史加载失败：' + historyError} action={<Button size="small" disabled={historyLoading} onClick={() => setHistoryRetry(value => value + 1)}>重试历史</Button>} />}
  {plan && <div className="face-repair-summary" aria-label="面修复汇总">
   <div className="face-repair-display-controls">{kinds.map(({kind, label}) => <Checkbox key={kind} checked={shown[kind]} onChange={event => setShown(old => ({...old, [kind]: event.target.checked}))}><i className={'face-repair-swatch is-' + kind}/>{label} {current.filter(item => item.kind === kind).length}</Checkbox>)}</div>
   <div className="face-repair-summary-actions">
    <Checkbox aria-label="全选候选" disabled={disabled||!selectable.length} checked={allSelected} indeterminate={!allSelected&&selectedCandidates.length>0} onChange={event=>setChecked(event.target.checked?selectable.map(item=>item.candidate_id):[])}>{allSelected?'取消全选':'全选'}</Checkbox>
    <span className="face-repair-selection-count" aria-live="polite">已选{selectedCandidates.length}项，可修复{chosen.length}项，涉及{involvedCount}个面{retained.length ? '，' + retained.length + '项已保留' : ''}{pendingReview.length ? '，' + pendingReview.length + '项待核对' : ''}</span>
    <div className="property-operation-group">
     {selectedReview.length>0&&<Button size="small" disabled={disabled} onClick={()=>void verify(selectedReview.map(item=>item.candidate_id))}>确认所选核对</Button>}
     <Button size="small" aria-expanded={detailsOpen} onClick={() => setDetailsOpen(open => !open)}>查看明细</Button>
     <Button size="small" disabled={disabled || !chosen.length} onClick={() => void apply()}>修复</Button>
    </div>
   </div>
   {detailsOpen && <div className="face-repair-table-wrap">
    <table className="face-repair-table face-repair-select-table" aria-label="面修复核对明细">
     <thead><tr><th scope="col">选择</th><th scope="col">问题类型</th><th scope="col">面积（px²）</th><th scope="col">依据</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead>
     <tbody>{rows.slice((page - 1) * pageSize, page * pageSize).map(row => {
      const item = row.candidate, acknowledged = verified.includes(item.candidate_id), blocked = !row.history&&hardBlocked(item);
      const lines = item.reference_line_ids ?? [], texts = item.reference_text_ids ?? [];
      const reasons = reasonTexts(item);
      return <tr key={row.key} data-candidate-id={item.candidate_id} data-risk-level={item.risk_level} data-operation-id={row.history?.operation_id} className={highlighted === row.key ? 'is-highlighted' : ''} onClick={() => locate(row)}>
       <td onClick={event=>event.stopPropagation()}><Checkbox aria-label={'选择候选 '+item.candidate_id} disabled={disabled||blocked||!!row.history} checked={!row.history&&checked.includes(item.candidate_id)} onChange={event=>setChecked(old=>event.target.checked?[...new Set([...old,item.candidate_id])]:old.filter(id=>id!==item.candidate_id))}/></td>
       <td><strong><i className={'face-repair-swatch is-' + item.kind}/>{kindLabel(item)}</strong>{item.kind === 'void' && <small>{row.history ? '已填充' : '未占用'}</small>}{item.kind === 'occupied_hole' && <small>{row.history ? '已合并内部碎面' : mergeable(item) ? '合并内部碎面' : '已占用'}</small>}</td>
       <td>{Number(item.area_px2.toFixed(1))}</td>
       <td className="face-repair-evidence">
        <small title={[...lines, ...texts].join('、')}>{lines.length || texts.length ? `相交线 ${lines.length} · 文字 ${texts.length}` : row.history ? '操作记录中无相交线或文字' : '未发现独立线或文字依据'}</small>
        {reasons.map(text => <small key={text}>{text}</small>)}
        {!row.history && item.kind === 'boundary_gap' && <small>开口区域归属需人工核对</small>}
       </td>
       <td>{row.history ? <span title={row.history.operation_id}><Tag color="green">已处理</Tag><small>修订 {row.history.result_revision}</small></span> : blocked ? <Tag>已保留</Tag> : ready(item as Candidate) ? <Tag color="blue">可修复</Tag> : <Tag color="gold">{item.kind === 'spur' && (acknowledged || !needsReview(item)) ? '待选接收面' : '待核对'}</Tag>}</td>
       <td onClick={event => event.stopPropagation()}><div className="face-repair-row-actions">
        <Button size="small" disabled={!item.geometry} onClick={() => locate(row)}>定位</Button>
        {!row.history && !blocked && needsReview(item) && <Button size="small" disabled={disabled} onClick={() => acknowledged ? cancelReview(item.candidate_id) : void verify([item.candidate_id])}>{acknowledged ? '取消核对' : '核对'}</Button>}
        {!row.history && !blocked && item.kind === 'spur' && <Select popupMatchSelectWidth={280} aria-label={'接收面 ' + item.candidate_id} placeholder="选择接收面" value={assignments[item.candidate_id]} disabled={disabled} onChange={value => setAssignments(old => ({...old, [item.candidate_id]: value}))} options={(item.receiver_options ?? []).map(option => ({value: option.feature_id, label: (option.feature_id === item.recommended_receiver_id ? '建议 · ' : '') + option.color + ' · ' + option.feature_id.slice(0, 8) + ' · 共边 ' + Number(option.shared_edge_px.toFixed(1)) + ' px'}))} />}
       </div></td>
      </tr>;
     })}</tbody>
    </table>
    {!rows.length && <p className="face-repair-empty">{historyLoading ? '正在加载处理历史…' : '没有待核对项或处理记录'}</p>}
    {rows.length > pageSize && <Pagination className="face-repair-pagination" size="small" current={page} pageSize={pageSize} total={rows.length} showSizeChanger={false} showTotal={total => '共 ' + total + ' 项'} onChange={setPage} />}
   </div>}
  </div>}
 </>;

 return <section className="face-repair-tools" aria-label="面几何修复">
  <Collapse ghost defaultActiveKey={['select_repair']} className="line-edit-groups face-repair-mode-groups" items={[
   {key: 'select_repair', label: '选择修复', children: <div className="face-repair-select-group"><div className="face-repair-toolbar">
    <div className="face-repair-toolbar-main">
     <div className="face-repair-toolbar-options" aria-label="面检查选项">
      <span className="face-repair-check-state" data-state={checkStatus} role="status" aria-label="面检查状态" aria-live="polite">{checking ? '正在检查…' : checkStatus === 'checked' ? '已检查' : checkStatus === 'error' ? '检查失败' : !singleFace ? '请选择单个面' : !validParameters ? '检查参数未填写完整' : '等待检查'}</span>
      {checkStatus === 'checked' && <span className="face-repair-candidate-count">{current.length} 项候选</span>}
      <div className="property-operation-group"><Button size="small" disabled={disabled || !active || !singleFace || !validParameters} onClick={() => void diagnose()}>{checkAttempted ? '重新检查' : '开始检查'}</Button>
      <Button size="small" aria-expanded={parametersOpen} onClick={() => setParametersOpen(open => !open)}>检查设置</Button></div>
     </div>
     {plan && <div className="face-repair-toolbar-actions" aria-label="面修复操作">
      <Button size="small" aria-label="清除预览" disabled={pending} onClick={clearPreview}>清除预览</Button>
     </div>}
    </div>
    {parametersOpen && <div className="face-repair-parameters">
     <label>窄枝宽度上限（px）<InputNumber disabled={busy || pending} aria-label="窄枝宽度上限" min={1} max={4} step={.5} value={width} onInput={setWidthDraft} onBlur={() => setWidthDraft(width === null ? '' : String(width))} onPressEnter={() => setWidthDraft(width === null ? '' : String(width))} onChange={value => {setWidth(value === null ? null : Number(value)); setWidthDraft(value === null ? '' : String(value));}} /></label>
     <label>候选面积上限（px²）<InputNumber disabled={busy || pending} aria-label="修复候选面积上限" min={1} max={2000} value={maxArea} onInput={setAreaDraft} onBlur={() => setAreaDraft(maxArea === null ? '' : String(maxArea))} onPressEnter={() => setAreaDraft(maxArea === null ? '' : String(maxArea))} onChange={value => {setMaxArea(value === null ? null : Number(value)); setAreaDraft(value === null ? '' : String(value));}} /></label>
    </div>}
    {!singleFace && <Alert type="info" message="请选择一个面后开始检查。" />}
   </div>{selectionResults}</div>},
   {key: 'brush_repair', label: '涂画修复', children: <div className="face-repair-brush-group">
    <Alert type="info" showIcon message="先选中一个面，再开始涂画；只有能并入该面的碎面才会被修复，其余碎面不受影响。" />
    <div className="property-operation-group">
     <Button size="small" aria-pressed={brush.brushing} disabled={disabled || !active || (!brush.brushing && !singleFace)} onClick={() => brush.brushing ? brush.onStopBrush() : brush.onStartBrush()}>{brush.brushing ? '退出涂画修复' : '开始涂画修复'}</Button>
    </div>
    {!singleFace && !brush.brushing && <Alert type="info" message="请选择单个面后开始涂画修复。" />}
    {brush.brushing && <div className="face-repair-brush-parameters" aria-label="涂画修复参数">
     <PropertyNumber disabled={busy} label="刷半径（px）" ariaLabel="碎面修复刷半径" min={1} max={100} value={brush.radius} onChange={brush.onRadiusChange} />
     <PropertyNumber disabled={busy} label="面积上限（px²）" ariaLabel="碎面修复面积上限" min={.1} value={brush.maxArea} onChange={brush.onMaxAreaChange} />
    </div>}
    {brush.preview}
   </div>},
  ]} />
 </section>;
}

export function FaceRepairOverlay({display, features}: {display: FaceRepairDisplay; features: Record<string, Feature>}) {
 const receivers = [...new Set(display.checked.map(id => display.assignments[id]).filter(Boolean))];
 return <g className="face-repair-overlay" pointerEvents="none">
  {receivers.map(id => features[id]?.feature_type === 'face' ? <path key={id} data-face-repair-receiver={id} d={geometryPath(features[id].geometry)} fill="none" stroke="#08979c" strokeWidth={3} strokeDasharray="6 3" vectorEffect="non-scaling-stroke" /> : null)}
  {display.plan.candidates.map(item => {
   const active = display.checked.includes(item.candidate_id) || display.highlighted === item.candidate_id;
   return <g key={item.candidate_id}><path data-face-repair-candidate={item.candidate_id} d={geometryPath(item.geometry)} fill={item.kind === 'spur' ? '#fa8c16' : item.kind === 'void' ? '#52c41a' : item.kind === 'boundary_gap' ? '#722ed1' : '#1677ff'} fillOpacity={item.delta_geometry ? .08 : .35} fillRule="evenodd" stroke={active ? '#d4380d' : '#595959'} strokeWidth={active ? 3 : 1} strokeDasharray={item.kind === 'occupied_hole' || item.kind === 'boundary_gap' ? '4 3' : undefined} vectorEffect="non-scaling-stroke" />
    {(['removed', 'added', 'transferred'] as const).map(kind => {const geometry = item.delta_geometry?.[kind]; return geometry ? <path key={kind} data-face-repair-delta={kind} data-face-repair-delta-candidate={item.candidate_id} d={geometryPath(geometry)} fill={kind === 'transferred' ? 'none' : kind === 'removed' ? '#f5222d' : '#52c41a'} fillOpacity={.28} fillRule="evenodd" stroke={kind === 'transferred' ? '#08979c' : kind === 'removed' ? '#cf1322' : '#389e0d'} strokeWidth={active ? 3 : 1.5} strokeDasharray={kind === 'transferred' ? '6 3' : undefined} vectorEffect="non-scaling-stroke" /> : null;})}
   </g>;
  })}
 </g>;
}
