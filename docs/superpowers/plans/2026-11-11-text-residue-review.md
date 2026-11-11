# 文字残影分组复核 Implementation Plan

> 使用superpowers:subagent-driven-development按任务隔离实施并独立审查。用户已确认设计，不重复询问。

**Goal:** 恢复可批量核对的待核对线清理，统一残影入口、固定所有属性页签、精简全图核对表并定位当前文字。

**Architecture:** 后端给现有局部预览追加带证据的复核组与持久保留决策，显式确认集合进入complete清理；跨框保留外部段，沿用operation/history。前端工作区串联局部复核、按需显示的全图文字列表及固定属性导航。细节接口见同日spec text-residue-review-design。

**Tech Stack:** FastAPI/Pydantic/SQLite WAL/Shapely；React/TypeScript/Ant Design；pytest/Playwright。

## Global Constraints

- 原工具栏、面线保护、文字/OCR/原图、幂等、草稿、批量原子性、撤销重做与状态隔离必须保留。
- 待核对不自动清理，明确地质边界/手工/语义线型/相邻文字有硬保护；跨框仅确认的框内部改变。
- 元数据保留不增加工作修订，证据变化重开，不把旧保留覆盖到新对象。
- 一切输入范围/ID需在服务端和有效预览绑定；旧命令幂等摘要兼容。
- 全部证据在repo runtime，正式数据不执行清理，实验仅隔离副本；不提交/推送。

## Tasks

- [x] 后端先红测分组/保留重开/错scope/期限/任意ID拒绝/跨框截取/硬保护/一次undo及幂等，实施helper/metadata migration/预览与命令字段，生成契约由root执行。
- [x] TextReviewPanel先红测默认精简列/可选列/上下标条件/全量列表定位跨页跨筛选且不勾选/全图残影状态保留，实施Props revealRequest和按需显示，保留旧业务。
- [x] Root固定三个图层属性Tabs，迁移显示控制，TextActions补录移review、统一入口，工作区集成分组确认/保留/刷选和执行；补有效草稿/迟到响应/失效保护测试。
- [x] 更新OpenAPI和生成类型，相关后端/前端回归及新用例，独立审查数据边界/关系/来源/作用域。
- [x] 隔离真实副本验收分组保留/确认清理/撤销、全图高亮及单/双/窄屏；新版在空闲8841启动，正式实际只读验收、截图/数据摘要与临时资源清理完成。
- [x] 更新验收说明，按去重测试数报告，不把中间绿测重复累加。

发布说明：自动审批阻止停止8840旧后端，未重试或换方式终止。保留8840，在8841启动新版，共用原正式工作区；用户应使用8841。验收见docs/migration/20261111-text-residue-review-acceptance.md。
