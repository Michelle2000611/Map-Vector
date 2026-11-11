# 属性输入与按钮紧凑化验收

删除“在画布选择x对象后编辑属性。”，不补替代提示。标题字体从Ant主题fontFamily继承，与工具实际字体、16px/600完全相同，不仅比较字号。

外观输入每行两列，线字段为颜色/宽度（px）/用途；文字内容与颜色、字号与角度、X/Y和只读W/H按两列，原图和位置分组跨行。复用原PropertyNumber/Color/Field与草稿hook，混合值、无效原始输入、IME和提交逻辑不改变。辅助aria线宽/线用途保留兼容，不把辅助标识误当业务字段。

常规属性按钮144×32px，长文案不换行、不全宽；表格行内操作保持原紧凑尺寸。双图原右栏较窄时按钮自动单列，输入容器不足340px降单列保证可读；不制造横向页面溢出。没有改工具栏或线/面/文字检查算法。

删除从对象来源页迁到独立底部：单图右侧Frame footer、双图原属性Card footer、手机属性Drawer footer，切页签可用。deleteAction只有一个定义，条件保证各模式唯一可见按钮；原数量文案、danger、确认Modal、草稿flush、命令及撤销语义保持。单图footer margin-top:auto、比较Card flex确保无候选/收起检查时也贴面板底部，不只是普通文档流。底部有实际空间，不覆盖候选列表按钮。

## 验证

新增浏览器5/5（runtime/property-compact-20261111/browser/verified/results.json）：空提示/实际字体、字段双列/按钮尺寸、文字坐标/无效草稿保留、删除三模式及确认取消、收起检查后footer底部/窄栏按钮不溢出。初红确证旧提示仍在，后续旧34px min-height造成尺寸红已修为32，Modal取消两汉字accessible自动间隔按真实语义匹配。第五例初隔离线fixture未含隔离对象，修为收起线检查等价无可见内容状态后验证底部贴合；原红记录保留。

既有回归29/29（object8+folds7+autosave9+tabs5）通过，保留原保存、IME、无效草稿、混合批量、来源、删除与失败重试断言。仅UI名称和删除可见范围定位适配，没有删断言或跳过功能。

独立review指出footer流位置与窄栏固定双按钮两问题，已修并补末例真实尺寸断言；最终只读审查无阻塞，报告与源码hash在review/。

最终tsc及生产构建通过：index-Dhxej2hZ.js、index-BKtMxjiO.css。Ant use-client及既有包体提示保留，无编译错误。

## 实际页面

正式8840只读验收使用现有线数据：唯一POST为纯查询selections，所有编辑写请求拦截拒绝；未执行检查、修复、保存或删除。实际字段宽各325px，同y且高32px；删除144×32px；工具与属性标题fontFamily/size/weight相同；页面errors=[]、writes=[]。

before/after两个项目修订为4和45，feature/face_attribute/line_attribute/text_attribute/operation全行摘要一致。官方health ready，HTML引用最终JS/CSS，无需重启后端；没有提交/推送。全部证据在仓库runtime/property-compact-20261111，截图line-properties-final.png、live-verification.json、service-final.json、business-before/after.json。
