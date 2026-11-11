# 迁移阶段核对

设计 DOCX 为需求依据，acceptance-report.md 为最终实现与验收事实记录。旧阶段清单中的 39 项、64 项等中间结果已经过时。

- [x] M0 来源、工作树差异、源码闭包、参考前端、依赖与模型哈希已冻结。
- [x] M1 FastAPI、React 五步、SQLite 项目、OpenAPI/TS、统一错误、启动和诊断已实现。
- [x] M2 多格式/多页影像、独立资产、WKB/RTree、复合归属、导入证据与隔离、稳定 UUID 和真实工程核对已实现。
- [x] M3 B2c、Rapid、Paddle 本地运行，串行进程树、取消、心跳、事件、恢复、工件验证与结果采用已实现。
- [x] M4 49 项旧操作都有接口与界面承接；面线文字、审核、残影、风险预览、样式/组/来源、撤销重做已实现。
- [x] M5 一致快照、保留审计的恢复、多格式导出回读、ROI keep/clip、关联清单、完整备份与旧版兼容导出已实现。
- [x] M6 自动回归、真实 19846 对象核对、浏览器核心链路与真实项目重开、多视口、备份回退及新端性能计时已执行。
- [ ] M6 外部验收：QGIS/ArcGIS、真实 U2 原问题逐点人工复核、原生缩放和更多大图、macOS/Linux、旧版同机性能与许可证授权核准。

用户要求已纳入：根环境指定 .venv；删除 .venv-api；Rapid 与主环境共用；Paddle 因 NumPy 冲突隔离；DOCX/Markdown/JSON 环境路径同步。旧项目只读，没有覆盖用户原始数据。

详细数据、最新测试数量、真实项目 ID、证据文件、已知限制和剩余人工验收均在 acceptance-report.md。49 项对照在 operation-matrix.md/json。不得把自动检查通过解释为全部真实错误已修复或发布许可已就绪。

最终检查：101 项后端测试通过（0 失败、0 跳过），Edge 21 项通过，前端 TypeScript/Vite 构建通过；两个 Python 环境依赖检查通过，npm 审计 0 漏洞。真实项目 19846 项几何属性逐项核对无差异，兼容导出由冻结旧编辑器重开对账一致。

本轮代码缺口补齐：domain/ports及归档存储隔离、严格生成类型、Zustand状态和ID索引、项目请求取消、任务耗时/计数/日志、Paddle环境固定、持久后台导出、文字显示框RTree和重叠文字选择。详见 completion-plan.md、architecture-completion.md、completion-code-review.md。
