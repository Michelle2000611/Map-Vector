# 快照列表内部错误与测试输出路径修复

2026-11-10用户反馈页面INTERNAL_ERROR及D盘根目录出现测试文件。本轮分别查证并修复。

## 内部错误

官方8840日志中的请求6686408e-1610-4b38-9591-f5df846bc07b对应GET snapshots。纯SELECT使用ProjectDatabase.transaction()，BEGIN IMMEDIATE竞争写锁，10秒后sqlite3.OperationalError: database is locked，变成500。日志不足以确定当时写锁持有者；不将相邻edit-previews请求当成已确认来源。

app.py仅修改两行：list_snapshots和download_export从transaction()改为既有mode=ro的read()。快照过滤/排序、导出归属/完成状态/路径防逃逸/文件hash校验均保留，真正编辑事务保持原样。此修复不声称缩短写预览事务。

新增两项真实WAL并发回归：持有BEGIN IMMEDIATE及未提交修改时，独立HTTP读请求仍能读取已提交快照、下载已完成成果；结果/修订保持不变。修复前两项均重现database is locked及500，修复后通过。测试仅缩短锁等待时间，不替代真实SQLite连接或HTTP处理。

## D盘根目录来源

只读回收站元数据及历史Codex执行记录证实，先前测试命令显式使用--basetemp=D:/mv-*、D:/mvp-*、D:/tmv/*等目录。发现26个已删除测试目录，今日13:55批次15个，凌晨11个；历史40条显式D根参数。属于我方不合适的测试输出目录选择，未发现生产Settings将工作区错误解析到D根的证据。未恢复、删除或修改D根任何对象。

移除backend/pyproject.toml中依赖cwd的默认basetemp。在backend/tests/conftest.py中，以文件位置固定仓库根，默认输出至runtime/pt/<短pid-随机ID>；不同运行独立，避免并行清理彼此。显式相对参数也以仓库根解析。外部、盘符相对、runtime及其pt容器本身在pytest创建/清理前拒绝；链接解析后仍须在runtime内。验证通过后才创建目标父目录。

路径单测14项通过，实际从不同cwd并行启动两个默认pytest进程的6项断言通过，marker互存、路径不同且均在仓库内；危险CLI参数返回UsageError且外部探测目录未创建。中途较深的自定义测试路径导致SQLite快照文件名258字符、附加journal后超Windows限制；改用项目内短路径后，原真实快照/导出回归通过，没有以跳过功能测试规避。

## 最终验证与服务状态

最终使用默认测试路径运行快照、恢复、导出、并发读取及路径套件，26/26通过。保留既有anyio弃用及像素空间未声明CRS警告。

确认无运行中识别/导出及活动HTTP连接后，更新8840、8841，保留5175。新监听PID分别308、67568；health均ready，原失败snapshots端点均200。实际CUA打开正式保存与导出页，完整加载、无INTERNAL_ERROR、控制台无warn/error；未点击保存、导出或修改对象。

更新前后项目均revision40，feature、face_attribute、line_attribute、text_attribute和operation表的全行摘要完全相同。未写入真实项目业务对象；未提交或推送。验收标签已关闭。

证据根目录：runtime/internal-error-path-20261110。包含read-lock-red.log、read-lock-green.log、final-regression.log、path-audit.md、deleted-test-path-audit.json、path-audit-green.log、path-integration.json、official-before.json、official-after.json、official-services.json、official-ui-snapshot.txt和official-export-page.png。
