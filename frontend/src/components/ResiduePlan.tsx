import {Button,Space} from 'antd';
import type {Preview} from '../services/models';

export function ResiduePlan({preview,busy,onLocate,onCleanup}:{preview:Preview;busy:boolean;onLocate:()=>void;onCleanup?:()=>void}){
 const display=preview.text_residue_display;
 if(!display)return null;
 return <div className="residue-plan">
  <Space wrap><Button size="small" onClick={onLocate}>定位到检查范围</Button>{onCleanup&&<Button disabled={busy} onClick={onCleanup}>清理残影</Button>}</Space>
 </div>;
}
