# ExamSage V2 student guide

ExamSage helps you study a course using material you can check. Ask a question, read the exact page cited in the answer, and save that page for your next revision session.

## Open the app

1. On Windows, sign in to the official Codex desktop app with your ChatGPT account. ExamSage uses the Python runtime supplied with Codex and the Codex allowance included in your plan. No model API key is required.
2. Extract the entire student ZIP to a writable folder and double-click **Start ExamSage.bat**. If you downloaded the full repository, use **Start ExamSage.bat** at its root. [Download the Windows student kit](https://raw.githubusercontent.com/LucasGuoyl/ExamSageV2/main/examsage-v2/releases/windows-study-pilot/ExamSage-Study-Windows.zip)
3. The study window opens in your browser on this computer. The English launcher starts in English. Use the sidebar language selector to switch between English and Chinese. Imported source pages and quotations retain their original wording.

## Try a question and a follow-up

Choose **Open spring example** in the sidebar. Paste the following question. Press **Ctrl+Enter** to send it, or click the send arrow. **Enter** starts a new line.

> What is the spring’s extension under the original load? Cite the page with the assumptions and the page with the calculation.

In the two-page `lesson.txt`, page 1 gives the stiffness of 200 N/m, the original load of 10 N and the conditions of static equilibrium within the linear elastic range. Page 2 gives `x = F/k = 0.05 m`. In the same conversation ask “Keep those assumptions and change only the force to 20 N. What changes?” Page 2 also shows the revised extension of **0.10 m**.

## Import your course

Choose **Import materials**, enter the course title and subject, then select files for that course. One import accepts **up to 24 files totalling 64 MiB**. Supported formats are PDF, PPTX, TXT and Markdown. Choose a role for each file, such as lecture material, past paper, mock paper or answer key. Enter the exam year when known and start the import.

For exam practice, try this prompt.

> Give me one multiple-choice question from the paper I imported. Wait for my answer, then explain each option. Give the page where the question appears and the handbook page that supports the answer.

To decide what to practise, ask “Which topics recur in these past papers? Give the years, question numbers and pages. Which questions could you not classify?” Check the findings against the syllabus for your exam. The available papers show what was examined in earlier years.

## Check exactly what supports an answer

Select **Compare sources** beside one point. The panel shows the evidence actually cited there and, separately, related material worth exploring. Select **Sources for this question** to see exam and lecture references for the complete answer.

Open a source card or a page reference to read the passage in context. File pages count from 1 and can differ from printed page numbers. For a graph or equation, switch to the original PDF image or an available slide rendering and zoom in. A static slide shows one combined image. If extraction failed or the relevant figure is missing, ask which part of the answer can still be verified. **Alt+R** opens the source reader and **Alt+Q** returns to the question box.

## Continue tomorrow

Open a cited page and select **Add to course review**. Next time, launch ExamSage under the same Windows account, choose the course and open **Course review**. Try answering from memory before selecting **Reveal source page**. Select **Practise again** or **Mark as learned**. Your saved question and self-assessment carry over. The draft answer you type while practising lasts for that card session. To resume the earlier conversation, open it from the sidebar.

## Your account and files

ExamSage stores imported courses, conversations and review progress under `%LOCALAPPDATA%\ExamSage\student-workspaces`. People sharing the same Windows login share that local student space. When you send a question, Codex sends the question, relevant conversation context and retrieved excerpts to ChatGPT. The account controls the available quota. If ExamSage reports a missing runtime, check your official Codex desktop installation. If it cannot confirm a usable subscription, check the signed-in account and its allowance.

## Optional use inside a Codex chat

Run **Register Student Plugins.bat** from the extracted kit. Open the registered ExamSage student marketplace in the Codex plugin directory and install and enable the personal-course and four-subject demo plugins. Run **Import Course Files.bat** to import files for the plugin. If the tools do not appear, fully close and reopen Codex. Keep the extracted folder because registration refers to files on this computer. The student app itself opens directly from **Start ExamSage.bat**.

[Developer and build instructions](examsage-v2/README.md) · [Windows release checks](https://github.com/LucasGuoyl/ExamSageV2/actions/workflows/student-release.yml)
