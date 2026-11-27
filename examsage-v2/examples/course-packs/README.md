# 跨学科演示课程包

这四份材料用于验证导入、引用、条件继承和证据边界，不是帝国理工或其他学校真实课程，不构成专家教学验收。
数学、物理练习与文学短诗/解读由开发代理原创；历史采用公共领域原文节选及原创分析题。
历史节选来源：[美国国家档案馆转录](https://www.archives.gov/founding-docs/declaration-transcript)，核对日期 2026-11-16。
TXT 中分页符 `\f` 定义本地页码，不能冒充原始书籍或档案页码。所有整理记录导入后保持 candidate。
每个 pack.json 都包含具体来源哈希、学习目标和记录关系，可作为新课程包的格式示例。

在 `examsage-v2` 目录使用现有 Python 批量导入（目标目录必须不存在）：

```powershell
$env:PYTHONPATH = 'src'
& '..\.worktrees\agent-kernel\.venv\Scripts\python.exe' -m examsage import-courses --source-root examples/course-packs --pack physics/pack.json --pack mathematics/pack.json --pack literature/pack.json --pack history/pack.json --output data/my-course-library
```

`--pack` 可重复；每个路径相对显式选择的 `--source-root`，资料文件相对各自的 `pack.json` 所在目录。支持现有TXT/MD（分页符定义页码）、PDF和PPTX提取。生成 `library.json`、每科独立快照、汇总 `review.json` 和 `course-reader.html`。双击阅读器可离线浏览文字、父题条件、参考答案与审核状态；它不调用模型、不显示完整PPTX原图，也不写回审核意见。

整批构建和阅读器生成成功才发布新目录；任何包哈希/格式/页数错误都使整批失败，不覆盖已有库。提取失败页、隐藏页、低文本页和未配对题目会列入审核，不会因此自动成为已审核资料。

新库可直接由现有MCP服务读取，显式指定课程白名单，例如：

```powershell
& '..\.worktrees\agent-kernel\.venv\Scripts\python.exe' -m examsage.mcp_server --library data/my-course-library --courses demo-physics,demo-mathematics,demo-literature,demo-history
```

这是供宿主配置使用的stdio服务入口，不会自动加入已安装插件。当前固定本机拥有者范围，不提供云端学生登录；实际插件更新和远程身份仍单独验收。整条导入流程不需要API Key，也不使用模型额度。
