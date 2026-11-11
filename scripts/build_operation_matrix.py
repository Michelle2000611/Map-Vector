import csv,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
groups=[
 ('pick box group grow select_gesture grow_sel shrink_sel','selections','Workbench 选择工具','test_geometry_commands.py; test_advanced_geometry.py','interaction.spec.ts'),
 ('recolour rewidth set_role','set_feature_color / set_line_width / set_line_role','属性与操作','test_geometry_commands.py','代码入口核对'),
 ('regroup ungroup_lines group_faces ungroup_faces','group_features / ungroup_features','逻辑归组 / 拆组','test_geometry_commands.py','代码入口核对'),
 ('isolate_lines restore_residue','isolate_lines / restore_lines','隔离 / 恢复隔离线','test_advanced_geometry.py; test_advanced_apply.py','interaction.spec.ts'),
 ('apply_legend set_style','set_style / bind_style','图例样式与图层','test_appearance.py; test_advanced_geometry.py','代码入口核对'),
 ('join_preview join_lines delete split draw line_to_face','edit-previews / join_lines / delete_lines / split_line / create_line / line_to_face','线工具与属性','test_geometry_commands.py; test_advanced_geometry.py','interaction.spec.ts 覆盖补画及隔离；其余未逐项点击'),
 ('merge merge_preview merge_groups merge_history merge_suggest','merge_adjacent_faces / merge_face_components / feature-lineage / edit-previews','面工具 / 对象来源','test_geometry_commands.py','代码入口核对'),
 ('heal_preview heal_apply','edit-previews / heal_faces','碎面修复刷 / 确认本次编辑','test_advanced_apply.py','代码入口核对'),
 ('set_roi roi_report roi_clip_preview','set_roi / roi-audits / roi-previews','质量与范围 / ROI 工具','test_scope_export.py; test_geometry_commands.py','interaction.spec.ts'),
 ('split_face_preview split_face_apply','edit-previews / split_faces','预览沿线切面 / 确认本次编辑','test_advanced_geometry.py','代码入口核对'),
 ('text_preview text_apply text_residue','runs OCR / edit-previews / cleanup_text_residue','局部 OCR / 文字残影 / 确认本次编辑','test_ocr_jobs.py; test_advanced_apply.py; test_text_residue.py','代码入口核对'),
 ('text_edit text_pick text_add text_delete','update_text / selections / create_text / delete_text','文字属性 / 点位补字 / 删除所选','test_commands.py','workflow.spec.ts; interaction.spec.ts'),
 ('review_classify review_queue review_decide','classify_review / reviews / confirm_text / skip_text','文字审核 / 按基线风险分流','test_review_routing.py; test_ocr.py','interaction.spec.ts'),
 ('undo redo save','undo / redo / snapshots','撤销 / 重做 / 保存工作快照','test_commands.py; test_snapshots.py','workflow.spec.ts'),
]
mapping={operation:(api,ui,unit,browser) for operations,api,ui,unit,browser in groups for operation in operations.split()}
rows=list(csv.DictReader((root/'20261106/功能迁移对照.csv').open(encoding='utf-8-sig')))
assert len(rows)==49 and len(mapping)==49
result=[]
for row in rows:
    name=row['旧操作'];api,ui,unit,browser=mapping[name]
    advanced=set('pick box group grow select_gesture grow_sel shrink_sel recolour rewidth set_role group_faces ungroup_faces apply_legend set_style join_preview join_lines delete split draw line_to_face merge_preview merge_groups merge_suggest heal_preview heal_apply split_face_preview split_face_apply text_apply text_residue text_edit text_pick text_add text_delete'.split())
    if name in advanced:browser='advanced.spec.ts 实际页面操作（合成拓扑/文字样本）'
    if name in ('merge','merge_history','text_preview','regroup','ungroup_lines','review_classify','review_queue','review_decide'):browser='advanced.spec.ts remaining legacy commands 页面流程；局部OCR记录与范围对账'
    result.append({'legacy_operation':name,'implementation':api,'ui_entry':ui,'backend_evidence':unit,'browser_evidence':browser,'status':'implemented','real_issue_acceptance':'manual_pending'})
out=root/'docs/migration/operation-matrix.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# 49 项旧操作承接对照','','implemented 表示代码入口已承接；浏览器列明确区分已实际点击和代码核对。真实图原问题均不因本表自动通过。','','|旧操作|新接口或命令|页面入口|后端证据|浏览器证据|','|---|---|---|---|---|']
for row in result:lines.append('|'+ '|'.join(row[key] for key in ('legacy_operation','implementation','ui_entry','backend_evidence','browser_evidence'))+'|')
(root/'docs/migration/operation-matrix.md').write_text(chr(10).join(lines)+chr(10),encoding='utf-8')
print('49 operations mapped')
