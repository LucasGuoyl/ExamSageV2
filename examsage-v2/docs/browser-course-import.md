# Import course materials in the local web service

Open the course import form in the header of the local ExamSage service. Enter the course name and discipline. Select files from one or more directories, removing any unwanted files before submission. One request accepts up to 24 PDF, PPTX, UTF-8 TXT or Markdown files within a 64 MiB upload limit.

The receipt reports the number of physical pages and the number partially extracted or unreadable. Open the source reader to inspect individual pages, extracted text, limitations and file hashes. Open the course conversation to check the ChatGPT plan connection and ask a question. Bookmark the reader and conversation addresses to use them again after restarting the same service.

This developer web service saves each import under `data/course-imports/<import-id>/`. The `draft` subdirectory can be edited for another build, and `library` supplies the course tools. Each import receives its own course ID, authorized source set and conversation scope. Files with identical names remain distinguishable. Missing curriculum details stay unset and new content awaits academic review. The loopback service serves one local user. An existing desktop plugin continues to use its registered library. For the downloadable Windows student app and its storage location, see the [student guide](../../README.en.md).

## Historical acceptance cases

| Round | Student activity | Result |
| --- | --- | --- |
| 27 | Select same-name files from different directories, remove a mistaken selection, and import a damaged PDF and a valid long filename. | The same-name files received independent document IDs. Review found two Windows defects involving leftover temporary files after a long filename and navigation in a course directory containing Chinese characters. Both were reproduced and fixed. |
| 28 | Import a groundwater feedback PDF and an overview slide deck, then change a reaction-front calculation from two years to five. | The two files contained 10 pages, all marked partially extracted. Two original PDF images could be retrieved. The stated ratio of 0.0086 and speed of 800 m/year give 13.76 m over two years and 34.4 m over five. The source also gives 8.6 m/year, so the discrepancy remains visible. The course listing was corrected to identify a raw import accurately. |
| 29 | Read a response citing a cross-document note, then cite only the calculation. | A missing review reminder and a lost second reference were fixed. Calculation evidence now carries the visible note and opens page 2 of its second source. Restricting either source hides the joint note. |

In that test round, 33 browser chat checks passed using simulated HTTP responses, including opening the second reference. Form tests covered selecting files in batches, removal, empty input, retry and a mobile viewport. A real local import receipt was replayed to open the corresponding reader. The groundwater exercises used live course retrieval, arithmetic, conversation assembly and citation verification, with answer wording supplied in the test conversation.

Those results describe the historical prototype. A Windows socket-pair timeout prevented a complete local pytest run at that stage, and live subscription-backed answers on the newly imported course awaited the local web service. The original receipts and browser evidence are kept with the maintainer's authorized course materials. [Current Windows student release checks](https://github.com/LucasGuoyl/ExamSageV2/actions/workflows/student-release.yml)
