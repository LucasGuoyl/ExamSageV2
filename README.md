# ExamSage V2

Study with your own lecture notes, past papers and answer keys. Ask a question, follow up in the same conversation and open the original page behind each cited point. ExamSage runs on Windows and uses the Codex usage included in your existing ChatGPT plan.

## Start studying

1. Sign in to the official Codex desktop app on Windows with your ChatGPT account. The student app uses the Python runtime supplied with Codex. You do not need a model API key.
2. Download the student ZIP and extract **all files** to a folder you can write to. [Download the Windows student kit](https://raw.githubusercontent.com/LucasGuoyl/ExamSageV2/main/examsage-v2/releases/windows-study-pilot/ExamSage-Study-Windows.zip)
3. Double-click **Start ExamSage.bat**. The English study window opens in your browser. You can switch between English and Chinese in the sidebar. If you downloaded the entire repository, use the launcher of the same name at its root.
4. Choose the spring example and ask “What is the original load, and how far does the spring extend? Cite both pages.” Open **Compare sources** beside the calculation to check the original. Use **Import materials** when you are ready to study your own course.

Use **Sources for this question** to see which exam and lecture pages support the whole answer. Open a page and select **Add to course review** to practise it again the next time you launch the app. [Student guide](README.en.md)

## What is included

- Four teaching examples cover physics, mathematics, literature and history. Original source text retains its language, so quotations and page references can be checked against the material you imported. [Example course packs and source credits](examsage-v2/examples/course-packs/README.md)
- Courses, chat history and review progress are stored for the current Windows user. When you ask a question, the relevant excerpts and conversation context are sent to ChatGPT through Codex. [Downloadable kit instructions](examsage-v2/student_kit/STUDENT-GUIDE.txt)
- The public repository contains the application source, release builder and tests. GitHub Actions rebuilds the kit and checks student workflows on Windows with Python 3.11 and 3.12. Additional integration tests use licensed course snapshots on the maintainer’s machine. [Developer guide](examsage-v2/README.md) · [Windows release checks](https://github.com/LucasGuoyl/ExamSageV2/actions/workflows/student-release.yml)
