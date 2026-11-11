# Map-Vector

依据 20261106/Map-Vector_新项目迁移技术设计.docx 实施的独立迁移工程。FastAPI 提供 /api，React 提供项目与原图、识别任务、编辑与审核、质量与范围、保存与导出五步界面。每个项目的 state/project.sqlite 是编辑真值；GIS 输出是固定快照的派生成果。

## Windows 安装和启动

需要 Python 3.11 和 Node.js。API、B2c、RapidOCR 共用根目录 .venv，安装缓存也进入 .venv。首次执行 powershell -ExecutionPolicy Bypass -File scripts/install.ps1；完成后执行 powershell -ExecutionPolicy Bypass -File scripts/start.ps1，或双击 scripts/start.cmd。

打开 http://127.0.0.1:8840/projects；接口文档 /docs，健康检查 /api/health。MAPVECTOR_API_PORT 可改端口，启动器检查占用。PyCharm 选择 .venv/Scripts/python.exe，以 mapvector 模块运行，工作目录为项目根目录。

Paddle 与主环境有 NumPy 冲突，使用 .venv-ocr-paddle 隔离，安装脚本 scripts/install-paddle.ps1。此环境不安装 API 包。模型不自动下载；models/rapid、models/paddle 的 manifest.json 固定所需文件和 SHA256。缺模型或哈希不符时诊断报错；可选 OCR 失败保留已完成的面线工件。

执行 .venv/Scripts/python.exe scripts/diagnose.py 查看解释器、依赖、模型、前端状态。前端修改后执行 npm --prefix frontend run build；开发执行 npm --prefix frontend run dev。

## 使用和存储

上传后可按页和 DPI 生成独立资产。采用另一资产、采用识别结果、恢复快照均保留历史。后台识别不会覆盖人工工作。文字内容修改、明确确认、自动放行、残影清理和隔离分别记录。

未完成审核可保存工作草稿。正式导出使用 baseline_compatible 政策，并单列审核状态与依据。像素坐标原点为左上角，x 向右、y 向下；像素项目可输出 GPKG/SHP/pixel_json。GeoJSON 需要配准并转换到 WGS84。

ROI 支持整图、保留跨界和实际裁切；输出读取所选快照中的 ROI。SHP ZIP 包含确定短字段映射、完整属性和来源关联清单。工作数据位于 workspaces/default；临时文件、日志、运行证据位于 runtime。数据、模型权重和虚拟环境均不入 Git。旧工程只读。

## 迁移和备份

检查：.venv/Scripts/python.exe scripts/migrate.py dry-run <旧项目目录> --output runtime/migration/dry-run.json。将 dry-run 改为 import 生成新项目。verify <新项目目录> 检查 SQLite、工件哈希和几何；scan、report 同样可用。来源不能证明的工程进入隔离报告。

备份：.venv/Scripts/python.exe scripts/backup.py create <新项目目录> <备份ZIP>。恢复：.venv/Scripts/python.exe scripts/backup.py restore <备份ZIP> <独立目标工作区>。目标存在时拒绝覆盖，备份前完成或取消运行中的识别和导出任务。

明确交回旧编辑器：.venv/Scripts/python.exe scripts/export_legacy.py <新项目目录> <snapshot_id> <独立输出.gpkg>，默认草稿，--formal 使用原审核门禁，--scope 支持 full/keep_crossing/clip。兼容清单保留稳定 ID 和旧版无法表达的字段；输出存在时拒绝覆盖。

## 验证

后端：.venv/Scripts/python.exe -m pytest backend/tests -q。前端：npm --prefix frontend run build；服务启动后 npm --prefix frontend run test:e2e。浏览器使用本机 Edge，样本由测试自身提供。

契约：.venv/Scripts/python.exe scripts/generate_contracts.py；再执行 frontend/node_modules/.bin/openapi-typescript.cmd contracts/openapi.json -o frontend/src/services/generated.ts --default-non-nullable false。

逐项迁移和证据见 docs/migration/acceptance-report.md 与 implementation-plan.md。自动验证不替代真实错误整改和外部 GIS 人工验收。许可证边界见 NOTICE.md。

页面导出使用持久后台任务，受理后可继续编辑；阶段、等待时间、取消与错误在保存导出页展示，完成并回读成功后才出现下载。任务日志可在识别页读取。应用边界和状态契约见 docs/migration/architecture-completion.md。
