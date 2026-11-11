# Inspector Contained Tools Implementation Plan

> Inline implementation under the user's existing authorization; independent review follows requesting-code-review. No commits of untracked business sources.

**Goal:** 检查内容只出现在所属页签，对象来源利用剩余空间。

**Architecture:** 复用 Ant Tabs 和现有三个检查组件，保持检查组件挂载；导航控制检查入口，业务写入仍走已有命令及草稿保护。

**Tech Stack:** React 18、TypeScript、Ant Design 5、Playwright。

## Global constraints

- 不修改后端及正式项目数据。
- 测试输出仅在仓库 runtime；使用现有 5175 前端测试服务和 8841 完整版本。
- 保留所有原有业务操作及可撤销、人工核对保护。

## Tasks

- [x] 在 `frontend/tests/inspector-contained-tools.cjs` 添加行为测试，运行 `node frontend/tests/inspector-contained-tools.cjs` 确认旧布局失败。
- [x] 修改 `PropertySectionTabs.tsx` 使不可见页签保持内容挂载，按上下文恢复默认页签，公开页签切换回调。
- [x] 修改 `Workbench.tsx` 将面修复和线检查移入几何工具，文字全图表格移入残影处理；切入/选择变化自动只读检查，保留错误重试。
- [x] 修改 `TextActions.tsx` 及 `TextReviewPanel.tsx`，精简文字操作并保留表格内确认。
- [x] 调整属性及框架 CSS，来源全高、导航固定、单一区域滚动。
- [x] 执行新工作区、批量残影、文字表格、属性草稿相关测试及生产构建；更新受界面入口变化影响的旧断言。
- [x] 对 8841 实际页面只读验证新资源，记录验收与截图。

独立评审发现的框选范围覆盖与长预览裁切均经红绿回归修复。新增用例18项，相关回归53项，共71项通过。没有提交仓库的未跟踪业务源码。
