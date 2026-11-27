# 保存与原页绑定的学习注记

本机候选现支持把待核查的发现保存为独立注记。注记绑定课程快照、目标页和每份依据的文件哈希；原页文字、源文件和原有审核状态保持不变。保存不等于专家确认，也不自动修正原稿。

这是已授权本机课程所有者的离线流程，不是云端学生写接口或认证服务。没有模型调用、API Key或额外计费。

1. 用当前项目的 `import-courses` 导入课程草稿，打开生成的 `course-reader.html`。
2. 打开来源原页，在“添加学习注记”填写发现。本页自动作为依据，可以选择其他可见页。
3. 点击“加入待保存列表”。列表按课程及快照分开，切换课程不会混合；刷新或关闭页面前须下载请求。
4. 点击“下载审核请求（尚未写入课程）”。下载只产生JSON请求，页面不会声称注记已保存到课程。
5. 用下列本地命令应用请求到新草稿，再导入新库。重新打开新阅读器，在原页下方可见“已保存学习注记”和依据链接。

在 `examsage-v2` 目录中，使用现有Python，替换为实际项目内路径：

```powershell
$env:PYTHONPATH = 'src'
& '..\.worktrees\agent-kernel\.venv\Scripts\python.exe' -m examsage apply-source-reviews --draft data/my-course-draft --library data/my-course-library --course-id my-course --request data/my-course-source-reviews.json --output data/my-course-reviewed-draft
& '..\.worktrees\agent-kernel\.venv\Scripts\python.exe' -m examsage import-courses --source-root data/my-course-reviewed-draft --pack pack.json --output data/my-course-reviewed-library
```

两个输出目录均须不存在。原草稿、原库和原文件不会覆盖。新草稿复制明确列明的源文件及新 `pack.json`，附应用收据；不会复制草稿目录中的无关文件。导入时重新提取源页。

应用命令重新核查课程、工作区、当前快照、来源范围、课程包内容与原文件哈希。陈旧请求、篡改文件、隐藏依据、重复注记ID、已存在输出都会拒绝。当前只支持追加，不能用同ID替换旧意见。

部分来源范围、历史截止导致来源不完整的范围，以及导出库均只读，不提供注记保存入口；应用端也拒绝。这防止保存完整草稿时把已移除的来源重新带回。需从具有完整来源范围的原始导入库进行本机审核。

文字、原图工具和算术复算会携带当前范围内的注记。任何一份目标或依据资料不可访问时，整条依赖它的注记不会出现在新返回结果、新阅读器或新导出中。已经下载的旧HTML/文件不能远程撤回；运行中的本机工具持有启动时的范围副本，这不构成实时撤权服务。

`user_note`、`agent_note`只表示注记类别，不证明作者身份；所有注记固定为 `unverified_note`，不存在自行勾选专家通过的选项。表单内容作为文字显示，不执行其中的HTML或指令。学术内容仍须核对原图、条件与推导。

本轮GRT样例入口：已保存注记的阅读器（本地验收记录）。它使用独立新库，尚未加入已安装的0.2.1插件；打开旧插件不会自动得到本轮改动。逐轮证据见第24–26轮报告（本地验收记录）。
