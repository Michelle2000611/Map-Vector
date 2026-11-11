# 线检查与提示时长

用户已要求实施底部线检查（三种检查队列）及10秒通知；沿用其持续执行、不反复确认的要求。本轮面合并只分析，不修改面合并算法。当前业务源码未纳入Git提交，继续原目录，不创建空worktree、不提交或推送。

## 交互

选择线层时在底部显示全宽“线检查”，共用BottomReviewPanel，桌面默认520px、小屏420px，支持折叠及调整高度。检查为显式“检查当前线层/重新检查”，以全图当前资产为范围，不跟随候选定位或普通选区变化自动重算。选中、切层或改参数不自动改对象。参数默认折叠。

三个类型页签为“断线接续 / 疑似文字短线 / 虚线编组”，表格显示对象数量、关键证据和风险、核对状态、定位。状态筛选为待核对/已保留/已处理/全部。默认无勾选。定位高亮原线，断线另外显示拟新增的连接段。复核“保留原状”可跨刷新保存并可重新纳入核对。候选本身不代表错误。

显式“核对所选”后才能“应用所选”；按当前类别执行接续、隔离或编组。多个候选组必须分别处理，不能扁平化接成一条线或编成同一个组；批次中共享对象则整体拒绝并说明，不能部分提交。隔离保留身份和几何，可通过撤销或原隔离线层恢复。面板不增加删除入口，普通按钮统一样式。

检查、定位、选择、核对、应用均保护属性草稿。应用先flush，再比对报告base_revision与当前workspace；后台再次绑定项目/资产/修订/摘要/期限/候选与确认集合。失败保留选择供重试，修订/项目/资产/图层变化清除旧报告与高亮，迟到响应不能恢复旧上下文。

## 检测与数据边界

断线采用空间索引寻找端点邻近、切向一致且外观/用途相容的候选。明确四种端点组合和线方向，原线不重采样。已知虚线/齿状线不接续；规则间隔短段也不作为普通断线自动补齐。分叉歧义、跨第三条线、属性不一致等标为受保护/不可直接应用。

疑似文字短线需文字框或已有关联的空间证据，短本身不足以说明文字。保护地质分界、手工线、跨框延伸及地质符号；只提供显式隔离，不删除。虚线候选需有效线型或规则间隔、方向、长度证据，只建立逻辑组，不补间隔、不改变原几何。已有正确编组保留，不能任意拆掉用户其他组。

新线检查专用命令只构造线与必要关系变化，不走旧全量editor adapter。面/文字/OCR/栅格逐字节或逐行保持原样，应用和undo/redo都不触发全项目OCR同步。接续保留一个原线身份、退休其他被并线并保留来源审计，撤销恢复原几何、索引和关系。

扫描先mode=ro+BEGIN物化一致快照，关闭连接后计算；最后短写事务仅重新校验资产/修订并保存edit_preview。不能在写事务中做全图诊断。使用空间索引而非全图两两遍历；如超出候选上限，明确返回范围/数量信息，不能静默丢掉候选。

“保留/重新核对”为检查元数据，独立于几何working_revision，记录候选证据摘要；证据变化自动回到待核对。应用使用现有operation/history保存，既有幂等、原子提交及全局撤销重做生效。

## 接口契约

POST /projects/{project_id}/line-check-previews：asset_id、base_revision、max_gap_px默认8(0–50)、angle_tolerance_deg默认15(1–45)、max_short_length_px默认12(1–100)。响应含preview_id、asset_id、base_revision、algorithm_revision、expires_at、input_sha256、candidates、history、summary。

Candidate固定字段：candidate_id、kind(join_gap/text_stroke/dash_group)、feature_ids、bounds_px、connectors（每条连接段为两个XY点）、metrics（gap_px/angle_delta_deg/length_px等数字）、reason_codes、blocked_reasons、reference_text_ids、status(pending/kept)、review_required(true)、allowed_action(join/isolate/group)。历史项沿用候选展示字段，另含operation_id/result_revision/created_at/status(applied)，不可再次勾选应用。

POST /projects/{project_id}/line-check-decisions：asset_id、base_revision、preview_id、candidate_ids、decision(keep/reopen)，绑定存储预览及当前证据，不增加工作修订；返回candidate_ids、decision。

edit-commands新增apply_line_check：asset_id、base_revision、idempotency_key、preview_id、candidate_ids（1–2000，唯一）、action(join/isolate/group)、verified_candidate_ids（必须与所选集合相同）。feature_ids必须省略/为空，不能客户端传入替换几何。后台逐候选执行，冲突批次整体回滚。

## 通知与面合并说明

全局已完成结果通知统一10秒自动消失，包括错误和长查询结果，保留手动关闭与重复结果替换。进行中的加载提示仍随请求生命周期结束。

面合并建议区分：共享边界溶解成单面；点接触/分离对象以MultiPolygon作为同一要素，保留真实缝隙与孔洞；接缝修复另设受容差、邻面归属、覆盖守恒与预览确认约束的操作。编组保留各自身份。不能把连通性限制、对象身份和自动补缝混在同一个按钮语义中。本轮只给用户解释该方向。
