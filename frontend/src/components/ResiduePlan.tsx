import {Button,Space} from 'antd';
import type {Preview} from '../services/models';

export function ResiduePlan({preview,busy,onLocate,onCleanup}:{preview:Preview;busy:boolean;onLocate:()=>void;onCleanup?:()=>void}){
 const display=preview.text_residue_display;
 if(!display)return null;
 return <div className="residue-plan">
  <Space wrap><span>碎面 {display.cleanup_face_feature_ids.length} 个 · 线段 {display.cleanup_line_feature_ids.length} 条</span><Button size="small" onClick={onLocate}>定位</Button>{onCleanup&&<Button disabled={busy} onClick={onCleanup}>清理残影</Button>}</Space>
  <details><summary>详情</summary><p>保留线段 {display.protected_line_feature_ids.length} 条 · 所属文字保持不变 · 可撤销</p><pre>{JSON.stringify(preview.legacy_report,null,2)}</pre></details>
 </div>;
}
