# Cross-subject teaching examples

ExamSage includes four small course packs for practising retrieval, citation, inherited question conditions and evidence checking. Choose the [English materials](../course-packs-en/) or the [original Chinese materials](./). The language editions share course and record IDs so that the same exercises can be followed in either language. Import one edition into each output library.

| Subject | What to try | What to check |
| --- | --- | --- |
| Physics | Find a spring's extension, then change only the applied load. | Page 1 gives the conditions and inputs. Page 2 contains the derivation and units. |
| Mathematics | Prove the finite sum formula by induction and evaluate it at a particular positive integer. | Find the base case and hypothesis before citing the induction step. |
| Literature | Compare two readings of the four-line poem *The Window*. | Cite line numbers and consider counterevidence for each reading. The English edition identifies the poem as a translation. |
| History | Explain the equality claim in an excerpt from the US Declaration of Independence. | Separate what the document says from what other evidence would be needed to establish social practice. |

The project created the physics and mathematics exercises, the original teaching poem and its discussion. The history pack combines a public-domain excerpt with an original analysis exercise. The English edition reproduces the same archival excerpt. These are teaching examples with candidate academic records. They carry no institutional accreditation or independent expert certification. The source transcription was checked on 16 November 2026. [US National Archives transcription](https://www.archives.gov/founding-docs/declaration-transcript)

A form feed (`\f`) starts a new local page in each text file. These numbers identify locations in the teaching pack. Each `pack.json` specifies source hashes, learning outcomes and relationships between records. Use it as a template for an independently authored course.

## Import an edition

From the `examsage-v2` directory, activate the development environment described in the [developer guide](../../README.md). Choose a fresh output path.

```powershell
python -m examsage import-courses --source-root examples/course-packs-en --pack physics/pack.json --pack mathematics/pack.json --pack literature/pack.json --pack history/pack.json --output data/my-course-library
```

For the original edition, set `--source-root examples/course-packs`. Each repeatable `--pack` path is relative to the selected source root. Files named inside a pack are relative to that pack's directory. The importer supports TXT and Markdown with form-feed page breaks, PDF and PPTX.

The importer creates `library.json`, a separate snapshot per course, a combined `review.json` and an offline `course-reader.html`. Open the reader to check text, parent conditions, reference answers and review status. Full-slide images and persistent review edits require other tools. The reader and importer operate without model calls.

Publication of the new library waits for all packs and the reader to build. A hash, format or page-count mismatch fails the batch and leaves existing libraries intact. Hidden, unreadable or low-text pages and unpaired questions remain flagged for review.

## Serve an imported library

To give a local MCP host read-only access to the four selected courses, start the stdio server with an explicit course list.

```powershell
python -m examsage.mcp_server --library data/my-course-library --courses demo-physics,demo-mathematics,demo-literature,demo-history
```

The host must be configured to use that server. Local ownership determines the available scope. Desktop plugin registration and authentication for a remote host have their own setup and acceptance checks.
