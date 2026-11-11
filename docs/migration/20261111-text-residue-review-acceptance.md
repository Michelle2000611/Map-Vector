# 文字残影分组复核及统一入口验收

## 最终交互

面、线、文字属性页签固定在属性标题下，保存状态、错误和预览排在其后。display:contents+flex order只重排布局，不复制或销毁各页表单。补录文字移到文字核对；残影页只有一个查看残影并清理入口，进入后局部预览和全图文字列表打开并高亮当前文字，真正修改由清理所选残影执行，待核对线没有被静默确认。

残影显示开关与退出入口全部位于右侧：疑似碎面/疑似线段/待核对线/其他面线。待核对线按文字、原因、空间关联、确认能力和保留状态分组，支持组选择、批量确认为残影、保留/重开和刷选；选择/高亮不改变当前文字对象选区。全选只包含可确认pending线，手工/明确分割/语义虚线齿线/其他文字等硬保护保留。

全图文字核对表初始隐藏但组件可缓存数据。入口打开后定位当前文字所在筛选/页码并滚动高亮，不勾选批量删除；列表仍为全资产全部文字。曾打开后切其他图层再回来保留列表状态，项目/资产/session重开失效。默认选择框/文字/核对状态/残影/操作，原始候选和识别分数为同表可选列；上下标只在存在或异常时显示，原因内联于文字。内容审核与残影状态仍独立。

## 后端与安全

新增text_residue_review局部helper、typed决策endpoint和证据绑定metadata；保留/重开不增加working_revision，按文字+线+真实证据摘要持久化，不把版本号/updated_at等无关变动当证据。预览生成在WAL只读快照内计算，短写只校验局部摘要/确认权限后存储。复核token与项目/资产/目标/修订/原始及normalized范围/摘要/TTL绑定，command确认集合必须与complete预览一致；keep可不增修订，因此apply也重查决策。旧无新字段命令摘要兼容。

明确确认的跨框线原完整几何进入隔离，框外部分生成可追溯active线段，继承原样式和编组；一次undo/redo补偿全部关系/索引。完整原线有applied拆分清理审计时，普通恢复隔离线拒绝，提示撤销对应清理，防止直接子段再次拆分后产生重复网络。普通整线隔离恢复保留。

新增text_ocr_index局部Rtree，migration一次回填，触发器维护primary OCR quad/lifecycle变化；原文字已移动时仍保护旧OCR位置，避免每次全图扫描。没有放开manual/split/semantic保护绕过legacy路径。文字、OCR、原图不因complete cleanup及其history同步改变；面仅处理既有疑似碎面并守恒原覆盖。

## 验证

后端按nodeid去重147/147通过（35新增），中间115/82/36/2不可累加。前端旧116、表格/会话11、原表格7、批量10、新集成7，共151个不同场景通过。合计298个测试场景在本轮验证，不声称全部最终同一源码一次重跑。保留所有中间红记录，源脚本/报告路径在runtime/text-residue-review-20261111/verification-summary.json。

独立审查发现并修复：无选区框选缺少残影工作区；同范围session迟到请求；远移文字原OCR框；跨框原线恢复的孙段绕过。另真实验收截图引发瞬时1×1 resize，使旧响应式分支重挂属性Card并丢Tabs状态；记录原DOM detached/resize trace后，以新用例先红后绿，忽略无意义极小宽度响应，并保持画布比例。正常980/手机断点仍保留。

OpenAPI和前端类型已更新，tsc和生产构建成功：index-CIONK3SC.js、index-Cqwcj0kh.css。Ant use-client及既有包体警告保留，无编译错误。

## 真实数据隔离副本

一致性备份revision45原项目为文字残影分组验收副本，所有编辑仅在独立8866 workspace_override副本执行。新桥文字预览范围914,265至948,289，92疑似碎面、1建议短线、1可确认跨框线、1复核组。完成保留→刷新仍保留→重开→确认→清理→一次撤销。

保留阶段revision45，12业务表/原图来源均不变，无编辑operation。一次清理45→46记录92个碎面、2条线（包含1条明确确认的跨框线）；原跨框完整几何隔离、生成1个框外active段。独立几何检查确认框外段union严格等于原线减检查框，原始几何原样保留；所有文字/OCR及资源不变，地质面union覆盖守恒。一次撤销46→47后全部原有业务对象、属性、编组、样式关系、空间索引恢复，原图/文字/OCR始终一致。

初始验收器错误要求新框外线段物理消失，实际history保留deleted审计墓碑。原失败报告verification-restored-before-audit-alignment.json与ui-completed-with-old-verifier.json保留；修正后分别严格校验全部原业务行恢复、每个额外记录必须由本次operation授权且inactive。没有改业务数据或基线来变绿。最终各阶段及框外验证通过，综合final-ui-verification.json明确列出旧验收器原因。临时副本最终留47和审计/元数据；8866关闭。

最后只读截图曾在临时服务过早关闭时产生failed fetch，该图被判无效；服务重开后等待全图146条报告完成、当前行aria-selected、所有请求结束再截图，final-preview-verification.json passed且无请求失败，之后才关闭临时服务。

## 发布与数据状态

正式空闲检查确认无运行中识别/导出、无活动请求。停止8840旧进程的操作被自动审批拒绝，仅返回blocked by policy；没有重试终止或改用其他手段。采用安全替代：旧8840保持运行，空闲8841启动新版，监听PID6628，提供全部新字段/接口与最终JS/CSS，health ready。5175原Vite保留；其默认API仍指向8840，因此新版功能应使用8841页面。

8841实际页面只读验收：初始全图队列隐藏、右栏正常；errors=[]、writes=[]，未在真实项目执行清理。发布前后两正式项目revision8和45，feature/face_attribute/line_attribute/text_attribute/operation全行摘要一致。所有测试输出在仓库runtime，无D盘根目录文件，未提交或推送。

主要证据：backend/deduplicated-results.json；regression/summary.json；table/session-green及panel/batch；workflow/final-verified；review/final-review.md；build-final.log；official-service-final.json、official-business-verification.json、official-page-verification.json；live各阶段capture/verification、exterior-line-verification.json、final-ui-verification.json及final-residue-workspace.png。
