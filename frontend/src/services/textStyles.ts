import type {Style} from './models';

export type TextStyleField='font_size_px'|'text_color'|'rotation_deg';
export function textStyleFields(style:Style):TextStyleField[]{return (['font_size_px','text_color','rotation_deg'] as const).filter(field=>style[field]!=null);}
export function textStyleSummary(style:Style){return [style.font_size_px!=null?style.font_size_px+' px':null,style.text_color,style.rotation_deg!=null?'角度 '+style.rotation_deg+'°':null].filter(Boolean).join(' · ');}
export function nextTextStyleName(styles:Style[]){const names=new Set(styles.filter(style=>style.feature_type==='text').map(style=>style.style_name));let index=1;while(names.has('文字样式 '+index))index++;return '文字样式 '+index;}
