# Map-Vector 迁移实现及验收报告

依据 2026-11-07 审定的迁移设计实现。自动验证和人工验收分开记录；本报告不把真实图旧问题视为已经修复。

本轮补齐后最新状态：应用端口隔离、生成契约、Zustand状态、会话取消、任务耗时/计数/日志、后台导出及文字显示框索引已实现。完整后端101项通过、浏览器21项通过；此前85/9为历史结果。详细补齐记录见 completion-plan.md、architecture-completion.md。

## 环境与来源

API、B2c、RapidOCR 共用根目录 .venv；Paddle 使用 .venv-ocr-paddle。安装缓存进入 .venv，模型在 models，测试与运行临时产物进入 runtime。.venv-api 已删除。DOCX、Markdown、JSON 的 API/Rapid 环境路径已同步为 .venv。

旧 scan2arcgis 与 Geological-Map-Digitizer 保持只读。B2c 14 模块、编辑内核、工作树补丁、839 个文件哈希和必要未跟踪源码清单归档于 baseline。前端参考提交和文件哈希见 frontend-reference.json；依赖许可元数据见 dependency-inventory.json。模型权重不入 Git。

## M0 至 M6 实现清单

|阶段|已交付代码及证据|尚未通过的外部验收|
|---|---|---|
|M0|冻结算法、编辑内核、来源补丁、依赖与模型哈希、参考前端清单|完整再分发许可原文核准|
|M1|FastAPI、统一错误、项目 SQLite、OpenAPI/TS、启动脚本、React 五步壳|macOS/Linux 实机|
|M2|影像/PDF 多页/DPI/GeoTIFF、资产采用、WKB/RTree、迁移 scan/dry-run/import/verify/report、来源门禁、幂等与隔离|更多历史异构工程|
|M3|B2c、Rapid/Paddle、串行子进程、固定输入/代码/依赖/模型、阶段日志、取消、恢复、明确采用和可选 OCR 警告|真实图 OCR 准确率|
|M4|49 旧操作的新接口和页面入口、预览、面/线/文字、审核、分组、样式、ROI、历史补偿|49 项逐一独立浏览器脚本及旧 U2 问题人工逐点验收|
|M5|SQLite 一致快照、派生 GPKG、恢复保留审计、像素 JSON/GPKG/SHP/WGS84 GeoJSON、ROI keep/clip、回读下载和关联清单|QGIS/ArcGIS 现场打开|
|M6|自动测试、真实项目几何属性对账、浏览器实图加载、多视口、备份回退、新端性能计时和依赖审计|旧版同机性能对比、大图、完整视觉/人工验收及发布授权|

49 项逐条映射在 operation-matrix.md/json。表中 implemented 表示代码承接；浏览器证据列明确列出实际点击或仅代码核对。没有把按钮存在当作真实问题通过。

## 自动验证

最终后端命令为 .venv/Scripts/python.exe -u -m pytest backend/tests -vv --disable-warnings --basetemp=runtime/final-acceptance，101项通过、0失败、0跳过，用时321.72秒，日志 runtime/completion-final.log。覆盖资产、迁移、算法来源、真实本地OCR、编辑、审核、预览、分组样式、范围、快照、恢复、备份、后台导出、架构端口、文字空间索引、安全整数、环境版本和进程所有权。最终审查新增明确重叠文字残影目标的回归，5项定向检查通过（residue-target-check.log）；提交时间修正后的导出6项及最终类型注解回归另见 post-review-check.log、review-types.log。

前端 TypeScript/Vite 构建记录在 runtime/build-final.log。npm ci 已按锁文件重新安装，缓存进入 .venv/npm-cache；npm audit 为 0 漏洞。API/Paddle 两个环境 pip check 均无冲突。

Edge整套21项通过（runtime/browser/completion-final.log），新增框刷套索/同色选择、逻辑组、分簇合并、来源对账、接拆线、样式绑定与显隐、碎面修复、沿线切面、实验线转面、残影隔离恢复、保存并确认、原图裁剪、删除撤销、重叠文字选择、缩放滚动坐标、会话切换、建议与改色/质量/ROI/差异图。原有项目→识别→采用→快照、后台导出回读、审核联动、真实项目加载及四种视口也通过。683×384是200% CSS视口等效检查，未操作浏览器原生缩放菜单。

构建有 AntD use-client 提示与约 1 MB 主包体积警告，未造成构建失败；后续可优化代码分包。像素 GPKG 的无 CRS 警告符合像素坐标契约，未伪造地理配准。

## 真实项目核对

源：scan2arcgis/.../p-20261106-003921-0933c4，826×794。原图 SHA256 cd40379a70f0dc10ff1ddd3391d66328d1dc13315f7b1d05b7a217b125941104；标准影像 db187917cf4151eb33be3c6bffb45f6ba0e6466957eefe5ae786428ac167d376；GPKG 73105ef3949c9ce39f97e3f150817a7a6740ad1b6f7ed41da7f03aeaf0030cfd。

最终导入副本：workspaces/default/projects/237ad80d-539d-46f1-bb84-c5305368757a，mapping_revision=1.2，来源键 f9e16569094b3b204255e57737f5ffbfdf9a33cc3a1e499a4e5d82b9595c87c2。19119 面、575 线、152 文字；484 组、575 成员、152 OCR 候选。19846 个对象的几何及属性逐项核对，差异均为 0；integrity_check=ok、foreign_key_check=[]，源文件哈希未变化。重复导入返回同一项目。

旧 OCR 候选无法证明原运行关联，保留原始文本和证据、run_id=null，报告 LEGACY_CANDIDATE_RUN_UNPROVEN；没有虚构 run 或人工审核事件。旧项目复制声明本身不能证明来源，需原运行输入清单或独立冻结重跑证据。

独立 B2c 重跑同一真实影像：19119 面、575 线，每个对象的规范化 WKB 和原属性摘要精确相同，报告 baseline-equivalence.json。此结论只覆盖这一样本的迁移运行一致，不代表算法质量改进。

## 性能与回退

在真实项目的独立复制数据库上计时 3 次（performance.json）：加载 P50/P95 约 2.77/2.91 秒；属性命令 0.21/0.24 秒；SQLite/GPKG 快照 3.83/3.86 秒；GPKG 写入并回读 10.76/10.83 秒。样本只有 3 次，P95 使用最近秩最大值。旧版交互计时与更大图尚缺，不能据此宣称性能等价。

完整备份 runtime/backup/real-project.zip 已恢复至独立 runtime/rollback-workspace 并通过几何和 SQLite 核对。旧工程保持独立可运行来源；新工程没有覆盖旧数据。真实项目初期诊断副本仍保留，最终应使用上述 mapping_revision=1.2 副本。

旧版交回通过 scripts/export_legacy.py 明确执行，以冻结快照生成兼容 GPKG、编辑记录和 compatibility.json。真实项目导出后由冻结旧编辑器重新打开，19119 面、575 线、152 文字，覆盖检查、几何与属性回读均通过；旧版无法表达的新审计、UUID 关系和配准放在关联清单，不伪装成旧项目数据库。证据 legacy-compatibility.json。

## 剩余验收及已知边界

- 旧 U2 问题保留原编号和证据；碎面、残影、线转面等已通过事务及合成拓扑检查，真实问题改善需同图同位置人工复核。
- QGIS/ArcGIS 目视检查、macOS/Linux、原生 200% 缩放、多种更大图和旧版性能对比未执行。
- 49项代码映射已按新增高级浏览器用例更新。合成拓扑检查覆盖主要高级入口；各操作的真实U2问题人工效果仍未签为通过，局部OCR/线逻辑组等代码与后端证据在 operation-matrix.md 单列。
- DOCX 容器和 XML 内容通过结构核对；因本机缺少 LibreOffice，render_docx.py 无法生成页面，Word 页面排版未签为通过。原样式保留，只替换环境路径。
- 模型与旧仓库缺少完整可确认的再分发许可，NOTICE.md 明确记录。当前成果适用于授权的本地迁移，不能据此推定可公开分发。
- strict_review 未启用；正式导出沿用 baseline_compatible，可放行自动项与人工确认分列。空范围 SHP 明确报错，像素 GeoJSON 明确拒绝。
- 页面已使用持久后台导出，显示阶段、等待、取消及错误；同步接口仅保留兼容。新任务冻结快照并由受控子进程写入回读，取消和重启恢复均有回归。旧版兼容工具由真实项目回读验证，外部旧版浏览器和GIS目视未执行。

本轮已补齐核对出的代码缺口并通过自动验证；上述外部验收意味着仍不能宣称全部真实问题已解决或全部迁移等价验收通过。真实项目在端口重构后再次核对并从完整备份恢复、兼容导出重开，19846对象无几何属性差异（runtime/completion-data-report.json）。

