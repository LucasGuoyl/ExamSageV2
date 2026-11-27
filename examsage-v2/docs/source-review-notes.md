# Save a study note with its source evidence

An authorized local course owner can add an observation as a separate note awaiting review. Each note records the course snapshot, target page and file hash of every supporting source. The original file, extracted wording and existing review status remain available. This offline operation requires no model calls or API key.

## From observation to saved note

1. Import a course draft with `import-courses` and open the generated `course-reader.html`.
2. Open a source page and enter a study note. The current page supplies the first reference. Add other visible pages as evidence where needed.
3. Add the note to the pending list. Queues are separate for each course and snapshot. Download the queue before refreshing or closing the page.
4. Download the review request. This is a JSON proposal. It becomes part of a course only when applied to a new draft and reimported.
5. Run the commands below from `examsage-v2` in the configured development environment. Replace the sample paths and identifiers with your own. Open the new reader to see the saved note below its original page with links to the evidence.

```powershell
python -m examsage apply-source-reviews --draft data/my-course-draft --library data/my-course-library --course-id my-course --request data/my-course-source-reviews.json --output data/my-course-reviewed-draft
python -m examsage import-courses --source-root data/my-course-reviewed-draft --pack pack.json --output data/my-course-reviewed-library
```

Both output directories must be new. The reviewed draft copies the explicitly listed source files and a new `pack.json`, and includes an application receipt. Unrelated files in the source draft are excluded. Import extracts the source pages again.

## Validation and visibility

Application rechecks the course, workspace, current snapshot, source scope, package contents and underlying file hashes. Stale requests, edited source files, hidden evidence, duplicate note IDs and existing output paths are rejected. Adding a note is append-only and requires a new ID.

Saving requires an original imported library with its full source scope. Partial source scopes, a historical cutoff that hides sources, and exported libraries are read-only. This prevents a restricted draft from bringing removed sources back into the library.

Text, original-image and calculation tools can return notes authorized for the current scope. If the target or any supporting source is unavailable, subsequent responses, readers and exports omit the whole note. Previously downloaded files remain with the recipient. A running local tool uses its startup scope until restarted.

`user_note` and `agent_note` describe the kind of note. They do not authenticate its author. All notes carry `unverified_note` status. The form renders the submitted text literally. Review the original image, assumptions and derivation before relying on its academic claim.

The groundwater pilot in rounds 24–26 saved a note into a separate new library. The previously installed 0.2.1 plugin continued to use its own library. Reader and test records for that pilot are held locally with the licensed course materials.
