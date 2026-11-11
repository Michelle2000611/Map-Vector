# 来源与许可记录

B2c 算法闭包与编辑内核来自本机只读 scan2arcgis 工作树。冻结提交为 c7b74d9c9a16d1b082f0dab694cecc8dc45363f9，工作树补丁、文件哈希和必要未跟踪源码保存在 docs/migration/baseline。适配修改登记在各自 source_manifest.json。旧仓库未提供可确认的完整再分发许可，本次本地迁移不授予额外公开发布许可。

前端布局和阶段导航参考 Geological-Map-Digitizer，来源提交和文件哈希见 docs/migration/frontend-reference.json。新界面在本项目实现；参考来源的再分发权利仍需核实。

RapidOCR、ONNX Runtime、PaddlePaddle、PaddleOCR、PaddleX 和 OCR 模型版本、来源、哈希见依赖清单与 models/manifest.json。模型权重不入 Git，本地副本不等于公开再分发授权。RapidOCR/PP-OCR 来源声明 Apache-2.0；Paddle 模型逐项条款待许可原文核对。

Python 许可元数据见 docs/migration/dependency-inventory.json；前端由 frontend/package-lock.json 固定，各安装包 LICENSE/NOTICE 保留在发行目录。元数据缺失时不推定授权。项目本身尚未指定开源许可证，本记录不替代第三方许可原文。
