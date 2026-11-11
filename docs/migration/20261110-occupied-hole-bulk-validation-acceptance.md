# 全选240项参数校验修复验收

## 根因与修改

用户实际选择的面为`1e2f1fcc-10f4-42a3-8778-7f8fef502826`。服务端预览包含242个占孔，其中240项可直接合并。全选将240个ID完整提交，但RepairFace模型对candidate_ids和merge_occupied_candidate_ids均设置max_length=100，导致FastAPI在执行命令前返回422、VALIDATION_ERROR、请求参数无效。内存复现实际预览payload得到两个too_long错误（actual_length240/max_length100）；实时8840 OpenAPI同样公布maxItems100。

移除RepairFace三个候选/确认列表的静态100项上限。命令仍要求非空候选、唯一身份、合并确认是所选子集；业务层仍按保存的预览核验项目/资产/目标/修订/摘要/有效期、候选身份、mergeable状态、完整内部面归属和覆盖无重叠。列表实际范围由精确预览集合限定，不截断全选，不拆成多次事务。未改几何算法、全选UI或其他命令约束。

已重新生成OpenAPI及前端类型；OpenAPI仅移除三个maxItems100，生成的TypeScript没有语义变化。生产构建成功，静态bundle仍为index-LemEhuMV.js。

## 自动回归

- 新增`backend/tests/test_occupied_hole_bulk.py`，240个真实预览孔洞整批应用、幂等重试、一次撤销恢复241个对象/属性/精确几何/索引。另6种超过100项的未知/重复/未选中确认及错误保护确认请求保持拒绝，完整数据库dump不变。
- 修复前新增7项按预期失败；修复后新增7项+既有占孔13项共20/20通过。
- Root另跑`test_face_repairs.py`和`test_foundation.py`，29/29通过。总计49项定向检查通过。
- 独立只读审查未发现范围校验弱化；没有分批操作或跳过保护。

## 实际数据副本

采用原项目一致性备份“240孔批量合并验收副本”，原项目revision34，未在原成果执行修改。CUA选择实际面、填充孔洞、全选：240个可合并复选框全部勾选，2个禁用候选均未勾选。点击应用后页面显示“编辑已提交，工作修订35”。

| 项目 | 初始 | 合并后 | 一次撤销后 |
| --- | --- | --- | --- |
| 副本修订 | 34 | 35 | 36 |
| 目标面积px² | 38208 | 39832 | 38208 |
| 孔数 | 242 | 2 | 242 |
| 723个内部面 | active | superseded | active |
| 目标与内部面活跃union面积 | 39832 | 39832 | 39832 |
| 重叠面积 | 0 | 0 | 0 |

只读三阶段校验11/11、30/30、28/28全部通过。检查精确240个候选/确认ID、1624px²转移面积、723个内部面、单次操作与单次撤销、UUID/属性/关联/索引恢复、所有其他对象与线/文字/OCR不变。原项目SQLite、完整逻辑数据、20,284个几何以及来源/原图/运行资源哈希保持相同。浏览器无error日志。

## 服务与证据

确认识别/导出任务空闲后更新8840和8841。两服务health ready，实时RepairFace schema均已移除三个maxItems，同时保留candidate_ids.minItems1。原项目仍revision34。Vite5175继续运行，临时8866与验收页已关闭。

证据：`runtime/occupied-hole-bulk-validation-20261110/`内schema-red.json、backend/red.txt/green.txt及各回归证据、root-regression.txt、build.log、services-verified.json；live目录包含fixtures、三阶段verification及压缩capture、cua-240-selected.png、cua-240-merged.png、cua-240-undone.png。副本保留在撤销后的状态。未提交或推送。

用户重试时刷新页面，重新点击“填充孔洞”生成当前预览，再全选并应用，避免沿用已过期的预览。
