# ExamSageV2

**押题宝学生版**让你用自己的课件、历年试卷和答案复习。在回答里点开出处，可以看到引用的原文和页码；收藏后，下次打开还能接着复习。

## 下载与启动

1. 在 Windows 上用自己的 ChatGPT 账号登录官方 Codex 桌面应用，确保配套 Python 运行时已安装。押题宝通过本机 Codex 使用该账号可用的套餐额度，无需配置模型 API Key。
2. [下载 Windows 学生包](https://raw.githubusercontent.com/LucasGuoyl/ExamSageV2/main/examsage-v2/releases/windows-study-pilot/ExamSage-Study-Windows.zip)，全部解压后双击 **开始学习.bat**。如果下载了整个仓库，双击 [最新版启动入口](最新版启动入口/) 里的 **启动押题宝.bat**。
3. 第一次可以点 **试用弹簧课件**，问“弹簧伸长量加倍时，弹力怎么变？”，再追问适用条件。点开回答引用的原页，核对讲义里的表述。

[新版源码与开发说明](examsage-v2/README.md) · [学生使用说明](examsage-v2/student_kit/学生使用说明.txt) · [四科演示及来源](examsage-v2/examples/course-packs/README.md)

## 发布验证

每次推送到 `main` 后，GitHub Actions 会在 Windows 上使用 Python 3.11 和 3.12 从源码重建学生 ZIP，核对包内文件、校验清单和双击启动目录，再运行学生分发、四科示例、问答、原文阅读和复习测试。问答测试使用模拟模型连接。[查看学生版验收结果](https://github.com/LucasGuoyl/ExamSageV2/actions/workflows/student-release.yml)

完整测试还覆盖授权课程的真实版本、勘误及试题来源。这部分在持有相应课程资料的本机运行。公开仓库附带四科示例，学生可以自行导入有权使用的材料。
