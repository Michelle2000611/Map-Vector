import type {Preview} from './models';
/** A complete check already owns the execution plan until its authorization changes. */
export function reusableResiduePlan(review:Preview|null,revision:number,verified:string[],assignments:Record<string,string>):boolean{
 return review?.preview_type==='text_residue'&&review.base_revision===revision&&!!review.text_residue_display?.complete_region&&!!review.cleanup_preview&&!verified.length&&!Object.keys(assignments).length;
}
