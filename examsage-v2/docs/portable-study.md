# Use an exported course file in a ChatGPT conversation

A maintainer can export selected material for students who want to discuss it in their own ChatGPT conversation. The exported text and page images represent the course snapshot at the time of export.

1. On the local course page, select the document and download its chat study file as TXT. For a chart, handwritten derivation or equation, open the corresponding physical page and download the original page PNG. A complete slide is exported as a static image. Plain-text lecture notes retain their line breaks.
2. In ChatGPT, attach the TXT file and the PNG for each page you want to discuss. Include both pages when a derivation crosses a page boundary. Upload availability and limits depend on the account. [ChatGPT file uploads](https://help.openai.com/en/articles/8555545-file-uploads-faq)
3. Ask “Using the attachments, state the conditions under which this equation applies. Give the filename, physical page and source ID. Identify any symbol you cannot read.” For a follow-up, ask “Keep the other conditions fixed. If we double this parameter, which conclusions change?”

The export prefixes each line of source wording with `│`. An accepted erratum supported entirely by that page appears on a separate line as an agent-checked source-page correction. Check the image when extraction is incomplete. If source values disagree, preserve the original wording alongside the result recalculated from the stated conditions. Physical page numbers start at 1 in the file and can differ from printed footers. Before sending files to a student, check the document list, page counts and extraction status in the TXT.

## Export several documents

In the configured project Python environment, repeat `--document` for each document ID in the current course and choose a new output filename. Omitting document IDs selects every visible document in the current course scope.

```powershell
python -m examsage study-file --library data --course-id grt --document doc_e26a6e2870a11e4f9596b7cb --output groundwater-feedback.txt
```

The local web download supports a single-page PNG up to 16 MiB. The native plugin limits images returned directly in the conversation to 2 MiB. The web handler was checked on 23 large groundwater slides. Maintainer-only records also cover exports and question sessions in seven courses. For example, physical page 17 in the second geodynamics lecture shows whiteboard footer 15.
