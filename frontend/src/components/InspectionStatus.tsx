import type {ReactNode} from 'react';
import {Button} from 'antd';
import './InspectionStatus.css';

type Props={state:'waiting'|'checking'|'done';attempted:boolean;disabled?:boolean;onCheck:()=>void;ariaLabel?:string;size?:'small';extra?:ReactNode};
const labels={waiting:'等待检查',checking:'正在检查',done:'检查完成'};

/** One "status dot + check button" row shared by every check tool: 等待检查 / 正在检查 / 检查完成. Failures are reported by the caller's own alert. */
export function InspectionStatus({state,attempted,disabled,onCheck,ariaLabel,size,extra}:Props){
 return <div className="inspection-status" data-state={state}>
  <span className="inspection-status-text" role="status" aria-live="polite" aria-atomic="true" aria-label={ariaLabel}><i className="inspection-status-dot" aria-hidden="true"/>{labels[state]}</span>
  <Button size={size} disabled={disabled||state==='checking'} onClick={onCheck}>{attempted?'重新检查':'开始检查'}</Button>
  {extra}
 </div>;
}
