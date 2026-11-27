"""Source-bound, visually checked transcription; never overwrite raw page records."""
from .domain import Document,Page,digest
from .questions import parse_exam


def parse_reviewed_exam(doc: Document, pages: list[Page], course: str, recipe: dict):
    original=parse_exam(doc,pages,course)
    matches=[x for x in recipe.get('documents',[]) if x['sha256']==doc.sha256]
    if not matches:
        return original
    if len(matches)!=1:
        raise ValueError('duplicate source transcription')
    edits={x['number']:x for x in matches[0]['pages']}
    revised=[]
    found=set()
    for page in pages:
        if page.document_id!=doc.id or page.number not in edits:
            revised.append(page)
            continue
        found.add(page.number)
        text=page.text
        for change in edits[page.number]['replacements']:
            before,after=change['before'],change['after']
            if not before or text.count(before)!=change.get('count',1):
                raise ValueError(f'stale transcription span: {doc.id} page {page.number}')
            text=text.replace(before,after)
        revised.append(page.model_copy(update={'text':text}))
    if found!=set(edits):
        raise ValueError('transcription page is missing')
    checked=parse_exam(doc,revised,course)
    raw={q.id:q for q in original}
    if {q.id for q in checked}!=set(raw):
        raise ValueError('transcription changed question structure')
    for question in checked:
        previous=raw[question.id]
        if question.details['marks']!=previous.details['marks']:
            raise ValueError('transcription changed question marks')
        if question.text==previous.text and question.details['shared_stem']==previous.details['shared_stem']:
            continue
        question.details.update(raw_text=previous.text,raw_shared_stem=previous.details['shared_stem'],
            transcription={'version':recipe['version'],'hash':digest(recipe),'source_sha256':doc.sha256,
                           'pages':sorted({r.page for r in question.refs if r.page in edits}),
                           'review':'agent_source_checked'})
        question.limitations.append('Source transcription visually checked by an agent; independent expert review remains pending.')
    return checked
