"""Match an annotation to the actual question, edition, and annotation date."""
from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from examsage.exam_outlook import evaluate_outlook, exam_outlook
from examsage.plugin_tools import Principal, load_library
from examsage.student_workspace import StudentWorkspace, student_tools
from examsage.web_intake import import_selection


def original_papers():
    binding, store = load_library(Path(__file__).resolve().parents[1] / 'data', ['grt'])._course('grt')
    return {d.exam_year: (binding.database.parent / 'assets' / d.asset).read_bytes()
            for d in store.manifest(binding.scope).documents if d.kind == 'exam'}


def receive(root, rows):
    space = StudentWorkspace(root, Principal('owner', frozenset()))
    files = [(name, BytesIO(raw)) for name, _, _, raw in rows]
    labels = [dict(filename=name, kind=kind, exam_year=year) for name, kind, year, _ in rows]
    receipt = import_selection(space.imports, 'Unnamed course', 'Earth science', files, materials=labels)
    api = student_tools(None, space)
    cid = 'upload-' + receipt['id']
    return cid, *api._course(cid)


def test_renamed_originals_return_question_scoped_evidence_and_multiple_labels(tmp_path):
    papers = original_papers()
    cid, binding, store = receive(tmp_path, [(f'{year}.pdf', 'exam', year, raw) for year, raw in papers.items()])
    forecast = exam_outlook(store, binding.scope, cid, 2027, 10, 'paper_year')
    assert forecast['coverage']['tagged_questions'] == forecast['coverage']['parent_questions'] == 12
    assert forecast['coverage']['source_checked_questions'] == 12
    pairs = {r['topic']: [(s['year'], s['question_number'], s['page']) for s in r['sources']] for r in forecast['ranking']}
    assert pairs['Dolomitisation'] == [(2024, '2', 2), (2022, '3', 2)]
    assert pairs['MVT deposits'] == [(2024, '5', 3), (2022, '6', 4)]
    assert pairs['Reaction-front kinetics'] == [(2022, '2', 2)]
    assert pairs['Reaction-front transport'] == [(2024, '3', 3), (2022, '4', 3)]
    for row in forecast['ranking']:
        for ref in row['sources']:
            page = store.get(binding.scope, ref['record_id'])
            assert ref['quote'] in ' '.join(page.details['raw_text'].split())
            assert ref['annotation_date'] == '2026-11-23'
    review = evaluate_outlook(store, binding.scope, cid, 2024, 10, 'paper_year')
    assert review['metrics'] is None and review['target_questions_total'] == 6
    q3 = next(q for q in review['target_questions'] if q['question_number']=='3')
    assert {x['label_origin'] for x in q3['topic_evidence']} == {'printed_title','source_checked_prompt'}
    assert all(x['source_id'] == q3['source']['source_id'] for x in q3['topic_evidence'])


def test_modified_edition_wrong_year_and_solution_do_not_inherit_labels(tmp_path):
    paper = original_papers()[2022]
    for i, (raw, year, kind) in enumerate([(paper+b'\n%new edition',2022,'exam'),(paper,2021,'exam'),(paper,2022,'exam_solution')]):
        cid, binding, store = receive(tmp_path/str(i), [('same.pdf',kind,year,raw)])
        assert not exam_outlook(store,binding.scope,cid,2027,10,'paper_year')['ranking']


def test_annotation_does_not_predate_its_review_even_for_a_previously_available_paper(tmp_path):
    from examsage.course_pack import CoursePack, import_pack
    from examsage.storage import Store
    from examsage.domain import Document, Manifest
    from examsage.course_profile import CourseProfile
    paper = original_papers()[2022]
    (tmp_path/'known.pdf').write_bytes(paper)
    doc = Document(id='p',kind='exam',exam_year=2022,available_from=date(2022,7,1),date_evidence='Archive record',
        relative_path='known.pdf',pages=4,sha256=sha256(paper).hexdigest())
    profile = CourseProfile(course_id='grt',institution=None,curriculum_system='school',stage='school',language='en',
        syllabus_version='trial',disciplines=['earth'],material_status='demonstration')
    pack = CoursePack(workspace='w',profile=profile,manifest=Manifest(course_key='grt',course_name='G',documents=[doc]),records=[],relations=[])
    out = tmp_path/'library'
    scope = import_pack(pack,tmp_path,out).scope
    store = Store(out/'course.sqlite3',read_only=True)
    assert exam_outlook(store,scope,'grt',2025,10,'strict')['ranking']==[]
    assert exam_outlook(store,scope,'grt',2027,10,'paper_year')['ranking']
    limited = scope.model_copy(update={'strict_history':True,'cutoff':date(2025,12,31)})
    assert not exam_outlook(store,limited,'grt',2027,10,'paper_year')['ranking']
    from examsage.release import publish_release
    reduced = tmp_path/'archive'
    publish_release(store,limited,out/'assets',reduced)
    assert 'Reaction-front kinetics' not in (reduced/'provenance.json').read_text(encoding='utf8')
    assert 'paper_topic_evidence' not in str(store.get(limited,'p:p2').details)


def test_annotations_stop_at_question_boundaries_and_verify_literal_titles(monkeypatch):
    from types import SimpleNamespace
    from examsage import paper_topics
    doc = SimpleNamespace(sha256='example', pages=2, kind='exam', exam_year=2022)
    pages = ['1. First title\nOpening statement.', 'Continuation about convection.\n2. Second title\nElastic strain.']
    blocks = [SimpleNamespace(visibility='visible', refs=[SimpleNamespace(page=p)],
                              details={'raw_text':t}) for p,t in enumerate(pages,1)]
    events = [{'path':'1','page':1,'offset':0},{'path':'2','page':2,'offset':pages[1].index('2.')}]
    def row(number, page, quote, origin='source_checked_prompt'):
        return dict(number=number,page=page,topic='study label',quote=quote,origin=origin)
    rows = [row('1',2,'about convection'), row('1',2,'Elastic strain'),row('2',1,'Opening statement'),
            row('1',1,'First title','printed_title'),row('1',2,'about convection','printed_title'),
            row('2',2,'Elastic strain.','printed_title')]
    monkeypatch.setattr(paper_topics,'_catalog',lambda:{'example':dict(exam_year=2022,annotation_date='2026-11-23',annotations=rows)})
    ok = paper_topics.index_paper_topics(doc,blocks,events)
    assert [(r['page'],r['quote']) for r in ok] == [(2,'about convection'),(1,'First title')]
    blocks[1].visibility='hidden'
    assert [r['quote'] for r in paper_topics.index_paper_topics(doc,blocks,events)]==['First title']
    assert not paper_topics.index_paper_topics(doc,blocks,[*events,dict(path='1',page=2,offset=3)])


def test_export_filters_topic_index_by_student_sources_and_historical_cutoff(tmp_path):
    import json
    from examsage.release import publish_release
    from examsage.storage import Store
    papers=original_papers()
    cid,binding,store=receive(tmp_path/'space',[(f'{year}.pdf','exam',year,raw) for year,raw in papers.items()])
    docs=store.manifest(binding.scope).documents
    did=next(d.id for d in docs if d.exam_year==2022)
    scope=binding.scope.model_copy(update={'allowed_sources':[did]})
    output=tmp_path/'limited'
    publish_release(store,scope,binding.database.parent/'assets',output)
    metadata=json.loads((output/'provenance.json').read_text(encoding='utf8'))
    assert set(metadata['paper_topic_evidence'])=={did}
    assert 'Mantle melt migration' not in str(metadata)
    new_scope=scope.model_copy(update={'snapshot':json.loads((output/'current.json').read_text(encoding='utf8'))['snapshot']})
    outlook=exam_outlook(Store(output/'course.sqlite3',read_only=True),new_scope,cid,2027,10,'paper_year')
    assert outlook['coverage']['source_checked_questions']==6


def test_cross_page_holdout_links_the_question_start_and_its_separate_quote_page(tmp_path,monkeypatch):
    from examsage import paper_topics
    text = b'Question 1\nInitial conditions given.\fUse convection to explain the change.\nQuestion 2\nOther task.'
    edition = {'exam_year':2024,'annotation_date':'2026-11-23','annotations':[
        {'number':'1','page':2,'topic':'Heat transfer','origin':'source_checked_prompt','quote':'Use convection'}]}
    monkeypatch.setattr(paper_topics,'_catalog',lambda:{sha256(text).hexdigest():edition})
    cid,binding,store=receive(tmp_path,[('school.txt','exam',2024,text)])
    review=evaluate_outlook(store,binding.scope,cid,2024,10,'paper_year')
    q1=next(q for q in review['target_questions'] if q['question_number']=='1')
    assert q1['source']['page']==1
    assert q1['topic_evidence'][0]['page']==2
    assert q1['topic_evidence'][0]['source_id'] != q1['source']['source_id']
