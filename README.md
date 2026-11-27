# ExamSage V2

ExamSage helps you connect an exam question to the lecture that explains it. Import your lectures, past papers and answer keys into the Windows app, ask about a specific question, and open the original page behind each cited point. Save the page to test yourself on the same material tomorrow.

**[Download the Windows student kit](https://raw.githubusercontent.com/LucasGuoyl/ExamSageV2/main/examsage-v2/releases/windows-study-pilot/ExamSage-Study-Windows.zip)** · [Step-by-step student guide](README.en.md) · [Build and test from source](examsage-v2/README.md)

## Start on Windows

1. Open the official Codex desktop app and sign in with a ChatGPT account that has available Codex usage. ExamSage uses the desktop app’s Python runtime and the Codex allowance included in your plan. You do not need a model API key.
2. Download the student ZIP above. In File Explorer, right-click it, choose **Extract All**, and open the extracted folder. Keep its contents together.
3. Double-click **Start ExamSage.bat**. The study window opens in your browser on this computer. The English launcher opens in English. Use the language selector in the sidebar to switch to Chinese. If you downloaded the full repository, double-click **Start ExamSage.bat** at its root.
4. Choose **Try the spring lesson** on the welcome screen. You can return to it later with **Open spring example** in the sidebar. The example is included in the download, so you can try a complete study session before importing a course.

## Try a question you can check yourself

> What is the spring’s extension under the original load? Show the calculation and cite the page that gives the assumptions.

Send the question with **Ctrl+Enter**. Choose **Compare sources** beside the calculation, then open the source card. The English example has just two pages, so you can judge the answer yourself.

| Look in `lesson.txt` | What you should find |
| --- | --- |
| Page 1 | The load is 10 N and the stiffness is 200 N/m. The spring is in static equilibrium within its linear elastic range. |
| Page 2 | The restoring force balances the load. The extension is `x = F/k = 10/200 = 0.05 m`, or 5 cm. |

Now ask in the **same conversation**, “Keep those assumptions and change only the load to 20 N. What is the new extension?” Page 2 gives **0.10 m**. Open that page and choose **Add to course review**. The next time you launch ExamSage, choose the spring course, open **Course review**, and try the calculation from memory before selecting **Reveal source page**.

## Study your own course

Choose **Import materials** and give the course a name you will recognise tomorrow. For a first import, select a past paper, its answer key if available, and the lecture or handbook that teaches the topic. One import accepts up to **24 files and 64 MiB in total** across PDF, PPTX, TXT and Markdown. Set each file’s role and enter the exam year when you know it. Then choose **Import and start studying**.

| What you want to do | A question to try |
| --- | --- |
| Practise before seeing the answer | “Give me one multiple-choice question from the past paper. Wait for my answer. Then explain the options and cite the question, answer key and relevant lecture page.” |
| Find the assumption behind a solution | “For question 2(b), quote the condition inherited from the start of question 2. Which step uses it? Give the filename and page.” Replace the question number with one from your paper. |
| Plan revision from past papers | “Which topics should I prioritize for the 2027 exam? Use the earlier papers in this course. Give the years, question numbers and pages, and explain any gaps.” Replace 2027 with your target year. |

**Compare sources** shows the references for one point. **Sources for this question** collects references across the answer. A card marked **Cited in the answer** identifies a page used for that point. **Related material** is a lead you can check, such as a lecture that shares a term with an exam question. Open the original before treating it as support. A revision ranking describes the papers you supplied. Your current syllabus and examiner guidance define the scope of your exam.

## What comes with the download

- **Four teaching examples** cover a physics calculation, a mathematical proof, a literary interpretation and a historical source. The study window opens the spring example directly. The four-subject collection is also available through the optional local Codex demo plugin. [Example materials and source credits](examsage-v2/examples/course-packs/README.md)
- **A local student workspace** keeps imported courses, conversations and review progress under your Windows account. Sending a question passes the question, relevant context and retrieved excerpts to ChatGPT through Codex. Source quotations retain their original language when you switch the interface language. [Your account and files](README.en.md#your-account-and-files) · [Troubleshooting](README.en.md#troubleshooting)
- **Source code and release checks** let you build the student ZIP yourself. The Windows workflow rebuilds it, compares its contents with the published kit and tests the study flow under Python 3.11 and 3.12. [Developer guide](examsage-v2/README.md) · [Windows release checks](https://github.com/LucasGuoyl/ExamSageV2/actions/workflows/student-release.yml)
