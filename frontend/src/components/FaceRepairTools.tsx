import {useEffect, useRef, useState} from 'react';
import {Alert, Button, Checkbox, Empty, InputNumber, Modal, Pagination, Select, Space, Tabs, Tag} from 'antd';
import {request} from '../services/client';
import {useWorkspace} from '../stores/workspace';
import {geometryPath} from './FeatureGlyph';
import type {Asset, Command, CommandInput, Feature, Geometry, Project, Work} from '../services/models';
import './FaceRepairTools.css';

type Candidate = {
 candidate_id: string;
 kind: 'spur' | 'void' | 'occupied_hole' | 'boundary_gap';
 geometry: Geometry;
 area_px2: number;
 receiver_options: {feature_id: string; color: string; shared_edge_px: number}[];
 blocked_reason?: string;
 occupying_feature_ids?: string[];
 protected_feature_ids?: string[];
 mergeable?: boolean;
 merging_feature_ids?: string[];
 review_required?: boolean;
 review_reason_codes?: string[];
 reference_line_ids?: string[];
 reference_text_ids?: string[];
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
type Filter = 'review' | 'ready' | 'processed' | 'all';
export type FaceRepairDisplay = {plan: Plan; checked: string[]; assignments: Record<string, string>; highlighted?: string};
type Props = {project: Project; asset: Asset; feature?: Feature; active?: boolean; busy: boolean; command: Command; work: Work; info: (message: string) => void; flush: () => Promise<boolean>; onPreview: (display: FaceRepairDisplay | null) => void; onLocate: (bounds: number[]) => void};

const blockedMessages: Record<string, string> = {
 PROTECTED_LINE_OR_TEXT: '与受保护线或文字相交',
 NO_VALID_EDGE_RECEIVER: '缺少可相接的接收面',
 OUTSIDE_VALID_RASTER: '超出有效原图范围',
 HOLE_EXCEEDS_AREA_LIMIT: '面积超过当前上限',
 OCCUPIED_HOLE_USE_MERGE: '孔洞占用情况未满足合并条件',
};
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
 if (item.kind === 'occupied_hole' || item.kind === 'boundary_gap') return !mergeable(item);
 if (item.kind === 'spur' && !item.receiver_options?.length) return true;
 return !!item.blocked_reason && !(item.kind === 'spur' && item.blocked_reason === 'PROTECTED_LINE_OR_TEXT');
}
function needsReview(item: Candidate | HistoryItem) {
 return item.review_required === true || item.kind === 'boundary_gap' ||
  (item.kind === 'spur' && item.blocked_reason === 'PROTECTED_LINE_OR_TEXT');
}
function kindLabel(item: Candidate | HistoryItem) {
 return item.kind === 'spur' ? '线状附着' : item.kind === 'boundary_gap' ? '边界缺口' : '孔洞';
}
function involvedIds(item: Candidate | HistoryItem, source: string | undefined, receiver?: string) {
 return [source, ...(item.merging_feature_ids ?? item.occupying_feature_ids ?? []), receiver].filter((id): id is string => !!id);
}

export function FaceRepairTools({project, asset, feature, active = true, busy, command, work, info, flush, onPreview, onLocate}: Props) {
 const [width, setWidth] = useState<number | null>(2), [maxArea, setMaxArea] = useState<number | null>(150);
 const [widthDraft, setWidthDraft] = useState('2'), [areaDraft, setAreaDraft] = useState('150');
 const [parametersOpen, setParametersOpen] = useState(false), [plan, setPlan] = useState<Plan | null>(null);
 const [checked, setChecked] = useState<string[]>([]), [verified, setVerified] = useState<string[]>([]);
 const [assignments, setAssignments] = useState<Record<string, string>>({});
 const [filter, setFilter] = useState<Filter>('all'), [page, setPage] = useState(1), [highlighted, setHighlighted] = useState('');
 const [pending, setPending] = useState(false), [error, setError] = useState('');
 const [errorAction, setErrorAction] = useState<'diagnose' | 'apply'>('diagnose');
 const [history, setHistory] = useState<HistoryItem[]>([]), [historyError, setHistoryError] = useState('');
 const [historyLoading, setHistoryLoading] = useState(false), [historyRetry, setHistoryRetry] = useState(0);
 const [reviewIds, setReviewIds] = useState<string[]>([]);
 const [checkStatus, setCheckStatus] = useState<'idle' | 'checking' | 'checked' | 'error'>('idle');
 const session = useWorkspace(state => state.session);
 const scope = JSON.stringify([project.project_id, asset.asset_id, feature?.feature_id, project.working_revision, session]);
 const scopeRef = useRef(scope), ticket = useRef(0), historyTicket = useRef(0), inFlight = useRef(false);
 scopeRef.current = scope;
 const singleFace = feature?.feature_type === 'face';
 const completeNumber = (value: string) => /^\+?(?:\d+|\d*\.\d+)$/.test(value.trim());
 const validParameters = width !== null && Number.isFinite(width) && width >= 1 && width <= 4 && completeNumber(widthDraft) &&
  maxArea !== null && Number.isFinite(maxArea) && maxArea >= 1 && maxArea <= 2000 && completeNumber(areaDraft);
 const inspectionScope = JSON.stringify([scope, active, width, maxArea, validParameters]);
 const inspectionRef = useRef(inspectionScope), attempted = useRef(''), previewAbort = useRef<AbortController | null>(null);
 const diagnoseRef = useRef<() => Promise<void>>();
 inspectionRef.current = inspectionScope;
 const checking = checkStatus === 'checking';

 useEffect(() => {
  ticket.current++;
  previewAbort.current?.abort(); attempted.current = ''; setCheckStatus('idle');
  setPlan(null); setChecked([]); setVerified([]); setAssignments({}); setHighlighted('');
  setError(''); setReviewIds([]); setPage(1);
  onPreview(null);
  return () => {ticket.current++; previewAbort.current?.abort(); onPreview(null);};
 }, [inspectionScope]);

 useEffect(() => {
  if (busy || pending || !active || !singleFace || !validParameters || attempted.current === inspectionScope) return;
  const timer = window.setTimeout(() => void diagnoseRef.current?.(), 250);
  return () => window.clearTimeout(timer);
 }, [inspectionScope, busy, pending]);

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
 const reviewed = (item: Candidate | HistoryItem) => !needsReview(item) || verified.includes(item.candidate_id);
 const eligible = (item: Candidate | HistoryItem) => !hardBlocked(item) && reviewed(item);
 const rows: Row[] = [
  ...current.map((candidate): Row => ({key: candidate.candidate_id, candidate})),
  ...history.map((item): Row => ({key: item.operation_id + ':' + item.candidate_id, candidate: item, history: item})),
 ].filter(row => filter === 'all' || (filter === 'processed' ? !!row.history : !row.history && (filter === 'ready' ? eligible(row.candidate) : !hardBlocked(row.candidate) && !reviewed(row.candidate))));
 useEffect(() => {
  setPage(currentPage => Math.min(currentPage, Math.max(1, Math.ceil(rows.length / pageSize))));
 }, [rows.length]);
 const chosen = current.filter(item => checked.includes(item.candidate_id));
 const involvedCount = new Set(chosen.flatMap(item => involvedIds(item, plan?.feature_id, assignments[item.candidate_id]))).size;
 const selectedReview = chosen.filter(item => !hardBlocked(item) && needsReview(item) && !verified.includes(item.candidate_id));
 const eligibleRows = rows.filter(row => !row.history && eligible(row.candidate));
 const allSelected = eligibleRows.length > 0 && eligibleRows.every(row => checked.includes(row.candidate.candidate_id));
 const applicable = !!plan && chosen.length > 0 && chosen.every(item => eligible(item) &&
  (item.kind !== 'spur' || item.receiver_options.some(option => option.feature_id === assignments[item.candidate_id])));
 const disabled = busy || pending || checking;

 useEffect(() => {
  if (plan) {
   const visible = rows.filter(row => !row.history).map(row => row.candidate as Candidate);
   const focused = rows.find(row => row.key === highlighted)?.candidate;
   const candidates = focused?.geometry && !visible.some(item => item.candidate_id === focused.candidate_id) ? [...visible, focused as Candidate] : visible;
   onPreview({plan: {...plan, candidates}, checked, assignments, highlighted: focused?.candidate_id});
  } else {
   const focused = history.find(item => item.operation_id + ':' + item.candidate_id === highlighted);
   if (focused?.geometry) onPreview({plan: {preview_id: '', base_revision: project.working_revision, feature_id: feature?.feature_id ?? '', expires_at: '', summary: {spur_count: 0, void_count: 0, occupied_hole_count: 0}, candidates: [focused as Candidate]}, checked: [], assignments: {}, highlighted: focused.candidate_id});
   else onPreview(null);
  }
 }, [plan, checked, assignments, highlighted, filter, verified, history]);

 function clearPreview() {
  ticket.current++;
  previewAbort.current?.abort(); attempted.current = inspectionRef.current; setCheckStatus('idle');
  setPlan(null); setChecked([]); setVerified([]); setAssignments({}); setHighlighted(''); setReviewIds([]);
  onPreview(null);
 }
 function changeFilter(next: Filter) {
  setFilter(next); setPage(1); setChecked([]); setHighlighted('');
 }
 function locate(row: Row) {
  setHighlighted(row.key);
  const bounds = boundsOf(row.candidate.geometry);
  if (bounds) onLocate(bounds);
 }
 function selectCandidate(id: string, selected: boolean) {
  setChecked(old => selected ? [...new Set([...old, id])] : old.filter(value => value !== id));
 }
 function cancelReview(id: string) {
  setVerified(old => old.filter(value => value !== id));
  setChecked(old => old.filter(value => value !== id));
 }
 async function diagnose() {
  if (busy || inFlight.current || !active || !singleFace || !feature || !validParameters) return;
  previewAbort.current?.abort();
  const controller = new AbortController(), context = inspectionRef.current, start = ++ticket.current;
  previewAbort.current = controller; attempted.current = context;
  setCheckStatus('checking'); setError(''); setErrorAction('diagnose');
  setPlan(null); setChecked([]); setVerified([]); setAssignments({}); setHighlighted(''); setReviewIds([]);
  onPreview(null);
  const identity = feature.feature_id, session = useWorkspace.getState().session;
  const currentRequest = () => ticket.current === start && inspectionRef.current === context && !controller.signal.aborted;
  try {
   if (!await flush() || !currentRequest()) return;
   const state = useWorkspace.getState(), revision = state.project?.working_revision;
   if (state.session !== session || state.project?.project_id !== project.project_id || state.asset?.asset_id !== asset.asset_id || state.layer !== 'face' || state.selected.length !== 1 || state.selected[0] !== identity || revision !== project.working_revision) return;
   const result = await request<Plan>('/projects/' + project.project_id + '/face-repair-previews', {asset_id: asset.asset_id, feature_id: identity, width_px: width, min_length_px: 12, max_area_px2: maxArea}, controller.signal, {quiet: true});
   const latest = useWorkspace.getState();
   if (!currentRequest() || latest.session !== session || latest.layer !== 'face' || latest.selected.length !== 1 || latest.selected[0] !== identity) return;
   if (result.feature_id !== identity || result.base_revision !== revision || latest.project?.working_revision !== revision) {
    setError('检查结果已失效，请重新检查。'); setCheckStatus('error'); return;
   }
   setPlan(result); setChecked([]); setVerified([]); setAssignments({}); setHighlighted(''); setPage(1); setCheckStatus('checked');
  } catch (e) {
   if (currentRequest() && useWorkspace.getState().session === session && !(e instanceof DOMException && e.name === 'AbortError')) {
    setError(e instanceof Error ? e.message : String(e)); setCheckStatus('error');
   }
  } finally {
   if (currentRequest()) setCheckStatus(value => value === 'checking' ? 'idle' : value);
  }
 }
 diagnoseRef.current = diagnose;
 async function apply() {
  if (!plan || !applicable || busy || inFlight.current) return;
  inFlight.current = true; setPending(true); setError(''); setErrorAction('apply');
  const context = scopeRef.current, ids = [...checked], session = useWorkspace.getState().session;
  try {
   await work(async () => {
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

 return <section className="face-repair-tools" aria-label="面几何修复">
  <div className="face-repair-toolbar">
   <div className="face-repair-toolbar-main">
    <div className="face-repair-toolbar-options" aria-label="面检查选项">
     <span className="face-repair-check-state" data-state={checkStatus} role="status" aria-label="面检查状态" aria-live="polite">{checking ? '正在检查…' : checkStatus === 'checked' ? '已检查' : checkStatus === 'error' ? '检查失败' : !singleFace ? '请选择单个面' : !validParameters ? '检查参数未填写完整' : '等待检查'}</span>
     {checkStatus === 'checked' && <span className="face-repair-candidate-count">{current.length} 项候选</span>}
     <div className="property-operation-group"><Button size="small" aria-label="重新检查" disabled={disabled || !active || !singleFace || !validParameters} onClick={() => void diagnose()}>重新检查</Button>
     <Button size="small" aria-expanded={parametersOpen} onClick={() => setParametersOpen(open => !open)}>检查设置</Button>
     {plan && <Button size="small" aria-label="清除预览" disabled={pending} onClick={clearPreview}>清除预览</Button>}</div>
    </div>
    <div className="face-repair-toolbar-actions" aria-label="面修复操作">
     <Checkbox aria-label="全选可修复项" aria-checked={allSelected ? true : eligibleRows.some(row => checked.includes(row.candidate.candidate_id)) ? 'mixed' : false} checked={allSelected} indeterminate={!allSelected && eligibleRows.some(row => checked.includes(row.candidate.candidate_id))} disabled={disabled || !eligibleRows.length} onChange={event => setChecked(event.target.checked ? [...new Set([...checked, ...eligibleRows.map(row => row.candidate.candidate_id)])] : checked.filter(id => !eligibleRows.some(row => row.candidate.candidate_id === id)))}>{allSelected ? '取消全选可修复项' : '全选可修复项'}</Checkbox>
     <span className="face-repair-selection-count" aria-live="polite">已选{chosen.length}项，涉及{involvedCount}个面</span>
     <div className="property-operation-group">{selectedReview.length>0&&<Button disabled={disabled} onClick={() => setReviewIds(selectedReview.map(item => item.candidate_id))}>核对所选</Button>}
     <Button disabled={disabled || !applicable} onClick={() => void apply()}>修复所选</Button></div>
    </div>
   </div>
   {parametersOpen && <div className="face-repair-parameters">
    <label>窄枝宽度上限（px）<InputNumber disabled={busy || pending} aria-label="窄枝宽度上限" min={1} max={4} step={.5} value={width} onInput={setWidthDraft} onBlur={() => setWidthDraft(width === null ? '' : String(width))} onPressEnter={() => setWidthDraft(width === null ? '' : String(width))} onChange={value => {setWidth(value === null ? null : Number(value)); setWidthDraft(value === null ? '' : String(value));}} /></label>
    <label>候选面积上限（px²）<InputNumber disabled={busy || pending} aria-label="修复候选面积上限" min={1} max={2000} value={maxArea} onInput={setAreaDraft} onBlur={() => setAreaDraft(maxArea === null ? '' : String(maxArea))} onPressEnter={() => setAreaDraft(maxArea === null ? '' : String(maxArea))} onChange={value => {setMaxArea(value === null ? null : Number(value)); setAreaDraft(value === null ? '' : String(value));}} /></label>
   </div>}
   <Tabs activeKey={filter} onChange={key => changeFilter(key as Filter)} items={[{key: 'review', label: '待核对'}, {key: 'ready', label: '可修复'}, {key: 'processed', label: '已处理'}, {key: 'all', label: '全部'}]} />
  </div>
  {!singleFace && <Alert type="info" message="请选择一个面，将自动检查面几何。" />}
  {error && <Alert type="error" showIcon message={error} action={<Button size="small" disabled={disabled || (errorAction === 'apply' && !applicable)} onClick={() => errorAction === 'apply' ? void apply() : void diagnose()}>重试</Button>} />}
  {historyError && <Alert type="warning" showIcon message={'处理历史加载失败：' + historyError} action={<Button size="small" disabled={historyLoading} onClick={() => setHistoryRetry(value => value + 1)}>重试历史</Button>} />}
  <div className="face-repair-table-wrap">
   <table className="face-repair-table" aria-label="面修复候选">
    <thead><tr><th scope="col">选择</th><th scope="col">问题类型</th><th scope="col">面积（px²）</th><th scope="col">涉及面数</th><th scope="col">线 / 文字依据</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead>
    <tbody>{rows.slice((page - 1) * pageSize, page * pageSize).map(row => {
     const item = row.candidate, blocked = !row.history && hardBlocked(item), acknowledged = verified.includes(item.candidate_id);
     const source = row.history?.source_feature_id ?? plan?.feature_id ?? feature?.feature_id;
     const lines = item.reference_line_ids ?? [], texts = item.reference_text_ids ?? [];
     return <tr key={row.key} data-candidate-id={item.candidate_id} data-operation-id={row.history?.operation_id} className={highlighted === row.key ? 'is-highlighted' : ''} onClick={() => locate(row)}>
      <td onClick={event => event.stopPropagation()}><Checkbox aria-label={'选择候选 ' + item.candidate_id} disabled={disabled || blocked || !!row.history} checked={!row.history && checked.includes(item.candidate_id)} onChange={event => selectCandidate(item.candidate_id, event.target.checked)} /></td>
      <td><strong>{kindLabel(item)}</strong>{item.kind === 'void' && <small>{row.history ? '已填充' : '未占用'}</small>}{item.kind === 'occupied_hole' && <small>{row.history ? '已合并内部碎面' : mergeable(item) ? '合并内部碎面' : '已占用'}</small>}</td>
      <td>{Number(item.area_px2.toFixed(1))}</td>
      <td>{new Set(involvedIds(item, source, assignments[item.candidate_id])).size}</td>
      <td className="face-repair-evidence">
       <span title={[...lines, ...texts].join('、')}>{lines.length || texts.length ? `相交线 ${lines.length} · 文字 ${texts.length}（仅空间相交）` : row.history ? '操作记录中无相交线或文字' : '未发现独立线或文字依据'}</span>
       {!row.history && item.kind === 'boundary_gap' && <small>开口区域归属需人工核对</small>}
       {blocked && <small>{blockedMessages[item.blocked_reason ?? ''] ?? '未满足安全修复条件，已保留'}</small>}
       {!row.history && mergeable(item) && <small>将{item.merging_feature_ids!.length}个碎面并入当前面，线和文字保留</small>}
      </td>
      <td>{row.history ? <span title={row.history.operation_id}><Tag color="green">已处理</Tag><small>修订 {row.history.result_revision}</small>{row.history.created_at && <small>{new Date(row.history.created_at).toLocaleString('zh-CN')}</small>}</span> : blocked ? <Tag>已保留</Tag> : !reviewed(item) ? <Tag color="gold">待核对</Tag> : <Tag color="blue">可修复</Tag>}</td>
      <td onClick={event => event.stopPropagation()}><Space wrap size={4}>
       <Button size="small" disabled={!item.geometry} onClick={() => locate(row)}>定位</Button>
       {!row.history && !blocked && needsReview(item) && <Button size="small" disabled={disabled} onClick={() => acknowledged ? cancelReview(item.candidate_id) : setReviewIds([item.candidate_id])}>{acknowledged ? '取消核对' : '核对'}</Button>}
       {!row.history && item.kind === 'spur' && !blocked && checked.includes(item.candidate_id) && <Select aria-label={'接收面 ' + item.candidate_id} placeholder="选择接收面" value={assignments[item.candidate_id]} disabled={disabled} onChange={value => setAssignments(old => ({...old, [item.candidate_id]: value}))} options={(item.receiver_options ?? []).map(option => ({value: option.feature_id, label: option.color + ' · ' + option.feature_id.slice(0, 8)}))} />}
      </Space></td>
     </tr>;
    })}</tbody>
   </table>
   {!rows.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={historyLoading && filter === 'processed' ? '正在加载处理历史…' : !singleFace ? '选择单个面后自动检查候选' : checking && filter !== 'processed' ? '正在检查当前面…' : !plan && filter !== 'processed' ? checkStatus === 'error' ? '检查失败，可重新检查' : '选择面后将自动生成修复候选' : '当前筛选下没有候选'} />}
  </div>
  {rows.length > pageSize && <Pagination className="face-repair-pagination" size="small" current={page} pageSize={pageSize} total={rows.length} showSizeChanger={false} showTotal={total => '共 ' + total + ' 项'} onChange={setPage} />}
  <Modal title={'核对 ' + reviewIds.length + ' 项修复候选'} open={reviewIds.length > 0} okText="确认核对" cancelText="取消" onCancel={() => setReviewIds([])} onOk={() => {
   setVerified(old => [...new Set([...old, ...reviewIds])]); setReviewIds([]);
  }}>
   <p>已核对区域属于当前地质面，且所需线和文字已保留。</p><p>请先定位检查这{reviewIds.length}项候选；确认后才可应用修复。</p>
  </Modal>
 </section>;
}

export function FaceRepairOverlay({display, features}: {display: FaceRepairDisplay; features: Record<string, Feature>}) {
 const receivers = [...new Set(display.checked.map(id => display.assignments[id]).filter(Boolean))];
 return <g className="face-repair-overlay" pointerEvents="none">
  {receivers.map(id => features[id]?.feature_type === 'face' ? <path key={id} data-face-repair-receiver={id} d={geometryPath(features[id].geometry)} fill="none" stroke="#08979c" strokeWidth={3} strokeDasharray="6 3" vectorEffect="non-scaling-stroke" /> : null)}
  {display.plan.candidates.map(item => {
   const active = display.checked.includes(item.candidate_id) || display.highlighted === item.candidate_id;
   return <path key={item.candidate_id} data-face-repair-candidate={item.candidate_id} d={geometryPath(item.geometry)} fill={item.kind === 'spur' ? '#fa8c16' : item.kind === 'void' ? '#52c41a' : item.kind === 'boundary_gap' ? '#722ed1' : '#1677ff'} fillOpacity={.35} fillRule="evenodd" stroke={active ? '#d4380d' : '#595959'} strokeWidth={active ? 3 : 1} strokeDasharray={item.kind === 'occupied_hole' || item.kind === 'boundary_gap' ? '4 3' : undefined} vectorEffect="non-scaling-stroke" />;
  })}
 </g>;
}
