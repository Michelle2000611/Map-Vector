# 全选240项请求校验修复

**根因：** 实际预览`efb8f7ad-6be5-47f4-9dfb-bb5ce88921e1`为242个占孔，其中240项可合并。前端按用户全选提交240个candidate_ids及merge_occupied_candidate_ids，RepairFace却限制最多100，FastAPI在业务执行前返回422 VALIDATION_ERROR。原项目仍revision34，没有发生部分合并。

**修复：** 去掉RepairFace三个候选ID列表的任意100项上限，以服务端保存的预览候选集合为实际范围。保留非空、唯一、子集、候选归属、几何保护、摘要/修订/有效期校验。整批保持单事务、单修订、单次撤销，不拆分请求、不截断选择。不修改原项目成果以做测试。

- [x] 写240项API回归并跑红：整批合并、幂等、一次撤销；非法/重复/未选择候选拒绝且无写入。
- [x] 最小修改domain/commands.py，生成OpenAPI与前端契约，跑定向后端和前端构建。
- [x] 从原项目一致性副本运行真实240项全选提交，验证2个不可合并孔保留、全部其他对象不变、一次撤销恢复。
- [x] 确认任务空闲后更新8840/8841后端，并核对实时OpenAPI不再maxItems100；记录原项目revision及源文件校验。

证据目录：`runtime/occupied-hole-bulk-validation-20261110/`。已用实际240项payload在内存Pydantic复现candidate_ids/merge_occupied_candidate_ids的too_long错误，详见schema-red.json。

结果：新增7项与既有13项占孔API测试20/20，Root的面修复与基础API回归29/29；构建成功。真实CUA副本选择240项成功提交（revision34→35）、723个碎面退休、面积38208→39832、孔数242→2，一次撤销恢复（revision36）。三阶段只读校验11/11、30/30、28/28通过。原项目保持revision34。8840/8841实时schema均已无三个maxItems，服务ready；临时8866和验收页关闭。
