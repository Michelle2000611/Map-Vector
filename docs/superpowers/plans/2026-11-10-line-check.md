# 线检查与10秒通知 Implementation Plan

> **For agentic workers:** 使用superpowers:subagent-driven-development逐任务执行、独立审查，用户已授权持续完成。工作在现有未跟踪源码目录，不提交、不推送。

**Goal:** 实现断线、文字短线、虚线编组三队列及10秒全局通知，解释面合并的科学模型。

**Architecture:** 新独立诊断/预览/线命令，仅修改线与关系，复用现有幂等operation/history；前端共用BottomReviewPanel并复用草稿flush、请求取消与画布定位。扫描不持写锁。

**Tech Stack:** FastAPI/Pydantic、SQLite WAL、Shapely、React/Ant Design/TypeScript、pytest、Playwright/CUA。

## Global Constraints

- 所有测试数据和证据在仓库runtime内，使用当前pytest短目录防护，禁止D盘根目录输出。
- 不在真实项目执行修复/检测命令；功能编辑只验收隔离副本，正式仅只读验收与安全更新。
- 面、文字、OCR、原栅格不被线检查及其undo/redo改变。
- 候选不自动应用；批次原子、幂等、显式核对，过期/错作用域拒绝。
- 面板全宽520/420，普通按钮；全局结果10秒，加载随请求。
- 新增接口/命令需更新OpenAPI及生成前端类型，不改面合并逻辑。

### Task 1: 结果通知10秒

- [x] 先红测10秒前仍可见/10秒后关闭、重复结果重置时钟、loading随请求。
- [x] 修改LoadingFeedback.tsx并迁移unified-feedback.cjs期望，独立回归。

### Task 2: 后端检测、绑定预览、决策、应用与历史

Files: 新geometry/line_checks.py、application/line_checks.py、api/line_checks.py、tests/test_line_checks.py；修改domain/commands.py、application/commands.py/history.py、repositories/migrations.py和api/app.py注册入口。

- [x] 先红测四端点方向、虚线保护、文字短线/地质线保护、独立组批量、作用域/期限/幂等、保留元数据及撤销。
- [x] 实现纯几何诊断、只读快照与锁外计算，短写缓存绑定当前修订。
- [x] 实现保留/重开元数据及专用apply_line_check，逐候选处理并阻止共享对象冲突。
- [x] command/history显式绕过OCR同步；逐表验证面/文字/OCR不变、线关系及索引可撤销。
- [x] 并发诊断阻塞时其他短写可完成，回归快照读取锁修复。

### Task 3: 前端面板、覆盖层及草稿/上下文保护

Files: 新components/LineCheckTools.tsx、LineCheckTools.css、services/lineChecks.ts、tests/line-check-panel.cjs；修改Workbench.tsx并复用BottomReviewPanel。

- [x] 先红测显式检查、三类候选/状态筛选、定位与连接段预览、确认后应用、保留/重开。
- [x] 草稿flush后检查修订；取消/序号/作用域防迟到，失败保留选择，成功/修订变化清空。
- [x] 集成仅line层全宽面板，单/双画布覆盖层，520/420、折叠和小屏内滚动。

### Task 4: 集成、独立审查与交付

- [x] 生成契约/类型，跑后端与前端相关回归及生产构建。
- [x] 独立审查处理候选保护、数据边界、并发、原子性和上下文问题。
- [x] 隔离真实副本CUA验证检测/预览/应用/撤销，检查原表/资源hash，保存截图。
- [x] 官方空闲时更新服务，health及页面只读验证；清理临时服务/标签，记录验收。
- [x] 给出面合并Polygon/MultiPolygon/接缝修复/编组的区别与建议，不改其算法。

验收：`docs/migration/20261110-line-check-acceptance.md`。去重后后端71、前端39项场景通过；最终生产构建成功。副本保留于撤销后revision47，业务表/资源与初始41一致，已保留审计和核对元数据。
