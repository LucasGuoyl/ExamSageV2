# 押题宝 · Windows 学生版

把自己的讲义、往年试卷和答案放进同一门课，在押题宝里提问、追问、打开回答引用的原页，并把想再看的页面加入复习。

## 开始学习

1. 在 Windows 上安装官方 Codex 桌面应用，用自己的 ChatGPT 账号登录。学生启动器会使用 Codex 桌面应用的配套 Python 运行时。模型问答使用该账号可用的 Codex 套餐额度，无需填写 API Key。
2. [下载学生版 ZIP](releases/windows-study-pilot/ExamSage-Study-Windows.zip?raw=1)，全部解压，双击 **开始学习.bat**。如果下载的是整个仓库，请双击仓库根目录 **最新版启动入口** 里的 **启动押题宝.bat**。
3. 第一次使用时选择 **试用弹簧课件**，可以先问“弹簧的伸长量加倍，弹力怎么变？请给出依据”，再追问适用条件。点回答中的出处可以核对页码和原文。
4. 复习自己的考试时，选择导入课件，按讲义、正式试卷、模拟卷和答案标记材料。学生空间保存在当前 Windows 用户的本机。发送问题时，用于回答的相关内容会交给已登录的 Codex。

[学生使用说明](student_kit/学生使用说明.txt) · [四科示例及来源](examples/course-packs/README.md)

## 从源码构建

开发环境使用 Python 3.11 或 3.12。在本目录打开 PowerShell 并执行下列命令。构建器的输出路径须尚未存在。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe tools\build_student_kit.py dist\ExamSage-Study-Windows.zip
Get-FileHash dist\ExamSage-Study-Windows.zip -Algorithm SHA256
```

本次随附学生 ZIP 的 SHA-256 为 `10db564dab529d65bd1b0cddb98fbb7386a70dba73fb15bcc19e9fea986397b6`。同一环境和相同源码可重建。包内的 `kit-files.json` 记录每个交付文件的 SHA-256。

## 开发与验证

- [应用源码](src/examsage/) 包含课程导入、检索、带出处的多轮问答、原页阅读、复习进度和本机工具服务。浏览器学习界面位于 [web/studio](src/examsage/web/studio/)。
- [学生包入口](student_kit/kit.py)、[课程技能](plugin/skills/course-study/SKILL.md)和[构建脚本](tools/build_student_kit.py)共同生成上述下载包。数学排版使用 KaTeX，[许可与来源](src/examsage/web/vendor/katex/)随源码和学生包分发。
- [测试](tests/)包含独立生成材料的回归测试，以及依赖开发者本地授权课程快照的集成测试。公开版附四科教学示例。真实课件、香港保险题库、学生数据，以及带有校方原文的历史标注和测试材料保留在本机。私课专属测试需要相应快照。
- 两个旧版学生 ZIP 作为历史兼容性测试样本保存在 `releases/windows-student-pilot-1` 和 `releases/windows-student-pilot-2`。日常学习请使用上面的最新版下载入口。

在这个目录运行以下命令，可复测学生包分发、四科示例、学生问答流程和原文阅读。测试使用临时学生空间和模拟模型连接。分发测试会启动独立 Python 子进程来模拟收件人的电脑，因此基础解释器也要具备学生运行时的依赖。Windows 开发者可以用 Codex 随附的 Python 创建上面的虚拟环境。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_student_distribution.py tests/test_cross_discipline_demo.py tests/test_student_study_window.py tests/test_study_host.py tests/test_study_reader.py tests/test_study_review.py
```
