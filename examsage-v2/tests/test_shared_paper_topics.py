"""Verified parent topics coexist with teaching links in a shared immutable course."""
from datetime import date
import json
from pathlib import Path

import pytest

from examsage.domain import Scope
from examsage.exam_outlook import evaluate_outlook, exam_outlook
from examsage.plugin_tools import CourseBinding, PluginTools, Principal
from examsage.release import publish_release
from examsage.storage import Store

ROOT=Path(__file__).resolve().parents[1]
BASE='snap_6565fa062c6de973fe8802097403ea16'


@pytest.fixture(scope='module')
def shared(tmp_path_factory):
    from examsage.paper_topics import structured_topic_metadata
    data=ROOT/'data/grt'
    original=Store(data/'course.sqlite3',read_only=True)
    original_scope=Scope.model_validate_json((data/'current.json').read_text(encoding='utf8')).model_copy(update={'snapshot':BASE})
    manifest=original.manifest(original_scope)
    records=original.list_records(original_scope)
    with original.connect() as db:
        from examsage.domain import Relation
        edges=[Relation.model_validate_json(r[0]) for r in db.execute('SELECT payload FROM relations WHERE snapshot=?',(BASE,))]
    index=structured_topic_metadata(manifest,records,original.path)
    # A historically available copy makes the annotation-date check independent of the paper date.
    for doc in manifest.documents:
        if doc.kind=='exam':
            doc.available_from=date(doc.exam_year,8,1)
    store=Store(tmp_path_factory.mktemp('shared')/'course.sqlite3')
    sid=store.publish(original_scope.workspace,manifest,records,edges,{**original.metadata(original_scope),**index})
    scope=original_scope.model_copy(update={'snapshot':sid})
    return store,scope,data/'assets'


def tools_for(store,scope):
    return PluginTools([CourseBinding('grt',store.path,scope)],Principal('student',frozenset(['grt'])))


def test_topic_and_teaching_relation_have_separate_evidence(shared):
    store,scope,_=shared
    api=tools_for(store,scope)
    wanted={(2022,'2'):{'Reaction-front kinetics'},(2022,'4'):{'Carbon mineral storage','Reaction-front transport'},
            (2024,'2'):{'Dolomitisation'},(2024,'3'):{'Carbon mineral storage','Reaction-front transport'}}
    for year in (2022,2024):
        r=evaluate_outlook(store,scope,'grt',year,10,'paper_year')
        assert r['metrics'] is None
        for q in r['target_questions']:
            key=year,q['question_number']
            if key not in wanted:
                continue
            assert set(q['observed_topics'])==wanted[key]
            ev=q['topic_evidence'][0]
            bundle=api.call('get_question',{'course_id':'grt','question_id':ev['question_id']})
            assert {t['topic'] for t in bundle['records'][0]['details']['exam_topic_evidence']}==wanted[key]
            assert bundle['relations']
            if key==(2022,'2'):
                assert any(edge['target'].endswith(':kinetics') for edge in bundle['relations'])
            page=api.call('get_source_page',{'course_id':'grt','document_id':ev['document_id'],'page':ev['page']})
            assert page['sources'][0]['source_id']==ev['source_id'] and ev['quote'] in ' '.join(page['records'][0]['text'].split())
    assert exam_outlook(store,scope,'grt',2027,10,'strict')['coverage']['source_checked_questions']==12


def test_restricted_history_keeps_question_but_omits_later_topics_and_does_not_guess(shared):
    store,scope,_=shared
    limited=scope.model_copy(update={'strict_history':True,'cutoff':date(2025,12,31)})
    r=exam_outlook(store,limited,'grt',2027,10,'paper_year')
    assert r['training_years']==[2022,2024] and r['coverage']['parent_questions']==12
    assert not r['ranking']
    q=next(q for q in store.list_records(scope,'question') if q.parent_id is None)
    ans=tools_for(store,limited).call('get_question',{'course_id':'grt','question_id':q.id})
    assert ans['records'] and not ans['records'][0]['details'].get('exam_topic_evidence')


def test_narrowed_shared_export_preserves_verified_labels_only_when_allowed(shared,tmp_path):
    store,scope,assets=shared
    doc=next(d for d in store.manifest(scope).documents if d.exam_year==2022 and d.kind=='exam')
    one=scope.model_copy(update={'allowed_sources':[doc.id]})
    folder=tmp_path/'release'
    publish_release(store,one,assets,folder)
    meta=json.loads((folder/'provenance.json').read_text(encoding='utf8'))
    assert set(meta['paper_topic_evidence'])=={doc.id}
    assert 'Mantle melt migration' not in str(meta['paper_topic_evidence'])
    s=Scope.model_validate_json((folder/'current.json').read_text(encoding='utf8'))
    src=Store(folder/'course.sqlite3',read_only=True)
    assert exam_outlook(src,s,'grt',2027,10,'paper_year')['coverage']['source_checked_questions']==6
    older=s.model_copy(update={'strict_history':True,'cutoff':date(2025,12,31)})
    out=tmp_path/'older'
    publish_release(src,older,folder/'assets',out)
    exported=json.loads((out/'provenance.json').read_text(encoding='utf8'))
    assert 'Reaction-front kinetics' not in json.dumps(exported,ensure_ascii=False)
    assert exported['paper_topic_documents']==[doc.id]
    for file in (out/'questions.jsonl',out/'blocks.jsonl'):
        assert 'source_checked_prompt' not in file.read_text(encoding='utf8')
    dated=Scope.model_validate_json((out/'current.json').read_text(encoding='utf8'))
    assert not exam_outlook(Store(out/'course.sqlite3',read_only=True),dated,'grt',2027,10,'paper_year')['ranking']


def test_public_question_topic_filter_uses_visible_paper_annotations(shared, tmp_path):
    from examsage.api import create_app
    from examsage.chat_runner import ChatRunner
    from examsage.ingest import atomic_json
    store,scope,_=shared
    data=store.path.parent
    def endpoint(grant):
        atomic_json(data/'current.json',grant.model_dump(mode='json'))
        app=create_app(data,chat_runner=runner,course_id='grt',private_preview_root=tmp_path/'previews')
        return next(r.endpoint for r in app.routes if getattr(r,'path','')=='/api/records')
    runner=ChatRunner(tmp_path/'chat',runtime=object())
    try:
        rows=endpoint(scope)
        assert {(q.details['exam_year'],q.details['number']) for q in rows('question','Dolomitisation',None,True)}=={(2022,'3'),(2024,'2')}
        assert not rows('question','dolomite',None,True)
        assert rows('concept','dolomite',None,False)
        past=endpoint(scope.model_copy(update={'strict_history':True,'cutoff':date(2025,12,31)}))
        assert not past('question','Dolomitisation',None,True)
    finally:
        runner.close()
