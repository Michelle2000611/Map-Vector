# 2026年11月8日问题修复验收

本轮实施用户确认的五阶段方案。原始影像、冻结算法和已有用户项目的基线不自动改写；新导入及新任务采用新逻辑。测试目录及测试文件继续被 Git 忽略。

## 输入与任务

识别按钮使用同步 ref 防重入。后端在 BEGIN IMMEDIATE 事务内按项目、资产、输入哈希、管线及局部范围复用相同活动任务；不同范围仍可分别处理，完成后可明确启动新任务。

JPEG/普通影像应用 EXIF 方向；调色板 TIFF 展开 RGB；透明像素对白底显示，同时以二值 alpha 保留有效数据区。GeoTIFF/JP2 读取有效掩膜，拉伸仅统计有效像素，真实黑色像素不因颜色黑而自动排除。新识别输出裁切至有效区，质量检查也采用有效区域。

原文件不变，规范化配置记录方向、波段、显示拉伸、无效像素及 alpha 策略。历史规范化影像不会静默重建，需要重新导入才能采用这些输入修复。

## 导出与审核政策

默认格式为 GPKG。Shapefile 仍受 DBF 字段限制，界面在选择格式时说明，完成后显示实际损失数量；损失清单保留 feature_id、字段、原因与完整值位置 property_manifest.json。存在截断时 attributes_match 为 false，stored_attributes_match 仅表示实际截断后的值通过回读，不能代表无损。

GeoJSON 对文件内原始 JSON 属性作精确比对，再由 GDAL 检查几何和其他属性；时间戳以原始属性为准，避免把 GDAL 转为毫秒的行为误当文件损失，不使用宽松时间误差掩盖真实变化。

兼容放行政策保持旧语义：confirmed、manual_edited、pipeline_complete_unverified、auto_accepted_unverified 可放行。strict_review 只放行当前内容版本已人工确认的文字；草稿输出仍可包含未确认文字。政策存入快照派生导出记录，编辑状态与人工确认不混写。

## 残影与重复文字

完整清理只处理疑似碎面与确定短线，蓝色待核对线和跨框线完整保留；复查只要求目标残影清除，不要求保护线消失。保护线如确需处理，在线图层另行人工核对和隔离。所属文字及框外对象不改，命令支持撤销重做。

多尺度/引擎同位置、同 NFC 文本按重叠范围融合，代表候选保留原始来源证据。相邻不同文字或不同读取不强行合并，分歧留待核对。重复候选采用时，如果当前区域已有同文字对象，返回 OCR_DUPLICATE_TEXT 并给出现有对象 ID；不再静默新增。旧项目现存的重复文字不自动删除。

## 识别和文字排版

冻结 B2c 代码不修改，新增迁移 worker 包装层。新结果通过骨架图恢复漏掉的中性暗色长线、分支和虚线单段，不跨空隙自动接线；在高分 OCR 框内，仅抑制完整包含于框中的暗色笔画连通块，跨框连通块保留。基线文件单独保留，结果报告记录后处理版本、恢复线数量及抑制像素数。

竖排中文由后端持久化为 rotation_deg=0 的逐字纵向 layout_runs，前端、命中范围、快照和导出共用这些字段。上下标继续以原图墨迹和 Unicode 证据分离字号及基线；不能从扫描图保证恢复原字体，也不能把所有 OCR 误字自动改正确。

同一 960×700 样本，旧结果为1211面/8线/16文字，新结果为546面/60线/7文字。新结果无同位置同文重复，窄面独立保留，两侧背景不混并，竖排字为0°纵排。数量变化不是准确率；存在读取分歧的代号仍保留为候选，不宣称所有 A 类问题已经解决。

## 配准与GIS交付

导入页可先选 World 文件和 CRS 文件，再上传原图。后端校验配对、数值、可逆仿射与CRS，将 World 像元中心转换为像元边缘原点，并保留文件与哈希证据。内部配准和外部配准冲突时拒绝自动覆盖。多页 GeoTIFF 用例验证第二页读取自身仿射。

已完成成果增加GIS交付包：固定快照成果、原图、配准旁文件、delivery.json、审核政策、字体/角度/上下标及线型说明、ArcGIS_验收.py。脚本在 ArcGIS Pro Python 中核对图层、ID、数量、CRS及文字排版字段，并可显式添加图层和标签。

本机未检测到 ArcGIS Pro/ArcPy，ArcGIS 实机验收状态保持 not_run。GDAL回读不等于ArcGIS视觉验收；逐字上下标、竖排、虚线齿形及参考比例尺仍需在有许可证的ArcGIS环境对照原图确认。

## 验证证据

- 失败后修复的回归：input-remediation-red、nodata-vector-red、export-remediation-red、cleanup-remediation-red、recognition-remediation-red、ocr-guided-red、external-georef-red、delivery-red 日志。
- 第一轮全量后端175项通过；最终回归以 runtime/remediation-final-backend.log 和 JUnit 为准。
- 新增多页配准定向3项通过，日志 runtime/multipage-georef-green.log。
- 实际影像和管线：runtime/remediation-verification/results.json。
- 浏览器双击1请求/1任务，竖排、政策选择、损失提示与交付链接检查通过：runtime/remediation-verification-browser.log。
- 浏览器截图位于 runtime/remediation-verification，前端构建日志 runtime/remediation-build4.log。

最终回归按批次覆盖181个唯一用例，0失败、0跳过：完整回归177项、当前非OCR回归173项、最终边界批次20项（有重叠，不相加）。六项真实引擎组合用例来自完整回归。新增JPEG EXIF旋转与World仿射同步用例通过。保护线实际浏览器清理、撤销、重做逐对象对账通过；原用户项目修订17，未替换其识别结果。

服务状态：当前8840后端自动重启被审批拒绝（blocked by policy，未返回更具体原因），未终止原服务；代码需后端下次启动加载。隔离8858服务已完成新代码验证。最终GIS交付包及验收脚本结构校验通过，ArcGIS实机状态仍为not_run。
