# 孔内碎面合并验收（2026-11-10）

## 问题与操作

截图中的外层黄色面有两个内环，内部实际上被识别成另外5个面。旧“填充孔洞”只允许未占用空洞，提示切换到普通面合并，无法在原位置直接完成修复。

现有入口新增可勾选的“合并内部碎面”。用户选外层面，展开“几何工具”，点击“填充孔洞”，勾选对应孔后点击“应用所选修复”。候选显示孔面积和将被吸收的小面数量。一次操作移除选中内环、将完整内部面的活跃身份标记为superseded，并保留审计、原几何、属性及撤销记录。

独立线、文字、OCR候选和原始栅格不变。未选孔保持原状。仅填外层内环而保留内部面的做法会产生重叠，此实现同时转移面归属。

## 数据约束

- 服务端从预览快照推导完整占有者，客户端只提交候选ID及显式`merge_occupied_candidate_ids`；旧请求默认不合并。
- 每个被吸收对象的全部几何必须在一个孔内，完整覆盖该孔且没有重叠。跨孔MultiPolygon、孔外岛、自有岛、局部覆盖、超面积阈值、超有效原图范围均拒绝。
- 接收者将在本批合并中退休的线状附着转移组合返回422，候选顺序不影响结果。
- 修订、摘要、预览有效期和资产范围校验保持；事务同步空间索引、编组/样式绑定、历史和面来源。一次撤销恢复原UUID、几何、属性和关联。

## 自动验证

Root最终运行以下定向回归：

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest backend/tests/test_occupied_hole_merge.py backend/tests/test_face_repairs.py backend/tests/test_geometry_commands.py backend/tests/test_advanced_geometry.py backend/tests/test_advanced_apply.py backend/tests/test_feature_properties.py backend/tests/test_bulk_text_delete.py backend/tests/test_architecture_ports.py --basetemp=D:/mv-ohm-root-20261110 -q
```

结果：**98 passed**，238.64秒。包括新增13项占孔测试、混合候选冲突及合法审计、导出排除退休面、局部选择、关系和索引恢复、幂等、undo/redo。警告为现有Starlette弃用和像素坐标导出没有CRS，不影响断言。

Root另运行`node frontend/tests/occupied-hole-merge.cjs`，**7/7通过**。UI实施方还运行旧`face-repair-tools.cjs`，通过。新用例覆盖4/6孔单请求、8类禁用候选、只合并选中项、真空洞显式空列表、失败保留重试、切图层清理、异常响应和旧修订。

`scripts/generate_contracts.py`、`npm --prefix frontend run generate:api`和`npm --prefix frontend run build`均成功。构建仍提示Ant Design现有`use client`指令被忽略及包体大小提示，无编译错误。

## 真实项目副本验收

原项目`623d34a2-2548-45f5-8c9a-79fec56296f3`，资产`537718ba-0d51-49eb-851d-de2dac35062c`，外层面`adbb6f72-6056-420c-9ce9-bb93b536343a`。用只读SQLite一致性备份和完整assets/sources/runs准备“孔内碎面合并验收副本”，在临时8866服务操作，未在原项目执行修改。

| 检查项 | 合并前 | 合并后 | 一次撤销后 |
| --- | --- | --- | --- |
| 副本修订 | 34 | 35 | 36 |
| 外层面积（px²） | 674 | 684 | 674 |
| 外层孔数 | 2 | 0 | 2 |
| 5个内部面 | active | superseded | active |
| 外层与内部面活跃union面积 | 684 | 684 | 684 |
| 重叠面积 | 0 | 0 | 0 |

CUA实际打开副本并选择黄色面，两候选分别为4px²/2个面、6px²/3个面；同时勾选应用后复查显示空洞0、占用孔0。随后点击一次撤销，两孔及5个面全部恢复。浏览器无error日志。

只读三阶段校验为8/8、22/22、21/21通过。除6个涉事面外，全部其他对象（含658条线、149个文字对象）、OCR和稳定数据表原样保持；对象总数仍为20284。原项目修订34、原manifest、原图/来源文件、6个涉事几何的SHA256前后完全相同。服务更新后再次验证仍相同。

证据位于`runtime/occupied-hole-merge-20261110/`：

- `backend/red.txt`、`mixed-red.txt`、`green.txt`、`regression.txt`及`summary.md`。
- `root-ui/results.json`、`ui/results.json`和`ui/two-holes-request.json`。
- `live/fixtures.json`、`verification-before.json`、`verification-merged.json`、`verification-undone.json`、`verification-report.json`及完整压缩capture。
- `live/cua-before.png`、`cua-merged.png`、`cua-merged-verified.png`、`cua-undone.png`。

## 运行状态

已在确认识别/导出任务均空闲后更新本地8840、8841服务。两个服务OpenAPI均包含显式合并字段、提供最新`index-DthktrKA.js`，原项目仍revision34。Vite5175原进程40604保持运行。临时8866服务和验收浏览器页已关闭，验收副本保留在撤销后的状态供复核。未提交、推送或自动修改真实成果。
