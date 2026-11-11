from pathlib import Path
root=Path(__file__).resolve().parents[1]
for name in ('docs/migration/implementation-plan.md','docs/migration/implementation-status.md'):
 path=root/name;data=path.read_text(encoding='utf-8').replace('85 项后端测试通过（0 失败、0 跳过），Edge 9 项通过','100 项后端测试通过（0 失败、0 跳过），Edge 20 项通过')
 data+=chr(10)+'本轮代码缺口补齐：domain/ports及归档存储隔离、严格生成类型、Zustand状态和ID索引、项目请求取消、任务耗时/计数/日志、Paddle环境固定、持久后台导出、文字显示框RTree和重叠文字选择。详见 completion-plan.md、architecture-completion.md、completion-code-review.md。'+chr(10)
 path.write_text(data,encoding='utf-8')
for name in ('README.md','docs/migration/running-guide.md'):
 path=root/name;data=path.read_text(encoding='utf-8')
 data=data.replace('备份前完成或取消运行中的识别任务','备份前完成或取消运行中的识别和导出任务')
 if '--default-non-nullable false' not in data:data=data.replace(' -o frontend/src/services/generated.ts。',' -o frontend/src/services/generated.ts --default-non-nullable false。')
 data+=chr(10)+'页面导出使用持久后台任务，受理后可继续编辑；阶段、等待时间、取消与错误在保存导出页展示，完成并回读成功后才出现下载。任务日志可在识别页读取。应用边界和状态契约见 docs/migration/architecture-completion.md。'+chr(10)
 path.write_text(data,encoding='utf-8')
