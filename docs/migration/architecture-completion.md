# 应用边界与前端状态

应用服务通过 domain/ports 的 RuntimePorts 调用数据库事务、要素仓储、文件、影像解码、编辑器、GIS、工作进程和归档连接。configuration/composition 是具体实现装配入口，SQL 事务接口由 SQLite 适配器实现，几何规则由冻结编辑器适配器实现。application 内没有 mapvector.infrastructure、mapvector.algorithms 或 sqlite3 的直接导入。

数据库端口仍保留事务 Session 的 execute 契约，服务中的已有查询未被改写成另一套数据行为。要素加载/恢复/索引操作有独立仓储端口，归档副本连接和 backup 单列为存储端口。use_ports 支持任务上下文替换，内存仓储替换测试不需要 SQLite。默认本地实现由包的组合入口安装；不存在从 domain 反向导入具体实现。

前端资源响应由后端 Pydantic 定义，OpenAPI 生成 TypeScript，models.ts 只选择生成字段与 UI 回调，不再用 any 透传业务对象。生成使用 --default-non-nullable false，与后端默认参数可省略保持一致；编辑命令采用判别联合并保留必填参数。

Zustand workspace 状态实际承载项目/资产/修订、要素数组及按 ID 索引、选区、视口、手势、预览、审核、候选、运行与导出。命令响应 upsert/remove，同时移除失效选区并失效预览；属性操作刷新其元数据。切项目使用统一 AbortController 取消旧请求，并校验项目和会话标识，旧响应不写入新项目。

识别运行新增 elapsed_ms、stage_elapsed_ms、实际面线/候选计数、stdout/stderr 相对路径和受控日志读取。Paddle 的独立环境包版本与模型、代码哈希一起固定，任务执行前复核。

后台导出由 /export-jobs 受理，独立进程只读取已保存快照。export 表保存冻结请求、阶段、心跳、所有权、取消和错误；阶段为校验、写入并回读、关联清单和提交。取消终止本次工作进程树，部分文件没有成功下载；重启后失联任务为 interrupted，排队任务恢复。同步 /exports 保留为兼容接口。

storage_migration 记录增量存储迁移；text_display_index 对既有文字显示框首次回填，之后编辑/历史/恢复同步维护。feature_index 始终保存原几何包围框，文字命中候选使用显示框索引并保留旧旋转命中规则。
