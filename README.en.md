# ExamSage V2 Student README

ExamSage turns your lecture notes, past papers and answer keys into a course you can question. Each answer can link back to the page that supports it. The Windows student app opens in your browser and uses your existing ChatGPT plan through the official Codex desktop app.

## Start on Windows

1. Open the official Codex desktop app and sign in with your ChatGPT account. ExamSage uses the Python runtime supplied with Codex and the Codex usage available on your plan. No model API key is required.
2. Download the student ZIP and **extract all files** to a folder you can write to. [Download the Windows student kit](https://raw.githubusercontent.com/LucasGuoyl/ExamSageV2/main/examsage-v2/releases/windows-study-pilot/ExamSage-Study-Windows.zip)
3. Double-click `开始学习.bat` (Start studying). If you downloaded the entire repository, open `最新版启动入口` and double-click `启动押题宝.bat` instead.

## Try one question and check the answer

On the welcome screen, click **试用弹簧课件** (Try the spring lesson). You can also open it from the sidebar with **打开弹簧示例**. Paste this question and press **Ctrl+Enter** to send. **Enter** starts a new line.

> What is the spring’s extension under the original load? Cite the page with the assumptions and the page with the calculation.

In `lesson.txt`, **page 1** gives the stiffness (200 N/m), the load (10 N) and the assumption of static equilibrium in the linear elastic range. **Page 2** gives the calculation, `x = F/k = 0.05 m`. In the same conversation, ask “What if the load increases to 20 N under the same assumptions?” You can check the result, **0.10 m**, on page 2.

## Study your own course

Choose **导入课件** (Import materials). Enter the course name and subject, then select the files for one course. Each import accepts up to **24 files and 64 MiB in total** across PDF, PPTX, TXT and Markdown. Label each file by its role and enter the exam year when known. Distinguishing official papers, mock papers and answer keys makes comparisons across years more useful. Click **导入并开始学习** (Import and start studying).

To practise before seeing the answer, try this prompt.

> Give me one multiple-choice question from the paper I imported. Wait for my answer. Then explain each option and show me the question page and the handbook page that supports the answer.

For revision planning, ask “Which topics recur in my past papers? Give the years, question numbers and pages. Which papers or questions could you not classify?” Use the result to decide what to practise. Your course syllabus sets the exam scope.

## Trace an answer back to the page

Click **对照出处** (Compare sources) beside an individual point. The panel distinguishes evidence cited for that point from related material on the same topic. Use **本题出处总览** (Sources for this question) to see the past-paper and lecture references across the whole answer.

Open a source card to read the passage in context. Page numbers count from the first page of the file, so they can differ from printed page numbers. For a graph or formula, open the original page image when available and zoom in. If the passage cannot be read, ask which part of the answer can still be verified.

## Resume tomorrow

On an original page, select **加入本课复习** (Add to course review). Next time, launch the app from the same Windows account, choose the course and open **本课复习** (Course review). Try answering from memory, then select **揭开原页核对** (Reveal the source page). Mark it **还要练** (Practise again) or **已掌握这页** (Learned). You can also reopen the earlier conversation from the sidebar.

## Account and storage

Your imported courses, conversations and review progress are stored under `%LOCALAPPDATA%\ExamSage\student-workspaces` for the current Windows user. When you send a question, Codex sends the question, relevant conversation context and retrieved course excerpts to ChatGPT. If the app reports a missing runtime, check the Codex desktop installation. If it reports a usage limit, check your signed-in account’s Codex allowance.

## Optional use inside Codex

To ask questions in a native Codex chat, run `1-登记学生插件.bat` from the extracted folder. In the Codex plugin directory, select **押题宝学生版**, then install and enable **押题宝 · 我的课程** (My courses) and **押题宝 · 四科演示** (Four subject demos). Use `2-导入自己的课件.bat` to import your files through the plugin workflow. The **Start studying** launcher works independently of this optional setup.

Developers can find the package build command, test instructions and Windows workflow in the repository. [Source and build instructions](https://github.com/LucasGuoyl/ExamSageV2/blob/main/examsage-v2/README.md) · [Windows release checks](https://github.com/LucasGuoyl/ExamSageV2/actions/workflows/student-release.yml)
