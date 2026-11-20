import {Button} from 'antd';
import {geometryPath,TextGlyph} from './FeatureGlyph';
import {LineGlyph} from './LineGlyph';
import type {ResidueCleanupPlan} from '../hooks/useResidueCleanupPlan';
import type {Style} from '../services/models';
import type {ResidueScene} from '../services/residueComparison';

type Props={plan:ResidueCleanupPlan;viewBox:string;scene?:ResidueScene};
export function ResidueCleanupResult({plan,viewBox,scene:actualScene}:Props){
 const scene=actualScene??plan.plan?.cleanup_preview,styles=new Map<string,Style>((scene?.styles??[]).map(item=>[item.style_id,item]));
 return <figure className="residue-cleanup-result"><figcaption>清理残影后预览</figcaption>
  {scene&&(actualScene||plan.status==='ready')?<>
   <svg className="residue-after-canvas" viewBox={viewBox} preserveAspectRatio="xMidYMid meet" role="img" aria-label="清理残影后预览">
    {scene.features.map(item=>{
     const style=item.style_id?styles.get(item.style_id):undefined;
     if(item.feature_type==='text')return <TextGlyph key={item.feature_id} feature={item} opacity={1} selected={false}/>;
     if(item.feature_type==='line')return <g key={item.feature_id} data-cleanup-feature-id={item.feature_id}><LineGlyph feature={item} style={style} selected={false}/></g>;
     const color=(item.style_override?.stroke_color as string|undefined)??style?.stroke_color;
     const width=(item.style_override?.stroke_width_px as number|undefined)??style?.stroke_width_px??0;
     return <path key={item.feature_id} data-cleanup-feature-id={item.feature_id} d={geometryPath(item.geometry)} fill={item.fill_color} fillRule="evenodd" stroke={color&&width>0?color:'none'} strokeWidth={width}/>;
    })}
   </svg>
   {!scene.has_changes&&<small className="residue-after-note">{plan.plan?.text_residue_display?.unresolved_face_feature_ids?.length?'剩余碎面没有可归并的相邻面，当前未修改':'当前无可清理对象'}</small>}
  </>:<div className="residue-after-placeholder" role="status">
   <span>{plan.status==='loading'?'正在生成清理后预览…':plan.message??'开始检查后显示清理后预览'}</span>
   {plan.status==='error'&&<Button size="small" onClick={plan.retry}>重新生成预览</Button>}
  </div>}
 </figure>;
}
