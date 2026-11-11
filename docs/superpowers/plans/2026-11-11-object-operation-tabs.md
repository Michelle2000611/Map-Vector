# Object Operation Tabs Implementation Plan

**Goal:** 用独立业务页签替代几何工具，新增共享边合并候选组表。

**Architecture:** 独立 FaceMergeTools 组件复用现有预览、命令和草稿保护。Workbench只负责页签归属、画布选区、定位及预览分发。

**Tech Stack:** React、TypeScript、Ant Design、Playwright。

## Global Constraints

- 不提交未跟踪的业务源码，不重启或终止8840，不写正式项目业务数据。
- 保持页签内容挂载，保留面修复与线检查现有行为。
- 用后端共享边连通组，不能把点接触或间隙推断为共享边。

## Tasks

- [x] 在 `frontend/tests/object-operation-tabs.cjs` 添加页签、表格、候选分组、跨标签、风险核对、精确合并和失效保护测试，先运行验证旧界面失败。
- [x] 新增 `FaceMergeTools.tsx` 和 CSS；扩展本地 PreviewItem 证据类型，复用 backend merge_faces / merge_suggest，不更改API。
- [x] 拆分Workbench的geometry页签并更新预览分发，保持面修复、线检查挂载及所有原有操作入口。
- [x] 更新受新页签影响的回归入口，运行新测试和有关自动保存、残影、面修复、线检查测试。
- [x] 生产构建、独立代码评审、正式页面只读检查，记录验收与构建资源。

验收：80项相关场景通过，独立评审与复核完成，构建通过。证据见 docs/migration/20261111-object-operation-tabs-acceptance.md。
