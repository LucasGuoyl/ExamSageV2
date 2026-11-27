"""Exercise actual stdio processes against existing course snapshots, no model calls."""
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
COURSES = {'grt': 'Darcy', 'geodynamics': 'flexural rigidity', 'planetary_science': 'Kepler',
           'sea_level': 'sea level', 'ses': '2024 Q1(c)(i) 答案'}


def exchange(calls):
    messages = [
        {'id': 0, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25',
            'capabilities': {}, 'clientInfo': {'name': 'examsage-student-protocol-check', 'version': '1'}}},
        {'method': 'notifications/initialized'},
    ] + [{'id': i + 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}}
         for i, (name, args) in enumerate(calls)]
    env = {k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP') if k in os.environ}
    env.update(PYTHONPATH=str(ROOT / 'src'), PYTHONUTF8='1')
    result = subprocess.run([sys.executable, '-B', '-m', 'examsage.mcp_server', '--library', str(ROOT/'data'),
        '--courses', ','.join(COURSES)], input=''.join(json.dumps({'jsonrpc': '2.0', **m}, ensure_ascii=False)+'\n'
        for m in messages), capture_output=True, encoding='utf-8', env=env, timeout=45)
    if result.returncode != 0:
        raise RuntimeError('Plugin subprocess failed')
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    if len(replies) != len(calls) + 1:
        raise RuntimeError('Unexpected response count')
    return [r['result'] for r in replies[1:]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round', type=int, default=3)
    cli_options = parser.parse_args()
    output = ROOT / 'data' / 'qa' / 'plugin-20261116'
    output.mkdir(parents=True, exist_ok=True)
    paths = [ROOT/'data'/c/'course.sqlite3' for c in COURSES]
    before = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in paths}
    queries = [('search_evidence', {'course_id': c, 'query': q}) for c, q in COURSES.items()]
    searches = exchange(queries)
    checks = []
    def check(name, passed):
        checks.append({'name': name, 'passed': bool(passed)})
    followups = []
    for course, result in zip(COURSES, searches):
        data = result.get('structuredContent', {})
        check(course + ': nonempty real-course evidence', not result.get('isError') and bool(data.get('records')))
        check(course + ': no unsupported sufficiency promotion', data.get('sufficiency') in ('unassessed', 'insufficient'))
        if not data.get('sources'):
            continue
        source = data['sources'][0]
        ref = source['refs'][0]
        followups += [
            ('get_source_page', {'course_id': course, 'document_id': ref['document_id'], 'page': ref['page']}),
            ('calculate', {'course_id': course, 'expression': '2^3', 'inputs': {}, 'units': 'arithmetic test only',
                           'sources': [{'source_id': source['source_id'], 'record_id': source['record_id']}]}),
        ]
    following = exchange(followups)
    for (name, args), reply in zip(followups, following):
        data = reply.get('structuredContent', {})
        check(args['course_id'] + ': ' + name, not reply.get('isError') and
              (data.get('value') == 8 if name == 'calculate' else bool(data.get('records'))))
    repeats = exchange([queries[0]] * 12)
    check('12 calls retain full independent records', all(r.get('structuredContent', {}).get('records') ==
          repeats[0].get('structuredContent', {}).get('records') for r in repeats) and bool(repeats[0].get('structuredContent', {}).get('records')))
    rejected = exchange([('search_evidence', {'course_id': 'not-authorized', 'query': 'Darcy'}),
                         ('get_source_page', {'course_id': 'grt', 'document_id': '../private', 'page': 1})])
    check('unregistered course refused', rejected[0].get('isError') is True)
    check('unknown source yields no evidence', rejected[1].get('structuredContent', {}).get('records') == [])
    after = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in paths}
    check('all five databases unchanged', before == after)
    report = {'round': cli_options.round, 'kind': 'real_course_stdio_not_model_answers', 'checks': checks,
              'passed': sum(c['passed'] for c in checks), 'total': len(checks),
              'databases_before': before, 'databases_after': after,
              'source_code': {name: sha256((ROOT/'src/examsage'/name).read_bytes()).hexdigest()
                              for name in ('plugin_tools.py', 'mcp_server.py', 'storage.py', 'search.py', 'domain.py', 'course_profile.py')},
              'search_results': searches, 'followup_results': following}
    (output/f'round{cli_options.round}-real-courses.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('kind', 'passed', 'total')}, ensure_ascii=False))
    for c in checks:
        if not c['passed']:
            print('FAIL: ' + c['name'])
    return 0 if all(c['passed'] for c in checks) else 1


if __name__ == '__main__':
    raise SystemExit(main())
