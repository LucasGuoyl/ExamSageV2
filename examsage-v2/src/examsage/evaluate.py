from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import platform
import statistics
import time

from .domain import Scope, digest
from .search import CourseQueryService


def evaluate(cases: dict, service: CourseQueryService, scope: Scope, split: str | None = None) -> dict:
    manifest=service.store.manifest(scope)
    documents={d.id:d for d in manifest.documents} if manifest else {}
    results=[]
    for case in cases['cases']:
        if split and case['split']!=split:
            continue
        response=service.search_evidence(scope,case['query'])
        refs=[s for r in response.records for s in r.refs]
        matches=[]
        for expected in case.get('evidence',[]):
            matches.append(any(s.document_id in documents and documents[s.document_id].relative_path.endswith(expected['source'])
                               and s.page in expected['pages'] for s in refs))
        passed=(response.sufficiency=='insufficient' and bool(response.limitations)) if case.get('missing') else bool(matches) and all(matches)
        results.append({'id':case['id'],'split':case['split'],'category':case.get('category','unknown'),
                        'query':case['query'],'passed':passed,'matched_groups':matches,
                        'retrieved_ids':[r.id for r in response.records], 'elapsed_ms':response.elapsed_ms,
                        'mode':response.mode,'limitations':response.limitations})
    groups={name:{'total':sum(r['split']==name for r in results),
                  'passed':sum(r['split']==name and r['passed'] for r in results)} for name in ['development','reserved']}
    return {'generated_at':datetime.now(timezone.utc).isoformat(),'snapshot':scope.snapshot,'case_version':cases['version'],
            'case_hash':digest(cases),'metric':'Expected source/page groups retrieved in top 8 including complete context',
            'not_measured':['scientific correctness','answer entailment','exam prediction accuracy','full visual comprehension'],
            'human_acceptance':'pending','reserved_set_note':'Agent-authored reserved queries, not an independent unseen human benchmark.',
            'total':len(results),'passed':sum(r['passed'] for r in results),'splits':groups,'results':results}


def benchmark(service: CourseQueryService, scope: Scope, queries: list[str], count: int=100) -> dict:
    samples=[]
    first=time.perf_counter()
    service.search_evidence(scope,queries[0])
    first_ms=(time.perf_counter()-first)*1000
    for i in range(count):
        start=time.perf_counter()
        service.search_evidence(scope,queries[i%len(queries)])
        samples.append((time.perf_counter()-start)*1000)
    ordered=sorted(samples)
    return {'snapshot':scope.snapshot,'queries':count,'first_benchmark_query_ms':round(first_ms,3),
            'warm_p50_ms':round(statistics.median(samples),3),'warm_p95_ms':round(ordered[min(len(ordered)-1,int(len(ordered)*.95))],3),
            'system':platform.platform(),'python':platform.python_version(),
            'scope':'Local retrieval: SQLite, aliases, ranking and record serialization. The service may already be warm from evaluation; cold-start latency is not measured. No answer-generation API call.',
            'mode':'hybrid' if service.vectors and service.embed_query else 'keyword_only'}
