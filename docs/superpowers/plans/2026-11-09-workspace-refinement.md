# 编辑工作区整理实施计划

> 使用 test-driven-development 和 verification-before-completion。分工文件互不重叠，实际浏览器复核后集成，不提交或推送现有未跟踪代码。

**目标：** 实现已确认的六项界面整理并保留草稿、画布与审核行为。

**架构：** Workbench保留当前画布和属性区，通过belowCanvas插槽承接持续挂载的审核栏；TextPositionFields承接可编辑坐标与只读尺寸，TextActions组织文字操作，LayerOpacity提供拖动预览及完成后单次保存。EditingWorkspace只协调文字图层、旧链接和审核栏可见性，App准备路由初始化状态。

**技术：** React18、Ant Design5、Zustand、TypeScript、Vite、Edge浏览器。

- [x] 建立回归用例并先观察红测：`workspace-refinement.cjs review` 与 `workspace-review-routing.cjs legacy` 均确认旧模式卡仍存在，随后按设计实施。
- [x] EditingWorkspace/App处理统一工作区、旧链接、图层同步与审核状态保留；Workbench提供belowCanvas和belowCanvasVisible属性，审核栏置于固定画布区外。路由模式提前准备，只在图层变化时同步URL，避免初始化与同项目导航互相覆盖。
- [x] TextPositionFields组件以现有PropertyNumber承接X/Y草稿和精度；W/H由display_bbox_px计算，只读，缺失或无效显示破折号。
- [x] Workbench工具区迁移不透明度滑块和隐藏层提示，去冗余标签与样式编辑，属性按钮按已确认布局分组。新增workspace-refinement.css统一响应式宽度，保留现有样式数据渲染；滑块拖动实时预览，松开单次保存。
- [x] 构建与TypeScript检查通过；主浏览器9项、独立路由5项通过，检验请求、草稿、URL、审核状态、预览切换、画布节点与1580/1100/720宽度。独立滑块审查另验证键盘与边界值、失败回显、跨图层隔离。
- [x] CUA复核独立实际项目副本：山前带对象W/H显示38.3/20.4，滑块显示40%，文字操作分组和双画布下方审核栏布局正确；隐藏文字层时提示及恢复按钮位于工具区，恢复并定位后画布无遮挡。
- [x] 完成独立审查并整理截图与结果记录；原项目数据库、全部assets/sources的最终SHA与夹具初始值一致，原项目未变。

验收证据沿用本次已经完成的执行结果，文档收尾未重跑测试：

- `runtime/ui-refinement-20261109/browser-results.json`：toolbar、coordinates、buttons、visibility、review、preview_navigation、opacity_drag、drafts、responsive共9项通过；同目录保存对应截图及三个屏宽的截图。
- `frontend/tests/workspace-review-routing.cjs`：前次命令 `node tests/workspace-review-routing.cjs` 退出码0，legacy、layer_url、persistent_queue、review_draft_priority、same_project_navigation共5项通过；结果来自该次终端输出，未另存日志。该轮 `npx tsc --noEmit` 退出码0。
- `runtime/ui-refinement-20261109/slider-review.cjs`：独立滑块审查退出码0；`final-live-ui.png` 记录CUA实际项目副本复核结果。
- `runtime/ui-refinement-20261109/original-hashes-final.json`：原数据库与全部assets/sources最终校验均为unchanged；`live/fixtures.json` 保存副本与原项目的对应关系。

修改前副本及哈希位于 `runtime/ui-refinement-20261109/before` 及 `source-before.json`。测试继续由gitignore排除，现有未跟踪代码未提交或推送。
