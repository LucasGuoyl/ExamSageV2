# ExamSage V2 development guide

This directory contains the course importer, evidence retrieval tools, conversation host and browser study window. To start studying immediately, extract the Windows student kit and run **Start ExamSage.bat**. The launcher uses the official Codex desktop runtime and the signed-in student’s ChatGPT plan. [Download the Windows student kit](releases/windows-study-pilot/ExamSage-Study-Windows.zip?raw=1) · [Student guide](../README.en.md)

## Build the student ZIP

Use Python 3.11 or 3.12. Open PowerShell in this `examsage-v2` directory. The output ZIP must have a new filename.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe tools\build_student_kit.py dist\ExamSage-Study-Windows.zip
Get-FileHash dist\ExamSage-Study-Windows.zip -Algorithm SHA256
```

The release workflow records the expected SHA-256 for the distributed archive. Inside the ZIP, `kit-files.json` contains a SHA-256 digest for every payload file. The workflow builds the kit again from source and checks its contents against the downloaded and extracted editions. [Release verification](../.github/workflows/student-release.yml)

## Find the implementation

- [Application modules](src/examsage/) cover import, search, source-linked multi-turn answers, original-page reading, review progress and local course tools. The student browser interface lives in [web/studio](src/examsage/web/studio/).
- The [student entry point](student_kit/kit.py), [course-study skill](plugin/skills/course-study/SKILL.md) and [builder](tools/build_student_kit.py) make up the downloadable kit. The source and kit both include the local KaTeX renderer with its [licence and provenance](src/examsage/web/vendor/katex/).
- The [tests](tests/) generate small course materials for regression checks. Some additional integration tests require the maintainer’s licensed course snapshots. The public [demo packs](examples/course-packs/README.md) provide four shareable examples.
- The archives in `releases/windows-student-pilot-1` and `releases/windows-student-pilot-2` are inputs for compatibility tests against earlier student kits. The current kit is in `releases/windows-study-pilot`.

## Run the Windows student checks

These tests exercise delivery to a fresh user, all four subject demos, chat, source pages and review. They use temporary student workspaces and a simulated model connection. Distribution tests start a separate Python process to reproduce the recipient environment. The base interpreter must therefore also have the student dependencies. A Windows developer can create the virtual environment from the Python runtime supplied with Codex.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_student_distribution.py tests/test_cross_discipline_demo.py tests/test_student_study_window.py tests/test_study_host.py tests/test_study_reader.py tests/test_study_review.py tests/test_student_languages.py tests/test_exam_outlook_chat.py tests/test_course_reader.py tests/test_study_links.py
```

To repeat the English browser test, use Node.js with `playwright-core` available and Microsoft Edge installed. Pass the test Python and an extracted student kit. The test runs the shipped application with a temporary student profile and a simulated Codex response, then checks two turns, the cited page, review, file import, language switching and mobile navigation.

```powershell
node tests/run_studio_language_check.cjs .\.venv\Scripts\python.exe ".\releases\windows-study-pilot\学生版"
```

## Further reading

[Data and retrieval architecture](docs/architecture.md) · [Browser course import](docs/browser-course-import.md) · [Portable study files](docs/portable-study.md) · [Source-linked review notes](docs/source-review-notes.md) · [HTTP course service](docs/course-mcp-http.md)
