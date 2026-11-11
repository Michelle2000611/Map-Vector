"""Record actual verification output and hashes for the current local deliverable."""
import hashlib,json,re
from datetime import datetime,timezone
from pathlib import Path
root=Path(__file__).resolve().parents[1]
paths={'backend':'runtime/completion-final.log','browser':'runtime/browser/completion-final.log','frontend_build':'runtime/completion-build.log','pip':'runtime/pip-check.log','paddle_pip':'runtime/pip-paddle-check.log','npm_install':'runtime/npm-ci.log','npm_audit':'runtime/npm-audit.json','real_import':'runtime/migration/real_verify_completion.json','legacy_readback':'runtime/legacy-compatibility/report.json','backup_create':'runtime/backup-create.log','backup_restore':'runtime/backup-restore.log','data_recovery':'runtime/completion-data-report.json','post_review':'runtime/post-review-check.log','typed_port_review':'runtime/review-types.log','explicit_text_target':'runtime/residue-target-check.log'}
outputs={name:(root/path).read_text(encoding='utf-8-sig',errors='replace') for name,path in paths.items()}
backend_match=re.search(r'([0-9]+) passed',outputs['backend']);browser_match=re.search(r'([0-9]+) passed',outputs['browser'])
assert backend_match and ' failed,' not in outputs['backend'] and 'FAILED [' not in outputs['backend']
assert browser_match and ' failed' not in outputs['browser']
assert 'built in' in outputs['frontend_build']
assert 'No broken requirements found' in outputs['pip'] and 'No broken requirements found' in outputs['paddle_pip']
assert json.loads(outputs['npm_audit'])['metadata']['vulnerabilities']['total']==0
report=json.loads(outputs['real_import'])['readback_report'];assert report['unchanged_geometry_checked']==19846 and report['geometry_mismatches']==report['attribute_mismatches']==[]
assert json.loads(outputs['legacy_readback'])['reopened_counts']=={'face':19119,'line':575,'text':152,'isolated_line':0}
records={name:{'rel_path':paths[name],'sha256':hashlib.sha256((root/paths[name]).read_bytes()).hexdigest(),'summary':text[-1000:] if name in ('backend','browser','pip','paddle_pip','frontend_build','npm_install') else 'Structured report retained at the recorded path'} for name,text in outputs.items()}
result={'checked_at':datetime.now(timezone.utc).isoformat(),'backend':{'passed':int(backend_match[1]),'failed':0,'skipped':0},'browser':{'passed':int(browser_match[1]),'failed':0},'npm_vulnerabilities':0,'records':records,'manual_acceptance':'See acceptance-report.md; external GIS, all real U2 locations, native zoom, additional large inputs, cross-platform and redistribution licensing remain unsigned'}
(root/'docs/migration/verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({name:result[name] for name in ('backend','browser','npm_vulnerabilities')}))
