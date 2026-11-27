import pytest
from fastapi import HTTPException

from examsage.api import create_app
from examsage.exam_outlook import evaluate_outlook
from test_chat_api import endpoint
from test_exam_outlook import corpus

REVIEW='/api/exam-outlook/review'
PAGE='/api/page/{doc_id}/{number}'


def course_app(folder, *, authorized=lambda:True):
    store,scope=corpus(folder)
    (folder/'current.json').write_text(scope.model_dump_json(),encoding='utf8')
    app=create_app(folder,private_preview_root=folder/'previews',chat_runner=object(),
                   course_id='student-math',is_authorized=authorized)
    return app,store,scope


def test_review_from_course_page_matches_evaluator_and_opens_canonical_source(tmp_path):
    app,store,scope=course_app(tmp_path)
    review=endpoint(app,REVIEW)(2024,2,'paper_year')
    expected=evaluate_outlook(store,scope,'student-math',2024,2,'paper_year',question_limit=20)
    assert {k:v for k,v in review.items() if k!='review_scope'}==expected
    assert review['review_scope']
    refs=[review['target_questions'][0]['source'],review['outlook']['ranking'][0]['sources'][0]]
    for ref in refs:
        row=endpoint(app,PAGE)(ref['document_id'],ref['page'],source_id=ref['source_id'])
        assert row['bundle'].records[0].id==ref['record_id']
    with pytest.raises(HTTPException) as err:
        endpoint(app,PAGE)(refs[0]['document_id'],refs[0]['page'],source_id=refs[1]['source_id'])
    assert err.value.status_code==409


def test_review_of_absent_target_and_strict_training_preserve_evidence_gaps(tmp_path):
    app,_,_=course_app(tmp_path)
    review=endpoint(app,REVIEW)
    assert review(2026,2,'paper_year')['comparison_status']=='no_target'
    assert review(2020,2,'strict')['comparison_status']=='no_forecast'
    assert not review(2026,2,'paper_year')['unobserved_predictions']


def test_recheck_grant_after_review_and_before_returning_a_cited_page(tmp_path):
    for path in [REVIEW,PAGE]:
        from examsage.domain import digest,record_source_id
        states=iter([True,False])
        app,store,scope=course_app(tmp_path/path.split('/')[2],authorized=lambda:next(states))
        sid=record_source_id('student-math',scope,digest(store.get(scope,'target:p1').model_dump(mode='json')))
        with pytest.raises(HTTPException) as err:
            if path==REVIEW: endpoint(app,REVIEW)(2024,2,'paper_year')
            else: endpoint(app,PAGE)('target',1,source_id=sid)
        assert err.value.status_code==409


def test_next_batch_rechecks_the_original_course_and_scope(tmp_path):
    app,store,scope=course_app(tmp_path)
    handle=endpoint(app,REVIEW)
    report=handle(2024,2,'paper_year')
    assert handle(2024,2,'paper_year',20,report['review_scope'])['target_questions']==[]
    limited=scope.model_copy(update={'allowed_sources':['a']})
    (tmp_path/'current.json').write_text(limited.model_dump_json(),encoding='utf8')
    rebuilt=create_app(tmp_path,private_preview_root=tmp_path/'previews',course_id='student-math',chat_runner=object())
    with pytest.raises(HTTPException) as err:
        endpoint(rebuilt,REVIEW)(2024,2,'paper_year',20,report['review_scope'])
    assert err.value.status_code==409

@pytest.mark.parametrize('suffix',['.pdf','.pptx'])
def test_cited_preview_and_download_are_the_original_bytes(tmp_path,suffix):
    from test_page_image import image_api,pdf_bytes
    from urllib.parse import parse_qs,urlsplit
    tools,doc,store,scope=image_api(tmp_path,suffix=suffix)
    (tmp_path/'current.json').write_text(scope.model_dump_json(),encoding='utf8')
    app=create_app(tmp_path,private_preview_root=tmp_path/'previews',chat_runner=object(),course_id='physics')
    sid=tools.call('get_source_page',dict(course_id='physics',document_id=doc.id,page=1))['sources'][0]['source_id']
    response=endpoint(app,PAGE)(doc.id,1,source_id=sid)
    assert parse_qs(urlsplit(response['preview_url']).query).get('source_id')==[sid]
    preview=endpoint(app,'/api/preview/{doc_id}/{number}')
    download=endpoint(app,'/api/source/{doc_id}')
    image=endpoint(app,'/api/study-image/{doc_id}/{number}')
    for action in (preview,image):
        good=action(doc.id,1,source_id=sid)
        assert good.body.startswith(b'\x89PNG') and good.headers['X-ExamSage-Source-ID']==sid
        with pytest.raises(HTTPException) as err: action(doc.id,1,source_id='src_'+'a'*64)
        assert err.value.status_code==409
    asset=tmp_path/'assets'/doc.asset
    assert download(doc.id,page=1,source_id=sid).body==asset.read_bytes()
    asset.write_bytes(pdf_bytes(702,499))
    for fn in (lambda:preview(doc.id,1,source_id=sid),lambda:image(doc.id,1,source_id=sid),
               lambda:download(doc.id,page=1,source_id=sid)):
        with pytest.raises(HTTPException) as err: fn()
        assert err.value.status_code in (404,409)

def test_leaving_the_cited_page_validates_anchor_and_returns_new_page_identity(tmp_path):
    from examsage.domain import record_source_id,digest
    store,scope=corpus(tmp_path)
    mf=store.manifest(scope)
    doc=next(d for d in mf.documents if d.id=='target')
    doc.pages=2
    records=store.list_records(scope)
    first=next(r for r in records if r.id=='target:p1')
    second=first.model_copy(update={'id':'target:p2','refs':[first.refs[0].model_copy(update={'page':2})]})
    snap=store.publish(scope.workspace,mf,[*records,second],[],{})
    scope=scope.model_copy(update={'snapshot':snap})
    (tmp_path/'current.json').write_text(scope.model_dump_json(),encoding='utf8')
    app=create_app(tmp_path,private_preview_root=tmp_path/'previews',chat_runner=object(),course_id='math')
    lookup=endpoint(app,PAGE)
    ids=[record_source_id('math',scope,digest(store.get(scope,r.id).model_dump(mode='json'))) for r in (first,second)]
    next_page=lookup(doc.id,2,source_id=ids[0],source_page=1)
    assert next_page['source_id']==ids[1] and ids[1] in next_page['preview_url']
    with pytest.raises(HTTPException) as err:
        lookup(doc.id,2,source_id=ids[0],source_page=2)
    assert err.value.status_code==409
