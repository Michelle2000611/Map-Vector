/**
 * One place that decides the colour of every review/processing status tag, so the same word has the same colour
 * in the face, line, text and residue panels. Use `statusColor(label)` for the antd <Tag color=...> value.
 */
export type ReviewStatus='pending'|'protected'|'verified'|'done'|'kept'|'neutral';

/** pending = still to be reviewed (gold); protected = requires explicit human review before cleanup (gold);
 *  verified = reviewed by the user (blue); done = applied (green); kept = explicitly retained (green); neutral = uncoloured. */
export const statusColors:Record<ReviewStatus,string|undefined>={pending:'gold',protected:'gold',verified:'blue',done:'green',kept:'green',neutral:undefined};

const labelStatus:Record<string,ReviewStatus>={
 待核对:'pending',待选接收面:'pending',
 受保护:'protected',
 已核对:'verified',已确认:'verified',可修复:'verified',
 已处理:'done',已清理:'done',
 已保留:'kept'
};

/** Colour for a status word shown in a tag; unknown words stay uncoloured so they never look like a status. */
export function statusColor(label:string):string|undefined{
 const status=labelStatus[label];
 return status?statusColors[status]:undefined;
}
