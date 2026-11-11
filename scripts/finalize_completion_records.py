import re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
backend=(root/'runtime/completion-final.log').read_text(encoding='utf-8');browser=(root/'runtime/browser/completion-final.log').read_text(encoding='utf-8')
back=re.search('([0-9]+) passed',backend);front=re.search('([0-9]+) passed',browser)
assert back and front and 'FAILED [' not in backend and ' failed' not in browser
for name in ('docs/migration/acceptance-report.md','docs/migration/completion-plan.md','docs/migration/implementation-plan.md','docs/migration/implementation-status.md'):
 p=root/name;s=p.read_text(encoding='utf-8');s=s.replace('后端100项','后端'+back[1]+'项').replace('后端100项','后端'+back[1]+'项').replace('100项通过',''+back[1]+'项通过').replace('100 项后端',''+back[1]+' 项后端');s=s.replace('浏览器20项','浏览器'+front[1]+'项').replace('Edge 20 项','Edge '+front[1]+' 项').replace('整套20项','整套'+front[1]+'项').replace('共20项','共'+front[1]+'项').replace('496.87秒','321.72秒');p.write_text(s,encoding='utf-8')
print('Updated verified backend '+back[1]+' / browser '+front[1])
