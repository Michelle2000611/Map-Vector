# 49 项旧操作承接对照

implemented 表示代码入口已承接；浏览器列明确区分已实际点击和代码核对。真实图原问题均不因本表自动通过。

|旧操作|新接口或命令|页面入口|后端证据|浏览器证据|
|---|---|---|---|---|
|pick|selections|Workbench 选择工具|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|box|selections|Workbench 选择工具|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|group|selections|Workbench 选择工具|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|grow|selections|Workbench 选择工具|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|select_gesture|selections|Workbench 选择工具|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|grow_sel|selections|Workbench 选择工具|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|shrink_sel|selections|Workbench 选择工具|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|recolour|set_feature_color / set_line_width / set_line_role|属性与操作|test_geometry_commands.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|rewidth|set_feature_color / set_line_width / set_line_role|属性与操作|test_geometry_commands.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|regroup|group_features / ungroup_features|逻辑归组 / 拆组|test_geometry_commands.py|advanced.spec.ts remaining legacy commands 页面流程；局部OCR记录与范围对账|
|ungroup_lines|group_features / ungroup_features|逻辑归组 / 拆组|test_geometry_commands.py|advanced.spec.ts remaining legacy commands 页面流程；局部OCR记录与范围对账|
|isolate_lines|isolate_lines / restore_lines|隔离 / 恢复隔离线|test_advanced_geometry.py; test_advanced_apply.py|interaction.spec.ts|
|set_role|set_feature_color / set_line_width / set_line_role|属性与操作|test_geometry_commands.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|apply_legend|set_style / bind_style|图例样式与图层|test_appearance.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|set_style|set_style / bind_style|图例样式与图层|test_appearance.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|join_preview|edit-previews / join_lines / delete_lines / split_line / create_line / line_to_face|线工具与属性|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|join_lines|edit-previews / join_lines / delete_lines / split_line / create_line / line_to_face|线工具与属性|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|delete|edit-previews / join_lines / delete_lines / split_line / create_line / line_to_face|线工具与属性|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|split|edit-previews / join_lines / delete_lines / split_line / create_line / line_to_face|线工具与属性|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|draw|edit-previews / join_lines / delete_lines / split_line / create_line / line_to_face|线工具与属性|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|line_to_face|edit-previews / join_lines / delete_lines / split_line / create_line / line_to_face|线工具与属性|test_geometry_commands.py; test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|merge|merge_adjacent_faces / merge_face_components / feature-lineage / edit-previews|面工具 / 对象来源|test_geometry_commands.py|advanced.spec.ts remaining legacy commands 页面流程；局部OCR记录与范围对账|
|merge_preview|merge_adjacent_faces / merge_face_components / feature-lineage / edit-previews|面工具 / 对象来源|test_geometry_commands.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|merge_groups|merge_adjacent_faces / merge_face_components / feature-lineage / edit-previews|面工具 / 对象来源|test_geometry_commands.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|merge_history|merge_adjacent_faces / merge_face_components / feature-lineage / edit-previews|面工具 / 对象来源|test_geometry_commands.py|advanced.spec.ts remaining legacy commands 页面流程；局部OCR记录与范围对账|
|merge_suggest|merge_adjacent_faces / merge_face_components / feature-lineage / edit-previews|面工具 / 对象来源|test_geometry_commands.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|group_faces|group_features / ungroup_features|逻辑归组 / 拆组|test_geometry_commands.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|ungroup_faces|group_features / ungroup_features|逻辑归组 / 拆组|test_geometry_commands.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|heal_preview|edit-previews / heal_faces|碎面修复刷 / 确认本次编辑|test_advanced_apply.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|heal_apply|edit-previews / heal_faces|碎面修复刷 / 确认本次编辑|test_advanced_apply.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|set_roi|set_roi / roi-audits / roi-previews|质量与范围 / ROI 工具|test_scope_export.py; test_geometry_commands.py|interaction.spec.ts|
|roi_report|set_roi / roi-audits / roi-previews|质量与范围 / ROI 工具|test_scope_export.py; test_geometry_commands.py|interaction.spec.ts|
|roi_clip_preview|set_roi / roi-audits / roi-previews|质量与范围 / ROI 工具|test_scope_export.py; test_geometry_commands.py|interaction.spec.ts|
|split_face_preview|edit-previews / split_faces|预览沿线切面 / 确认本次编辑|test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|split_face_apply|edit-previews / split_faces|预览沿线切面 / 确认本次编辑|test_advanced_geometry.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|text_preview|runs OCR / edit-previews / cleanup_text_residue|局部 OCR / 文字残影 / 确认本次编辑|test_ocr_jobs.py; test_advanced_apply.py; test_text_residue.py|advanced.spec.ts remaining legacy commands 页面流程；局部OCR记录与范围对账|
|text_apply|runs OCR / edit-previews / cleanup_text_residue|局部 OCR / 文字残影 / 确认本次编辑|test_ocr_jobs.py; test_advanced_apply.py; test_text_residue.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|text_residue|runs OCR / edit-previews / cleanup_text_residue|局部 OCR / 文字残影 / 确认本次编辑|test_ocr_jobs.py; test_advanced_apply.py; test_text_residue.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|text_edit|update_text / selections / create_text / delete_text|文字属性 / 点位补字 / 删除所选|test_commands.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|text_pick|update_text / selections / create_text / delete_text|文字属性 / 点位补字 / 删除所选|test_commands.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|text_add|update_text / selections / create_text / delete_text|文字属性 / 点位补字 / 删除所选|test_commands.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|text_delete|update_text / selections / create_text / delete_text|文字属性 / 点位补字 / 删除所选|test_commands.py|advanced.spec.ts 实际页面操作（合成拓扑/文字样本）|
|restore_residue|isolate_lines / restore_lines|隔离 / 恢复隔离线|test_advanced_geometry.py; test_advanced_apply.py|interaction.spec.ts|
|review_classify|classify_review / reviews / confirm_text / skip_text|文字审核 / 按基线风险分流|test_review_routing.py; test_ocr.py|advanced.spec.ts remaining legacy commands 页面流程；局部OCR记录与范围对账|
|review_queue|classify_review / reviews / confirm_text / skip_text|文字审核 / 按基线风险分流|test_review_routing.py; test_ocr.py|advanced.spec.ts remaining legacy commands 页面流程；局部OCR记录与范围对账|
|review_decide|classify_review / reviews / confirm_text / skip_text|文字审核 / 按基线风险分流|test_review_routing.py; test_ocr.py|advanced.spec.ts remaining legacy commands 页面流程；局部OCR记录与范围对账|
|undo|undo / redo / snapshots|撤销 / 重做 / 保存工作快照|test_commands.py; test_snapshots.py|workflow.spec.ts|
|redo|undo / redo / snapshots|撤销 / 重做 / 保存工作快照|test_commands.py; test_snapshots.py|workflow.spec.ts|
|save|undo / redo / snapshots|撤销 / 重做 / 保存工作快照|test_commands.py; test_snapshots.py|workflow.spec.ts|
