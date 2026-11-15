import {geometryPath} from './FeatureGlyph';
import type {FaceMergePreview} from '../services/faceMerges';

/** Draw only the local patches and exact result outline; inner rings stay open. */
export function FaceMergeOverlay({preview}:{preview:FaceMergePreview}){
 const selected=new Set(preview.selected_gap_candidate_ids);
 const result=preview.capabilities.gap_single;
 return <g data-face-merge-preview={preview.preview_id} pointerEvents="none">
  {preview.gap_candidates.map(candidate=><path key={candidate.candidate_id} data-face-merge-gap={candidate.candidate_id} d={geometryPath(candidate.geometry)} fill={selected.has(candidate.candidate_id)?'#52c41a':'#faad14'} fillOpacity={selected.has(candidate.candidate_id)?.5:.16} fillRule="evenodd" stroke={selected.has(candidate.candidate_id)?'#237804':'#d48806'} strokeWidth={2} strokeDasharray={selected.has(candidate.candidate_id)?undefined:'3 3'} vectorEffect="non-scaling-stroke"/>)}
  {selected.size>0&&result.eligible&&result.output_component_count===1&&result.result_geometry?.type==='Polygon'&&<path data-face-merge-result="true" d={geometryPath(result.result_geometry)} fill="none" stroke="#389e0d" strokeWidth={1.5} strokeDasharray="5 3" vectorEffect="non-scaling-stroke"/>}
 </g>;
}
