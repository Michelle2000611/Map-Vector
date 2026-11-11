# 内部碎面全选实施计划

**目标：** 用户可在当前面的“合并内部碎面”候选列表中全选、取消全选，并看出部分选中状态。

**设计：** 列表上方用三态复选框提供“全选 / 取消全选”。相比两颗按钮，它同时表达选中状态且占用更少空间。仅操作当前预览中可合并的occupied_hole，保留用户对普通空洞的独立选择；忙碌时禁用。没有可合并项时不显示。仍由“应用所选修复”执行操作，API及后端不变。

**文件：** `frontend/src/components/FaceRepairTools.tsx`、同目录CSS，已有`frontend/tests/occupied-hole-merge.cjs`。

- [x] 在混合安全占孔、禁用占孔和普通空洞的浏览器场景中，先验证缺少全选入口导致失败。
- [x] 从当前可见候选派生安全ID集合及已选数，复选框全选时去重合并到checked、取消时仅移除这些ID；indeterminate表达部分选中。
- [x] 跑新增行为场景及原7项占孔用例、旧face-repair-tools；构建前端并检查实际服务提供最新bundle。
- [x] 浏览器检查入口与部分/全选/取消状态，截图留证；不修改真实项目数据。

用户已明确要求直接加全选/取消全选，沿用此前连续完成的授权，不增加设计审批或提交Git。

验收：新增浏览器场景1/1、完整占孔用例8/8、旧修复用例单独重跑1/1通过；旧用例首次并行运行的瞬时失败已记录在test-report。生产构建成功，8840/8841均提供`index-LemEhuMV.js`，无需重启后端。CUA在真实数据副本验证半选、全选、取消及应用按钮可用性，未执行合并，副本revision36、原项目revision34均保持。临时8866和验收页已关闭。

证据：`runtime/occupied-hole-select-all-20261110/`下的`test-report.md`、red/green结果、`build.log`、`served-build.json`、`final-verification.json`和`cua-all-selected.png`/`cua-all-cancelled.png`。只读独立审查新逻辑无阻断问题。
