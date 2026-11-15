import type {CommandInput,Feature,Style} from './models';

type LineStyleFields=Pick<Extract<CommandInput,{operation_type:'set_style'}>,'stroke_color'|'stroke_width_px'|'line_pattern'|'dash_pattern_px'|'tooth_spacing_px'|'tooth_height_px'|'tooth_side'>;

/** Save the visible appearance: unclassified recognition lines render as solid. */
export function lineStyleProperties(feature:Extract<Feature,{feature_type:'line'}>,style?:Style):LineStyleFields{
 const override=feature.style_override??{};
 const rawPattern=override.line_pattern??style?.line_pattern??feature.line_pattern;
 const pattern=rawPattern==='dashed'||rawPattern==='teeth'?rawPattern:'solid';
 const toothSide=override.tooth_side??style?.tooth_side;
 return {
  stroke_color:feature.stroke_color,stroke_width_px:feature.stroke_width_px,line_pattern:pattern,
  dash_pattern_px:pattern==='dashed'?(style?.dash_pattern_px?.length?style.dash_pattern_px:[6,4]):[],
  ...(pattern==='teeth'?{
   tooth_spacing_px:(override.tooth_spacing_px as number|undefined)??style?.tooth_spacing_px??10,
   tooth_height_px:(override.tooth_height_px as number|undefined)??style?.tooth_height_px??4,
   tooth_side:toothSide==='right'?'right':'left',
  }:{}),
 };
}
