# ExamSage V2 student guide

This guide takes you from a fresh Windows download to a second revision session. Start with the spring example to learn how the citations work, then repeat the same steps with one of your own past papers.

## Open the app

1. Open the official Codex desktop app on Windows and sign in with your ChatGPT account. For new answers, you need internet access and available Codex usage in your plan. The student kit uses the Python runtime supplied with Codex. You do not need a model API key.
2. Download the student ZIP and use **Extract All** in File Explorer. Pick a folder you can write to and keep all the extracted files together. [Download the Windows student kit](https://raw.githubusercontent.com/LucasGuoyl/ExamSageV2/main/examsage-v2/releases/windows-study-pilot/ExamSage-Study-Windows.zip)
3. Double-click **Start ExamSage.bat** in that folder. If you downloaded the full repository, use the launcher with the same name at its root. The study window opens in your browser on this computer.
4. The sidebar holds the course selector, conversations, course review and language selector. Switching to English changes the controls. It preserves the wording of imported pages, saved questions and previous answers.

## Try a question and a follow-up

Choose **Try the spring lesson** on the welcome screen or **Open spring example** in the sidebar. Paste the following question. Press **Ctrl+Enter** to send, or click the send arrow. **Enter** starts a new line.

> What is the spring’s extension under the original load? Cite the page with the assumptions and the page with the calculation.

Open **Compare sources** beside the calculation and select a source card. Look for two different pieces of evidence in `lesson.txt`.

- **Page 1 gives the conditions.** The spring is in static equilibrium within its linear elastic range. Its stiffness is 200 N/m and the applied force is 10 N. These conditions tell you when the calculation is valid.
- **Page 2 gives the derivation.** The restoring force is `−kx`. Balancing it against the applied force gives `x = F/k = 10/200 = 0.05 m`. The units reduce to metres.

In the same conversation, ask “Keep the stiffness and assumptions from before. What happens if the force increases to 20 N?” Page 2 also gives the new extension, **0.10 m**. This follow-up lets you check whether the answer carried forward the right assumptions and changed only the load.

## Import a past paper with the materials needed to check it

Choose **Import materials**. Enter a course title and subject. For a first practice session, select a question paper, its matching answer key if you have it, and one lecture or handbook covering the topic. Each import accepts **1–24 files totalling up to 64 MiB**. The supported extensions are `.pdf`, `.pptx`, `.txt` and `.md`.

| File you have | Material type to choose | Detail worth recording |
| --- | --- | --- |
| The paper sat by students | **Past paper** | Enter the sitting year if known. |
| The published solutions or marking scheme | **Answer key** | Use the year of the corresponding paper when known. Keep the question number and subpart visible in the source. |
| A practice paper written for revision | **Mock exam** | Enter its year if known. This label keeps it distinct from a past sitting. |
| Lecture slides, teaching notes or a handbook | **Lecture notes** | Include pages explaining the assumptions, terminology or rule used by the question. |
| Additional material outside these roles | **Other** | A descriptive filename will help you recognise it in a citation. |

Leave uncertain years blank. Choose **Import and start studying** and check the selected course name before asking. To practise without seeing the solution immediately, send this as your first turn.

> Give me one multiple-choice question from the past paper I imported. Wait for my answer. After I reply, explain each option. Give the filename and page for the question, any official answer you find, and the handbook rule that supports the explanation.

After choosing an option, send your letter and your reason. If there is no official key in your course, ask which parts of the explanation can be inferred from the handbook and which remain unverified.

## Trace one claim through the paper and the lecture

1. Pick one statement to check, such as “option B follows from this definition.” Select **Compare sources** beside that point. Use **Sources for this question** when you want the references across the whole answer.
2. Read the card label. **Cited in the answer** means the answer used that page. **Related material** identifies another page worth checking. A shared term can connect two passages even when their assumptions differ.
3. Open the paper page and check the exact question and subpart. For a question such as 2(b), read the start of question 2 as well. Then open the key or lecture page and check whether it supports the specific option, formula or rule.
4. Use the filename and **file page** to find the same passage in your own copy. Page numbering starts at the first page of the file, including any cover. A printed footer can show a different number. For charts or equations, choose **View page image** when available and zoom in. If the figure is unreadable, treat that part of the conclusion as unresolved.

**Alt+R** opens the source reader and **Alt+Q** returns to the question box. A useful follow-up when the matching lecture page is ambiguous is “Quote the words connecting this rule to question 2(b). Which condition, if any, still needs to be checked?”

## Use past papers to choose what to practise

Give one target year and identify the evidence you want. For example, “Which top 3 topics should I prioritize for the 2027 exam? Give the exam years, question numbers and source pages.” Replace 2027 with the sitting you are studying for. Open one cited question to see what skill it actually tests.

For a historical check, add “Use only sources available before the exam.” This stricter analysis needs evidence of when materials were available. A paper’s cover year alone cannot establish that date. If the result is sparse, ask which papers or questions could not be classified. Topic frequencies describe the available past papers. They provide neither an official syllabus nor the probability that a topic will appear next year.

## Continue tomorrow

On a source page you want to remember, choose **Add to course review**. The next time you open ExamSage under the same Windows account, select the course and open **Course review**.

1. Open the saved page from **To review**. Try retrieving the answer from memory. For the spring, explain why force divided by stiffness has units of length.
2. Select **Reveal source page** and compare the original with what you recalled. You can edit the question you want to see next time.
3. Choose **Practise again** or **Mark as learned**. You can revisit learned pages under **Learned**. The saved page, review question and self-assessment persist. Text typed into the recall box lasts for that card session.

To continue the original discussion instead, open the earlier conversation from the sidebar and send your follow-up there.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| The launcher cannot find the student kit or runtime | Extract the entire ZIP, then launch from the extracted folder. If the message names the Codex desktop Python runtime, open the official Codex desktop app and check its installation. |
| An older study window is using the workspace | Close the older window, allow up to ten minutes for its local service to exit, then double-click **Start ExamSage.bat** again. |
| A course opens but a new answer cannot start | Check your internet connection, your ChatGPT sign-in in Codex and the account’s available Codex allowance. The model request stops if included usage cannot be verified or has been exhausted. |
| The result links to a lecture but you wanted a past-paper question | Check the selected course, confirm that the paper was included and labelled **Past paper**, and ask again with its year and exact question or subquestion number. |
| The file page differs from a printed number, or a formula looks incomplete | Use the filename and file-page count to locate the passage. Open **View page image** when offered. If needed, compare the same page in the original PDF or slides. |
| Yesterday’s saved page seems missing | Reopen the same Windows account and course. Check both **To review** and **Learned**. Previous chat messages are in the conversation sidebar. |

## Your account and files

Imported courses, conversations and review progress live under `%LOCALAPPDATA%\ExamSage\student-workspaces`. People sharing a Windows login share that student space. When you send a question, the Codex host sends the question, relevant conversation context and retrieved course excerpts to ChatGPT. Use materials you are authorised to study this way.

For offline reading, the **Import Course Files.bat** workflow gives you a local reader address after a successful import. Open that address to inspect the imported material. Generating a new model answer requires the signed-in Codex connection.

## Optional course tools inside Codex

The main study window opens directly from **Start ExamSage.bat**. If you also want to ask about a course in a native Codex chat, keep the extracted kit in a permanent folder and follow these steps.

1. Run **Register Student Plugins.bat**. In the Codex plugin directory, open **ExamSage Student**, then install and enable **ExamSage · My courses** and **ExamSage · Four subject demos**. Fully exit and reopen Codex if the tools do not appear.
2. Use **Import Course Files.bat** to add your own course through the file picker. For the demo plugin, choose among physics, mathematics, literature and history. [Demo lessons and suggested questions](examsage-v2/examples/course-packs/README.md)
3. In a Codex chat with the course tools enabled, ask “List the courses available to me.” Choose one, then ask for a passage by filename and page. Keep the extracted folder in place because the plugin registration refers to files there.

[Repository home](README.md) · [Developer and build instructions](examsage-v2/README.md) · [Windows release checks](https://github.com/LucasGuoyl/ExamSageV2/actions/workflows/student-release.yml)
