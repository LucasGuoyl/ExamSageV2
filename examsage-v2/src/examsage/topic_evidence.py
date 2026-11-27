"""Project the immutable paper-topic index within a given document and date grant."""
from collections import defaultdict


def scoped_topic_evidence(metadata, document_ids, cutoff=None):
    index = metadata.get('paper_topic_evidence', {})
    result = {}
    for doc_id in sorted(set(document_ids) & index.keys()):
        rows = [r for r in index[doc_id] if cutoff is None or r['annotation_date'] <= cutoff.isoformat()]
        if rows:
            result[doc_id] = rows
    return result


def structured_question_evidence(metadata, document_ids, cutoff=None):
    by_question = defaultdict(list)
    for doc_id, rows in scoped_topic_evidence(metadata, document_ids, cutoff).items():
        for row in rows:
            if 'question_id' in row:
                by_question[row['question_id']].append({
                    **row,'document_id':doc_id,'record_id':f"{doc_id}:p{row['page']}"})
    return by_question
