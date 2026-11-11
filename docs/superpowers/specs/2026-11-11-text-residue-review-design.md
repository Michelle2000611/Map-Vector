# 文字残影分组复核与统一入口

用户已确认以下方案及面/线也固定属性页签，授权连续实施，不再次暂停审批。

## 范围与安全

残影清理保留疑似碎面并入背景、疑似线段移隔离；补回待核对线的分组确认/保留。默认不清待核对线，人工确认后可合并进同一次清理。明确分割线、手工线、语义虚线/齿状线、涉及其他文字等有硬保护原因的线不能随普通全选处理。跨框线仅处理选定文字检查框内部分，原线身份和完整原始几何保留隔离审计，框外段继续active并有来源；一次撤销/重做恢复全部关系、身份和索引。

“保留”是检查元数据，按文字+线+真实证据摘要持久化，不推进working_revision；证据变化重新待核对。分组以当前文字、同类风险原因及空间关联为依据，不合并线几何。高亮/定位不是清理勾选。默认高置信清理不要求逐条确认。

所有新确认必须绑定项目、资产、文字、预览ID、修订、范围、输入摘要、期限和预览内可确认对象。过期/错资产/未知ID/硬保护/已保留对象不能通过客户端改ID越权。批次先完整校验再原子执行，幂等重试、草稿flush与旧响应隔离保持。

## 固定后端契约（前后端共同遵循）

现有PreviewRequest增加verified_line_feature_ids:list[UUIDString]=[]、line_review_preview_id:UUIDString|null=None。只对text_residue/complete_region生效；非空verified必须有同修订同文字的有效原复核preview，不能借其他文字范围。

TextResidueDisplay增加review_groups: list[ResidueReviewGroup]=[]；ResidueReviewGroup字段：group_id:str、feature_ids:list[str]、bounds_px:list[float]、reason_codes:list[str]、status:'pending'|'kept'、can_confirm:bool、evidence_sha256:str。每组同一确认能力/原因/状态；保留组可重新纳入核对，硬保护组可保留不可确认。display中protected_line_feature_ids仍包含待核对/硬保护的原线，默认清理不改变它们；verified后只把明确批准集合纳入计划。

POST /api/projects/{project_id}/text-residue-decisions：body asset_id/base_revision/preview_id/feature_ids(unique)/decision('keep'|'reopen')，response feature_ids/decision。按stored preview验证当前scope/摘要，记录元数据，不写几何/修订。

现有ApplyPreview cleanup_text_residue增加verified_line_feature_ids:list[UUIDString]=[]；必须与complete预览中验证后的集合完全相等。无新字段的历史payload幂等摘要保持兼容。review_summary记录确认线/保留线/拆分来源。保留的线不能被后续同证据preview自动重选。

预览组生成在原preview读scope中完成，仅物化局部数据；避免新增全图读写或全量editor副作用。尽量只做局部计算，不重建全项目GeoDataFrame。独立复核命令绝不更改文字、OCR及栅格；面仅既有残影碎面计划可变，线仅确认范围可变。

## 统一前端入口与列表

TextActions“补录文字”属于review页；residue页只留“查看残影并清理”入口。点击先flush有效草稿、生成只读局部预览、打开文字核对面板并请求聚焦当前feature_id。这个入口不静默确认任何待核对线，实际几何修改由残影工作区中的“清理所选残影”执行，建议碎面/线默认进入计划，待核对线按组或画布刷选后确认。

残影显示控制（疑似碎面/疑似线段/待核对线/其他面线/退出）移出画布header，放右侧残影页。残影页显示建议数量、待核对分组表、选择/定位/批量确认为残影/保留/重新核对和清理动作。选择一组即高亮其线，画布刷选只更新独立的复核线集合，不更改当前文字选区。受保护线仍可看但不可确认。退出清理高亮和刷选工具。

属性页签固定在标题下面（面/线/文字一致），任何保存状态、错误、提示、预览都排在页签之后；sticky仅固定nav，不能把整块预览一起固定。切页签不销毁表单DOM、草稿或检查实例。

全图文字核对面板初始不显示（数据仍可按需加载）。点击统一入口再出现/重新展开；数据范围仍是当前资产全部文字，不伪装为仅一条。自动切到能显示目标的筛选/页码，清除“仅疑似”导致的隐藏，滚到该行并高亮，不能自动勾选批量删除。项目/资产/会话变化清理旧request，迟到请求不回跳。高亮目标已确认也可定位。

TextReviewPanel默认列：选择框、文字、核对状态、残影、操作。原始候选和识别分数通过“显示列”菜单开关，仍在同表格，不删除数据。上下标只在存在/异常时在文字旁显示；需核对原因在文字下简短显示，不单列普通文字。内容审核状态和残影状态独立。

## 全局约束

工具栏其余控件/原选择模式、单/双画布50/50、删除固定底部、输入/按钮尺寸、面修复/线检查、草稿/幂等/撤销都保持。所有测试在repo/runtime/text-residue-review-20261111；不得在D盘根目录写测试。业务源码未跟踪，不提交/推送或创建空工作树；真实项目仅只读验收，编辑只用隔离副本。
