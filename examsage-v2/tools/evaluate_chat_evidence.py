"""Offline source-location precheck. This does not call or grade a model."""
import json
from pathlib import Path

from examsage.chat_service import CourseTools, build_context
from examsage.cli import load


def main():
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / 'evaluation/chat_student_cases.json').read_text(encoding='utf-8'))
    results = []
    for case in cases:
        store, scope = load(root / 'data' / case['course'])
        tools = CourseTools(store, scope)
        row = {'id': case['id'], 'course': case['course'], 'snapshot': scope.snapshot,
               'model_called': False, 'checks': [], 'teaching_answer': 'not_run'}
        for query in case['queries']:
            try:
                found = tools.call('search_evidence', {'query': query})
                row['checks'].append({'query': query,
                                      'records': len(found['records']) + len(found.get('record_references', [])),
                                      'reused_records': len(found.get('record_references', [])),
                                      'evidence_count': len(tools.evidence)})
            except Exception as exc:
                row['checks'].append({'query': query, 'error': str(exc)})
        documents = {ref['document_id'] for e in tools.evidence.values() for ref in e['refs']}
        row['missing_expected_documents'] = sorted(set(case['documents']) - documents)
        row['limitations'] = tools.limitations
        row['evidence'] = list(tools.evidence.values())
        row['passed'] = not row['missing_expected_documents'] and all(
            'error' not in c and c['records'] > 0 for c in row['checks'])
        context = build_context([{'role': 'user', 'content': case['question']},
                                 {'role': 'user', 'content': case['followup']}], scope.course)
        row['both_user_turns_preserved'] = all(text in context for text in (case['question'], case['followup']))
        results.append(row)
    out = root / 'data/qa/chat-20261111'
    out.mkdir(parents=True, exist_ok=True)
    report = {'kind': 'offline_evidence_precheck_not_model_evaluation', 'model_called': False,
              'passed': sum(r['passed'] for r in results), 'total': len(results), 'cases': results}
    (out / 'evidence-precheck.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'total': report['total'], 'model_called': False,
                      'failures': [{'id': r['id'], 'checks': r['checks'], 'missing': r['missing_expected_documents']}
                                   for r in results if not r['passed']]}, ensure_ascii=False))
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
