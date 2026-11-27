"""Explicit source/render-bound agent observations, separate from raw extraction."""
from .domain import Document, Page, Record, SourceRef


def apply_visual_review(doc: Document, pages: list[Page], recipe: dict, course: str):
    entry = recipe.get('documents', {}).get(doc.sha256)
    if not entry:
        return pages, []
    copied = [p.model_copy(deep=True) for p in pages]
    by_number = {p.number: p for p in copied}
    reviewed = set()
    for item in entry['pages']:
        n = item['number']
        page = by_number.get(n)
        if n in reviewed or page is None or not page.render or page.render['sha256'] != item['render_sha256']:
            raise ValueError('Visual review page/render mismatch')
        if page.render['source_sha256'] != doc.sha256:
            raise ValueError('Visual review source mismatch')
        reviewed.add(n)
        page.visual_status = 'agent_reviewed'
        page.visual_review = dict(item, review='agent_source_checked', source_sha256=doc.sha256,
                                  scope='layout_and_key_content', expert_acceptance='pending')
        page.issues = [i for i in page.issues if i not in {'embedded_equations_may_require_visual_review',
                       'Static full-slide render available; independent content review remains separate.'}]
        page.issues += ['Agent checked slide layout and key content; independent expert acceptance pending.']
        page.issues += item.get('warnings', [])
    derived = []
    for item in entry.get('derivations', []):
        refs = set(item['pages'])
        if not refs or not refs <= reviewed or any(by_number[n].hidden for n in refs):
            raise ValueError('Derivation references unreviewed or hidden pages')
        if any(not set(step['pages']) <= refs for step in item['steps']):
            raise ValueError('Derivation step escapes reviewed references')
        key = f'{course}:derivation:{item["key"]}'
        text = item['summary'] + '\n' + '\n'.join(step['title'] + '：' + step['text'] for step in item['steps'])
        derived.append(Record(id=key, kind='concept', title=item['title'], text=text,
                       refs=[SourceRef(document_id=doc.id, page=n) for n in sorted(refs)],
                       topic='groundwater', aliases=item.get('aliases', []), review='agent_source_checked',
                       details={'derivation': item, 'source_sha256': doc.sha256},
                       limitations=['由代理对照原页整理的学习导读，尚未经独立学科专家验收，不是官方答案。'] + item.get('warnings', [])))
        for n in refs:
            by_number[n].visual_review.setdefault('derivations', []).append({'id': key, 'title': item['title']})
    return copied, derived
