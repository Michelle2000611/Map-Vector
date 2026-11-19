import type {components} from './generated';
import type {TextFeature} from './models';

export type TextFormatSample=components['schemas']['TextFormatSample'];
export type TextFormatSource={featureId:string;label:string;sample:TextFormatSample};

/** Copy relative typography only: never source placement, OCR or review metadata. */
export function captureTextFormat(feature:TextFeature):TextFormatSource{
 if(!feature.text_value.trim()||!Number.isFinite(feature.font_size_px)||feature.font_size_px<1||feature.font_size_px>200||!/^#[0-9a-f]{6}$/i.test(feature.text_color))throw Error('该文字的内容或外观无效，请先检查后再取样。');
 return {featureId:feature.feature_id,label:feature.text_value,sample:{font_size_px:feature.font_size_px,text_color:feature.text_color,rotation_deg:feature.rotation_deg??0,text_value:feature.text_value,
  layout_runs:(feature.layout_runs??[]).map(run=>({text:run.text,script:run.script,font_size_px:run.font_size_px,x_offset_px:run.x_offset_px,baseline_offset_px:run.baseline_offset_px,width_px:run.width_px,ink_bbox_px:run.ink_bbox_px?.length===4?[run.ink_bbox_px[0],run.ink_bbox_px[1],run.ink_bbox_px[2],run.ink_bbox_px[3]] as [number,number,number,number]:null,quality_reasons:run.quality_reasons??[]})),
  layout_width_px:feature.layout_width_px??null,layout_height_px:feature.layout_height_px??null,baseline_offset_px:feature.baseline_offset_px??null,layout_basis:feature.layout_basis??null}};
}
