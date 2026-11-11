# 文字核对与残影简化实施计划

> 使用 subagent-driven-development、test-driven-development、verification-before-completion，持续实施已批准方案。

**目标：** 简化清理与审核操作，同时保留修订隔离、草稿和保护线规则。

**架构：** TextReviewPanel 管理筛选、详情和高级操作；Workbench 管理选中对象、提交与自动导航；TextActions 只负责操作布局；抽取 ResiduePlan 管理精简清理信息。

**技术：** React 18、Ant Design 5、TypeScript、Zustand、Vite、Playwright、pytest。

## 约束

- 不批量改写原项目，不修改清理保护算法。后台清理仍要求完整计划和事务复查。
- 自动导航只在同一项目、资产、图层、选区的成功操作后发生；未保存草稿继续保留。
- 分工文件互不重叠，不提交或推送现有未跟踪业务代码。

## 任务

- [x] 1. TextReviewPanel.tsx、EditingWorkspace.tsx 和独立 CSS：先运行针对新筛选、展开详情、单行“查看”和高级操作收纳的红测，再实现面板；新增 frontend/tests/text-review-panel.cjs，验证状态保留、读取范围与点击行为。
- [x] 2. Workbench.tsx、TextActions.tsx、ResiduePlan.tsx：先建立直接清理和审核导航红测；移除独立确认，直接清理自动取完整计划，查看范围只预览，清理摘要缩短。保存并确认/稍后处理成功后从最新待核对队列（required/manual_edited）找下一条，失败与切换不跳转。
- [x] 3. frontend/tests/text-review-flow.cjs 和既有 browser 回归：覆盖直接清理只生成一次完整计划和一次清理命令、只读查看不写、无可清理对象、失败、切对象/项目、审核导航及草稿保留；更新旧文案定位器，不弱化原有断言。
- [x] 4. 构建、面板/流程/既有回归及针对性的后端清理测试；独立代码复核并修正阻断问题。
- [x] 5. 用 CUA 检查隔离副本真实布局，保存桌面/窄屏截图，更新 README 和本轮验收记录。

修改前快照：runtime/text-review-simplification-20261109/before；禁止用空 Git 基线创建新工作树覆盖这些文件。

验收证据见 docs/migration/20261109-text-review-simplification-acceptance.md；桌面及三个宽度的独立浏览器截图已保留。
