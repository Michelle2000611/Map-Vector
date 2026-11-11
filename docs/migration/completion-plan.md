# 按设计逐项补齐

文档为需求依据。此前实现清单把主体功能承接等同于全部代码完成，现按实际代码重新检查。

- [x] 任务 1：domain/ports 定义与装配；应用层不直接导入基础设施、SQLite 或旧编辑器实现，架构约束与内存仓储替换测试通过。
- [x] 任务 2：前端实际使用生成类型与 Zustand 状态分域、按 ID 要素索引；取消旧会话请求，生产页面无显式 any，严格命令联合编译通过。
- [x] 任务 3：运行及阶段耗时、实际计数、日志相对位置和受控读取；页面阶段与等待时间，运行重试保留局部范围，Paddle独立环境版本固定。
- [x] 任务 4：持久后台导出受理、阶段、取消、失联恢复与查询；固定快照和ROI，提交前校验取消；同步接口兼容保留。
- [x] 任务 5：新增高级编辑、重叠字选择、缩放滚动、会话切换等浏览器回归，共21项通过；文字显示框空间索引、JS安全整数、PDF等契约检查通过。
- [x] 任务 6：最新完整后端101项通过，浏览器21项通过，真实19846对象逐项核对、备份恢复与兼容重开通过。外部人工/工具验收未伪造。

根环境 .venv；Paddle .venv-ocr-paddle。旧源码与旧数据只读。不得修改冻结参数，不新增业务政策，不把 strict_review 提前启用。无推送、合并或发布授权。

证据：runtime/completion-final.log，runtime/browser/completion-final.log，runtime/completion-data-report.json；架构与审查记录 architecture-completion.md、completion-code-review.md。这些完成状态不表示QGIS/ArcGIS、所有U2真实问题人工验收、跨平台及公开再分发许可已通过。
